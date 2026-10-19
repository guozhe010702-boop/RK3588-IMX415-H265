"""Build a portable Windows folder and ZIP using locked project dependencies."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED
from evm_console import __version__

ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(); parser.add_argument('--ffmpeg',help='Windows ffmpeg.exe path; defaults to PATH')
args=parser.parse_args()
source=Path(args.ffmpeg or shutil.which('ffmpeg') or '')
if not source.is_file(): raise SystemExit('Pass --ffmpeg with a Windows ffmpeg.exe path')
vendor=ROOT/'vendor/ffmpeg'; vendor.mkdir(parents=True,exist_ok=True)
source_digest=hashlib.sha256(source.read_bytes()).hexdigest()
destination=vendor/'ffmpeg.exe'
if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest()!=source_digest:
    shutil.copy2(source,destination)
version=subprocess.check_output([str(source),'-version'],text=True,encoding='utf-8',errors='replace')
manifest={'application':__version__,'python':sys.version,'ffmpegSha256':source_digest,
          'ffmpegVersion':version,'dependencies':{item.metadata['Name']:item.version for item in importlib.metadata.distributions()}}
application_sources = [ROOT/'main.py', ROOT/'requirements.lock.txt', ROOT/'README_PORTABLE.txt',
                       ROOT/'THIRD_PARTY_NOTICES.md'] + sorted((ROOT/'evm_console').glob('*.py'))
manifest['sourceSha256'] = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in application_sources}
(ROOT/'vendor/build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
# PNG icon is rendered from the project SVG; PyInstaller converts it for Windows.
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
image=QImage(256,256,QImage.Format.Format_ARGB32); image.fill(0); painter=QPainter(image)
QSvgRenderer(str(ROOT/'assets/camera.svg')).render(painter); painter.end(); image.save(str(ROOT/'vendor/camera.png'))
command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','EVM3588CameraConsole',
         '--distpath',str(ROOT.parent/'releases/desktop'/__version__),'--workpath',str(ROOT.parent/'.cache/desktop-build'/__version__),'--specpath',str(ROOT.parent/'.cache/desktop-build'/__version__),
         '--icon',str(ROOT/'vendor/camera.png'),'--add-data',str(ROOT/'assets')+';assets',
         '--add-data',str(ROOT/'THIRD_PARTY_NOTICES.md')+';.',
         '--hidden-import','keyring.backends.Windows','--exclude-module','PySide6.QtWebEngineCore',
         '--exclude-module','PySide6.QtWebEngineWidgets','--exclude-module','PySide6.QtQml',
         '--exclude-module','PySide6.QtQuick','--exclude-module','PySide6.QtPdf','--exclude-module','pytest',
         str(ROOT/'main.py')]
subprocess.run(command,check=True,cwd=ROOT)
if manifest['sourceSha256'] != {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in application_sources}:
    raise SystemExit('Application sources changed during packaging; rebuild before delivery')
delivery=ROOT.parent/'releases/desktop'/__version__/'EVM3588CameraConsole'; ffmpeg=delivery/'ffmpeg'; ffmpeg.mkdir(exist_ok=True)
shutil.copy2(source,ffmpeg/'ffmpeg.exe')
for name in ('README_PORTABLE.txt','THIRD_PARTY_NOTICES.md'): shutil.copy2(ROOT/name,delivery/name)
shutil.copy2(ROOT/'vendor/build-manifest.json',delivery/'build-manifest.json')
licenses=delivery/'licenses'; licenses.mkdir(exist_ok=True)
for distribution in importlib.metadata.distributions():
    for entry in distribution.files or []:
        if 'licenses' in entry.parts or entry.name.upper().startswith(('LICENSE','COPYING')):
            file=Path(distribution.locate_file(entry))
            if file.is_file():
                target=licenses/distribution.metadata['Name']/entry.name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(file,target)
license_candidates=[source.parent/'LICENSE',source.parent.parent/'LICENSE',source.parent.parent/'LICENSE.txt']
for candidate in license_candidates:
    if candidate.is_file(): shutil.copy2(candidate,licenses/'FFmpeg-LICENSE.txt'); break
archive=ROOT.parent/'releases'/f'EVM3588CameraConsole-Windows-x64-v{__version__}.zip'
with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=6) as out:
    for file in delivery.rglob('*'):
        if file.is_file(): out.write(file,file.relative_to(delivery.parent).as_posix())
with ZipFile(archive) as out: assert out.testzip() is None
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n')
print(json.dumps({'zip':str(archive),'bytes':archive.stat().st_size,'sha256':digest}))
