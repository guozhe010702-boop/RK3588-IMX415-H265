// Test-only RKNN ABI implementation. Never distributed to the board runtime.
#include "rknn_api.h"
#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <vector>
struct Context {
    bool clip;
};
static std::mutex mu;
static std::map<rknn_context, Context> contexts;
static uint64_t next_id = 1;
static int releases = 0, runs = 0;
extern "C" {
int mock_alive() {
    return contexts.size();
}
int mock_releases() {
    return releases;
}
int mock_runs() {
    return runs;
}
int rknn_init(rknn_context *ctx, void *data, uint32_t size, uint32_t, rknn_init_extend *) {
    if (!size)
        return -1;
    std::lock_guard<std::mutex> l(mu);
    *ctx = next_id++;
    contexts[*ctx] = {*static_cast<char *>(data) == 'C'};
    return 0;
}
int rknn_destroy(rknn_context c) {
    std::lock_guard<std::mutex> l(mu);
    contexts.erase(c);
    return 0;
}
int rknn_set_core_mask(rknn_context, rknn_core_mask mask) {
    return std::getenv("MOCK_FAIL_MASK") && std::atoi(std::getenv("MOCK_FAIL_MASK")) == int(mask)
               ? -1
               : 0;
}
int rknn_query(rknn_context c, rknn_query_cmd cmd, void *ptr, uint32_t) {
    auto state = contexts.at(c);
    if (cmd == RKNN_QUERY_SDK_VERSION) {
        auto *v = static_cast<rknn_sdk_version *>(ptr);
        strcpy(v->api_version, "TEST MOCK");
        strcpy(v->drv_version, "NOT HARDWARE");
        return 0;
    }
    if (cmd == RKNN_QUERY_IN_OUT_NUM) {
        auto *n = static_cast<rknn_input_output_num *>(ptr);
        n->n_input = state.clip ? 1 : 2;
        n->n_output = state.clip ? 1 : 6;
        return 0;
    }
    auto *a = static_cast<rknn_tensor_attr *>(ptr);
    unsigned idx = a->index;
    memset(a, 0, sizeof(*a));
    a->index = idx;
    a->type = RKNN_TENSOR_FLOAT32;
    a->fmt = RKNN_TENSOR_NCHW;
    if (state.clip) {
        a->n_dims = 2;
        a->dims[0] = 1;
        a->dims[1] = cmd == RKNN_QUERY_INPUT_ATTR ? 77 : 16;
        if (cmd == RKNN_QUERY_INPUT_ATTR)
            a->type = RKNN_TENSOR_INT32;
    } else if (cmd == RKNN_QUERY_INPUT_ATTR && idx == 0) {
        a->fmt = RKNN_TENSOR_NHWC;
        a->n_dims = 4;
        a->dims[0] = 1;
        a->dims[1] = a->dims[2] = 64;
        a->dims[3] = 3;
        a->type = RKNN_TENSOR_UINT8;
    } else if (cmd == RKNN_QUERY_INPUT_ATTR) {
        a->n_dims = 3;
        a->dims[0] = 1;
        a->dims[1] = 80;
        a->dims[2] = 16;
    } else {
        a->n_dims = 4;
        a->dims[0] = 1;
        a->dims[1] = idx % 2 ? 4 : 80;
        a->dims[2] = a->dims[3] = 8 >> (idx / 2);
    }
    a->n_elems = 1;
    for (unsigned j = 0; j < a->n_dims; ++j)
        a->n_elems *= a->dims[j];
    a->size = a->n_elems * 4;
    return 0;
}
int rknn_inputs_set(rknn_context, uint32_t, rknn_input *) {
    return 0;
}
int rknn_run(rknn_context, rknn_run_extend *) {
    ++runs;
    return 0;
}
int rknn_outputs_get(rknn_context c, uint32_t n, rknn_output *out, rknn_output_extend *) {
    for (unsigned i = 0; i < n; ++i) {
        rknn_tensor_attr a{};
        a.index = i;
        rknn_query(c, RKNN_QUERY_OUTPUT_ATTR, &a, sizeof(a));
        out[i].size = a.n_elems * 4;
        out[i].buf = calloc(a.n_elems, 4);
        auto *values = static_cast<float *>(out[i].buf);
        if (contexts.at(c).clip) {
            values[0] = 1;
        } else if (i % 2 == 0) {
            int grid = a.dims[2] * a.dims[3];
            values[0] = .9f;
            values[grid] = .99f; /* padded class must not win */
        } else
            std::fill(values, values + a.n_elems, 1.f);
    }
    return 0;
}
int rknn_outputs_release(rknn_context, uint32_t n, rknn_output *out) {
    ++releases;
    for (unsigned i = 0; i < n; ++i)
        free(out[i].buf);
    return 0;
}
}
