/* Minimal H.265 MPP encode_put_frame / encode_get_packet path. */
#define MODULE_TAG "evm_mpp_h265"
#include "mpp_h265.h"

#include <string.h>

#define ALIGN16(x) (((x) + 15) & ~15)

static int cfg_s32(H265Encoder *enc, const char *key, RK_S32 value)
{
    MPP_RET ret = mpp_enc_cfg_set_s32(enc->cfg, key, value);
    if (ret != MPP_OK)
        fprintf(stderr, "MPP config %s=%d failed: %d\n", key, value, ret);
    return ret == MPP_OK ? 0 : -1;
}

static int write_packet(H265Encoder *enc, MppPacket packet)
{
    size_t len = mpp_packet_get_length(packet);
    if (len && fwrite(mpp_packet_get_pos(packet), 1, len, enc->output) != len) {
        perror("write H.265 packet");
        return -1;
    }
    enc->bytes += len;
    return 0;
}

void h265_encoder_close(H265Encoder *enc)
{
    if (enc->header) mpp_buffer_put(enc->header);
    if (enc->input) mpp_buffer_put(enc->input);
    if (enc->group) mpp_buffer_group_put(enc->group);
    if (enc->cfg) mpp_enc_cfg_deinit(enc->cfg);
    if (enc->ctx) mpp_destroy(enc->ctx);
    memset(enc, 0, sizeof(*enc));
}

int h265_encoder_open(H265Encoder *enc, FILE *output, int width, int height,
                      int bitrate, int fps)
{
    MppPollType timeout = MPP_POLL_BLOCK;
    MppEncHeaderMode header_mode = MPP_ENC_HEADER_MODE_EACH_IDR;
    MppPacket packet = NULL;
    size_t frame_size;
    MPP_RET ret;

    memset(enc, 0, sizeof(*enc));
    if (!output || width < 96 || height < 64 || width > 8192 || height > 8192 ||
        (width & 1) || (height & 1) || bitrate < 100000 ||
        bitrate > 100000000 || fps < 1 || fps > 120) {
        fprintf(stderr, "Invalid H.265 dimensions, bitrate or frame rate\n");
        return -1;
    }
    enc->output = output;
    enc->width = width;
    enc->height = height;
    enc->stride = ALIGN16(width);
    enc->vstride = ALIGN16(height);
    enc->fps = fps;
    frame_size = (size_t)enc->stride * enc->vstride * 3 / 2;

    ret = mpp_create(&enc->ctx, &enc->mpi);
    if (ret != MPP_OK) goto fail;
    ret = enc->mpi->control(enc->ctx, MPP_SET_OUTPUT_TIMEOUT, &timeout);
    if (ret != MPP_OK) goto fail;
    ret = mpp_init(enc->ctx, MPP_CTX_ENC, MPP_VIDEO_CodingHEVC);
    if (ret != MPP_OK) goto fail;
    ret = mpp_enc_cfg_init(&enc->cfg);
    if (ret != MPP_OK) goto fail;
    ret = enc->mpi->control(enc->ctx, MPP_ENC_GET_CFG, enc->cfg);
    if (ret != MPP_OK) goto fail;

    if (cfg_s32(enc, "prep:width", width) ||
        cfg_s32(enc, "prep:height", height) ||
        cfg_s32(enc, "prep:hor_stride", enc->stride) ||
        cfg_s32(enc, "prep:ver_stride", enc->vstride) ||
        cfg_s32(enc, "prep:format", MPP_FMT_YUV420SP) ||
        cfg_s32(enc, "rc:mode", MPP_ENC_RC_MODE_CBR) ||
        cfg_s32(enc, "rc:bps_target", bitrate) ||
        cfg_s32(enc, "rc:bps_max", bitrate * 17 / 16) ||
        cfg_s32(enc, "rc:bps_min", bitrate * 15 / 16) ||
        cfg_s32(enc, "rc:fps_in_num", fps) ||
        cfg_s32(enc, "rc:fps_in_denorm", 1) ||
        cfg_s32(enc, "rc:fps_out_num", fps) ||
        cfg_s32(enc, "rc:fps_out_denorm", 1) ||
        cfg_s32(enc, "rc:gop", fps) ||
        cfg_s32(enc, "codec:type", MPP_VIDEO_CodingHEVC))
        goto fail;

    ret = enc->mpi->control(enc->ctx, MPP_ENC_SET_CFG, enc->cfg);
    if (ret != MPP_OK) goto fail;
    ret = enc->mpi->control(enc->ctx, MPP_ENC_SET_HEADER_MODE, &header_mode);
    if (ret != MPP_OK) goto fail;

    ret = mpp_buffer_group_get_internal(&enc->group, MPP_BUFFER_TYPE_DRM);
    if (ret != MPP_OK) goto fail;
    ret = mpp_buffer_group_limit_config(enc->group, frame_size, 2);
    if (ret != MPP_OK) goto fail;
    ret = mpp_buffer_get(enc->group, &enc->input, frame_size);
    if (ret != MPP_OK) goto fail;
    ret = mpp_buffer_get(enc->group, &enc->header, 65536);
    if (ret != MPP_OK) goto fail;
    memset(mpp_buffer_get_ptr(enc->input), 0, frame_size);

    ret = mpp_packet_init_with_buffer(&packet, enc->header);
    if (ret != MPP_OK) goto fail;
    mpp_packet_set_length(packet, 0);
    ret = enc->mpi->control(enc->ctx, MPP_ENC_GET_HDR_SYNC, packet);
    if (ret == MPP_OK && write_packet(enc, packet) != 0) ret = MPP_NOK;
    mpp_packet_deinit(&packet);
    if (ret != MPP_OK) goto fail;

    fprintf(stderr, "MPP H.265: %dx%d stride=%dx%d, %d bps, %d fps\n",
            width, height, enc->stride, enc->vstride, bitrate, fps);
    return 0;

fail:
    if (packet) mpp_packet_deinit(&packet);
    fprintf(stderr, "MPP H.265 initialization failed: %d\n", ret);
    h265_encoder_close(enc);
    return -1;
}

