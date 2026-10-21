#include "model.hpp"
#include <dlfcn.h>
#include <fstream>
#include <iostream>
using namespace yw;
int main() {
    std::ofstream("mock_clip.rknn") << "C";
    std::ofstream("mock_yolo.rknn") << "Y";
    std::ofstream("mock_classes.txt") << "person\n";
    auto text = encode_text("mock_clip.rknn", "mock_classes.txt");
    require(text.dimension == 16 && text.labels.size() == 1, "text cache failed");
    void *mock = dlopen("librknnrt.so", RTLD_NOW);
    auto alive = reinterpret_cast<int (*)()>(dlsym(mock, "mock_alive"));
    auto runs = reinterpret_cast<int (*)()>(dlsym(mock, "mock_runs"));
    auto releases = reinterpret_cast<int (*)()>(dlsym(mock, "mock_releases"));
    require(alive() == 0 && runs() == 1 && releases() == 1, "CLIP lifecycle failed");
    {
        std::vector<std::unique_ptr<Detector>> contexts;
        std::vector<uint8_t> rgb(64 * 64 * 3);
        for (int i = 0; i < 9; ++i) {
            contexts.emplace_back(new Detector("mock_yolo.rknn", text, i));
            auto result = contexts.back()->infer(rgb.data());
            require(!result.empty(), "postprocess empty");
            for (auto &box : result)
                require(box.cls == 0, "padded class was selected");
        }
        require(alive() == 9 && runs() == 10 && releases() == 10,
                "context/output ownership failed");
    }
    require(alive() == 0, "context leak");
    setenv("MOCK_FAIL_MASK", "2", 1);
    bool threw = false;
    try {
        Detector bad("mock_yolo.rknn", text, 1);
    } catch (...) {
        threw = true;
    }
    unsetenv("MOCK_FAIL_MASK");
    require(threw && alive() == 0, "failed initialization leaked context");
    std::cout << "PASS: CLIP startup cache/release; 9 context ownership; padded class mask; output "
                 "release; bind failure cleanup (MOCK ONLY)\n";
    dlclose(mock);
}
