#include <assert.h>
#include <stdio.h>
#include "../patches/v4l2_nv12m_copy.h"

int main(void)
{
    /* Distinct Y/UV bytes, two nonzero offsets and independent padded pitches. */
    const uint8_t y[] = {99,99, 1,2,3,4,88,88, 5,6,7,8,88,88};
    const uint8_t uv[] = {99, 10,20,30,40,88,88,88};
    const uint8_t expected[] = {1,2,3,4,5,6,7,8,10,20,30,40};
    uint8_t out[12] = {0};
    V4L2Nv12mPlane planes[2] = {{y,sizeof(y),sizeof(y),2,6}, {uv,sizeof(uv),sizeof(uv),1,7}};
    assert(v4l2_nv12m_copy(out,sizeof(out),planes,4,2) == 0);
    assert(memcmp(out,expected,sizeof(out)) == 0);
    /* Packed planes exercise the bulk-copy path, preserving nonzero offsets. */
    const uint8_t packed_y[] = {99,1,2,3,4,5,6,7,8};
    const uint8_t packed_uv[] = {99,10,20,30,40};
    V4L2Nv12mPlane packed[2] = {{packed_y,9,9,1,4}, {packed_uv,5,5,1,4}};
    assert(v4l2_nv12m_copy(out,sizeof(out),packed,4,2) == 0);
    assert(memcmp(out,expected,sizeof(out)) == 0);
    packed[0].bytesused--;
    assert(v4l2_nv12m_copy(out,sizeof(out),packed,4,2) < 0);
    planes[1].bytesused = 4;
    assert(v4l2_nv12m_copy(out,sizeof(out),planes,4,2) < 0);
    planes[1].bytesused = sizeof(uv) + 1;
    assert(v4l2_nv12m_copy(out,sizeof(out),planes,4,2) < 0);
    planes[1].bytesused = sizeof(uv); planes[1].data_offset = sizeof(uv) + 1;
    assert(v4l2_nv12m_copy(out,sizeof(out),planes,4,2) < 0);
    planes[1].data_offset = 1; planes[0].pitch = 3;
    assert(v4l2_nv12m_copy(out,sizeof(out),planes,4,2) < 0);
    planes[0].pitch = 6;
    assert(v4l2_nv12m_copy(out,11,planes,4,2) < 0);
    assert(v4l2_nv12m_copy(out,sizeof(out),planes,3,2) < 0);
    assert(v4l2_nv12m_copy(out,sizeof(out),planes,4,0) < 0);
    puts("NV12M packing: stride, plane identity, offsets, bounds and dimensions OK");
    return 0;
}
