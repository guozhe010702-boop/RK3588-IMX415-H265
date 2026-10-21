#include "model.hpp"
#include <fstream>
#include <iostream>
#include <thread>
#include <mutex>
using namespace yw;
static void compare(const std::vector<Box> &a, const std::vector<Box> &b) {
    require(a.size() == b.size(), "concurrent box count differs");
    for (size_t i = 0; i < a.size(); ++i)
        require(a[i].cls == b[i].cls && std::abs(a[i].score - b[i].score) < .002 &&
                    std::abs(a[i].x1 - b[i].x1) < 1 && std::abs(a[i].y1 - b[i].y1) < 1 &&
                    std::abs(a[i].x2 - b[i].x2) < 1 && std::abs(a[i].y2 - b[i].y2) < 1,
                "concurrent box mismatch");
}
int main(int argc, char **argv) {
    try {
        require(argc == 2, "picture_parity expects a model-sized RGB fixture");
        std::ifstream file(argv[1], std::ios::binary);
        std::vector<uint8_t> rgb((std::istreambuf_iterator<char>(file)), {});
        auto text = encode_text("model/clip_text_fp16.rknn", "model/detect_classes.txt");
        {
            std::vector<std::unique_ptr<Detector>> contexts;
            for (int i = 0; i < 9; ++i)
                contexts.emplace_back(new Detector("model/yolo_world_v2s_i8.rknn", text, i));
            require(rgb.size() == size_t(contexts[0]->width()) * contexts[0]->height() * 3,
                    "fixture dimensions mismatch");
            auto expected = contexts[0]->infer(rgb.data());
            require(!expected.empty(), "known image detected nothing");
            std::vector<std::vector<Box>> results(9);
            std::vector<std::thread> workers;
            std::mutex mu;
            std::exception_ptr error;
            for (int i = 0; i < 9; ++i)
                workers.emplace_back([&, i] {
                    try {
                        results[i] = contexts[i]->infer(rgb.data());
                    } catch (...) {
                        std::lock_guard<std::mutex> l(mu);
                        if (!error)
                            error = std::current_exception();
                    }
                });
            for (auto &t : workers)
                t.join();
            if (error)
                std::rethrow_exception(error);
            for (auto &actual : results)
                compare(expected, actual);
            std::cout << "{\"test\":\"real_concurrent_picture\",\"contexts\":9,\"boxes\":[";
            for (size_t i = 0; i < expected.size(); ++i) {
                auto &b = expected[i];
                if (i)
                    std::cout << ',';
                std::cout << "{\"class\":" << b.cls << ",\"score\":" << b.score
                          << ",\"x1\":" << b.x1 << ",\"y1\":" << b.y1 << ",\"x2\":" << b.x2
                          << ",\"y2\":" << b.y2 << '}';
            }
            std::cout << "],\"parity\":true}\n";
        }
        std::ofstream("one-class-test.txt") << "bus\n";
        auto one = encode_text("model/clip_text_fp16.rknn", "one-class-test.txt");
        Detector single("model/yolo_world_v2s_i8.rknn", one, 0);
        auto result = single.infer(rgb.data());
        require(!result.empty(), "single bus class produced no result");
        for (auto &b : result)
            require(b.cls == 0, "padded class escaped mask");
        std::cout << "{\"test\":\"real_single_class\",\"active_classes\":1,\"boxes\":"
                  << result.size() << ",\"passed\":true}\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
