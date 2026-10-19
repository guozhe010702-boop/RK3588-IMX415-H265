"""Generate a separate, reversible buffer/observability patch after 0001 + 0002.

Run make_ffmpeg_patch.py first if the pinned upstream cache is absent.
The existing deployed compatibility and metrics patches stay byte-for-byte intact.
"""
from pathlib import Path
import difflib
import re

ROOT = Path(__file__).resolve().parents[2]
PATCHES = ROOT / "board/ffmpeg_pipeline/patches"


def apply_patch(original, patch, filename):
    lines, result, cursor, active = original.splitlines(True), [], 0, False
    for line in patch.splitlines(True):
        if line.startswith("--- "):
            active = False
        elif line.startswith("+++ "):
            active = line.strip() == "+++ b/libavdevice/" + filename
        elif active and line.startswith("@@ "):
            start = int(re.match(r"@@ -(\d+)", line)[1]) - 1
            result.extend(lines[cursor:start])
            cursor = start
        elif active and line.startswith((" ", "-")):
            assert lines[cursor] == line[1:], (cursor, line)
            if line[0] == " ":
                result.append(line[1:])
            cursor += 1
        elif active and line.startswith("+"):
            result.append(line[1:])
    return "".join(result + lines[cursor:])


def replace(text, before, after):
    assert text.count(before) == 1, before[:100]
    return text.replace(before, after, 1)


def main():
    original = (ROOT / ".cache/ffmpeg-upstream/libavdevice/v4l2.c").read_text(encoding="utf-8")
    for name in ("0001-nv12m-capture.patch", "0002-capture-metrics.patch"):
        original = apply_patch(original, (PATCHES / name).read_text(encoding="utf-8"), "v4l2.c")
    changed = replace(original, "static const int desired_video_buffers = 8;\n", "")
    changed = replace(changed, "    int buffers;\n", "    int buffers;\n    int capture_buffers;\n")
    changed = replace(changed, "    int64_t capture_report_at;\n",
        "    int64_t capture_report_at;\n    int64_t capture_hold_max, capture_age_max;\n")
    changed = replace(changed, ".count  = desired_video_buffers,", ".count  = s->capture_buffers,")
    changed = replace(changed, "    s->buffers = req.count;\n",
        '    s->buffers = req.count;\n    av_log(ctx, AV_LOG_INFO, "AV_CAPTURE_BUFFERS requested=%d actual=%d\\n", s->capture_buffers, s->buffers);\n')
    changed = replace(changed, "    struct timeval buf_ts;\n",
        "    struct timeval buf_ts;\n    int64_t dequeued_at = 0, buffer_age = 0;\n    uint32_t missing = 0, previous_sequence = 0;\n")
    changed = replace(changed, "    buf_ts = buf.timestamp;\n",
        """    buf_ts = buf.timestamp;
    if (s->pixelformat == V4L2_PIX_FMT_NV12M) {
        dequeued_at = av_gettime_relative();
        /* Driver timestamps are comparable only when explicitly MONOTONIC. */
        if ((buf.flags & V4L2_BUF_FLAG_TIMESTAMP_MASK) == V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC)
            buffer_age = FFMAX(0, dequeued_at - (buf_ts.tv_sec * INT64_C(1000000) + buf_ts.tv_usec));
    }
""")
    changed = replace(changed, """                if (distance > 1 && distance < UINT32_MAX / 2)
                    s->capture_gaps += distance - 1;""", """                if (distance > 1 && distance < UINT32_MAX / 2) {
                    missing = distance - 1;
                    previous_sequence = s->capture_sequence;
                    s->capture_gaps += missing;
                }""")
    begin = changed.index("            if (av_gettime_relative() - s->capture_report_at >= 1000000)")
    end = changed.index("        } else if (V4L2_TYPE_IS_MULTIPLANAR(buf.type))", begin)
    changed = changed[:begin] + changed[end:]
    needle = """        res = enqueue_buffer(s, &buf);
        if (res) {
            av_packet_unref(pkt);
            return res;
        }
"""
    changed = replace(changed, needle, needle + """        if (s->pixelformat == V4L2_PIX_FMT_NV12M) {
            int64_t now = av_gettime_relative();
            int64_t hold = now - dequeued_at;
            s->capture_hold_max = FFMAX(s->capture_hold_max, hold);
            s->capture_age_max = FFMAX(s->capture_age_max, buffer_age);
            /* Log only after QBUF: diagnostics must not delay buffer return. */
            if (missing)
                av_log(ctx, AV_LOG_WARNING, "AV_CAPTURE_GAP previous=%u current=%u missing=%u age_us=%lld hold_us=%lld\\n",
                       previous_sequence, s->capture_sequence, missing, (long long)buffer_age, (long long)hold);
            if (now - s->capture_report_at >= 1000000) {
                s->capture_report_at = now;
                av_log(ctx, AV_LOG_INFO, "AV_CAPTURE frames=%llu gaps=%llu width=%d height=%d errors=%llu mono_us=%lld buffers=%d max_hold_us=%lld max_age_us=%lld\\n",
                       (unsigned long long)s->capture_frames, (unsigned long long)s->capture_gaps,
                       s->width, s->height, (unsigned long long)s->capture_errors, (long long)now,
                       s->buffers, (long long)s->capture_hold_max, (long long)s->capture_age_max);
                s->capture_hold_max = s->capture_age_max = 0;
            }
        }
""")
    changed = replace(changed, "static const AVOption options[] = {\n",
        'static const AVOption options[] = {\n    { "capture_buffers", "requested mmap capture buffers (bounded for raw 4K memory)", OFFSET(capture_buffers), AV_OPT_TYPE_INT, {.i64 = 16}, 4, 32, DEC },\n')
    parts = list(difflib.unified_diff(original.splitlines(True), changed.splitlines(True),
        fromfile="a/libavdevice/v4l2.c", tofile="b/libavdevice/v4l2.c"))
    base = (PATCHES / "0001-nv12m-capture.patch").read_text(encoding="utf-8")
    header = base.split("+++ b/libavdevice/v4l2_nv12m_copy.h\n", 1)[1]
    header = "".join(line[1:] for line in header.splitlines(True) if line.startswith("+"))
    parts += list(difflib.unified_diff(header.splitlines(True),
        (PATCHES / "v4l2_nv12m_copy.h").read_text(encoding="utf-8").splitlines(True),
        fromfile="a/libavdevice/v4l2_nv12m_copy.h", tofile="b/libavdevice/v4l2_nv12m_copy.h"))
    (PATCHES / "0003-capture-buffers.patch").write_text("".join(parts), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
