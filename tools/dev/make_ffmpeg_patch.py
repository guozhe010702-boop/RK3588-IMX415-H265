"""Create the pinned FFmpeg NV12M compatibility patch from pristine sources."""
from pathlib import Path
import difflib
import urllib.request
ROOT = Path(__file__).resolve().parents[2]
source = ROOT / '.cache/ffmpeg-upstream/libavdevice'
source.mkdir(parents=True,exist_ok=True)
for name in ('v4l2.c','v4l2-common.c'):
    if not (source/name).exists():
        urllib.request.urlretrieve('https://raw.githubusercontent.com/nyanmisaka/ffmpeg-rockchip/d90e3a1c18d7929383cf88c1b3da2e2d1c966cbf/libavdevice/'+name,source/name)
parts = []
def diff(name, old, new):
    parts.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/libavdevice/'+name,tofile='b/libavdevice/'+name))
def replace_once(text, old, new):
    assert text.count(old) == 1, old[:80]
    return text.replace(old,new,1)

old=(source/'v4l2-common.c').read_text(encoding='utf-8'); new=replace_once(old,
    '    { AV_PIX_FMT_NV12,    AV_CODEC_ID_RAWVIDEO, V4L2_PIX_FMT_NV12    },',
    '    { AV_PIX_FMT_NV12,    AV_CODEC_ID_RAWVIDEO, V4L2_PIX_FMT_NV12    },\n#ifdef V4L2_PIX_FMT_NV12M\n    { AV_PIX_FMT_NV12,    AV_CODEC_ID_RAWVIDEO, V4L2_PIX_FMT_NV12M   },\n#endif')
diff('v4l2-common.c',old,new)
old=(source/'v4l2.c').read_text(encoding='utf-8'); new=old
new=replace_once(new,'#include "v4l2-common.h"','#include "v4l2-common.h"\n#include "v4l2_nv12m_copy.h"')
new=replace_once(new,'static const int desired_video_buffers = 256;','static const int desired_video_buffers = 8;')
new=replace_once(new,'    int plane_count;','    int plane_count;\n    unsigned int plane_pitch[VIDEO_MAX_PLANES];')
a=new.index('static int device_init('); b=new.index('static int first_field(',a)
new=new[:a]+'''static int device_init(AVFormatContext *ctx, int *width, int *height,
                       uint32_t pixelformat)
{
    struct video_data *s = ctx->priv_data;
    struct v4l2_format fmt = { .type = s->multi_planer ? V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE : V4L2_BUF_TYPE_VIDEO_CAPTURE };
    uint32_t actual_format, field;
    int actual_width, actual_height;
    if (s->multi_planer) {
        fmt.fmt.pix_mp.width = *width;
        fmt.fmt.pix_mp.height = *height;
        fmt.fmt.pix_mp.pixelformat = pixelformat;
        fmt.fmt.pix_mp.field = V4L2_FIELD_NONE;
    } else {
        fmt.fmt.pix.width = *width;
        fmt.fmt.pix.height = *height;
        fmt.fmt.pix.pixelformat = pixelformat;
        fmt.fmt.pix.field = V4L2_FIELD_ANY;
    }
    if (v4l2_ioctl(s->fd, VIDIOC_S_FMT, &fmt) < 0)
        return AVERROR(errno);
    if (s->multi_planer) {
        actual_width = fmt.fmt.pix_mp.width;
        actual_height = fmt.fmt.pix_mp.height;
        actual_format = fmt.fmt.pix_mp.pixelformat;
        field = fmt.fmt.pix_mp.field;
        for (int p = 0; p < fmt.fmt.pix_mp.num_planes && p < VIDEO_MAX_PLANES; p++)
            s->plane_pitch[p] = fmt.fmt.pix_mp.plane_fmt[p].bytesperline;
        if (actual_format == V4L2_PIX_FMT_NV12M && fmt.fmt.pix_mp.num_planes != 2)
            return AVERROR(EINVAL);
    } else {
        actual_width = fmt.fmt.pix.width;
        actual_height = fmt.fmt.pix.height;
        actual_format = fmt.fmt.pix.pixelformat;
        field = fmt.fmt.pix.field;
    }
    if (actual_format != pixelformat)
        return AVERROR(EINVAL);
    if (*width != actual_width || *height != actual_height)
        av_log(ctx, AV_LOG_INFO, "Driver selected %dx%d\\n", actual_width, actual_height);
    *width = actual_width; *height = actual_height;
    s->interlaced = field == V4L2_FIELD_INTERLACED;
    return 0;
}

'''+new[b:]
new=new.replace('av_malloc_array(s->buffers, sizeof(void **))','av_calloc(s->buffers, sizeof(void **))').replace('av_malloc_array(s->buffers, sizeof(unsigned int*))','av_calloc(s->buffers, sizeof(unsigned int*))')
new=replace_once(new,'if (s->buf_start[i] == MAP_FAILED)','if (s->buf_start[i][iplane] == MAP_FAILED)')
new=replace_once(new,'if (s->frame_size > 0 && total_frame_size != s->frame_size)','if (s->pixelformat != V4L2_PIX_FMT_NV12M && s->frame_size > 0 && total_frame_size != s->frame_size)')
needle='''        if (V4L2_TYPE_IS_MULTIPLANAR(buf.type)) {
            int totalbytes = 0;'''
