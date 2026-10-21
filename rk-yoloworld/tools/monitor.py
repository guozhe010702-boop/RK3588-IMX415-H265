#!/usr/bin/env python3
"""Read-only board terminal monitor. Python stdlib only; never controls processes.

CPU uses /proc counter deltas (one logical core = 100%). NPU driver exposes
per-core busy percentages, not per-RKNN-context usage. Thread memory is shared.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def delta_rate(value, previous, elapsed):
    if previous is None or elapsed <= 0 or value < previous:
        return None
    return (value - previous) / elapsed


def task_stat(path):
    text = read(path)
    if ")" not in text:
        return None
    fields = text[text.rfind(")") + 2 :].split()
    try:
        return int(fields[11]) + int(fields[12]), int(fields[19])
    except (IndexError, ValueError):
        return None


def npu_load(text):
    values = {int(k): float(v) for k, v in re.findall(r"Core\s*(\d+)\s*:\s*(\d+(?:\.\d+)?)%", text)}
    return [values.get(i) for i in range(3)]


def preview_udp_drops():
    rows = [line.split() for line in read("/proc/net/udp").splitlines()[1:]]
    values = [int(row[-1]) for row in rows if len(row) > 12 and row[1] == "0100007F:04D4"]
    return sum(values) if values else None


def latest_metrics(root, pid):
    files = list((root / "logs").glob("*.jsonl"))
    if not files:
        return None, None
    path = max(files, key=lambda p: p.stat().st_mtime)
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - 32768))
            lines = f.read().splitlines()
        for line in reversed(lines):
            try:
                data = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if data.get("pid") == pid:
                return data, max(0, time.time() - path.stat().st_mtime)
    except OSError:
        pass
    return None, None


class Sampler:
    def __init__(self, root=ROOT, interface="eth1"):
        self.root, self.interface = Path(root), interface
        self.previous = {}
        self.hz = os.sysconf("SC_CLK_TCK")
        self.worker_base = {}
        self.worker_rates = {}
        self.pid_identity = None

    def rate(self, key, value, now):
        old = self.previous.get(key)
        self.previous[key] = (value, now)
        return delta_rate(value, old[0], now - old[1]) if old else None

    def process(self, pid, now):
        path = Path("/proc") / str(pid)
        stat = task_stat(path / "stat")
        if not stat:
            return None
        rate = self.rate(("process", pid, stat[1]), stat[0], now)
        match = re.search(r"^VmRSS:\s+(\d+)", read(path / "status"), re.M)
        return {
            "pid": pid,
            "cpu_core_percent": rate / self.hz * 100 if rate is not None else None,
            "rss_mib": int(match[1]) / 1024 if match else None,
        }

    def sample(self):
        now = time.monotonic()
        processes = []
        for path in Path("/proc").glob("[0-9]*"):
            try:
                args = (path / "cmdline").read_bytes().split(b"\0")
                processes.append((int(path.name), args))
            except OSError:
                continue
        pid = None
        for number, args in processes:
            if args and Path(os.fsdecode(args[0])).name == "rknn_yolo_world_realtime":
                try:
                    if Path("/proc", str(number), "cwd").resolve() == self.root.resolve():
                        pid = number
                        break
                except OSError:
                    pass
        metrics, age = latest_metrics(self.root, pid) if pid else (None, None)
        fresh = metrics is not None and age is not None and age <= 3
        identity = (pid, task_stat(Path("/proc", str(pid), "stat"))) if pid else None
        identity = (pid, identity[1][1]) if identity and identity[1] else None
        if identity != self.pid_identity:
            self.previous.clear()
            self.worker_base.clear()
            self.worker_rates.clear()
            self.pid_identity = identity
        workers = []
        if pid:
            stats_workers = {w["worker"]: w for w in (metrics or {}).get("workers", [])}
            for path in Path("/proc", str(pid), "task").glob("[0-9]*"):
                name = read(path / "comm").strip()
                match = re.fullmatch(r"infer([0-8])-npu([0-2])", name)
                stat = task_stat(path / "stat")
                if not match or not stat:
                    continue
                index, core, tid = int(match[1]), int(match[2]), int(path.name)
                cpu = self.rate(("thread", pid, tid, stat[1]), stat[0], now)
                completed = stats_workers.get(index, {}).get("completed") if fresh else None
                frame_rate = None
                if completed is not None and stats_workers[index].get("tid") == tid:
                    stamp = metrics["elapsed_s"]
                    old = self.worker_base.get(index)
                    if not old or stamp != old[1]:
                        self.worker_rates[index] = (
                            delta_rate(completed, old[0], stamp - old[1]) if old else None
                        )
                        self.worker_base[index] = (completed, stamp)
                    frame_rate = self.worker_rates.get(index)
                workers.append(
                    {
                        "worker": index,
                        "tid": tid,
                        "core": core,
                        "cpu_core_percent": cpu / self.hz * 100 if cpu is not None else None,
                        "inference_fps": frame_rate,
                        "completed": completed,
                    }
                )
        cpu = read("/proc/stat").splitlines()[0].split()[1:9]
        cpu = list(map(int, cpu))
        total = self.rate("host_total", sum(cpu), now)
        idle = self.rate("host_idle", cpu[3] + cpu[4], now)
        host_cpu = (
            max(0, min(100, (1 - idle / total) * 100)) if total and idle is not None else None
        )
        memory = {
            k: int(v)
            for k, v in re.findall(
                r"^(MemTotal|MemAvailable):\s+(\d+)", read("/proc/meminfo"), re.M
            )
        }
        nic = read(Path("/sys/class/net") / self.interface / "statistics/tx_bytes").strip()
        rx = read(Path("/sys/class/net") / self.interface / "statistics/rx_bytes").strip()
        tx_rate = self.rate("tx", int(nic), now) if nic.isdigit() else None
        rx_rate = self.rate("rx", int(rx), now) if rx.isdigit() else None
        speed = read(Path("/sys/class/net") / self.interface / "speed").strip()
        speed = float(speed) if speed.isdigit() and int(speed) > 0 else None
        related = {}
        if pid:
            for number, args in processes:
                if args and Path(os.fsdecode(args[0])).name == "ffmpeg":
                    if re.search(
                        r"^PPid:\s+" + str(pid) + r"\s*$",
                        read(Path("/proc", str(number), "status")),
                        re.M,
                    ):
                        related["encoder"] = self.process(number, now)
        try:
            display = json.loads(read(self.root / "state/detection-hdmi.json"))
            for key, field, marker in (
                ("hdmi_decoder", "decoderPid", b"127.0.0.1:1236"),
                ("hdmi_player", "playerPid", b"YOLO-World detection HDMI"),
            ):
                number = display[field]
                args = next((a for n, a in processes if n == number), [])
                if marker in b" ".join(args):
                    related[key] = self.process(number, now)
        except (ValueError, KeyError):
            pass
        return {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "running": pid is not None,
            "metrics_fresh": fresh,
            "metrics_age_s": age,
            "application": self.process(pid, now) if pid else None,
            "related": related,
            "host_cpu_percent": host_cpu,
            "host_memory_used_mib": (
                (memory["MemTotal"] - memory["MemAvailable"]) / 1024 if len(memory) == 2 else None
            ),
            "host_memory_total_mib": memory.get("MemTotal", 0) / 1024 or None,
            "npu_core_percent": npu_load(read("/sys/kernel/debug/rknpu/load")),
            "workers": sorted(workers, key=lambda w: w["worker"]),
            "hdmi": {
                "requested": (self.root / "state/detection-hdmi.json").exists(),
                "running": bool(related.get("hdmi_decoder") and related.get("hdmi_player")),
            },
            "metrics": metrics if fresh else None,
            "network": {
                "interface": self.interface,
                "tx_mbps": tx_rate * 8 / 1e6 if tx_rate is not None else None,
                "rx_mbps": rx_rate * 8 / 1e6 if rx_rate is not None else None,
                "link_mbps": speed,
                "tx_utilization_percent": (
                    tx_rate * 8 / 1e6 / speed * 100 if tx_rate is not None and speed else None
                ),
                "hdmi_udp_socket_drops": preview_udp_drops() if "hdmi_decoder" in related else None,
            },
        }


def text_report(data):
    def f(value, unit=""):
        return "不可用" if value is None else "{:.2f}{}".format(value, unit)

    app, net = data["application"] or {}, data["network"]
    metrics = data["metrics"] or {}
    lines = [
        "YOLO-World 实时监测  " + data["time"],
        "检测：{} | 统计：{}".format(
            "运行中" if data["running"] else "未运行",
            "新鲜" if data["metrics_fresh"] else "无数据/已过期",
        ),
        "采集 {} fps | 推理 {} fps | 有效输出 {} fps".format(
            *(f(metrics.get(k)) for k in ("capture_fps", "infer_fps", "output_fps"))
        ),
        "检测 PID {} | CPU {} (一核=100%) | RSS {}".format(
            app.get("pid", "-"), f(app.get("cpu_core_percent"), "%"), f(app.get("rss_mib"), " MiB")
        ),
        "整板 CPU {} | 内存 {} / {}".format(
            f(data["host_cpu_percent"], "%"),
            f(data["host_memory_used_mib"], " MiB"),
            f(data["host_memory_total_mib"], " MiB"),
        ),
        "NPU 三核忙碌率：" + " / ".join(f(x, "%") for x in data["npu_core_percent"]),
        "检测 HDMI："
        + (
            "运行中"
            if data["hdmi"]["running"]
            else "进程已退出，请查看 HDMI 日志" if data["hdmi"]["requested"] else "未开启"
        ),
        "{} TX {} | RX {} | 链路 {} | TX占用 {}".format(
            net["interface"],
            f(net["tx_mbps"], " Mbit/s"),
            f(net["rx_mbps"], " Mbit/s"),
            f(net["link_mbps"], " Mbit/s"),
            f(net["tx_utilization_percent"], "%"),
        ),
        "HDMI 本机 UDP socket 丢包：{}".format(
            net.get("hdmi_udp_socket_drops")
            if net.get("hdmi_udp_socket_drops") is not None
            else "不可用"
        ),
        "worker  TID       NPU核   线程CPU%    推理FPS    累计完成",
    ]
    for w in data["workers"]:
        lines.append(
            "{:<7} {:<9} {:<7} {:<11} {:<10} {}".format(
                w["worker"],
                w["tid"],
                w["core"],
                f(w["cpu_core_percent"]),
                f(w["inference_fps"]),
                w["completed"] if w["completed"] is not None else "-",
            )
        )
    for name, p in data["related"].items():
        if p:
            lines.append(
                "{} PID {} CPU {} RSS {}".format(
                    name, p["pid"], f(p["cpu_core_percent"], "%"), f(p["rss_mib"], " MiB")
                )
            )
    lines += [
        "NPU% 是每核总忙碌率；驱动未提供每个 context 的独立 NPU 占用率。",
        "9 个推理线程共享进程内存；线程 CPU 等待 NPU 时可能很低。Ctrl+C 只退出监测。",
    ]
    return "\n".join(lines)


def flatten(data):
    app, metrics = data["application"] or {}, data["metrics"] or {}
    row = {
        k: data[k]
        for k in ("time", "running", "metrics_fresh", "host_cpu_percent", "host_memory_used_mib")
    }
    row.update({"app_" + k: v for k, v in app.items()})
    row.update(
        {
            k: metrics.get(k)
            for k in ("capture_fps", "infer_fps", "output_fps", "steady_driver_gaps")
        }
    )
    row.update(
        {"npu{}_percent".format(i): value for i, value in enumerate(data["npu_core_percent"])}
    )
    row.update({"nic_" + k: v for k, v in data["network"].items()})
    for i in range(9):
        w = next((w for w in data["workers"] if w["worker"] == i), {})
        row.update(
            {
                "worker{}_{}".format(i, k): w.get(k)
                for k in ("tid", "core", "cpu_core_percent", "inference_fps", "completed")
            }
        )
    # Stable columns even when the application starts/stops while monitoring.
    for key in ("pid", "cpu_core_percent", "rss_mib"):
        row.setdefault("app_" + key, None)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--interval", type=float, default=1)
    p.add_argument("--count", type=int, default=0, help="0 means until Ctrl+C")
    p.add_argument("--interface", default="eth1")
    p.add_argument("--csv", type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if not 0.25 <= args.interval <= 60 or args.count < 0:
        p.error("invalid interval/count")
    sampler = Sampler(interface=args.interface)
    out = writer = None
    try:
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            out = args.csv.open("w", newline="", encoding="utf-8-sig")
        count = 0
        while args.count == 0 or count < args.count:
            start = time.monotonic()
            data = sampler.sample()
            if out:
                row = flatten(data)
                if writer is None:
                    writer = csv.DictWriter(out, fieldnames=sorted(row))
                    writer.writeheader()
                writer.writerow(row)
                out.flush()
            if not args.json and sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            print(
                json.dumps(data, ensure_ascii=False) if args.json else text_report(data), flush=True
            )
            count += 1
            if args.count == 0 or count < args.count:
                time.sleep(max(0, args.interval - (time.monotonic() - start)))
    except KeyboardInterrupt:
        pass
    finally:
        if out:
            out.close()


if __name__ == "__main__":
    main()
