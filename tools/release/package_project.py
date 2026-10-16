"""Build one source ZIP, without making another editable source directory."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'releases/av_dev-source.zip'
OUTPUT.parent.mkdir(exist_ok=True)
EXCLUDED = {'__pycache__', '.pytest_cache', 'runtime', 'build', 'dist', 'vendor',
            'state', 'logs', 'recordings', 'snapshots'}
EXTENSIONS = {'.sh','.c','.h','.dts','.md','.py','.json','.yml','.patch','.txt','.ps1','.svg','.html','.js'}
files = [ROOT/name for name in ('README.md','.gitignore','.gitattributes')]
for folder in ('board','desktop','docs','examples','tools','web'):
    for file in (ROOT/folder).rglob('*'):
        relative=file.relative_to(ROOT)
        if (file.is_file() and not any(part in EXCLUDED for part in relative.parts)
            and file.name not in ('config.json','board_status.js')
            and (file.suffix in EXTENSIONS or file.name=='Makefile')):
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
