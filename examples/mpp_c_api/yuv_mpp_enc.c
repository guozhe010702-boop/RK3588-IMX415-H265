/* File-based MPP H.265 self-test: tightly packed NV12 -> .h265.
 * Uses the same encoder path as v4l2_mpp_enc without opening the camera.
 */
#include "mpp_h265.h"

#include <errno.h>
#include <getopt.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

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
    fprintf(stderr, "Usage: %s -i input.nv12 -o output.h265 [-c h265] "
            "[-w 640] [-h 360] [-b 1000000] [-f 30] [-n 30]\n"
            "Input must be tightly packed NV12 with no row padding.\n", program);
}

int main(int argc, char **argv)
{
    const char *input_path = NULL, *output_path = NULL;
    int width = 640, height = 360, bitrate = 1000000, fps = 30, frames = 30;
    int opt, result = 1;
    size_t y_bytes, frame_bytes;
    uint8_t *raw = NULL;
    FILE *input = NULL, *output = NULL;
    H265Encoder encoder = {0};
    struct timespec start, end;

    while ((opt = getopt(argc, argv, "i:o:c:w:h:b:f:n:")) != -1) {
        switch (opt) {
        case 'i': input_path = optarg; break;
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
    if (optind != argc || !input_path || !output_path || width < 0 ||
        height < 0 || bitrate < 0 || fps < 0 || frames < 0 ||
        (width & 1) || (height & 1)) {
        usage(argv[0]); return 2;
    }
    y_bytes = (size_t)width * height;
    frame_bytes = y_bytes * 3 / 2;
    raw = malloc(frame_bytes);
    if (!raw) { perror("allocate NV12 frame"); goto cleanup; }
    input = fopen(input_path, "rb");
    if (!input) { perror("open NV12 input"); goto cleanup; }
    output = fopen(output_path, "wx");
    if (!output) { perror("create H.265 output"); goto cleanup; }
    if (h265_encoder_open(&encoder, output, width, height, bitrate, fps) < 0)
        goto cleanup;

    clock_gettime(CLOCK_MONOTONIC, &start);
    for (int i = 0; i < frames; i++) {
        size_t got = fread(raw, 1, frame_bytes, input);
        if (got != frame_bytes) {
            fprintf(stderr, "NV12 input ended at frame %d (read %zu/%zu bytes)\n",
                    i, got, frame_bytes);
            goto cleanup;
        }
        if (h265_encoder_frame(&encoder,
                               raw, y_bytes, width,
                               raw + y_bytes, frame_bytes - y_bytes, width,
                               i + 1 == frames) < 0)
            goto cleanup;
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
    if (input) fclose(input);
    free(raw);
    return result;
}