new=replace_once(new,needle,'''        if (s->pixelformat == V4L2_PIX_FMT_NV12M) {
            V4L2Nv12mPlane input[2];
            if (buf.length != 2 || (buf.flags & V4L2_BUF_FLAG_ERROR)) {
                enqueue_buffer(s, &buf);
                return AVERROR(EAGAIN);
            }
            for (int p = 0; p < 2; p++) {
                input[p] = (V4L2Nv12mPlane) {
                    s->buf_start[buf.index][p], s->buf_len[buf.index][p],
                    planes[p].bytesused, planes[p].data_offset, s->plane_pitch[p]
                };
            }
            res = av_new_packet(pkt, s->frame_size);
            if (res >= 0)
                res = v4l2_nv12m_copy(pkt->data, pkt->size, input, s->width, s->height);
            if (res < 0) {
                av_packet_unref(pkt);
                enqueue_buffer(s, &buf);
                return res;
            }
        } else if (V4L2_TYPE_IS_MULTIPLANAR(buf.type)) {
            int totalbytes = 0;''')
new=replace_once(new,'s->buf_start[buf.index][plane->data_offset], plane->bytesused','(uint8_t *)s->buf_start[buf.index][iplane] + plane->data_offset, plane->bytesused - plane->data_offset')
new=replace_once(new,'totalbytes += plane->bytesused;','totalbytes += plane->bytesused - plane->data_offset;')
new=replace_once(new,'''    for (int iplane = 0; iplane < s->plane_count; iplane++) {
        av_freep(&s->buf_start[iplane]);
        av_freep(&s->buf_len[iplane]);
    }''','''    for (i = 0; i < s->buffers; i++) {
        av_freep(&s->buf_start[i]);
        av_freep(&s->buf_len[i]);
    }''')
new=replace_once(new,'''            tpf->numerator   = framerate_q.num;
            tpf->denominator = framerate_q.den;''','''            tpf->numerator   = framerate_q.den;
            tpf->denominator = framerate_q.num;''')
new=replace_once(new,'''    *desired_format = ff_fmt_ff2v4l(pix_fmt, ctx->video_codec_id);''','''    struct video_data *s = ctx->priv_data;
    *desired_format = ff_fmt_ff2v4l(pix_fmt, ctx->video_codec_id);
    if (s->multi_planer && *desired_format == V4L2_PIX_FMT_NV12)
        *desired_format = V4L2_PIX_FMT_NV12M;''')
diff('v4l2.c',old,new)
header=(ROOT/'board/ffmpeg_pipeline/patches/v4l2_nv12m_copy.h').read_text(encoding='utf-8')
parts.extend(difflib.unified_diff([],header.splitlines(True),fromfile='/dev/null',tofile='b/libavdevice/v4l2_nv12m_copy.h'))
output=ROOT/'board/ffmpeg_pipeline/patches/0001-nv12m-capture.patch'
output.write_text(''.join(parts),encoding='utf-8',newline='\n')
print('Pinned NV12M patch generated')
