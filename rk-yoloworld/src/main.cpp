#include "capture.hpp"
#include "model.hpp"
#include "output.hpp"
#include <csignal>
#include <array>
#include <fstream>
#include <functional>
#include <iostream>
#include <sstream>
#include <pthread.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <thread>
#include <unistd.h>
using namespace yw;
static void signal_handler(int) {
    interrupted = 1;
}
struct Config {
    std::string clip = "model/clip_text_fp16.rknn", yolo = "model/yolo_world_v2s_i8.rknn",
                classes = "model/detect_classes.txt", device = "/dev/video44", verify_rgb;
    OutputConfig output{"/userdata/av_dev/ffmpeg_pipeline/runtime/bin/ffmpeg",
                        "/userdata/av_dev/ffmpeg_pipeline/runtime/lib:/userdata/"
                        "av_dev/ffmpeg_pipeline/runtime/lib64",
                        "udp://192.168.2.165:1235?pkt_size=1316"};
    int buffers = 3, skip = 5, seconds = 0, capture_priority = 0;
    bool probe = false;
};
static void help() {
    std::cout << "rknn_yolo_world_realtime [--probe] [--verify-rgb FILE] [--clip "
                 "FILE] [--yolo FILE] [--classes FILE]\n"
                 " [--device /dev/video44] [--width 2560] [--height 1440] [--fps "
                 "60] [--buffers 3] [--skip 5]\n"
                 " [--url udp://192.168.2.165:1235?pkt_size=1316] [--bitrate "
                 "40000000] [--gop 10]\n"
                 " [--ffmpeg FILE] [--ffmpeg-lib DIRECTORY_LIST] [--seconds N] [--capture-priority "
                 "0..20]\n"
                 " [--local-preview] mirror the encoded stream to board UDP 1236\n"
                 "--probe initializes CLIP once, all 9 core-bound contexts and "
                 "RGA, without opening camera.\n"
                 "--verify-rgb additionally compares all 9 contexts on an exact "
                 "model-sized RGB image.\n";
}
static Config options(int argc, char **argv) {
    Config c;
    for (int i = 1; i < argc; ++i) {
        std::string k = argv[i];
        if (k == "--help") {
            help();
            std::exit(0);
        }
        if (k == "--probe") {
            c.probe = true;
            continue;
        }
        if (k == "--local-preview") {
            c.output.local_preview = true;
            continue;
        }
        require(i + 1 < argc, "missing option value");
        std::string v = argv[++i];
        auto number = [&] {
            size_t n;
            int value = std::stoi(v, &n);
            require(n == v.size(), "invalid integer");
            return value;
        };
        if (k == "--clip")
            c.clip = v;
        else if (k == "--yolo")
            c.yolo = v;
        else if (k == "--classes")
            c.classes = v;
        else if (k == "--device")
            c.device = v;
        else if (k == "--url")
            c.output.url = v;
        else if (k == "--ffmpeg")
            c.output.ffmpeg = v;
        else if (k == "--ffmpeg-lib")
            c.output.ffmpeg_lib = v;
        else if (k == "--verify-rgb") {
            c.verify_rgb = v;
            c.probe = true;
        } else if (k == "--width")
            c.output.w = number();
        else if (k == "--height")
            c.output.h = number();
        else if (k == "--fps")
            c.output.fps = number();
        else if (k == "--buffers")
            c.buffers = number();
        else if (k == "--skip")
            c.skip = number();
        else if (k == "--seconds")
            c.seconds = number();
        else if (k == "--bitrate")
            c.output.bitrate = number();
        else if (k == "--gop")
            c.output.gop = number();
        else if (k == "--capture-priority")
            c.capture_priority = number();
        else
            throw std::runtime_error("unknown option: " + k);
    }
    require(c.output.w >= 64 && c.output.w <= 3840 && c.output.h >= 64 && c.output.h <= 2160 &&
                !(c.output.w % 2) && !(c.output.h % 2),
            "invalid capture dimensions");
    require(c.output.fps >= 1 && c.output.fps <= 60 && c.buffers >= 2 && c.buffers <= 32 &&
                c.skip >= 0 && c.skip <= 1000 && c.seconds >= 0 && c.capture_priority >= 0 &&
                c.capture_priority <= 20,
            "invalid capture limits");
    require(c.output.url.rfind("udp://", 0) == 0 && c.output.bitrate > 0 &&
                c.output.bitrate <= 100000000 && c.output.gop > 0,
            "invalid output config");
    return c;
}
struct Samples {
    std::mutex mu;
    std::deque<double> v;
    std::array<uint64_t, 10002> histogram{};
    uint64_t total = 0;
    void add(double x) {
        std::lock_guard<std::mutex> l(mu);
        v.push_back(x);
        ++histogram[std::clamp(int(x * 2), 0, 10001)];
        ++total;
        if (v.size() > 4096)
            v.pop_front();
    }
    std::pair<double, double> all_quantiles() {
        std::lock_guard<std::mutex> l(mu);
        if (!total)
            return {-1, -1};
        double p50 = -1, p95 = -1;
        uint64_t n = 0;
        for (size_t i = 0; i < histogram.size(); ++i) {
            n += histogram[i];
            if (p50 < 0 && n >= (total + 1) / 2)
                p50 = i * .5;
            if (n >= (total * 95 + 99) / 100) {
                p95 = i * .5;
                break;
            }
        }
        return {p50, p95};
    }
    std::pair<double, double> quantiles() {
        std::lock_guard<std::mutex> l(mu);
        if (v.empty())
            return {-1, -1};
        std::vector<double> copy(v.begin(), v.end());
        std::sort(copy.begin(), copy.end());
        return {copy[(copy.size() - 1) / 2], copy[(copy.size() - 1) * 95 / 100]};
    }
};
struct Stats {
    std::atomic<uint64_t> worker_completed[9]{};
    std::atomic<pid_t> worker_tid[9]{};
    std::atomic<uint64_t> captured{0}, preprocessed{0}, inferred{0}, rendered{0}, output{0},
        gaps{0}, startup_gaps{0}, resets{0}, timeouts{0}, pool_drops{0}, pts_drops{0};
    Samples rga_ms, infer_ms, age_ms;
};
static std::string json_quote(const std::string &s) {
    std::string r = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') {
            r += '\\';
            r += c;
        } else if (c == '\n' || c == '\r')
            r += ' ';
        else if (c >= 32)
            r += c;
    }
    return r + '"';
}
static std::string npu_load() {
    std::ifstream f("/sys/kernel/debug/rknpu/load");
    std::string s;
    std::getline(f, s);
    return s.empty() ? "unavailable" : s;
}
static double cpu_seconds() {
    rusage r{};
    getrusage(RUSAGE_SELF, &r);
    return r.ru_utime.tv_sec + r.ru_utime.tv_usec / 1e6 + r.ru_stime.tv_sec +
           r.ru_stime.tv_usec / 1e6;
}
int main(int argc, char **argv) {
    try {
        auto cfg = options(argc, argv);
        signal(SIGINT, signal_handler);
        signal(SIGTERM, signal_handler);
        signal(SIGPIPE, SIG_IGN);
        auto text = encode_text(cfg.clip, cfg.classes);
        std::vector<std::unique_ptr<Detector>> models;
        for (int i = 0; i < 9; ++i) {
            require(!interrupted, "startup interrupted");
            models.emplace_back(new Detector(cfg.yolo, text, i));
            if (i)
                require(models[i]->width() == models[0]->width() &&
                            models[i]->height() == models[0]->height(),
                        "context dimensions differ");
        }
        int mw = models[0]->width(), mh = models[0]->height();
        if (cfg.probe) {
            Preprocess pp(cfg.output.w, cfg.output.h, mw, mh, true);
            Frame f;
            f.nv12 = std::make_shared<std::vector<uint8_t>>(
                size_t(cfg.output.w) * cfg.output.h * 3 / 2, 128);
            f.rgb = std::make_shared<std::vector<uint8_t>>(size_t(mw) * mh * 3);
            pp.run(f);
            if (!cfg.verify_rgb.empty()) {
                std::ifstream input(cfg.verify_rgb, std::ios::binary);
                require(bool(input), "RGB fixture missing");
                std::vector<uint8_t> rgb((std::istreambuf_iterator<char>(input)), {});
                require(rgb.size() == size_t(mw) * mh * 3, "RGB fixture size mismatch");
                auto expected = models[0]->infer(rgb.data());
                for (int i = 1; i < 9; ++i) {
                    auto actual = models[i]->infer(rgb.data());
                    require(actual.size() == expected.size(), "context parity box count differs");
                    for (size_t j = 0; j < actual.size(); ++j) {
                        auto a = actual[j], b = expected[j];
                        require(a.cls == b.cls && std::abs(a.score - b.score) < .002 &&
                                    std::abs(a.x1 - b.x1) < 1 && std::abs(a.y1 - b.y1) < 1 &&
                                    std::abs(a.x2 - b.x2) < 1 && std::abs(a.y2 - b.y2) < 1,
                                "context parity differs");
                    }
                }
                std::cout << "{\"probe\":true,\"contexts\":9,\"parity\":true,\"boxes\":"
                          << expected.size() << "}\n";
            } else {
                std::cout << "{\"probe\":true,\"contexts\":9,\"parity\":null}\n";
            }
            return 0;
        }
        require(!interrupted, "startup interrupted");
        Capture capture(cfg.device, cfg.output.w, cfg.output.h, cfg.output.fps, cfg.buffers);
        Pool raw_pool(24, size_t(cfg.output.w) * cfg.output.h * 3 / 2),
            rgb_pool(16, size_t(mw) * mh * 3);
        std::vector<std::unique_ptr<Preprocess>> pre;
        for (int i = 0; i < 2; ++i)
            pre.emplace_back(
                new Preprocess(cfg.output.w, cfg.output.h, mw, mh, capture.full_range()));
        std::atomic<bool> running{true};
        Stats stats;
        Queue<Task> raw(2), prepared(2);
        Latest<Task> results, encoded;
        std::mutex error_mu;
        std::string error;
        auto close_queues = [&] {
            running = false;
            raw.stop();
            prepared.stop();
            results.stop();
            encoded.stop();
        };
        auto fail = [&](const std::string &why) {
            std::lock_guard<std::mutex> l(error_mu);
            if (error.empty()) {
                error = why;
                std::cerr << "fatal: " << why << '\n';
            }
            close_queues();
        };
        Encoder encoder(cfg.output, running);
        std::vector<std::thread> threads;
        auto launch = [&](const char *name, std::function<void()> work) {
            threads.emplace_back([&, name, work] {
                pthread_setname_np(pthread_self(), name);
                try {
                    work();
                } catch (const std::exception &e) {
                    fail(std::string(name) + ": " + e.what());
                } catch (...) {
                    fail(std::string(name) + ": unknown exception");
                }
            });
        };
        auto started = now_us();
        try {
            launch("capture", [&] {
                if (cfg.capture_priority) {
                    sched_param param{};
                    param.sched_priority = cfg.capture_priority;
                    require(pthread_setschedparam(pthread_self(), SCHED_RR, &param) == 0,
                            "requested capture realtime priority requires CAP_SYS_NICE/root");
                }
                std::cerr << "capture_SCHED_RR_priority=" << cfg.capture_priority
                          << " (0=normal)\n";
                uint64_t seq = 0;
                uint32_t previous = 0;
                bool seen = false;
                int skip = cfg.skip;
                int64_t last_pts = -1, last_good = now_us();
                std::vector<uint8_t> drain(size_t(cfg.output.w) * cfg.output.h * 3 / 2);
                while (running) {
                    auto bytes = raw_pool.acquire();
                    uint32_t driver;
                    int64_t stamp;
                    if (!capture.read(bytes ? bytes->data() : drain.data(), driver, stamp)) {
                        ++stats.timeouts;
                        require(now_us() - last_good < 5000000, "no camera frames for 5 seconds");
                        continue;
                    }
                    last_good = now_us();
                    if (seen) {
                        uint32_t delta = driver - previous;
                        if (delta > 0 && delta < 0x80000000u) {
                            stats.gaps += delta - 1;
                            if (skip)
                                stats.startup_gaps += delta - 1;
                        } else
                            ++stats.resets;
                    }
                    previous = driver;
                    seen = true;
                    ++stats.captured;
                    if (stats.captured <= 10)
                        fprintf(stderr, "capture_initial: count=%llu sequence=%u age_ms=%.3f\n",
                                (unsigned long long)stats.captured.load(), driver,
                                (now_us() - stamp) / 1000.);
                    if (skip) {
                        --skip;
                        continue;
                    }
                    if (!bytes) {
                        ++stats.pool_drops;
                        continue;
                    }
                    if (stamp <= last_pts) {
                        ++stats.pts_drops;
                        continue;
                    }
                    last_pts = stamp;
                    auto f = std::make_shared<Frame>();
                    f->seq = ++seq;
                    f->driver_seq = driver;
                    f->captured = stamp;
                    f->nv12 = std::move(bytes);
                    raw.push(std::move(f));
                }
            });
            for (int i = 0; i < 2; ++i)
                launch("preprocess", [&, i] {
                    Task f;
                    while (running && raw.pop(f)) {
                        auto rgb = rgb_pool.acquire();
                        if (!rgb) {
                            ++stats.pool_drops;
                            f.reset();
                            continue;
                        }
                        f->rgb = std::move(rgb);
                        auto t = now_us();
                        pre[i]->run(*f);
                        stats.rga_ms.add((now_us() - t) / 1000.);
                        ++stats.preprocessed;
                        prepared.push(std::move(f));
                    }
                });
            for (int i = 0; i < 9; ++i)
                launch("inference", [&, i] {
                    char name[16];
                    snprintf(name, sizeof(name), "infer%d-npu%d", i, i % 3);
                    pthread_setname_np(pthread_self(), name);
                    stats.worker_tid[i] = static_cast<pid_t>(syscall(SYS_gettid));
                    Task f;
                    while (running && prepared.pop(f)) {
                        auto t = now_us();
                        f->boxes = models[i]->infer(f->rgb->data());
                        stats.infer_ms.add((now_us() - t) / 1000.);
                        f->rgb.reset();
                        ++stats.inferred;
                        ++stats.worker_completed[i];
                        results.push(std::move(f));
                    }
                });
            launch("render", [&] {
                Task f;
                while (running && results.pop(f)) {
                    draw_nv12(*f, cfg.output.w, cfg.output.h, text.labels);
                    ++stats.rendered;
                    encoded.push(std::move(f));
                }
            });
            launch("output", [&] {
                Task f;
                int64_t last = 0;
                while (running && encoded.pop(f)) {
                    auto wait = last + 1000000 / cfg.output.fps - now_us();
                    if (wait > 0)
                        std::this_thread::sleep_for(std::chrono::microseconds(wait));
                    if (!running)
                        break;
                    encoder.write(*f);
                    last = now_us();
                    stats.age_ms.add((last - f->captured) / 1000.);
                    ++stats.output;
                }
            });
            launch("stats", [&] {
                int64_t last = now_us();
                uint64_t counts[4]{};
                double previous_cpu = cpu_seconds();
                while (running) {
                    for (int i = 0; i < 10 && running; ++i)
                        std::this_thread::sleep_for(std::chrono::milliseconds(100));
                    if (!running)
                        break;
                    auto now = now_us();
                    double dt = (now - last) / 1e6;
                    uint64_t current[] = {stats.captured.load(), stats.preprocessed.load(),
                                          stats.inferred.load(), stats.output.load()};
                    double fps[4];
                    for (int i = 0; i < 4; ++i) {
                        fps[i] = (current[i] - counts[i]) / dt;
                        counts[i] = current[i];
                    }
                    double cpu = cpu_seconds();
                    std::ifstream statm("/proc/self/statm");
                    long pages = 0, resident = 0;
                    statm >> pages >> resident;
                    auto age = stats.age_ms.quantiles(), rga = stats.rga_ms.quantiles(),
                         infer = stats.infer_ms.quantiles();
                    auto age_all = stats.age_ms.all_quantiles();
                    std::cout << "{\"pid\":" << getpid()
                              << ",\"elapsed_s\":" << (now - started) / 1e6
                              << ",\"capture_fps\":" << fps[0] << ",\"rga_fps\":" << fps[1]
                              << ",\"infer_fps\":" << fps[2] << ",\"output_fps\":" << fps[3]
                              << ",\"capture_total\":" << current[0]
                              << ",\"infer_total\":" << current[2]
                              << ",\"output_total\":" << current[3] << ",\"driver_gaps\":"
                              << stats.gaps.load() - stats.startup_gaps.load()
                              << ",\"driver_gaps_total\":" << stats.gaps
                              << ",\"startup_driver_gaps\":" << stats.startup_gaps
                              << ",\"steady_driver_gaps\":"
                              << stats.gaps.load() - stats.startup_gaps.load()
                              << ",\"driver_resets\":" << stats.resets
                              << ",\"raw_drops\":" << raw.dropped
                              << ",\"prepared_drops\":" << prepared.dropped
                              << ",\"stale_results\":" << results.stale
                              << ",\"result_replaced\":" << results.replaced
                              << ",\"output_replaced\":" << encoded.replaced
                              << ",\"pool_drops\":" << stats.pool_drops
                              << ",\"pts_drops\":" << stats.pts_drops
                              << ",\"timeouts\":" << stats.timeouts
                              << ",\"age_p50_ms\":" << age.first << ",\"age_p95_ms\":" << age.second
                              << ",\"age_all_p50_ms\":" << age_all.first
                              << ",\"age_all_p95_ms\":" << age_all.second
                              << ",\"rga_p50_ms\":" << rga.first << ",\"rga_p95_ms\":" << rga.second
                              << ",\"infer_p50_ms\":" << infer.first
                              << ",\"infer_p95_ms\":" << infer.second
                              << ",\"cpu_core_percent\":" << (cpu - previous_cpu) / dt * 100
                              << ",\"rss_mib\":" << resident * sysconf(_SC_PAGESIZE) / 1048576.
                              << ",\"npu\":" << json_quote(npu_load()) << ",\"workers\":[";
                    for (int i = 0; i < 9; ++i) {
                        if (i)
                            std::cout << ',';
                        std::cout << "{\"worker\":" << i << ",\"tid\":" << stats.worker_tid[i]
                                  << ",\"core\":" << i % 3
                                  << ",\"completed\":" << stats.worker_completed[i] << '}';
                    }
                    std::cout << "]}\n" << std::flush;
                    previous_cpu = cpu;
                    last = now;
                }
            });
            std::cerr << "application_threads=16 (15 workers + main); RKNN internals "
                         "excluded\n";
            while (running && !interrupted &&
                   (!cfg.seconds || now_us() - started < int64_t(cfg.seconds) * 1000000))
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
        } catch (...) {
            close_queues();
            for (auto &t : threads)
                if (t.joinable())
                    t.join();
            throw;
        }
        close_queues();
        for (auto &t : threads)
            t.join();
        std::lock_guard<std::mutex> l(error_mu);
        return error.empty() ? 0 : 1;
    } catch (const std::exception &e) {
        std::cerr << "fatal: " << e.what() << '\n';
        return 1;
    }
}
