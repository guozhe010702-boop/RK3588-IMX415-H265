#include "model.hpp"
#include "clip_tokenizer.h"
#include "rknn_api.h"
#include <cmath>
#include <cstdio>
#include <dlfcn.h>
#include <fstream>
#include <limits>
#include <sstream>
namespace yw {
struct Api {
    void *handle = nullptr;
#define FN(n) decltype(&::n) n = nullptr;
    FN(rknn_init)
    FN(rknn_destroy)
    FN(rknn_query)
    FN(rknn_set_core_mask)
    FN(rknn_inputs_set)
    FN(rknn_run) FN(rknn_outputs_get) FN(rknn_outputs_release)
#undef FN
        Api() {
        handle = dlopen("librknnrt.so", RTLD_NOW | RTLD_LOCAL);
        if (!handle)
            throw std::runtime_error(dlerror());
        try {
#define LOAD(n)                                                                                    \
    n = reinterpret_cast<decltype(n)>(dlsym(handle, #n));                                          \
    require(n != nullptr, "RKNN runtime missing " #n);
            LOAD(rknn_init)
            LOAD(rknn_destroy)
            LOAD(rknn_query)
            LOAD(rknn_set_core_mask)
            LOAD(rknn_inputs_set) LOAD(rknn_run) LOAD(rknn_outputs_get) LOAD(rknn_outputs_release)
#undef LOAD
        } catch (...) {
            dlclose(handle);
            handle = nullptr;
            throw;
        }
    }
    ~Api() {
        if (handle)
            dlclose(handle);
    }
};
static Api &api() {
    static Api instance;
    return instance;
}
static void check(int n, const char *op) {
    if (n < 0)
        throw std::runtime_error(std::string(op) + ": RKNN error " + std::to_string(n));
}
static void run_model(rknn_context context, const char *description) {
    rknn_run_extend extended{};
    extended.timeout_ms = 5000;
    extended.fence_fd = -1;
    check(api().rknn_run(context, &extended), description);
}
struct Model {
    rknn_context ctx = 0;
    std::vector<rknn_tensor_attr> in, out;
    Model(const std::string &path) {
        std::ifstream f(path, std::ios::binary);
        require(bool(f), "model missing");
        std::vector<char> data((std::istreambuf_iterator<char>(f)), {});
        require(!data.empty() && data.size() < std::numeric_limits<uint32_t>::max(),
                "invalid model size");
        check(api().rknn_init(&ctx, data.data(), data.size(), 0, nullptr),
              "init model (check runtime/driver compatibility)");
        try {
            rknn_input_output_num num{};
            check(api().rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &num, sizeof(num)), "query io");
            require(num.n_input > 0 && num.n_input <= 8 && num.n_output > 0 && num.n_output <= 32,
                    "unexpected tensor count");
            in.resize(num.n_input);
            out.resize(num.n_output);
            for (unsigned i = 0; i < in.size(); ++i) {
                in[i].index = i;
                check(api().rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &in[i], sizeof(in[i])),
                      "query input");
            }
            for (unsigned i = 0; i < out.size(); ++i) {
                out[i].index = i;
                check(api().rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &out[i], sizeof(out[i])),
                      "query output");
            }
            rknn_sdk_version ver{};
            check(api().rknn_query(ctx, RKNN_QUERY_SDK_VERSION, &ver, sizeof(ver)), "query sdk");
            fprintf(stderr, "model=%s runtime=%s driver=%s\n", path.c_str(), ver.api_version,
                    ver.drv_version);
            for (auto *list : {&in, &out})
                for (auto &a : *list) {
                    fprintf(stderr,
                            "tensor index=%u name=%s fmt=%d type=%d qnt=%d zp=%d "
                            "scale=%g dims=",
                            a.index, a.name, a.fmt, a.type, a.qnt_type, a.zp, a.scale);
                    for (unsigned j = 0; j < a.n_dims; ++j)
                        fprintf(stderr, "%u,", a.dims[j]);
                    fprintf(stderr, " elements=%u\n", a.n_elems);
                }
        } catch (...) {
            api().rknn_destroy(ctx);
            ctx = 0;
            throw;
        }
    }
    ~Model() {
        if (ctx)
            api().rknn_destroy(ctx);
    }
    Model(const Model &) = delete;
};
struct Outputs {
    Model &model;
    std::vector<rknn_output> buffers;
    bool acquired = false;
    explicit Outputs(Model &m) : model(m), buffers(m.out.size()) {
        for (unsigned i = 0; i < buffers.size(); ++i) {
            buffers[i].index = i;
            buffers[i].want_float = 1;
        }
        check(api().rknn_outputs_get(m.ctx, buffers.size(), buffers.data(), nullptr),
              "get outputs");
        acquired = true;
    }
    ~Outputs() {
        if (acquired)
            api().rknn_outputs_release(model.ctx, buffers.size(), buffers.data());
    }
};
Text encode_text(const std::string &model, const std::string &file) {
    Text t;
    std::ifstream f(file);
    require(bool(f), "classes file missing");
    std::string s;
    while (std::getline(f, s)) {
        if (!s.empty() && s.back() == '\r')
            s.pop_back();
        if (t.labels.empty() && s.compare(0, 3, "\xef\xbb\xbf") == 0)
            s.erase(0, 3);
        if (!s.empty())
            t.labels.push_back(s);
    }
    require(!t.labels.empty() && t.labels.size() <= 80,
            "classes must contain 1..80 nonempty prompts");
    Model m(model);
    require(m.in.size() == 1 && m.out.size() == 1, "unsupported CLIP layout");
    require(m.in[0].n_dims == 2 && m.in[0].dims[0] == 1 &&
                (m.in[0].type == RKNN_TENSOR_INT32 || m.in[0].type == RKNN_TENSOR_INT64),
            "CLIP requires batch=1 int32/int64 tokens");
    require(m.out[0].n_dims == 2 && m.out[0].dims[0] == 1, "unsupported CLIP output");
    t.dimension = m.out[0].n_elems;
    require(t.dimension > 0 && t.dimension <= 4096, "invalid CLIP embedding size");
    CLIPTokenizer tokenizer;
    for (auto &label : t.labels) {
        require(!interrupted, "text initialization interrupted");
        auto tokens = tokenizer.tokenize(label, m.in[0].n_elems, true);
        std::vector<int64_t> tokens64(tokens.begin(), tokens.end());
        require(tokens.size() == m.in[0].n_elems, "token length mismatch");
        rknn_input input{};
        input.index = 0;
        input.buf = m.in[0].type == RKNN_TENSOR_INT64 ? static_cast<void *>(tokens64.data())
                                                      : static_cast<void *>(tokens.data());
        input.size =
            tokens.size() * (m.in[0].type == RKNN_TENSOR_INT64 ? sizeof(int64_t) : sizeof(int32_t));
        input.type = m.in[0].type;
        input.fmt = RKNN_TENSOR_UNDEFINED;
        check(api().rknn_inputs_set(m.ctx, 1, &input), "CLIP input");
        run_model(m.ctx, "CLIP run");
        Outputs output(m);
        require(output.buffers[0].size >= t.dimension * sizeof(float), "truncated CLIP embedding");
        auto *begin = static_cast<float *>(output.buffers[0].buf);
        for (size_t i = 0; i < t.dimension; ++i)
            require(std::isfinite(begin[i]), "nonfinite CLIP embedding");
        t.embeddings.insert(t.embeddings.end(), begin, begin + t.dimension);
    }
    fprintf(stderr,
            "text_cache: startup_runs=%zu dimension=%zu (CLIP released before "
            "video)\n",
            t.labels.size(), t.dimension);
    return t;
}
struct Detector::Impl {
    Model m;
    const Text &text;
    std::vector<float> padded;
    int w = 0, h = 0;
    Impl(const std::string &path, const Text &t, int worker) : m(path), text(t) {
        require(worker >= 0 && worker < 9, "invalid worker");
        auto mask = static_cast<rknn_core_mask>(1 << (worker % 3));
        check(api().rknn_set_core_mask(m.ctx, mask), "set core mask");
        fprintf(stderr, "worker=%d core=%d mask=%d context=%llu\n", worker, worker % 3, int(mask),
                (unsigned long long)m.ctx);
        require(m.in.size() == 2, "YOLO requires image + text inputs");
        auto &a = m.in[0];
        require(a.n_dims == 4 && a.dims[0] == 1, "unsupported image tensor");
        if (a.fmt == RKNN_TENSOR_NHWC) {
            h = a.dims[1];
            w = a.dims[2];
            require(a.dims[3] == 3, "image must have 3 channels");
        } else {
            require(a.fmt == RKNN_TENSOR_NCHW && a.dims[1] == 3, "unsupported image format");
            h = a.dims[2];
            w = a.dims[3];
        }
        require(w > 0 && h > 0 && w <= 2048 && h <= 2048 && !(w % 2) && !(h % 2),
                "invalid model size");
        require(m.in[1].n_elems % t.dimension == 0, "text dimension mismatch");
        size_t capacity = m.in[1].n_elems / t.dimension;
        require(capacity >= t.labels.size() && capacity <= 80, "class capacity mismatch");
        padded.assign(m.in[1].n_elems, 0);
        std::copy(t.embeddings.begin(), t.embeddings.end(), padded.begin());
        require(m.out.size() == 6 || m.out.size() == 9,
                "unsupported YOLO head count (expected decoded distance heads)");
        unsigned step = m.out.size() / 3;
        for (unsigned i = 0; i < 3; ++i) {
            auto &s = m.out[i * step];
            auto &b = m.out[i * step + 1];
            require(s.n_dims == 4 && b.n_dims == 4 && s.fmt == RKNN_TENSOR_NCHW &&
                        b.fmt == RKNN_TENSOR_NCHW && s.dims[0] == 1 && b.dims[0] == 1 &&
                        b.dims[1] == 4 && s.dims[1] == capacity && s.dims[2] == b.dims[2] &&
                        s.dims[3] == b.dims[3] && b.dims[2] > 0 && b.dims[3] > 0,
                    "unsupported YOLO head shape");
        }
    }
};
Detector::Detector(const std::string &f, const Text &t, int n) : p(new Impl(f, t, n)) {}
Detector::~Detector() = default;
int Detector::width() const {
    return p->w;
}
int Detector::height() const {
    return p->h;
}
std::vector<Box> Detector::infer(const uint8_t *rgb) {
    rknn_input inputs[2]{};
    inputs[0].index = 0;
    inputs[0].buf = const_cast<uint8_t *>(rgb);
    inputs[0].size = p->w * p->h * 3;
    inputs[0].type = RKNN_TENSOR_UINT8;
    inputs[0].fmt = RKNN_TENSOR_NHWC;
    inputs[1].index = 1;
    inputs[1].buf = p->padded.data();
    inputs[1].size = p->padded.size() * 4;
    inputs[1].type = RKNN_TENSOR_FLOAT32;
    inputs[1].fmt = RKNN_TENSOR_UNDEFINED;
    check(api().rknn_inputs_set(p->m.ctx, 2, inputs), "YOLO input");
    run_model(p->m.ctx, "YOLO run");
    Outputs out(p->m);
    std::vector<Box> all;
    unsigned step = p->m.out.size() / 3;
    for (unsigned branch = 0; branch < 3; ++branch) {
        unsigned si = branch * step, bi = si + 1;
        auto &a = p->m.out[bi];
        int gh = a.dims[2], gw = a.dims[3], grid = gh * gw;
        require(out.buffers[si].size >= p->m.out[si].n_elems * 4 &&
                    out.buffers[bi].size >= a.n_elems * 4,
                "truncated YOLO output");
        auto *scores = static_cast<float *>(out.buffers[si].buf);
        auto *distances = static_cast<float *>(out.buffers[bi].buf);
        for (int cell = 0; cell < grid; ++cell) {
            float best = .25f;
            int cls = -1;
            for (size_t c = 0; c < p->text.labels.size(); ++c) {
                float score = scores[c * grid + cell];
                if (std::isfinite(score) && score > best) {
                    best = score;
                    cls = c;
                }
            }
            if (cls < 0)
                continue;
            float sx = float(p->w) / gw, sy = float(p->h) / gh, x = cell % gw + .5f,
                  y = cell / gw + .5f;
            Box b{(x - distances[cell]) * sx,
                  (y - distances[grid + cell]) * sy,
                  (x + distances[2 * grid + cell]) * sx,
                  (y + distances[3 * grid + cell]) * sy,
                  best,
                  cls};
            if (std::isfinite(b.x1) && std::isfinite(b.y1) && std::isfinite(b.x2) &&
                std::isfinite(b.y2) && b.x2 > b.x1 && b.y2 > b.y1)
                all.push_back(b);
        }
    }
    return nms(std::move(all), .45f);
}
} // namespace yw
