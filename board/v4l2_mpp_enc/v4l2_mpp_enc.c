/* IMX415 /dev/video44 (NV12M, two V4L2 planes) -> MPP H.265 elementary stream.
 * The capture node is exclusive: stop the GStreamer preview pipeline first.
 * This learning program writes a file; it does not display or send TCP video.
 */
#include "mpp_h265.h"

#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <linux/videodev2.h>

#define CAP_BUFFERS 4
#define CAP_PLANES 2

typedef struct { void *addr; size_t length; } PlaneMap;
typedef struct {
    int fd, streaming, count, width, height;
    size_t pitch[CAP_PLANES];
    PlaneMap map[CAP_BUFFERS][CAP_PLANES];
} Capture;
typedef struct {
    int index;
    const uint8_t *data[CAP_PLANES];
    size_t size[CAP_PLANES];
} CaptureFrame;

static int ioctl_retry(int fd, unsigned long request, void *arg)
{
    int ret;
    do { ret = ioctl(fd, request, arg); } while (ret < 0 && errno == EINTR);
    return ret;
}

static void capture_close(Capture *cap)
{
    if (cap->fd < 0) return;
    if (cap->streaming) {
        enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        ioctl_retry(cap->fd, VIDIOC_STREAMOFF, &type);
    }
    for (int i = 0; i < CAP_BUFFERS; i++) {
        for (int p = 0; p < CAP_PLANES; p++) {
            if (cap->map[i][p].addr)
                munmap(cap->map[i][p].addr, cap->map[i][p].length);
        }
    }
    close(cap->fd);
    cap->fd = -1;
}

static int capture_queue(Capture *cap, int index)
{
    struct v4l2_buffer buf = {0};
    struct v4l2_plane planes[CAP_PLANES] = {{0}};
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    buf.memory = V4L2_MEMORY_MMAP;
    buf.index = index;
    buf.length = CAP_PLANES;
    buf.m.planes = planes;
    if (ioctl_retry(cap->fd, VIDIOC_QBUF, &buf) < 0) {
        perror("VIDIOC_QBUF");
        return -1;
    }
    return 0;
}

