"""Synchronize the local delivery copy and ZIP using an explicit source list."""
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "音视频代码包"
ARCHIVE = ROOT / "EVM3588-B_音视频代码包.zip"

files = [ROOT / name for name in (
    "deploy.ps1", "refresh_status.ps1", "README.txt", "README.md",
    "board_status.example.js", "EVM3588-B_音视频实时压缩方案.html",
)]
for directory in ("board", "docs", "tools"):
    files.extend(path for path in (ROOT / directory).rglob("*")
                 if path.is_file() and not any(part in {'runtime','build','state','logs','recordings','snapshots','__pycache__'} for part in path.relative_to(ROOT).parts)
                 and path.name != 'config.json' and (path.suffix in {".sh", ".c", ".h", ".md", ".html", ".py", ".json", ".yml", ".patch"}
                                       or path.name == "Makefile"))

entries = []
for source in sorted(set(files)):
    relative = source.relative_to(ROOT)
    destination = PACKAGE / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    copy2(source, destination)
    entries.append(relative)

# Never package the locally generated snapshot with device IDs and addresses.
copy2(ROOT / "board_status.example.js", PACKAGE / "board_status.js")
entries.append(Path("board_status.js"))

with ZipFile(ARCHIVE, "w", compression=ZIP_DEFLATED) as archive:
    for relative in sorted(entries):
        archive.write(PACKAGE / relative, relative.as_posix())
with ZipFile(ARCHIVE) as archive:
    assert archive.testzip() is None
    for relative in entries:
        assert archive.read(relative.as_posix()) == (PACKAGE / relative).read_bytes()
print(f"Delivery copy and ZIP verified: {len(entries)} files; live state excluded")
