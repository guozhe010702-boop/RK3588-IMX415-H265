// Link-time syscall double. Exercises production Capture RAII without a camera.
#include "capture.hpp"
#include <cstdarg>
#include <cerrno>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <linux/v4l2-subdev.h>
#include <poll.h>
#include <sys/mman.h>
#include <iostream>
using namespace yw;
struct State {
    bool multi = true, timeout = false, busy = false, bad_format = false, bad_length = false,
         error_flag = false;
    int fail_map = 0, maps = 0, unmaps = 0, closed = 0, queued = 0, stream_on = 0, stream_off = 0;
    uint8_t bytes[6][64]{};
} s;
extern "C" {
int __real_open(const char *, int, ...);
int __wrap_open(const char *path, int flags, ...) {
    if (std::string(path) == "/dev/video44")
        return 7001;
    if (std::string(path) == "/dev/v4l-subdev2")
        return 7002;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        int mode = va_arg(ap, int);
        va_end(ap);
        return __real_open(path, flags, mode);
    }
    return __real_open(path, flags);
}
int __real_close(int);
int __wrap_close(int fd) {
    if (fd == 7001) {
        ++s.closed;
        return 0;
    }
    if (fd == 7002)
        return 0;
    return __real_close(fd);
}
void *__real_mmap(void *, size_t, int, int, int, off_t);
void *__wrap_mmap(void *ptr, size_t len, int prot, int flags, int fd, off_t offset) {
    if (fd != 7001)
        return __real_mmap(ptr, len, prot, flags, fd, offset);
    ++s.maps;
    if (s.fail_map == s.maps) {
        errno = ENOMEM;
        return MAP_FAILED;
    }
    return s.bytes[offset / 64];
}
int __real_munmap(void *, size_t);
int __wrap_munmap(void *ptr, size_t len) {
    for (auto &b : s.bytes)
        if (ptr == b) {
            ++s.unmaps;
            return 0;
        }
    return __real_munmap(ptr, len);
}
int __real_poll(pollfd *, nfds_t, int);
int __wrap_poll(pollfd *p, nfds_t n, int ms) {
    if (n == 1 && p->fd == 7001) {
        if (s.timeout)
            return 0;
        p->revents = POLLIN;
        return 1;
    }
    return __real_poll(p, n, ms);
}
int __wrap_ioctl(int fd, unsigned long op, ...) {
    va_list ap;
    va_start(ap, op);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    if (fd == 7002 && op == VIDIOC_SUBDEV_G_FRAME_INTERVAL) {
        auto *f = static_cast<v4l2_subdev_frame_interval *>(arg);
        f->interval = {1, 60};
        return 0;
    }
    if (fd != 7001) {
        errno = EINVAL;
        return -1;
    }
    if (op == VIDIOC_QUERYCAP) {
        auto *c = static_cast<v4l2_capability *>(arg);
        c->capabilities =
            V4L2_CAP_STREAMING | (s.multi ? V4L2_CAP_VIDEO_CAPTURE_MPLANE : V4L2_CAP_VIDEO_CAPTURE);
        return 0;
    }
    if (op == VIDIOC_S_FMT) {
        if (s.busy) {
            errno = EBUSY;
            return -1;
        }
        auto *f = static_cast<v4l2_format *>(arg);
        if (s.multi) {
            auto &p = f->fmt.pix_mp;
            p.width = 4;
            p.height = 2;
            p.pixelformat = s.bad_format ? V4L2_PIX_FMT_YUYV : V4L2_PIX_FMT_NV12M;
            p.num_planes = 2;
            p.quantization = V4L2_QUANTIZATION_FULL_RANGE;
            p.plane_fmt[0].bytesperline = 6;
            p.plane_fmt[1].bytesperline = 4;
        } else {
            auto &p = f->fmt.pix;
            p.width = 4;
            p.height = 2;
            p.pixelformat = V4L2_PIX_FMT_NV12;
            p.bytesperline = 6;
        }
        return 0;
    }
    if (op == VIDIOC_S_PARM) {
        errno = EINVAL;
        return -1;
    }
    if (op == VIDIOC_REQBUFS) {
        static_cast<v4l2_requestbuffers *>(arg)->count = 3;
        return 0;
    }
    if (op == VIDIOC_QUERYBUF) {
        auto *b = static_cast<v4l2_buffer *>(arg);
        if (s.multi) {
            for (int j = 0; j < 2; ++j) {
                b->m.planes[j].length = 64;
                b->m.planes[j].m.mem_offset = (b->index * 2 + j) * 64;
            }
        } else {
            b->length = 64;
            b->m.offset = b->index * 128;
        }
        return 0;
    }
    if (op == VIDIOC_QBUF) {
        ++s.queued;
        return 0;
    }
    if (op == VIDIOC_STREAMON) {
        ++s.stream_on;
        return 0;
    }
    if (op == VIDIOC_STREAMOFF) {
        ++s.stream_off;
        return 0;
    }
    if (op == VIDIOC_DQBUF) {
        auto *b = static_cast<v4l2_buffer *>(arg);
        b->index = 0;
        b->sequence = 42;
        b->flags = V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC | (s.error_flag ? V4L2_BUF_FLAG_ERROR : 0);
        b->timestamp = {1, 0};
        if (s.multi) {
            b->m.planes[0].bytesused = s.bad_length ? 6 : 12;
            b->m.planes[0].data_offset = 2;
            b->m.planes[1].bytesused = 7;
            b->m.planes[1].data_offset = 3;
        } else {
            b->bytesused = 18; /* Single planar has no data_offset. */
        }
        return 0;
    }
    errno = EINVAL;
    return -1;
}
}
static void reset() {
    s = State{};
    for (int i = 0; i < 4; ++i) {
        s.bytes[0][i + 2] = i + 1;
        s.bytes[0][i + 8] = i + 5;
        s.bytes[1][i + 3] = i + 9;
    }
}
template <class F> static void throws(F fn) {
    bool failed = false;
    try {
        fn();
    } catch (...) {
        failed = true;
    }
    require(failed, "expected capture rejection");
}
int main() {
    std::vector<uint8_t> pixels(12);
    uint32_t seq;
    int64_t time;
    reset();
    {
        Capture camera("/dev/video44", 4, 2, 60, 3);
        require(s.stream_on == 0, "stream started during initialization");
        require(camera.read(pixels.data(), seq, time), "valid frame unavailable");
        require(seq == 42 &&
                    pixels == std::vector<uint8_t>({1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}),
                "NV12M offset copy wrong");
        require(s.queued == 4, "frame not returned");
    }
    require(s.unmaps == 6 && s.closed == 1 && s.stream_off == 1, "normal cleanup failed");
    reset();
    s.multi = false;
    for (int i = 0; i < 4; ++i) {
        s.bytes[0][i] = i + 1;
        s.bytes[0][i + 6] = i + 5;
        s.bytes[0][i + 12] = i + 9;
    }
    {
        Capture camera("/dev/video44", 4, 2, 60, 3);
        require(camera.read(pixels.data(), seq, time), "single NV12 unavailable");
        require(pixels == std::vector<uint8_t>({1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}),
                "single NV12 stride wrong");
    }
    require(s.unmaps == 3 && s.closed == 1, "single plane cleanup failed");
    reset();
    s.timeout = true;
    {
        Capture camera("/dev/video44", 4, 2, 60, 3);
        require(!camera.read(pixels.data(), seq, time), "timeout became a frame");
        require(s.queued == 3, "timeout requeued an unowned buffer");
    }
    for (int flag = 0; flag < 2; ++flag) {
        reset();
        s.bad_length = flag == 0;
        s.error_flag = flag == 1;
        {
            Capture camera("/dev/video44", 4, 2, 60, 3);
            throws([&] { camera.read(pixels.data(), seq, time); });
            require(s.queued == 4, "bad frame not returned before throwing");
        }
        require(s.unmaps == 6 && s.closed == 1, "bad frame cleanup failed");
    }
    reset();
    s.fail_map = 2;
    throws([] { Capture c("/dev/video44", 4, 2, 60, 3); });
    require(s.unmaps == 1 && s.closed == 1, "partial mmap cleanup failed");
    reset();
    s.bad_format = true;
    throws([] { Capture c("/dev/video44", 4, 2, 60, 3); });
    require(s.closed == 1 && s.maps == 0, "format failure cleanup failed");
    reset();
    s.busy = true;
    throws([] { Capture c("/dev/video44", 4, 2, 60, 3); });
    require(s.closed == 1 && s.maps == 0, "busy failure cleanup failed");
    std::cout << "PASS: production Capture NV12/NV12M, deferred STREAMON, timeout, invalid format, "
                 "error flags, QBUF on errors, partial mmap cleanup (MOCK SYSCALLS)\n";
}
