#include "output.hpp"
extern "C" {
#include <libavformat/avformat.h>
#include <libavutil/mem.h>
#include <libavutil/pixfmt.h>
}
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
namespace yw {
struct Nut::Impl {
    int fd;
    int64_t last = -1, packet_deadline = 0;
    size_t bytes;
    AVFormatContext *fmt = nullptr;
    AVIOContext *io = nullptr;
    std::atomic<bool> &running;
    static int writer(void *self, const uint8_t *data, int length) {
        auto &s = *static_cast<Impl *>(self);
        int sent = 0;
        while (sent < length) {
            // Finish a packet already started even after a normal stop request.
            // Aborting halfway through rawvideo would leave a corrupt NUT packet.
            // A genuinely blocked/dead encoder is still bounded by the deadline.
            if (now_us() > s.packet_deadline)
                return AVERROR_EXIT;
            ssize_t n = ::write(s.fd, data + sent, length - sent);
            if (n > 0) {
                sent += n;
                continue;
            }
            if (n < 0 && (errno == EINTR || errno == EAGAIN)) {
                pollfd p{s.fd, POLLOUT, 0};
                poll(&p, 1, 50);
                continue;
            }
            return AVERROR(n < 0 ? errno : EPIPE);
        }
        return sent;
    }
    Impl(int f, int w, int h, int fps, std::atomic<bool> &r)
        : fd(f), bytes(size_t(w) * h * 3 / 2), running(r) {
        try {
            require(avformat_alloc_output_context2(&fmt, nullptr, "nut", nullptr) >= 0 && fmt,
                    "cannot allocate NUT");
            auto *buffer = static_cast<uint8_t *>(av_malloc(32768));
            require(buffer, "AVIO allocation failed");
            io = avio_alloc_context(buffer, 32768, 1, this, nullptr, writer, nullptr);
            if (!io) {
                av_free(buffer);
                throw std::runtime_error("AVIO context failed");
            }
            fmt->pb = io;
            fmt->flags |= AVFMT_FLAG_CUSTOM_IO | AVFMT_FLAG_FLUSH_PACKETS;
            auto *stream = avformat_new_stream(fmt, nullptr);
            require(stream, "cannot allocate NUT stream");
            stream->time_base = {1, 1000000};
            stream->avg_frame_rate = {fps, 1};
            auto *par = stream->codecpar;
            par->codec_type = AVMEDIA_TYPE_VIDEO;
            par->codec_id = AV_CODEC_ID_RAWVIDEO;
            par->codec_tag = MKTAG('N', 'V', '1', '2');
            par->format = AV_PIX_FMT_NV12;
            par->width = w;
            par->height = h;
            par->color_range = AVCOL_RANGE_JPEG;
            par->color_space = AVCOL_SPC_BT709;
            packet_deadline = now_us() + 2000000;
            require(avformat_write_header(fmt, nullptr) >= 0, "NUT header write failed");
        } catch (...) {
            cleanup();
            throw;
        }
    }
    void cleanup() {
        if (fmt) {
            fmt->pb = nullptr;
            avformat_free_context(fmt);
            fmt = nullptr;
        }
        if (io) {
            av_freep(&io->buffer);
            avio_context_free(&io);
        }
    }
    ~Impl() {
        if (fmt && running) {
            packet_deadline = now_us() + 2000000;
            av_write_trailer(fmt);
            avio_flush(io);
        }
        cleanup();
    }
};
Nut::Nut(int fd, int w, int h, int fps, std::atomic<bool> &r) : p(new Impl(fd, w, h, fps, r)) {}
Nut::~Nut() = default;
void Nut::write(const uint8_t *data, size_t size, int64_t pts) {
    p->packet_deadline = now_us() + 2000000;
    require(size == p->bytes && pts >= 0 && pts > p->last,
            "NUT invalid frame size or nonmonotonic PTS");
    AVPacket packet{};
    packet.data = const_cast<uint8_t *>(data);
    packet.size = size;
    packet.stream_index = 0;
    packet.pts = packet.dts = av_rescale_q(pts, {1, 1000000}, p->fmt->streams[0]->time_base);
    packet.flags = AV_PKT_FLAG_KEY;
    require(av_write_frame(p->fmt, &packet) >= 0, "NUT output failed or encoder stalled");
    avio_flush(p->io);
    require(p->io->error >= 0, "NUT pipe error");
    p->last = pts;
}
std::vector<std::string> encoder_arguments(const OutputConfig &c) {
    require(c.url.rfind("udp://", 0) == 0 && c.url.find_first_of("|[]\\'\r\n") == std::string::npos,
            "invalid UDP destination or reserved tee character");
    std::vector<std::string> args{c.ffmpeg,
                                  "-hide_banner",
                                  "-loglevel",
                                  "warning",
                                  "-nostdin",
                                  "-fflags",
                                  "nobuffer",
                                  "-flags",
                                  "low_delay",
                                  "-probesize",
                                  "32768",
                                  "-analyzeduration",
                                  "0",
                                  "-f",
                                  "nut",
                                  "-i",
                                  "pipe:0",
                                  "-an",
                                  "-c:v",
                                  "h264_rkmpp",
                                  "-rc_mode",
                                  "CBR",
                                  "-b:v",
                                  std::to_string(c.bitrate),
                                  "-g",
                                  std::to_string(c.gop),
                                  "-bf",
                                  "0",
                                  "-enc_time_base:v",
                                  "1:1000000",
                                  "-fps_mode",
                                  "passthrough"};
    if (c.local_preview) {
        // Both destinations receive the SAME encoded packets; no second encoder.
        args.insert(args.end(), {"-map", "0:v:0", "-f", "tee",
                                 "[f=mpegts:onfail=ignore:flush_packets=1]" + c.url +
                                     "|[f=mpegts:onfail=ignore:flush_packets=1]udp://"
                                     "127.0.0.1:1236?pkt_size=1316&bitrate=" +
                                     std::to_string(c.bitrate) + "&burst_bits=65536"});
    } else
        args.insert(args.end(), {"-f", "mpegts", "-flush_packets", "1", "-muxdelay", "0",
                                 "-muxpreload", "0", c.url});
    return args;
}
struct Encoder::Impl {
    pid_t child = -1;
    int fd = -1;
    std::unique_ptr<Nut> nut;
    int64_t origin = -1;
    Impl(const OutputConfig &c, std::atomic<bool> &r) {
        auto args = encoder_arguments(c);
        int pipes[2];
        require(pipe2(pipes, O_CLOEXEC) == 0, "encoder pipe failed");
        std::vector<char *> av;
        for (auto &s : args)
            av.push_back(s.data());
        av.push_back(nullptr);
        std::vector<std::string> env;
        for (char **e = environ; *e; ++e)
            if (std::string(*e).rfind("LD_LIBRARY_PATH=", 0) != 0 &&
                std::string(*e).rfind("LD_PRELOAD=", 0) != 0)
                env.emplace_back(*e);
        env.push_back("LD_LIBRARY_PATH=" + c.ffmpeg_lib);
        std::vector<char *> ev;
        for (auto &s : env)
            ev.push_back(s.data());
        ev.push_back(nullptr);
        posix_spawn_file_actions_t action;
        posix_spawn_file_actions_init(&action);
        posix_spawn_file_actions_adddup2(&action, pipes[0], STDIN_FILENO);
        posix_spawn_file_actions_addclose(&action, pipes[0]);
        posix_spawn_file_actions_addclose(&action, pipes[1]);
        int error = posix_spawn(&child, c.ffmpeg.c_str(), &action, nullptr, av.data(), ev.data());
        posix_spawn_file_actions_destroy(&action);
        close(pipes[0]);
        if (error) {
            close(pipes[1]);
            child = -1;
            throw std::runtime_error("cannot spawn private FFmpeg: " + std::to_string(error));
        }
        fd = pipes[1];
        fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK);
        try {
            nut.reset(new Nut(fd, c.w, c.h, c.fps, r));
        } catch (...) {
            shutdown();
            throw;
        }
    }
    void shutdown() {
        nut.reset();
        if (fd >= 0) {
            close(fd);
            fd = -1;
        }
        if (child > 0) {
            int status = 0;
            bool done = false;
            for (int i = 0; i < 30; ++i) {
                auto n = waitpid(child, &status, WNOHANG);
                if (n == child || n < 0) {
                    done = true;
                    break;
                }
                usleep(100000);
            }
            if (!done) {
                kill(child, SIGTERM);
                for (int i = 0; i < 20; ++i) {
                    auto n = waitpid(child, &status, WNOHANG);
                    if (n == child || n < 0) {
                        done = true;
                        break;
                    }
                    usleep(100000);
                }
                if (!done) {
                    kill(child, SIGKILL);
                    waitpid(child, &status, 0);
                }
            }
            fprintf(stderr, "encoder_exit_status=%d\n", status);
            child = -1;
        }
    }
    ~Impl() {
        shutdown();
    }
};
Encoder::Encoder(const OutputConfig &c, std::atomic<bool> &r) : p(new Impl(c, r)) {}
Encoder::~Encoder() = default;
void Encoder::write(const Frame &f) {
    if (p->origin < 0)
        p->origin = f.captured;
    p->nut->write(f.nv12->data(), f.nv12->size(), f.captured - p->origin);
}
} // namespace yw
