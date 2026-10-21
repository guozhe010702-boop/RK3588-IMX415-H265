#pragma once
#include "core.hpp"
#include <string>
namespace yw {
struct Text {
    std::vector<std::string> labels;
    std::vector<float> embeddings;
    size_t dimension = 0;
};
Text encode_text(const std::string &model, const std::string &classes);
class Detector {
    struct Impl;
    std::unique_ptr<Impl> p;

  public:
    Detector(const std::string &path, const Text &, int worker);
    ~Detector();
    int width() const;
    int height() const;
    std::vector<Box> infer(const uint8_t *rgb);
};
class Preprocess {
    struct Impl;
    std::unique_ptr<Impl> p;

  public:
    Preprocess(int source_w, int source_h, int model_w, int model_h, bool full_range);
    ~Preprocess();
    void run(Frame &f);
};
void draw_nv12(Frame &, int w, int h, const std::vector<std::string> &labels);
} // namespace yw
