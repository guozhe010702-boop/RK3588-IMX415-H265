#include "core.hpp"
#include <future>
#include <iostream>
using namespace yw;
static void expect(bool v) {
    if (!v)
        throw std::runtime_error("test failed");
}
template <class F> static void rejects(F f) {
    bool threw = false;
    try {
        f();
    } catch (const std::runtime_error &) {
        threw = true;
    }
    expect(threw);
}
int main() {
    // Strided Y/UV, nonzero independent plane offsets, sentinel padding.
    std::vector<uint8_t> y = {99, 99, 1, 2, 3, 4, 99, 99, 5, 6, 7, 8}, uv = {99, 9, 10, 11, 12},
                         dst(12);
    pack_nv12({{y.data(), y.size(), y.size(), 2, 6}, {uv.data(), uv.size(), uv.size(), 1, 4}}, 4, 2,
              dst.data());
    expect(dst == std::vector<uint8_t>({1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}));
    rejects([&] {
        pack_nv12({{y.data(), y.size(), 6, 2, 6}, {uv.data(), uv.size(), uv.size(), 1, 4}}, 4, 2,
                  dst.data());
    });
    rejects([&] { pack_nv12({{y.data(), y.size(), 13, 0, 4}}, 4, 2, dst.data()); });
    rejects([&] { pack_nv12({{y.data(), y.size(), 1, 2, 4}}, 4, 2, dst.data()); });
    std::vector<uint8_t> single = {99, 1, 2, 3, 4, 99, 99, 5, 6, 7, 8, 99, 99, 9, 10, 11, 12};
    pack_nv12({{single.data(), single.size(), single.size(), 1, 6}}, 4, 2, dst.data());
    expect(dst == std::vector<uint8_t>({1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}));
    Pool pool(2, 16);
    auto a = pool.acquire(), b = pool.acquire();
    expect(a && b && !pool.acquire());
    a.reset();
    expect(bool(pool.acquire()));
    Queue<Task> q(2);
    for (int i = 1; i <= 3; ++i) {
        auto f = std::make_shared<Frame>();
        f->seq = i;
        q.push(f);
    }
    Task f;
    q.pop(f);
    expect(f->seq == 2 && q.dropped == 1);
    q.pop(f);
    expect(f->seq == 3);
    q.stop();
    expect(!q.pop(f));
    Latest<Task> latest;
    auto push = [&](int seq) {
        auto f = std::make_shared<Frame>();
        f->seq = seq;
        return latest.push(f);
    };
    expect(push(9));
    expect(!push(8));
    expect(push(11));
    latest.pop(f);
    expect(f->seq == 11);
    expect(!push(10));
    expect(latest.stale == 2 && latest.replaced == 1);
    latest.stop();
    expect(!latest.pop(f));
    Queue<int> blocked(1);
    auto waiter = std::async(std::launch::async, [&] {
        int v;
        return blocked.pop(v);
    });
    blocked.stop();
    expect(waiter.wait_for(std::chrono::seconds(1)) == std::future_status::ready && !waiter.get());
    auto boxes =
        nms({{0, 0, 10, 10, .9f, 0}, {0, 0, 10, 10, .8f, 0}, {0, 0, 10, 10, .7f, 1}}, .45f);
    expect(boxes.size() == 2 && boxes[1].cls == 1);
    // Concurrency: workers finish in reversed order, latest result never
    // regresses.
    Latest<Task> concurrent;
    std::vector<std::future<void>> workers;
    for (int i = 0; i < 9; ++i)
        workers.emplace_back(std::async(std::launch::async, [&, i] {
            auto f = std::make_shared<Frame>();
            f->seq = i + 1;
            std::this_thread::sleep_for(std::chrono::milliseconds(9 - i));
            concurrent.push(f);
        }));
    for (auto &t : workers)
        t.get();
    concurrent.pop(f);
    expect(f->seq == 9);
    concurrent.stop();
    std::cout << "PASS: plane bounds/stride/offset; pool leases; queue "
                 "drops/shutdown; sequence guard; concurrent ordering; NMS\n";
}
