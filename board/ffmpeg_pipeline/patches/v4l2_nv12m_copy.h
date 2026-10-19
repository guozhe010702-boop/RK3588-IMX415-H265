/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Pack two independently mapped NV12M planes, respecting stride and offset.
 */
#ifndef V4L2_NV12M_COPY_H
#define V4L2_NV12M_COPY_H
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct V4L2Nv12mPlane {
    const uint8_t *data;
    size_t mapped_size, bytesused, data_offset, pitch;
} V4L2Nv12mPlane;

static int v4l2_nv12m_copy(uint8_t *out, size_t out_size,
                         const V4L2Nv12mPlane planes[2], int width, int height)
{
    size_t y_size, required;
    if (!out || !planes || width <= 0 || height <= 0 || (width & 1) || (height & 1))
        return -EINVAL;
    if ((size_t)height > SIZE_MAX / (size_t)width)
        return -EINVAL;
    y_size = (size_t)width * height;
    if (y_size > SIZE_MAX - y_size / 2)
        return -EINVAL;
    required = y_size + y_size / 2;
    if (out_size < required)
        return -EINVAL;
    for (int p = 0; p < 2; p++) {
        const V4L2Nv12mPlane *plane = &planes[p];
        size_t rows = p ? (size_t)height / 2 : (size_t)height;
        size_t available;
        if (!plane->data || plane->bytesused > plane->mapped_size ||
            plane->bytesused < plane->data_offset || plane->pitch < (size_t)width)
            return -EINVAL;
        available = plane->bytesused - plane->data_offset;
        if (available < (size_t)width || rows - 1 > (available - width) / plane->pitch)
            return -EINVAL;
    }
    for (int p = 0; p < 2; p++) {
        const V4L2Nv12mPlane *plane = &planes[p];
        size_t rows = p ? (size_t)height / 2 : (size_t)height;
        uint8_t *dest = out + (p ? y_size : 0);
        if (plane->pitch == (size_t)width)
            memcpy(dest, plane->data + plane->data_offset, rows * width);
        else
            for (size_t row = 0; row < rows; row++)
                memcpy(dest + row * width, plane->data + plane->data_offset + row * plane->pitch, width);
    }
    return 0;
}
#endif
