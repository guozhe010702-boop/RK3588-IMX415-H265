"""Package local candidate firmware only; never publish or flash it."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / '.cache/bsp'
SOURCE = ROOT / 'board/bsp/imx415-4k60'
fit = BUILD / 'fit-candidate'
manifest = json.loads((fit / 'boot-candidate.json').read_text())
binary = fit / 'boot-candidate.img'
assert hashlib.sha256(binary.read_bytes()).hexdigest() == manifest['candidateBootSha256']
files = {file.name: file for file in SOURCE.iterdir() if file.is_file()}
files.update({'boot-candidate.img': binary, 'boot-candidate.json': fit / 'boot-candidate.json',
              'candidate.dtb': fit / 'candidate.dtb', 'candidate.its': fit / 'candidate.its',
              'kernel.config': BUILD / 'matched-kernel.config'})
release = ROOT / 'releases/EVM3588-IMX415-4K60-BSP-CANDIDATE-20261016.zip'
with ZipFile(release, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
    for name, file in files.items():
        archive.write(file, 'UNVALIDATED-CANDIDATE/' + name)
with ZipFile(release) as archive:
    assert archive.testzip() is None
digest = hashlib.sha256(release.read_bytes()).hexdigest()
release.with_suffix('.zip.sha256').write_text(digest + '  ' + release.name + '\n')
print(json.dumps({'zip': str(release), 'sha256': digest, 'bytes': release.stat().st_size,
                  'flashed': False, 'real4k60Validated': False}))
