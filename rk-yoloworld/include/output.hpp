#pragma once
#include "core.hpp"
#include <string>
namespace yw {
struct OutputConfig {
    std::string ffmpeg, ffmpeg_lib, url;
    int w = 2560, h = 1440, fps = 60, bitrate = 40000000, gop = 10;
    bool local_preview = false;
};
std::vector<std::string> encoder_arguments(const OutputConfig &);
class Encoder {
    struct Impl;
    std::unique_ptr<Impl> p;

  public:
    Encoder(const OutputConfig &, std::atomic<bool> &running);
    ~Encoder();
    void write(const Frame &);
};
// Testable muxer also used by the real encoder process.
class Nut {
    struct Impl;
    std::unique_ptr<Impl> p;

  public:
    Nut(int fd, int w, int h, int max_fps, std::atomic<bool> &running);
    ~Nut();
    void write(const uint8_t *, size_t, int64_t pts_us);
};
} // namespace yw
