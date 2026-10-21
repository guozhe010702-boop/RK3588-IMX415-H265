#include "output.hpp"
#include <csignal>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>
#include <thread>
using namespace yw;
int main() {
    OutputConfig options{"/bin/false", "", "udp://192.168.2.165:1235?pkt_size=1316"};
    auto single = encoder_arguments(options);
    require(single.back() == options.url, "single destination changed");
    options.local_preview = true;
    auto mirrored = encoder_arguments(options);
    require(mirrored[mirrored.size() - 2] == "tee" &&
                mirrored.back().find("udp://127.0.0.1:1236") != std::string::npos,
            "preview must mirror one encoded stream");
    require(std::count(mirrored.begin(), mirrored.end(), "h264_rkmpp") == 1 &&
                std::find(mirrored.begin(), mirrored.end(), "passthrough") != mirrored.end(),
            "tee changed codec or timestamp policy");
    bool invalid = false;
    options.url += "|untrusted";
    try {
        encoder_arguments(options);
    } catch (...) {
        invalid = true;
    }
    require(invalid, "reserved tee separator was accepted");
    signal(SIGPIPE, SIG_IGN);
    std::atomic<bool> running{true};
    int fds[2];
    require(pipe2(fds, O_NONBLOCK | O_CLOEXEC) == 0, "test pipe failed");
    close(fds[0]);
    bool broke = false;
    try {
        Nut mux(fds[1], 64, 64, 60, running);
        std::vector<uint8_t> b(6144, 128);
        mux.write(b.data(), b.size(), 0);
    } catch (...) {
        broke = true;
    }
    close(fds[1]);
    require(broke, "closed encoder pipe not detected");
    require(pipe2(fds, O_NONBLOCK | O_CLOEXEC) == 0, "test pipe failed");
    bool stalled = false;
    auto start = now_us();
    try {
        Nut mux(fds[1], 64, 64, 60, running);
        std::vector<uint8_t> b(6144, 128);
        for (int i = 0; i < 100; ++i)
            mux.write(b.data(), b.size(), i * 20000);
    } catch (...) {
        stalled = true;
    }
    close(fds[0]);
    close(fds[1]);
    require(stalled && now_us() - start < 6000000, "blocked pipe deadline failed");
    // Regression: a normal stop request must not truncate an already-started frame.
    require(pipe2(fds, O_NONBLOCK | O_CLOEXEC) == 0, "test pipe failed");
    std::atomic<size_t> received{0};
    running = true;
    std::thread reader([&] {
        uint8_t buffer[8192];
        while (true) {
            auto n = read(fds[0], buffer, sizeof(buffer));
            if (n > 0) {
                received += n;
                running = false;
            } else if (n == 0)
                break;
            else if (errno == EAGAIN || errno == EINTR)
                usleep(1000);
            else
                break;
        }
    });
    bool complete = false;
    try {
        {
            Nut mux(fds[1], 640, 480, 60, running);
            std::vector<uint8_t> image(640 * 480 * 3 / 2, 128);
            mux.write(image.data(), image.size(), 0);
            complete = true;
        }
    } catch (...) {
    }
    close(fds[1]);
    reader.join();
    close(fds[0]);
    require(complete && received >= 640 * 480 * 3 / 2, "normal stop truncated a frame");
    running = true;
    {
        OutputConfig c{"/bin/false", "", "udp://127.0.0.1:1235"};
        c.w = c.h = 64;
        bool exited = false;
        try {
            Encoder encoder(c, running);
            Frame frame;
            frame.nv12 = std::make_shared<std::vector<uint8_t>>(6144, 128);
            frame.captured = 1;
            for (int i = 0; i < 100; ++i) {
                frame.captured += 20000;
                encoder.write(frame);
            }
        } catch (...) {
            exited = true;
        }
        require(exited, "encoder exit not detected");
    }
    std::cout << "PASS: EPIPE, encoder exit/reaping, backpressure deadline\n";
}