static int capture_open(Capture *cap, const char *device, int width, int height, int fps)
{
    struct v4l2_capability capability = {0};
    struct v4l2_format fmt = {0};
    struct v4l2_requestbuffers request = {0};
    unsigned int device_caps;

    memset(cap, 0, sizeof(*cap));
    cap->fd = -1;
    cap->fd = open(device, O_RDWR | O_NONBLOCK);
    if (cap->fd < 0) { perror("open V4L2 device"); return -1; }
    if (ioctl_retry(cap->fd, VIDIOC_QUERYCAP, &capability) < 0) {
        perror("VIDIOC_QUERYCAP"); goto fail;
    }
    device_caps = (capability.capabilities & V4L2_CAP_DEVICE_CAPS) ?
                  capability.device_caps : capability.capabilities;
    if (!(device_caps & V4L2_CAP_VIDEO_CAPTURE_MPLANE) ||
        !(device_caps & V4L2_CAP_STREAMING)) {
        fprintf(stderr, "%s is not a streaming multi-plane capture node\n", device);
        goto fail;
    }

    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    fmt.fmt.pix_mp.width = width;
    fmt.fmt.pix_mp.height = height;
    fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_NV12M;
    fmt.fmt.pix_mp.field = V4L2_FIELD_NONE;
    if (ioctl_retry(cap->fd, VIDIOC_S_FMT, &fmt) < 0) {
        perror("VIDIOC_S_FMT (camera busy or format unsupported)"); goto fail;
    }
    if (fmt.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_NV12M ||
        fmt.fmt.pix_mp.num_planes != CAP_PLANES ||
        (fmt.fmt.pix_mp.width & 1) || (fmt.fmt.pix_mp.height & 1)) {
        fprintf(stderr, "Expected two-plane NM12, got fourcc %c%c%c%c, %u planes\n",
                fmt.fmt.pix_mp.pixelformat & 255,
                (fmt.fmt.pix_mp.pixelformat >> 8) & 255,
                (fmt.fmt.pix_mp.pixelformat >> 16) & 255,
                (fmt.fmt.pix_mp.pixelformat >> 24) & 255,
                fmt.fmt.pix_mp.num_planes);
        goto fail;
    }
    cap->width = fmt.fmt.pix_mp.width;
    cap->height = fmt.fmt.pix_mp.height;
    for (int p = 0; p < CAP_PLANES; p++) {
        cap->pitch[p] = fmt.fmt.pix_mp.plane_fmt[p].bytesperline;
        if (cap->pitch[p] < (size_t)cap->width) {
            fprintf(stderr, "V4L2 plane %d stride is shorter than image width\n", p);
            goto fail;
        }
    }
    fprintf(stderr, "V4L2 %s: NM12 %dx%d, Y stride=%zu, UV stride=%zu\n",
            device, cap->width, cap->height, cap->pitch[0], cap->pitch[1]);

    struct v4l2_streamparm parm = {0};
    parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    if (ioctl_retry(cap->fd, VIDIOC_G_PARM, &parm) == 0 &&
        (parm.parm.capture.capability & V4L2_CAP_TIMEPERFRAME)) {
        parm.parm.capture.timeperframe.numerator = 1;
        parm.parm.capture.timeperframe.denominator = fps;
        if (ioctl_retry(cap->fd, VIDIOC_S_PARM, &parm) < 0)
            perror("VIDIOC_S_PARM (continuing with current frame rate)");
    }

    request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    request.memory = V4L2_MEMORY_MMAP;
    request.count = CAP_BUFFERS;
    if (ioctl_retry(cap->fd, VIDIOC_REQBUFS, &request) < 0) {
        perror("VIDIOC_REQBUFS"); goto fail;
    }
    if (request.count < 2 || request.count > CAP_BUFFERS) {
        fprintf(stderr, "V4L2 returned unsupported buffer count %u\n", request.count);
        goto fail;
    }
    cap->count = request.count;
    for (int i = 0; i < cap->count; i++) {
        struct v4l2_buffer buf = {0};
        struct v4l2_plane planes[CAP_PLANES] = {{0}};
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        buf.length = CAP_PLANES;
        buf.m.planes = planes;
        if (ioctl_retry(cap->fd, VIDIOC_QUERYBUF, &buf) < 0) {
            perror("VIDIOC_QUERYBUF"); goto fail;
        }
        if (buf.length != CAP_PLANES) {
            fprintf(stderr, "Unexpected V4L2 plane count in buffer %d\n", i);
            goto fail;
        }
        for (int p = 0; p < CAP_PLANES; p++) {
            cap->map[i][p].length = planes[p].length;
            void *addr = mmap(NULL, planes[p].length, PROT_READ | PROT_WRITE,
                              MAP_SHARED, cap->fd, planes[p].m.mem_offset);
            if (addr == MAP_FAILED) { perror("mmap V4L2 plane"); goto fail; }
            cap->map[i][p].addr = addr;
        }
        if (capture_queue(cap, i) < 0) goto fail;
    }
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    if (ioctl_retry(cap->fd, VIDIOC_STREAMON, &type) < 0) {
        perror("VIDIOC_STREAMON"); goto fail;
    }
    cap->streaming = 1;
    return 0;

fail:
    capture_close(cap);
    return -1;
}

static int capture_dequeue(Capture *cap, CaptureFrame *frame)
{
    struct pollfd pfd = {cap->fd, POLLIN, 0};
    struct v4l2_buffer buf = {0};
    struct v4l2_plane planes[CAP_PLANES] = {{0}};
    int ready;
    do { ready = poll(&pfd, 1, 3000); } while (ready < 0 && errno == EINTR);
    if (ready <= 0) { fprintf(stderr, "V4L2 frame timeout or poll error\n"); return -1; }
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    buf.memory = V4L2_MEMORY_MMAP;
    buf.length = CAP_PLANES;
    buf.m.planes = planes;
    if (ioctl_retry(cap->fd, VIDIOC_DQBUF, &buf) < 0) {
        perror("VIDIOC_DQBUF"); return -1;
    }
    if (buf.index >= (unsigned)cap->count || buf.length != CAP_PLANES) {
        fprintf(stderr, "Unexpected V4L2 buffer index or plane count\n"); return -1;
    }
    frame->index = buf.index;
    for (int p = 0; p < CAP_PLANES; p++) {
        size_t offset = planes[p].data_offset;
        size_t bytes = planes[p].bytesused;
        if (bytes < offset || bytes > cap->map[buf.index][p].length) {
            fprintf(stderr, "Invalid bytesused in V4L2 plane %d\n", p);
            return -1;
        }
        frame->data[p] = (uint8_t *)cap->map[buf.index][p].addr + offset;
        frame->size[p] = bytes - offset;
    }
    return 0;
}

