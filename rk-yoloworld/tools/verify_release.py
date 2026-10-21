"""Check ZIP integrity and correspondence with the tested executable and sources."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    dist = ROOT / "dist"
    manifest = json.loads((dist / "release-sha256.json").read_text())
    build = json.loads((dist / "build-manifest.json").read_text())
    for name, expected in manifest.items():
        path = dist / name
        assert path.stat().st_size == expected["bytes"], name
        assert digest(path.read_bytes()) == expected["sha256"], name
    with zipfile.ZipFile(dist / "rk-yoloworld-source.zip") as source, zipfile.ZipFile(
        dist / "rk-yoloworld-EVM3588-arm64.zip"
    ) as deploy:
        for archive in (source, deploy):
            assert archive.testzip() is None
            names = archive.namelist()
            assert len(names) == len(set(names)), "Duplicate ZIP entries"
            assert all(n.startswith("rk-yoloworld/") and ".." not in Path(n).parts for n in names)
            assert not any("/logs/" in n or "/state/" in n or "/.cache/" in n for n in names)
        assert not any(n.endswith((".rknn", ".so", ".jpg", ".ts")) for n in source.namelist())
        for name, expected in build["sourceFiles"].items():
            assert digest(source.read("rk-yoloworld/" + name)) == expected, name
        for name, expected in build["runtimeFiles"].items():
            assert digest(deploy.read("rk-yoloworld/" + name)) == expected["sha256"], name
        assert (
            deploy.read("rk-yoloworld/source/rk-yoloworld-source.zip")
            == (dist / "rk-yoloworld-source.zip").read_bytes()
        )
        assert deploy.read("rk-yoloworld/README.md") == (ROOT / "README.md").read_bytes()
        for name in ("run_with_restore.py", "hdmi_preview.py", "monitor.py"):
            assert deploy.read("rk-yoloworld/tools/" + name) == (ROOT / "tools" / name).read_bytes()
        imported = json.loads((dist / "package-manifest.json").read_text())["files"]
        for name, expected in imported.items():
            if not name.startswith("package-libraries/"):
                assert digest(deploy.read("rk-yoloworld/" + name)) == expected["sha256"], name
    print(
        json.dumps(
            {
                "zipIntegrity": True,
                "sourcesMatch": True,
                "runtimeMatches": True,
                "executable": build["runtimeFiles"]["rknn_yolo_world_realtime"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
