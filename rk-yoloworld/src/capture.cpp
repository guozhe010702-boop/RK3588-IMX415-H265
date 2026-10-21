#include "capture.hpp"
#include <cerrno>
#include <cstdio>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <linux/v4l2-subdev.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
namespace yw {
static int xi(int f, unsigned long op, void *a) {
    int r;
    do {
        r = ioctl(f, op, a);
    } while (r < 0 && errno == EINTR);
    return r;
}
struct Capture::Impl {
    int fd = -1, w = 0, h = 0;
    bool streaming = false, multi = false, full = false;
    v4l2_buf_type type{};
    unsigned np = 0;
    size_t strides[2]{};
    struct Map {
        void *ptr = MAP_FAILED;
        size_t size = 0;
    };
    std::vector<std::vector<Map>> maps;
    ~Impl() {
        if (fd >= 0) {
            if (streaming)
                xi(fd, VIDIOC_STREAMOFF, &type);
            for (auto &b : maps)
                for (auto &m : b)
                    if (m.ptr != MAP_FAILED)
                        munmap(m.ptr, m.size);
            close(fd);
        }
    }
    void qbuf(v4l2_buffer &b) {
        require(xi(fd, VIDIOC_QBUF, &b) == 0, "VIDIOC_QBUF failed");
    }
};
Capture::Capture(const std::string &path, int w, int h, int fps, int buffers) : p(new Impl) {
    require(buffers >= 2 && buffers <= 32, "buffer count must be 2..32");
    p->fd = open(path.c_str(), O_RDWR | O_NONBLOCK | O_CLOEXEC);
    require(p->fd >= 0, "cannot open camera");
    v4l2_capability cap{};
    require(xi(p->fd, VIDIOC_QUERYCAP, &cap) == 0, "QUERYCAP failed");
    auto caps = (cap.capabilities & V4L2_CAP_DEVICE_CAPS) ? cap.device_caps : cap.capabilities;
    require(caps & V4L2_CAP_STREAMING, "camera lacks streaming");
    p->multi = caps & V4L2_CAP_VIDEO_CAPTURE_MPLANE;
    require(p->multi || (caps & V4L2_CAP_VIDEO_CAPTURE), "not a capture node");
    p->type = p->multi ? V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE : V4L2_BUF_TYPE_VIDEO_CAPTURE;
    v4l2_format fmt{};
    fmt.type = p->type;
    if (p->multi) {
        fmt.fmt.pix_mp.width = w;
        fmt.fmt.pix_mp.height = h;
        fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_NV12M;
        fmt.fmt.pix_mp.field = V4L2_FIELD_NONE;
    } else {
        fmt.fmt.pix.width = w;
        fmt.fmt.pix.height = h;
        fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12;
        fmt.fmt.pix.field = V4L2_FIELD_NONE;
    }
    if (xi(p->fd, VIDIOC_S_FMT, &fmt) < 0)
        throw std::runtime_error(
            errno == EBUSY ? "camera busy; inspect lsof /dev/video44; no process was killed"
                           : "VIDIOC_S_FMT failed");
    uint32_t pixel = 0;
    if (p->multi) {
        auto &f = fmt.fmt.pix_mp;
        p->w = f.width;
        p->h = f.height;
        pixel = f.pixelformat;
        p->np = f.num_planes;
        p->full = f.quantization == V4L2_QUANTIZATION_FULL_RANGE;
        require(p->np >= 1 && p->np <= 2, "unsupported plane count");
        for (unsigned i = 0; i < p->np; ++i)
            p->strides[i] = f.plane_fmt[i].bytesperline;
    } else {
        auto &f = fmt.fmt.pix;
        p->w = f.width;
        p->h = f.height;
        pixel = f.pixelformat;
        p->np = 1;
        p->strides[0] = f.bytesperline;
        p->full = f.quantization == V4L2_QUANTIZATION_FULL_RANGE;
    }
    require(p->w == w && p->h == h, "driver changed requested dimensions");
    require((pixel == V4L2_PIX_FMT_NV12 && p->np == 1) ||
                (pixel == V4L2_PIX_FMT_NV12M && p->np == 2),
            "driver returned incompatible format");
    v4l2_streamparm parm{};
    parm.type = p->type;
    parm.parm.capture.timeperframe.numerator = 1;
    parm.parm.capture.timeperframe.denominator = fps;
    int rate = xi(p->fd, VIDIOC_S_PARM, &parm);
    if (path == "/dev/video44") {
        int sensor = open("/dev/v4l-subdev2", O_RDWR | O_CLOEXEC);
        if (sensor >= 0) {
            v4l2_subdev_frame_interval interval{};
            if (xi(sensor, VIDIOC_SUBDEV_G_FRAME_INTERVAL, &interval) == 0 &&
                interval.interval.numerator)
                fprintf(stderr,
                        "sensor_actual_fps=%.6f interval=%u/%u subdevice=/dev/v4l-subdev2\n",
                        double(interval.interval.denominator) / interval.interval.numerator,
                        interval.interval.numerator, interval.interval.denominator);
            else
                fprintf(stderr, "sensor_actual_fps=unavailable\n");
            close(sensor);
        } else
            fprintf(stderr, "sensor_actual_fps=unavailable\n");
    }
    fprintf(stderr,
            "capture_actual: %dx%d %.4s planes=%u stride=%zu,%zu "
            "buffers_requested=%d fps_requested=%d video_S_PARM=%s\n",
            w, h, reinterpret_cast<char *>(&pixel), p->np, p->strides[0], p->strides[1], buffers,
            fps, rate == 0 ? "accepted" : "unsupported (see sensor report/effective fps)");
    v4l2_requestbuffers req{};
    req.type = p->type;
    req.memory = V4L2_MEMORY_MMAP;
    req.count = buffers;
    require(xi(p->fd, VIDIOC_REQBUFS, &req) == 0 && req.count >= 2, "REQBUFS failed");
    p->maps.resize(req.count);
    fprintf(stderr, "capture_buffers_actual=%u\n", req.count);
    for (unsigned i = 0; i < req.count; ++i) {
        v4l2_plane ps[VIDEO_MAX_PLANES]{};
        v4l2_buffer b{};
        b.type = p->type;
        b.memory = V4L2_MEMORY_MMAP;
        b.index = i;
        if (p->multi) {
            b.m.planes = ps;
            b.length = p->np;
        }
        require(xi(p->fd, VIDIOC_QUERYBUF, &b) == 0, "QUERYBUF failed");
        p->maps[i].resize(p->np);
        for (unsigned j = 0; j < p->np; ++j) {
            auto &m = p->maps[i][j];
            m.size = p->multi ? ps[j].length : b.length;
            auto off = p->multi ? ps[j].m.mem_offset : b.m.offset;
            m.ptr = mmap(nullptr, m.size, PROT_READ | PROT_WRITE, MAP_SHARED, p->fd, off);
            require(m.ptr != MAP_FAILED, "camera mmap failed");
        }
        p->qbuf(b);
    }
    // STREAMON is deliberately deferred until the capture worker's first read.
    // Model/pool/RGA/encoder initialization must not fill and starve 3 mmap slots.
}
Capture::~Capture() = default;
int Capture::width() const {
    return p->w;
}
int Capture::height() const {
    return p->h;
}
bool Capture::full_range() const {
    return p->full;
}
bool Capture::read(uint8_t *dst, uint32_t &seq, int64_t &timestamp) {
    if (!p->streaming) {
        require(xi(p->fd, VIDIOC_STREAMON, &p->type) == 0, "STREAMON failed");
        p->streaming = true;
    }
    pollfd poller{p->fd, POLLIN, 0};
    int ready = poll(&poller, 1, 1000);
    if (ready == 0 || (ready < 0 && errno == EINTR))
        return false;
    require(ready > 0 && !(poller.revents & (POLLERR | POLLNVAL)), "camera poll failed");
    v4l2_plane ps[VIDEO_MAX_PLANES]{};
    v4l2_buffer b{};
    b.type = p->type;
    b.memory = V4L2_MEMORY_MMAP;
    if (p->multi) {
        b.m.planes = ps;
        b.length = p->np;
    }
    if (xi(p->fd, VIDIOC_DQBUF, &b) < 0) {
        if (errno == EAGAIN)
            return false;
        throw std::runtime_error("DQBUF failed");
    }
    try {
        require(b.index < p->maps.size(), "invalid camera buffer index");
        require(!(b.flags & V4L2_BUF_FLAG_ERROR), "camera flagged frame error");
        std::vector<Plane> planes;
        for (unsigned j = 0; j < p->np; ++j) {
            auto &m = p->maps[b.index][j];
            planes.push_back({static_cast<uint8_t *>(m.ptr), m.size,
                              p->multi ? ps[j].bytesused : b.bytesused,
                              p->multi ? ps[j].data_offset : 0, p->strides[j]});
        }
        pack_nv12(planes, p->w, p->h, dst);
        seq = b.sequence;
        if ((b.flags & V4L2_BUF_FLAG_TIMESTAMP_MASK) == V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC)
            timestamp = int64_t(b.timestamp.tv_sec) * 1000000 + b.timestamp.tv_usec;
        else
            timestamp = now_us();
    } catch (...) {
        p->qbuf(b);
        throw;
    }
    p->qbuf(b);
    return true;
}
} // namespace yw