static int number(const char *text, int low, int high)
{
    char *end;
    long value;
    errno = 0;
    value = strtol(text, &end, 10);
    if (errno || *end || value < low || value > high) return -1;
    return (int)value;
}

static void usage(const char *program)
{
    fprintf(stderr, "Usage: %s [-d /dev/video44] [-o cap.h265] [-c h265] "
            "[-w 1920] [-h 1080] [-b 4000000] [-f 30] [-n 90]\n"
            "The output file must not already exist. Stop the preview pipeline first.\n",
            program);
}

int main(int argc, char **argv)
{
    const char *device = "/dev/video44", *output_path = "cap_mpp.h265";
    int width = 1920, height = 1080, bitrate = 4000000, fps = 30, frames = 90;
    int opt, result = 1;
    Capture capture = {.fd = -1};
    H265Encoder encoder = {0};
    FILE *output = NULL;
    struct timespec start, end;

    while ((opt = getopt(argc, argv, "d:o:c:w:h:b:f:n:")) != -1) {
        switch (opt) {
        case 'd': device = optarg; break;
        case 'o': output_path = optarg; break;
        case 'c':
            if (strcmp(optarg, "h265") != 0) { usage(argv[0]); return 2; }
            break;
        case 'w': width = number(optarg, 96, 8192); break;
        case 'h': height = number(optarg, 64, 8192); break;
        case 'b': bitrate = number(optarg, 100000, 100000000); break;
        case 'f': fps = number(optarg, 1, 120); break;
        case 'n': frames = number(optarg, 1, 100000); break;
        default: usage(argv[0]); return 2;
        }
    }
    if (optind != argc || width < 0 || height < 0 || bitrate < 0 || fps < 0 ||
        frames < 0 || (width & 1) || (height & 1)) {
        usage(argv[0]); return 2;
    }
    if (capture_open(&capture, device, width, height, fps) < 0) return 1;
    output = fopen(output_path, "wx");
    if (!output) { perror("create H.265 output"); goto cleanup; }
    if (h265_encoder_open(&encoder, output, capture.width, capture.height,
                          bitrate, fps) < 0) goto cleanup;

    clock_gettime(CLOCK_MONOTONIC, &start);
    for (int i = 0; i < frames; i++) {
        CaptureFrame frame = {0};
        if (capture_dequeue(&capture, &frame) < 0) goto cleanup;
        int encoded = h265_encoder_frame(&encoder,
                                         frame.data[0], frame.size[0], capture.pitch[0],
                                         frame.data[1], frame.size[1], capture.pitch[1],
                                         i + 1 == frames);
        if (capture_queue(&capture, frame.index) < 0 || encoded < 0) goto cleanup;
        if ((i + 1) % 30 == 0)
            fprintf(stderr, "Encoded %d/%d frames, %llu bytes\n", i + 1, frames,
                    (unsigned long long)encoder.bytes);
    }
    clock_gettime(CLOCK_MONOTONIC, &end);
    double seconds = (end.tv_sec - start.tv_sec) +
                     (end.tv_nsec - start.tv_nsec) / 1000000000.0;
    fprintf(stderr, "Done: %u frames, %llu bytes, %.2f s, %.1f fps, output %s\n",
            encoder.frames, (unsigned long long)encoder.bytes, seconds,
            seconds > 0 ? encoder.frames / seconds : 0.0, output_path);
    result = 0;

cleanup:
    h265_encoder_close(&encoder);
    if (output && fclose(output) != 0) { perror("close output"); result = 1; }
    capture_close(&capture);
    return result;
}
