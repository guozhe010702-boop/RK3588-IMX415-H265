#ifndef EVM_MPP_H265_H
#define EVM_MPP_H265_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include <rockchip/rk_mpi.h>
#include <rockchip/rk_venc_cfg.h>
#include <rockchip/mpp_buffer.h>
#include <rockchip/mpp_frame.h>
#include <rockchip/mpp_packet.h>

typedef struct {
    MppCtx ctx;
    MppApi *mpi;
    MppEncCfg cfg;
    MppBufferGroup group;
    MppBuffer input;
    MppBuffer header;
    FILE *output;
    int width, height, stride, vstride, fps;
    uint64_t bytes;
    unsigned frames;
} H265Encoder;

int h265_encoder_open(H265Encoder *enc, FILE *output, int width, int height,
                      int bitrate, int fps);
int h265_encoder_frame(H265Encoder *enc,
                       const uint8_t *y, size_t y_size, size_t y_pitch,
                       const uint8_t *uv, size_t uv_size, size_t uv_pitch,
                       int last);
void h265_encoder_close(H265Encoder *enc);

#endif
