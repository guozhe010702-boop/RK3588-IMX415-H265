"""Fetch pinned reference tokenizer and SDK headers; no board changes."""

import hashlib, json, urllib.request, subprocess, tarfile, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = "5b6995905425115029ad63820a007368d2a2882f"
LOCK = (
    json.loads((ROOT / "sources.lock.json").read_text())
    if (ROOT / "sources.lock.json").exists()
    else {}
)


def fetch(url, path):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    expected = LOCK.get("files", {}).get(path)
    if expected and p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == expected["sha256"]:
        return expected
    data = urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "rk-yoloworld-source-preparation"}),
        timeout=60,
    ).read()
    if expected and hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise ValueError("Source checksum mismatch: " + path)
    p.write_bytes(data)
    return {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    entries = {}
    base = "https://raw.githubusercontent.com/zyp0424/-RK3588-yolo-world-/" + REF + "/"
    for name in ["clip_tokenizer.cpp", "clip_tokenizer.h", "clip_vocab.h"]:
        dest = "vendor/tokenizer/" + name
        entries[dest] = fetch(base + "cpp/tokenizer/" + name, dest)
    for name in ["LICENSE", "cpp/postprocess.cc", "cpp/realtime_main.cc"]:
        dest = "vendor/reference/" + name.replace("/", "-")
        entries[dest] = fetch(base + name, dest)
    sdk = "https://raw.githubusercontent.com/airockchip/rknn-toolkit2/v2.3.2/rknpu2/runtime/Linux/librknn_api/include/rknn_api.h"
    entries["vendor/include/rknn_api.h"] = fetch(sdk, "vendor/include/rknn_api.h")
    # Stock FFmpeg only supplies a tiny private NUT muxer, never capture/encoding.
    entries["vendor/ffmpeg-7.1.1.tar.xz"] = fetch(
        "https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz", "vendor/ffmpeg-7.1.1.tar.xz"
    )
    # RGA archive is also shipped in the local source bundle. Recreate from the
    # fixed Git revision on a fresh source-only checkout if it is not present.
    archive = ROOT / "vendor/rga-source.tar.gz"
    if not archive.exists():
        repo = ROOT / "build/rga-checkout"
        repo.parent.mkdir(exist_ok=True)
        subprocess.run(
            ["git", "clone", "https://gitee.com/nyanmisaka/rga.git", str(repo)], check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "archive",
                "--format=tar.gz",
                "--output=" + str(archive),
                "1d330cc28551943bed3380261a5a9c6fbd58ff53",
            ],
            check=True,
        )
    source = ROOT / "build/rga-source"
    source.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        for item in tar.getmembers():
            target = (source / item.name).resolve()
            if source.resolve() not in target.parents and target != source.resolve():
                raise ValueError("Unsafe RGA archive")
            if item.issym() or item.islnk():
                raise ValueError("Unexpected RGA archive link")
        tar.extractall(source)
    for group in ["im2d_api", "include"]:
        for header in (source / group).glob("*.h*"):
            dest = "vendor/include/rga/" + header.name
            data = header.read_bytes()
            expected = LOCK.get("files", {}).get(dest)
            if expected and hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise ValueError("RGA header checksum mismatch")
            target = ROOT / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            entries[dest] = {
                "url": "https://gitee.com/nyanmisaka/rga/blob/1d330cc28551943bed3380261a5a9c6fbd58ff53/"
                + group
                + "/"
                + header.name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
    # Preserve validated board library identity separately from reproducible source.
    if LOCK.get("rga"):
        entries_rga = LOCK["rga"]
    else:
        entries_rga = {
            "repository": "https://gitee.com/nyanmisaka/rga.git",
            "commit": "1d330cc28551943bed3380261a5a9c6fbd58ff53",
        }
    (ROOT / "sources.lock.json").write_text(
        json.dumps({"referenceCommit": REF, "rga": entries_rga, "files": entries}, indent=2) + "\n"
    )
    print(json.dumps({p: v["bytes"] for p, v in entries.items()}))


if __name__ == "__main__":
    main()
