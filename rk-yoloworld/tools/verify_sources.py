"""Fail before compilation if a locked source/header has changed."""

import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    data = json.loads((ROOT / "sources.lock.json").read_text())
    for name, item in data["files"].items():
        path = ROOT / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit("Missing/modified locked source: " + name)
    print("Locked source checksums OK:", len(data["files"]))


if __name__ == "__main__":
    main()
