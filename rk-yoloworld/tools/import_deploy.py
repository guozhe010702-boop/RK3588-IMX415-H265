"""Import expected model data/runtime from deploy.zip OR its extracted directory.

Never executes supplied demo binaries. Archive paths and directory symlinks are
checked before writing only the explicitly allowed destination files.
"""

import argparse, hashlib, json, stat, zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "clip_text_fp16.rknn": "model/clip_text_fp16.rknn",
    "yolo_world_v2s_i8.rknn": "model/yolo_world_v2s_i8.rknn",
    "detect_classes.txt": "model/detect_classes.txt",
    "librknnrt.so": "lib/librknnrt.so",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    data = {}
    manifest = {"input": source.name, "files": {}}
    optional = {"bus.jpg": "model/bus.jpg", "librga.so": "package-libraries/librga.so"}
    wanted = dict(FILES, **optional)
    if source.is_dir():
        for name in wanted:
            paths = [p for p in source.rglob(name) if p.is_file()]
            if len(paths) > 1:
                raise ValueError("Ambiguous entry: " + name)
            if paths:
                path = paths[0].resolve()
                if source not in path.parents:
                    raise ValueError("Escaping directory symlink")
                data[name] = path.read_bytes()
    else:
        manifest["archive_sha256"] = digest(source.read_bytes())
        manifest["archive_bytes"] = source.stat().st_size
        with zipfile.ZipFile(source) as z:
            for item in z.infolist():
                path = PurePosixPath(item.filename.replace("\\", "/"))
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or any(":" in part for part in path.parts)
                ):
                    raise ValueError("Unsafe archive path")
                if path.name not in wanted or stat.S_ISLNK(item.external_attr >> 16):
                    continue
                if path.name in data:
                    raise ValueError("Ambiguous archive entry")
                if item.file_size > 512 * 1024 * 1024:
                    raise ValueError("Unexpected large package entry")
                data[path.name] = z.read(item)
    missing = set(FILES) - set(data)
    if missing:
        raise ValueError("Missing files: " + str(missing))
    for name, content in data.items():
        target = ROOT / "dist" / wanted[name]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        manifest["files"][wanted[name]] = {"sha256": digest(content), "bytes": len(content)}
    (ROOT / "dist/package-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Imported models/runtime; original demo was not executed. Board-tested RGA remains selected."
    )


if __name__ == "__main__":
    main()
