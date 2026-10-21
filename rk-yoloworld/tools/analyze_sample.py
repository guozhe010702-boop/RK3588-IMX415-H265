"""Validate an offline keyframe-aligned network sample, independently of RKNN."""

import json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    file = ROOT / "build/detection-clean.ts"

    def probe(*args):
        return json.loads(
            subprocess.check_output(
                ["ffprobe", "-v", "error", *args, "-of", "json", str(file)], text=True
            )
        )

    packets = probe(
        "-select_streams", "v:0", "-show_packets", "-show_entries", "packet=pts_time,dts_time"
    )["packets"]
    pts = [float(p["pts_time"]) for p in packets]
    dts = [float(p["dts_time"]) for p in packets]
    assert all(a < b for a, b in zip(pts, pts[1:])), "PTS regressed/repeated"
    assert pts == dts, "Unexpected reorder/B frame"
    stream = probe("-select_streams", "v:0", "-count_frames", "-show_streams")["streams"][0]
    assert (stream["codec_name"], stream["width"], stream["height"]) == ("h264", 2560, 1440)
    decoded = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(file), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    assert decoded.returncode == 0 and not decoded.stderr, decoded.stderr
    report = {
        "codec": stream["codec_name"],
        "width": stream["width"],
        "height": stream["height"],
        "decoded_frames": int(stream["nb_read_frames"]),
        "packets": len(pts),
        "first_pts": pts[0],
        "last_pts": pts[-1],
        "pts_measured_fps": (len(pts) - 1) / (pts[-1] - pts[0]),
        "monotonic_pts": True,
        "b_frames": stream.get("has_b_frames"),
        "decode_errors": 0,
    }
    (ROOT / "build/stream-validation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
