"""Record toolchain, source identities and deployed ELF hashes (no model payloads)."""

import hashlib, json, os, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    def run(*args):
        return subprocess.check_output(args, text=True).strip()

    compiler = os.environ.get("CC", "aarch64-linux-gnu-gcc")
    tag = run(compiler, "-dumpversion").split(".")[0]
    flags = (
        ROOT / "build" / ("arm64-gcc" + tag) / "CMakeFiles/rknn_yolo_world_realtime.dir/flags.make"
    ).read_text()
    if "-O3" not in flags or "-DNDEBUG" not in flags:
        raise SystemExit("Release optimization flags are missing; package refused")
    entries = {}
    for path in (ROOT / "dist").rglob("*"):
        if path.is_file() and (
            path.name == "rknn_yolo_world_realtime" or "/lib/" in path.as_posix()
        ):
            entries[path.relative_to(ROOT / "dist").as_posix()] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
    data = {
        "compiler": run(compiler, "--version").splitlines()[0],
        "cmake": run("cmake", "--version").splitlines()[0],
        "target": "Ubuntu 20.04 ARM64 / GLIBC <=2.31",
        "sourceLock": hashlib.sha256((ROOT / "sources.lock.json").read_bytes()).hexdigest(),
        "privateNutFFmpeg": "7.1.1, LGPL-2.1-or-later; NUT muxer only",
        "parallelJobs": 4,
        "cxxFlagsRelease": "-O3 -DNDEBUG",
        "sourceFiles": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(
                list((ROOT / "src").glob("*.cpp"))
                + list((ROOT / "include").glob("*.hpp"))
                + [ROOT / "CMakeLists.txt", ROOT / "tools/build_linux.sh"]
            )
        },
        "runtimeFiles": entries,
    }
    (ROOT / "dist/build-manifest.json").write_text(json.dumps(data, indent=2) + "\n")
    print("Build manifest written.")


if __name__ == "__main__":
    main()