static int enough_rows(size_t size, size_t pitch, int rows, int width)
{
    return pitch >= (size_t)width &&
           size >= (size_t)(rows - 1) * pitch + (size_t)width;
}

int h265_encoder_frame(H265Encoder *enc,
                       const uint8_t *y, size_t y_size, size_t y_pitch,
                       const uint8_t *uv, size_t uv_size, size_t uv_pitch,
                       int last)
{
    uint8_t *dest = mpp_buffer_get_ptr(enc->input);
    MppFrame frame = NULL;
    MppPacket packet = NULL;
    MPP_RET ret;
    int done;

    if (!y || !uv || !dest ||
        !enough_rows(y_size, y_pitch, enc->height, enc->width) ||
        !enough_rows(uv_size, uv_pitch, enc->height / 2, enc->width)) {
        fprintf(stderr, "Invalid NV12 plane size or stride\n");
        return -1;
    }
    for (int row = 0; row < enc->height; row++)
        memcpy(dest + (size_t)row * enc->stride, y + (size_t)row * y_pitch,
               enc->width);
    dest += (size_t)enc->stride * enc->vstride;
    for (int row = 0; row < enc->height / 2; row++)
        memcpy(dest + (size_t)row * enc->stride, uv + (size_t)row * uv_pitch,
               enc->width);

    ret = mpp_frame_init(&frame);
    if (ret != MPP_OK) return -1;
    mpp_frame_set_buffer(frame, enc->input);
    mpp_frame_set_width(frame, enc->width);
    mpp_frame_set_height(frame, enc->height);
    mpp_frame_set_hor_stride(frame, enc->stride);
    mpp_frame_set_ver_stride(frame, enc->vstride);
    mpp_frame_set_fmt(frame, MPP_FMT_YUV420SP);
    mpp_frame_set_pts(frame, (RK_S64)enc->frames * 1000000 / enc->fps);
    mpp_frame_set_eos(frame, last);
    ret = enc->mpi->encode_put_frame(enc->ctx, frame);
    mpp_frame_deinit(&frame);
    if (ret != MPP_OK) {
        fprintf(stderr, "encode_put_frame failed: %d\n", ret);
        return -1;
    }

    do {
        ret = enc->mpi->encode_get_packet(enc->ctx, &packet);
        if (ret != MPP_OK || !packet) {
            fprintf(stderr, "encode_get_packet failed: %d\n", ret);
            return -1;
        }
        done = !mpp_packet_is_partition(packet) || mpp_packet_is_eoi(packet);
        ret = write_packet(enc, packet) == 0 ? MPP_OK : MPP_NOK;
        mpp_packet_deinit(&packet);
        if (ret != MPP_OK) return -1;
    } while (!done);

    enc->frames++;
    return 0;
}
