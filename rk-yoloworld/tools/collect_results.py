"""Collect this test's logs and summarize measured counters (no model/credential data)."""

import json, re, subprocess, statistics
from pathlib import Path
from board_link import ROOT, remote, ADB


def main():
    info = json.loads(
        remote(
            """from pathlib import Path
import json
r=Path('/userdata/rk-yoloworld');fs=sorted((r/'logs').glob('*.jsonl'));last=fs[-1]
print(json.dumps({'log':str(last),'wrapper':(r/'state/test-wrapper.log').read_text().splitlines()[-3:]}))
"""
        )
    )
    destination = ROOT / "logs" / Path(info["log"]).stem
    destination.mkdir(parents=True, exist_ok=True)
    for path in [
        info["log"],
        info["log"].replace(".jsonl", ".log"),
        "/userdata/rk-yoloworld/state/test-wrapper.log",
        "/userdata/rk-yoloworld/state/before-test.json",
        "/userdata/rk-yoloworld/state/restored.json",
    ]:
        subprocess.run(
            [str(ADB), "pull", path, str(destination / Path(path).name)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    rows = []
    for line in (destination / Path(info["log"]).name).read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "capture_fps" in row:
            rows.append(row)
    assert rows, "No performance samples"
    a, b = rows[0], rows[-1]
    dt = b["elapsed_s"] - a["elapsed_s"]
    average = {
        name: (b[key] - a[key]) / dt
        for name, key in [
            ("capture_fps", "capture_total"),
            ("inference_fps", "infer_total"),
            ("output_fps", "output_total"),
        ]
    }
    npu = [[] for _ in range(3)]
    for row in rows:
        for core, value in re.findall(r"Core([012]):\s*(\d+)%", row.get("npu", "")):
            npu[int(core)].append(int(value))
    errors = (destination / Path(info["log"]).with_suffix(".log").name).read_text(errors="replace")
    report = {
        "log": Path(info["log"]).name,
        "samples": len(rows),
        "last_elapsed_s": b["elapsed_s"],
        "measured_interval_s": dt,
        "averages": average,
        "rss_start_mib": a["rss_mib"],
        "rss_end_mib": b["rss_mib"],
        "rss_max_mib": max(r["rss_mib"] for r in rows),
        "cpu_core_percent_mean": statistics.mean(r["cpu_core_percent"] for r in rows),
        "npu_mean_percent": [statistics.mean(v) if v else None for v in npu],
        "capture_to_pipe_age_p50_ms": b.get("age_all_p50_ms"),
        "capture_to_pipe_age_p95_ms": b.get("age_all_p95_ms"),
        "steady_driver_gaps": b.get("steady_driver_gaps"),
        "startup_driver_gaps": b.get("startup_driver_gaps"),
        "raw_drops": b["raw_drops"],
        "prepared_drops": b["prepared_drops"],
        "stale_results": b["stale_results"],
        "timeouts": b["timeouts"],
        "pool_drops": b["pool_drops"],
        "fatal_errors": errors.count("fatal:"),
        "timestamp_warnings": errors.count("Non-monotonic DTS"),
        "rawvideo_errors": errors.count("Invalid buffer size"),
        "wrapper_tail": info["wrapper"],
    }
    (ROOT / "build/validation-summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    import csv

    with (destination / "metrics.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
