#pragma once
#include "core.hpp"
#include <string>
namespace yw {
class Capture {
    struct Impl;
    std::unique_ptr<Impl> p;

  public:
    Capture(const std::string &device, int w, int h, int fps, int buffers);
    ~Capture();
    // Timeout returns false; malformed frames throw after QBUF.
    bool read(uint8_t *dst, uint32_t &sequence, int64_t &timestamp);
    int width() const;
    int height() const;
    bool full_range() const;
};
} // namespace yw
