#include "capture.hpp"
#include "model.hpp"
#include "output.hpp"
#include <csignal>
#include <fstream>
#include <iostream>
// Explicitly not a detector. Validate the capture/RGA/mux/encoder integration.
int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    try {
        bool capture = argc > 1 && std::string(argv[1]) == "--capture";
        int w = capture ? 2560 : 640, h = capture ? 1440 : 480;
        std::unique_ptr<yw::Capture> camera;
        if (capture)
            camera.reset(new yw::Capture("/dev/video44", w, h, 60, 3));
        yw::Frame f;
        f.nv12 = std::make_shared<std::vector<uint8_t>>(size_t(w) * h * 3 / 2, 128);
        f.rgb = std::make_shared<std::vector<uint8_t>>(640 * 640 * 3);
        yw::Preprocess p(w, h, 640, 640, true);
        if (!capture) {
            auto &b = *f.nv12;
            const uint8_t colors[4][3] = {
                {0, 128, 128}, {255, 128, 128}, {54, 99, 255}, {182, 30, 12}};
            for (int y = 0; y < h; ++y)
                for (int x = 0; x < w; ++x)
                    b[y * w + x] = colors[x / (w / 4)][0];
            for (int y = 0; y < h / 2; ++y)
                for (int x = 0; x < w; x += 2) {
                    b[w * h + y * w + x] = colors[x / (w / 4)][1];
                    b[w * h + y * w + x + 1] = colors[x / (w / 4)][2];
                }
            p.run(f);
            std::ofstream out("rga-smoke.rgb", std::ios::binary);
            out.write(reinterpret_cast<char *>(f.rgb->data()), f.rgb->size());
            std::cout << "synthetic_rga_ok (not inference)\n";
            return 0;
        }
        std::atomic<bool> running{true};
        yw::OutputConfig c{"/userdata/av_dev/ffmpeg_pipeline/runtime/bin/ffmpeg",
                           "/userdata/av_dev/ffmpeg_pipeline/runtime/lib:/userdata/"
                           "av_dev/ffmpeg_pipeline/runtime/lib64",
                           "udp://192.168.2.165:1235?pkt_size=1316"};
        yw::Encoder encoder(c, running);
        uint64_t n = 0, gaps = 0;
        uint32_t prev = 0;
        auto start = yw::now_us();
        while (yw::now_us() - start < 10000000) {
            uint32_t seq;
            int64_t stamp;
            if (!camera->read(f.nv12->data(), seq, stamp))
                continue;
            if (n && seq > prev)
                gaps += seq - prev - 1;
            prev = seq;
            ++n;
            f.seq = n;
            f.captured = stamp;
            if (n <= 5)
                continue;
            p.run(f);
            encoder.write(f);
        }
        std::cout << "{\"io_only\":true,\"capture_count\":" << n
                  << ",\"fps\":" << n * 1000000. / (yw::now_us() - start) << ",\"gaps\":" << gaps
                  << "}\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
