"""Build one source ZIP, without making another editable source directory."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import os

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'releases/av_dev-source.zip'
OUTPUT.parent.mkdir(exist_ok=True)
EXCLUDED = {'__pycache__', '.pytest_cache', 'runtime', 'build', 'dist', 'vendor',
            'state', 'logs', 'recordings', 'snapshots', '.cache', 'rknn_yolo_world_demo',
            'models', 'lib', 'inputs', '.git', '.venv', '.venv-desktop'}
EXTENSIONS = {'.sh','.c','.h','.cpp','.hpp','.dts','.md','.py','.json','.yml','.patch','.txt','.ps1','.svg','.html','.js','.env'}
files = [ROOT/name for name in ('README.md','.gitignore','.gitattributes')]
for folder in ('board','desktop','docs','examples','tools','web','rk-yoloworld'):
    for directory, subdirs, names in os.walk(ROOT/folder, followlinks=False):
        # Prune caches before traversing them: Linux build symlinks may be
        # inaccessible from Windows, and private runtime trees are not source.
        subdirs[:] = [name for name in subdirs if name not in EXCLUDED
                      and not (Path(directory)/name).is_symlink()]
        for name in names:
            file=Path(directory)/name
            if (file.name not in ('config.json','board_status.js')
                and (file.suffix in EXTENSIONS or file.name in {'Makefile','Dockerfile','LICENSE',
                     '.gitignore','.gitattributes','.dockerignore','.clang-format'})
                and not file.is_symlink() and file.is_file()):
                files.append(file)
for name in ('releases/README.md','reference/README.md'):
    if (ROOT/name).is_file(): files.append(ROOT/name)
temporary=OUTPUT.with_suffix('.tmp.zip')
with ZipFile(temporary,'w',ZIP_DEFLATED) as archive:
    for file in sorted(set(files)):
        archive.write(file,file.relative_to(ROOT).as_posix())
    archive.write(ROOT/'web/board_status.example.js','web/board_status.js')
with ZipFile(temporary) as archive:
    assert archive.testzip() is None
    for file in set(files):
        assert archive.read(file.relative_to(ROOT).as_posix())==file.read_bytes()
temporary.replace(OUTPUT)
OUTPUT.with_suffix('.zip.sha256').write_text(hashlib.sha256(OUTPUT.read_bytes()).hexdigest()+'  '+OUTPUT.name+'\n')
print(f'Verified source ZIP: {len(set(files))+1} files; {OUTPUT}')
