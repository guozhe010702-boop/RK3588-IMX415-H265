"""Optional RK3588 camera IRQ experiment. Dry run by default; no firmware writes.

Only CIF and active ISP interrupt lines move. This never changes IRQ default
affinity, networking, VPU, CPU clocks or scheduling policy. Reboot also restores
the system's original IRQ configuration. Do not apply while irqbalance is active.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess


def parse_list(value):
    result = set()
    for part in value.strip().split(","):
        bounds = part.split("-")
        low, high = int(bounds[0]), int(bounds[-1])
        result.update(range(low, high + 1))
    return result


def plan_interrupts(text, capacities, online):
    candidates = [cpu for cpu in online if capacities.get(cpu, 0) == max(capacities.values())]
    if len(candidates) < 2:
        raise ValueError("Need at least two online high-capacity CPUs")
    cif_cpu, isp_cpu = sorted(candidates)[:2]
    result = []
    for line in text.splitlines():
        match = re.match(r"\s*(\d+):\s+(.*)", line)
        if not match:
            continue
        fields = match[2].split()
        counts = []
        for word in fields:
            if not word.isdigit():
                break
            counts.append(int(word))
        handler = fields[-1] if fields else ""
        if handler not in ("rkcifhw", "rkisp_hw") or not counts or not sum(counts):
            continue
        # A shared IRQ containing unrelated handlers must not be moved.
        if "," in match[2]:
            continue
        result.append({"irq": int(match[1]), "handler": handler,
            "cpu": cif_cpu if handler == "rkcifhw" else isp_cpu})
    if not any(r["handler"] == "rkcifhw" for r in result) or not any(r["handler"] == "rkisp_hw" for r in result):
        raise ValueError("Active CIF and ISP interrupt handlers not found")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true")
    group.add_argument("--restore", action="store_true")
    parser.add_argument("--state", type=Path, default=Path(__file__).resolve().parent / "state/capture-irq-backup.json")
    args = parser.parse_args()
    compatible = Path("/proc/device-tree/compatible").read_bytes()
    if b"rockchip,rk3588" not in compatible:
        raise ValueError("This experiment is restricted to RK3588")
    active = subprocess.run(["systemctl", "is-active", "--quiet", "irqbalance"], check=False).returncode == 0
    if active:
        raise ValueError("irqbalance active; refusing to compete with it")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if args.restore:
        backup = json.loads(args.state.read_text())
        if backup["bootId"] != boot_id:
            raise ValueError("Previous boot's IRQ numbers are not valid for this boot")
        for row in backup["irqs"]:
            path = Path("/proc/irq/{}/smp_affinity_list".format(row["irq"]))
            if path.read_text().strip() != str(row["cpu"]):
                raise ValueError("Affinity changed externally; refusing to overwrite IRQ "+str(row["irq"]))
        for row in reversed(backup["irqs"]):
            path = Path("/proc/irq/{}/smp_affinity_list".format(row["irq"]))
            path.write_text(row["original"])
            if path.read_text().strip() != row["original"]:
                raise ValueError("Restored affinity readback mismatch")
        args.state.unlink()
        print(json.dumps({"ok": True, "restored": True, "irqs": backup["irqs"]}))
        return
    online = parse_list(Path("/sys/devices/system/cpu/online").read_text())
    capacities = {cpu: int(Path("/sys/devices/system/cpu/cpu{}/cpu_capacity".format(cpu)).read_text()) for cpu in online}
    plan = plan_interrupts(Path("/proc/interrupts").read_text(), capacities, online)
    for row in plan:
        row["original"] = Path("/proc/irq/{}/smp_affinity_list".format(row["irq"])).read_text().strip()
    report = {"bootId": boot_id, "irqs": plan, "capacities": capacities, "applied": False}
    if args.apply:
        if args.state.exists():
            raise ValueError("Backup exists; restore or inspect it before applying again")
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(report, indent=2))
        modified = []
        try:
            for row in plan:
                path = Path("/proc/irq/{}/smp_affinity_list".format(row["irq"]))
                path.write_text(str(row["cpu"]))
                modified.append(row)
                if path.read_text().strip() != str(row["cpu"]):
                    raise ValueError("IRQ affinity readback mismatch")
            report["applied"] = True
            args.state.write_text(json.dumps(report, indent=2))
        except Exception:
            for row in reversed(modified):
                Path("/proc/irq/{}/smp_affinity_list".format(row["irq"])).write_text(row["original"])
            args.state.unlink()
            raise
    print(json.dumps(dict(report, ok=True)))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1)
