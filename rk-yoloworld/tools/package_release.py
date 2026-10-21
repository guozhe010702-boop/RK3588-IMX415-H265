"""Create local deployment + corresponding source ZIPs, never includes test logs."""

import hashlib, json, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def add(z, path, name):
    entry = zipfile.ZipInfo(name)
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = (
        0o100755 if path.suffix == ".sh" or path.name == "rknn_yolo_world_realtime" else 0o100644
    ) << 16
    z.writestr(entry, path.read_bytes())


def main():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    source = dist / "rk-yoloworld-source.zip"
    with zipfile.ZipFile(source, "w") as z:
        for folder in ["src", "include", "tests", "tools", "licenses"]:
            for path in (ROOT / folder).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    add(z, path, "rk-yoloworld/" + path.relative_to(ROOT).as_posix())
        for name in [
            "README.md",
            "VALIDATION.md",
            "todo.md",
            "CMakeLists.txt",
            "sources.lock.json",
            "config.env",
            "run_realtime_yolo_world.sh",
            "receive_windows.ps1",
            ".gitignore",
            ".clang-format",
            ".dockerignore",
            ".gitattributes",
            "LICENSE",
            "THIRD_PARTY.md",
        ]:
            add(z, ROOT / name, "rk-yoloworld/" + name)
        for path in (ROOT / "vendor").rglob("*"):
            if path.is_file() and path.suffix != ".so":
                add(z, path, "rk-yoloworld/" + path.relative_to(ROOT).as_posix())
    required = [
        "rknn_yolo_world_realtime",
        "model/clip_text_fp16.rknn",
        "model/yolo_world_v2s_i8.rknn",
        "model/detect_classes.txt",
        "lib/librknnrt.so",
        "lib/librga.so.2",
        "lib/libavformat.so.61",
        "package-manifest.json",
        "build-manifest.json",
    ]
    for name in required:
        if not (dist / name).is_file():
            raise SystemExit("Missing deployment component: " + name)
    deploy = dist / "rk-yoloworld-EVM3588-arm64.zip"
    with zipfile.ZipFile(deploy, "w") as z:
        for path in dist.rglob("*"):
            if (
                path.is_file()
                and path.suffix != ".zip"
                and path.name != "release-sha256.json"
                and "package-libraries" not in path.parts
            ):
                add(z, path, "rk-yoloworld/" + path.relative_to(dist).as_posix())
        for name in [
            "README.md",
            "VALIDATION.md",
            "THIRD_PARTY.md",
            "LICENSE",
            "receive_windows.ps1",
        ]:
            add(z, ROOT / name, "rk-yoloworld/" + name)
        for name in ["run_with_restore.py", "hdmi_preview.py", "monitor.py"]:
            add(z, ROOT / "tools" / name, "rk-yoloworld/tools/" + name)
        for path in (ROOT / "licenses").iterdir():
            add(z, path, "rk-yoloworld/licenses/" + path.name)
        add(z, source, "rk-yoloworld/source/" + source.name)
    manifest = {
        p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        for p in (source, deploy)
    }
    (dist / "release-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
