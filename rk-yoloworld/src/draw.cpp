#include "model.hpp"
#include <cctype>
#include <cstdio>
namespace yw {
// 5x7 ASCII glyphs; unknown/non-ASCII prompts are rendered as '?', never
// corrupt bytes.
static const char *alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ.-_:%? ";
static const uint8_t glyphs[][5] = {
    {62, 81, 73, 69, 62},  {0, 66, 127, 64, 0},   {66, 97, 81, 73, 70},   {33, 65, 69, 75, 49},
    {24, 20, 18, 127, 16}, {39, 69, 69, 69, 57},  {60, 74, 73, 73, 48},   {1, 113, 9, 5, 3},
    {54, 73, 73, 73, 54},  {6, 73, 73, 41, 30},   {126, 17, 17, 17, 126}, {127, 73, 73, 73, 54},
    {62, 65, 65, 65, 34},  {127, 65, 65, 34, 28}, {127, 73, 73, 73, 65},  {127, 9, 9, 9, 1},
    {62, 65, 73, 73, 122}, {127, 8, 8, 8, 127},   {0, 65, 127, 65, 0},    {32, 64, 65, 63, 1},
    {127, 8, 20, 34, 65},  {127, 64, 64, 64, 64}, {127, 2, 12, 2, 127},   {127, 4, 8, 16, 127},
    {62, 65, 65, 65, 62},  {127, 9, 9, 9, 6},     {62, 65, 81, 33, 94},   {127, 9, 25, 41, 70},
    {70, 73, 73, 73, 49},  {1, 1, 127, 1, 1},     {63, 64, 64, 64, 63},   {31, 32, 64, 32, 31},
    {63, 64, 56, 64, 63},  {99, 20, 8, 20, 99},   {7, 8, 112, 8, 7},      {97, 81, 73, 69, 67},
    {0, 96, 96, 0, 0},     {8, 8, 8, 8, 8},       {64, 64, 64, 64, 64},   {0, 54, 54, 0, 0},
    {99, 19, 8, 100, 99},  {2, 1, 81, 9, 6},      {0, 0, 0, 0, 0}};
static void pixel(std::vector<uint8_t> &b, int w, int h, int x, int y, uint8_t Y, uint8_t U,
                  uint8_t V) {
    if (x < 0 || y < 0 || x >= w || y >= h)
        return;
    b[size_t(y) * w + x] = Y;
    size_t uv = size_t(w) * h + size_t(y / 2) * w + (x & ~1);
    b[uv] = U;
    b[uv + 1] = V;
}
static void text(std::vector<uint8_t> &b, int w, int h, int x, int y, const std::string &s) {
    for (unsigned char raw : s) {
        char c = raw < 128 ? std::toupper(raw) : '?';
        auto *pos = std::strchr(alphabet, c);
        size_t idx = pos ? pos - alphabet : 41;
        for (int dx = 0; dx < 5; ++dx)
            for (int dy = 0; dy < 7; ++dy)
                if (glyphs[idx][dx] & (1 << dy))
                    for (int a = 0; a < 2; ++a)
                        for (int z = 0; z < 2; ++z)
                            pixel(b, w, h, x + dx * 2 + a, y + dy * 2 + z, 235, 128, 128);
        x += 12;
        if (x > w - 12)
            break;
    }
}
void draw_nv12(Frame &f, int w, int h, const std::vector<std::string> &labels) {
    auto &b = *f.nv12;
    for (auto box : f.boxes) {
        int x1 = std::clamp(int((box.x1 - f.pad_x) / f.sx), 0, w - 1),
            y1 = std::clamp(int((box.y1 - f.pad_y) / f.sy), 0, h - 1),
            x2 = std::clamp(int((box.x2 - f.pad_x) / f.sx), 0, w - 1),
            y2 = std::clamp(int((box.y2 - f.pad_y) / f.sy), 0, h - 1);
        if (x2 <= x1 || y2 <= y1)
            continue;
        for (int n = 0; n < 3; ++n) {
            for (int x = x1; x <= x2; ++x) {
                pixel(b, w, h, x, y1 + n, 180, 45, 45);
                pixel(b, w, h, x, y2 - n, 180, 45, 45);
            }
            for (int y = y1; y <= y2; ++y) {
                pixel(b, w, h, x1 + n, y, 180, 45, 45);
                pixel(b, w, h, x2 - n, y, 180, 45, 45);
            }
        }
        char value[32];
        snprintf(value, sizeof(value), " %.0f%%", box.score * 100);
        auto label = labels.at(box.cls) + value;
        int ty = std::max(0, y1 - 18);
        for (int y = ty; y < std::min(h, ty + 17); ++y)
            for (int x = x1; x < std::min(w, x1 + int(label.size()) * 12); ++x)
                pixel(b, w, h, x, y, 24, 128, 128);
        text(b, w, h, x1, ty + 1, label);
    }
    text(b, w, h, 12, 12, "FRAME " + std::to_string(f.seq));
}
} // namespace yw
