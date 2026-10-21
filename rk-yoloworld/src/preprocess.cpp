#include "model.hpp"
#include "im2d.h"
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
namespace yw {
struct HeapAllocation {
    uint64_t len;
    uint32_t fd, fd_flags;
    uint64_t heap_flags;
};
struct Dma {
    int fd = -1;
    void *data = MAP_FAILED;
    size_t size;
    explicit Dma(size_t n) : size(n) {
        int heap = open("/dev/dma_heap/system-dma32", O_RDWR | O_CLOEXEC);
        require(heap >= 0, "DMA32 heap unavailable; refusing unverified RGA buffer fallback");
        HeapAllocation a{};
        a.len = (n + 4095) & ~size_t(4095);
        a.fd_flags = O_RDWR | O_CLOEXEC;
        int r = ioctl(heap, _IOWR('H', 0, HeapAllocation), &a);
        close(heap);
        require(r == 0, "DMA allocation failed");
        fd = a.fd;
        data = mmap(nullptr, n, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        if (data == MAP_FAILED) {
            close(fd);
            fd = -1;
            throw std::runtime_error("DMA mmap failed");
        }
    }
    ~Dma() {
        if (data != MAP_FAILED)
            munmap(data, size);
        if (fd >= 0)
            close(fd);
    }
    void sync(bool end, bool write) {
        struct {
            uint64_t flags;
        } s{uint64_t((end ? 4 : 0) | (write ? 2 : 1))};
        require(ioctl(fd, _IOW('b', 0, decltype(s)), &s) == 0, "DMA cache sync failed");
    }
    void sync_rw(bool end) {
        struct {
            uint64_t flags;
        } s{uint64_t((end ? 4 : 0) | 3)};
        require(ioctl(fd, _IOW('b', 0, decltype(s)), &s) == 0, "DMA read/write cache sync failed");
    }
};
struct Preprocess::Impl {
    int sw, sh, mw, mh, rw, rh, px, py;
    bool full;
    Dma source, dest, intermediate;
    Impl(int w, int h, int m, int n, bool f)
        : sw(w), sh(h), mw(m), mh(n), full(f), source(size_t(w) * h * 3 / 2),
          dest(size_t(m) * n * 3), intermediate(size_t(m) * n * 3 / 2) {
        float scale = std::min(float(m) / w, float(n) / h);
        rw = std::max(2, int(w * scale) / 2 * 2);
        rh = std::max(2, int(h * scale) / 2 * 2);
        px = (mw - rw) / 2;
        py = (mh - rh) / 2;
    }
};
Preprocess::Preprocess(int w, int h, int m, int n, bool f) : p(new Impl(w, h, m, n, f)) {}
Preprocess::~Preprocess() = default;
void Preprocess::run(Frame &f) {
    p->source.sync(false, true);
    memcpy(p->source.data, f.nv12->data(), f.nv12->size());
    p->source.sync(true, true);
    p->dest.sync(false, true);
    memset(p->dest.data, 114, p->dest.size);
    p->dest.sync(true, true);
    auto src = wrapbuffer_fd_t(p->source.fd, p->sw, p->sh, p->sw, p->sh, RK_FORMAT_YCbCr_420_SP);
    auto dst = wrapbuffer_fd_t(p->dest.fd, p->mw, p->mh, p->mw, p->mh, RK_FORMAT_RGB_888);
    im_rect sr{0, 0, p->sw, p->sh}, dr{p->px, p->py, p->rw, p->rh};
    IM_STATUS r;
    if (p->full) {
        // This BSP cannot execute BT709-full CSC reliably. RGA still performs
        // resize + NV12->RGB. A small CPU range remap at MODEL resolution enables
        // the hardware's verified BT709-limited CSC without clipping RGB channels.
        p->intermediate.sync(false, true);
        memset(p->intermediate.data, 114, size_t(p->mw) * p->mh);
        memset(static_cast<uint8_t *>(p->intermediate.data) + size_t(p->mw) * p->mh, 128,
               size_t(p->mw) * p->mh / 2);
        p->intermediate.sync(true, true);
        auto mid =
            wrapbuffer_fd_t(p->intermediate.fd, p->mw, p->mh, p->mw, p->mh, RK_FORMAT_YCbCr_420_SP);
        r = improcess(src, mid, {}, sr, dr, {}, -1, nullptr, nullptr, IM_SYNC);
        if (r != IM_STATUS_SUCCESS)
            throw std::runtime_error(std::string("RGA full-range intermediate: ") +
                                     imStrError_t(r));
        p->intermediate.sync_rw(false);
        auto *values = static_cast<uint8_t *>(p->intermediate.data);
        const size_t pixels = size_t(p->mw) * p->mh;
        for (size_t i = 0; i < pixels; ++i)
            values[i] = 16 + (unsigned(values[i]) * 219 + 127) / 255;
        for (size_t i = pixels; i < pixels * 3 / 2; ++i)
            values[i] = 16 + (unsigned(values[i]) * 224 + 127) / 255;
        p->intermediate.sync_rw(true);
        r = imcvtcolor(mid, dst, RK_FORMAT_YCbCr_420_SP, RK_FORMAT_RGB_888,
                       IM_YUV_TO_RGB_BT709_LIMIT);
    } else {
        dst.color_space_mode = IM_YUV_TO_RGB_BT709_LIMIT;
        r = improcess(src, dst, {}, sr, dr, {}, -1, nullptr, nullptr, IM_SYNC);
    }
    if (r != IM_STATUS_SUCCESS)
        throw std::runtime_error(std::string("RGA preprocess failed: ") + imStrError_t(r));
    p->dest.sync(false, false);
    memcpy(f.rgb->data(), p->dest.data, p->dest.size);
    p->dest.sync(true, false);
    f.sx = float(p->rw) / p->sw;
    f.sy = float(p->rh) / p->sh;
    f.pad_x = p->px;
    f.pad_y = p->py;
}
} // namespace yw
