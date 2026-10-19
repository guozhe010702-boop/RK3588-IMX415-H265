"""Package the reviewed boot trial, without writing devices or publishing it."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fit-dir', type=Path, default=ROOT/'.cache/bsp/fit-candidate-b1-v2')
    parser.add_argument('--partition-image', type=Path, required=True,
                        help='Reviewed zero-padded 64 MiB ordinary image file')
    parser.add_argument('--output', type=Path,
                        default=ROOT/'releases/EVM3588-IMX415-4K60-BSP-TRIAL-20261019.zip')
    args = parser.parse_args()
    source = ROOT/'board/bsp/imx415-4k60'
    review = json.loads((source/'build-validation.json').read_text(encoding='utf-8'))
    manifest = json.loads((args.fit_dir/'boot-candidate.json').read_text(encoding='utf-8'))
    fit = (args.fit_dir/'boot-candidate.img').read_bytes()
    partition = args.partition_image.read_bytes()
    if (hashlib.sha256(fit).hexdigest() != manifest['candidateBootSha256']
            or manifest['candidateBootSha256'] != review['candidateBootSha256']
            or len(partition) != 67108864 or not partition.startswith(fit)
            or partition[len(fit):] != bytes(len(partition)-len(fit))
            or hashlib.sha256(partition).hexdigest() != review['partitionImageSha256']):
        raise SystemExit('Candidate/review/partition image mismatch; refusing to package')
    files = {p.relative_to(source).as_posix(): p for p in source.rglob('*')
             if p.is_file() and '__pycache__' not in p.parts}
    files.update({'boot-candidate-partition.img': args.partition_image,
                  'fit-manifest.json': args.fit_dir/'boot-candidate.json',
                  'candidate.dtb': args.fit_dir/'candidate.dtb',
                  'candidate.its': args.fit_dir/'candidate.its',
                  'tools/prepare_boot_candidate.py': ROOT/'tools/dev/prepare_boot_candidate.py',
                  'kernel.config': ROOT/'.cache/bsp/matched-kernel.config'})
    args.output.parent.mkdir(exist_ok=True, parents=True)
    with ZipFile(args.output, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
        for name, file in files.items():
            archive.write(file, 'BSP-TRIAL/' + name)
    with ZipFile(args.output) as archive:
        if archive.testzip() is not None:
            raise SystemExit('BSP ZIP integrity check failed')
        for name, file in files.items():
            if archive.read('BSP-TRIAL/'+name) != file.read_bytes():
                raise SystemExit('BSP ZIP differs from reviewed files')
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.zip.sha256').write_text(digest+'  '+args.output.name+'\n')
    print(json.dumps({'zip': str(args.output), 'sha256': digest, 'bytes': args.output.stat().st_size,
                      'bootTested': review['bootTested'],
                      'real4k60Validated': review['realCamera4k60Validated'],
                      'deviceWritesPerformedByPackaging': False}))


if __name__ == '__main__':
    main()
