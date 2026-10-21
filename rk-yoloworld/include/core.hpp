#pragma once
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <vector>
namespace yw {
inline volatile sig_atomic_t interrupted = 0;
inline int64_t now_us() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}
inline void require(bool ok, const char *why) {
    if (!ok)
        throw std::runtime_error(why);
}
// Waiting work only: deleting an item returns all shared pool leases
// immediately.
template <class T> class Queue {
    std::mutex mu;
    std::condition_variable cv;
    std::deque<T> q;
    size_t cap;
    bool closed = false;

  public:
    std::atomic<uint64_t> dropped{0};
    explicit Queue(size_t n) : cap(n) {
        require(n > 0, "zero queue capacity");
    }
    bool push(T t) {
        std::lock_guard<std::mutex> l(mu);
        if (closed)
            return false;
        if (q.size() == cap) {
            q.pop_front();
            ++dropped;
        }
        q.push_back(std::move(t));
        cv.notify_one();
        return true;
    }
    bool pop(T &t) {
        std::unique_lock<std::mutex> l(mu);
        cv.wait(l, [&] { return closed || !q.empty(); });
        if (q.empty())
            return false;
        t = std::move(q.front());
        q.pop_front();
        return true;
    }
    void stop() {
        std::lock_guard<std::mutex> l(mu);
        closed = true;
        q.clear();
        cv.notify_all();
    }
};
template <class T> class Latest {
    std::mutex mu;
    std::condition_variable cv;
    T slot{};
    uint64_t highest = 0;
    bool has = false, seen = false, closed = false;

  public:
    std::atomic<uint64_t> stale{0}, replaced{0};
    bool push(T t) {
        std::lock_guard<std::mutex> l(mu);
        if (closed)
            return false;
        if (seen && t->seq <= highest) {
            ++stale;
            return false;
        }
        highest = t->seq;
        seen = true;
        if (has)
            ++replaced;
        slot = std::move(t);
        has = true;
        cv.notify_one();
        return true;
    }
    bool pop(T &t) {
        std::unique_lock<std::mutex> l(mu);
        cv.wait(l, [&] { return closed || has; });
        if (!has)
            return false;
        t = std::move(slot);
        has = false;
        return true;
    }
    void stop() {
        std::lock_guard<std::mutex> l(mu);
        closed = true;
        slot = {};
        has = false;
        cv.notify_all();
    }
};
class Pool {
    struct State {
        std::mutex mu;
        std::vector<std::unique_ptr<std::vector<uint8_t>>> storage;
        std::vector<std::vector<uint8_t> *> free;
    };
    std::shared_ptr<State> state = std::make_shared<State>();

  public:
    Pool(size_t count, size_t bytes) {
        for (size_t i = 0; i < count; ++i) {
            state->storage.emplace_back(new std::vector<uint8_t>(bytes));
            state->free.push_back(state->storage.back().get());
        }
    }
    std::shared_ptr<std::vector<uint8_t>> acquire() {
        auto s = state;
        std::lock_guard<std::mutex> l(s->mu);
        if (s->free.empty())
            return {};
        auto *p = s->free.back();
        s->free.pop_back();
        return {p, [s](auto *v) {
                    std::lock_guard<std::mutex> g(s->mu);
                    s->free.push_back(v);
                }};
    }
};
struct Plane {
    const uint8_t *data;
    size_t mapped, used, offset, stride;
};
inline void pack_plane(const Plane &p, int width, int rows, uint8_t *dst) {
    require(width > 0 && rows > 0 && p.stride >= size_t(width), "invalid plane geometry");
    require(p.data && p.offset <= p.used && p.used <= p.mapped, "invalid plane offset/bytesused");
    const size_t need = size_t(rows - 1) * p.stride + width;
    require(need <= p.used - p.offset, "truncated plane");
    for (int y = 0; y < rows; ++y)
        std::memcpy(dst + size_t(y) * width, p.data + p.offset + size_t(y) * p.stride, width);
}
inline void pack_nv12(const std::vector<Plane> &planes, int w, int h, uint8_t *dst) {
    require(w > 0 && h > 0 && !(w % 2) && !(h % 2), "NV12 requires even dimensions");
    require(planes.size() == 1 || planes.size() == 2, "unsupported NV12 plane count");
    if (planes.size() == 2) {
        pack_plane(planes[0], w, h, dst);
        pack_plane(planes[1], w, h / 2, dst + size_t(w) * h);
    } else {
        auto p = planes[0];
        pack_plane(p, w, h, dst);
        size_t uv = p.offset + p.stride * size_t(h);
        require(uv >= p.offset, "offset overflow");
        p.offset = uv;
        pack_plane(p, w, h / 2, dst + size_t(w) * h);
    }
}
struct Box {
    float x1, y1, x2, y2, score;
    int cls;
};
struct Frame {
    uint64_t seq = 0;
    uint32_t driver_seq = 0;
    int64_t captured = 0;
    std::shared_ptr<std::vector<uint8_t>> nv12, rgb;
    float sx = 1, sy = 1;
    int pad_x = 0, pad_y = 0;
    std::vector<Box> boxes;
};
using Task = std::shared_ptr<Frame>;
inline float iou(const Box &a, const Box &b) {
    float v = std::max(0.f, std::min(a.x2, b.x2) - std::max(a.x1, b.x1)) *
              std::max(0.f, std::min(a.y2, b.y2) - std::max(a.y1, b.y1));
    float u = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - v;
    return u > 0 ? v / u : 0;
}
inline std::vector<Box> nms(std::vector<Box> all, float threshold) {
    std::stable_sort(all.begin(), all.end(), [](auto &a, auto &b) { return a.score > b.score; });
    std::vector<Box> result;
    for (auto &b : all) {
        bool keep = true;
        for (auto &a : result)
            if (a.cls == b.cls && iou(a, b) > threshold) {
                keep = false;
                break;
            }
        if (keep) {
            result.push_back(b);
            if (result.size() == 128)
                break;
        }
    }
    return result;
}
} // namespace yw
