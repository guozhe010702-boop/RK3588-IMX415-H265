"""Linux-only: repack a verified original FIT with candidate kernel and DT opt-in.

Requires official dtc/fdtput and U-Boot mkimage. Never opens a block device.
All firmware outputs stay local. The result is not a board-validated release.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess


def properties(blob):
    if len(blob) < 40:
        raise ValueError('Short FDT header')
    magic, total, structure, strings = struct.unpack_from('>4I', blob)
    if magic != 0xd00dfeed or total > len(blob):
        raise ValueError('Invalid FIT header')
    result, stack, cursor = {}, [], structure
    while cursor < total:
        token, = struct.unpack_from('>I', blob, cursor)
        cursor += 4
        if token == 1:
            end = blob.index(b'\0', cursor)
            stack.append(blob[cursor:end].decode())
            cursor = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, name_offset = struct.unpack_from('>2I', blob, cursor)
            cursor += 8
            offset = strings + name_offset
            name = blob[offset:blob.index(b'\0', offset)].decode()
            result[('/'.join(stack), name)] = blob[cursor:cursor+size]
            cursor = (cursor + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            return result
        else:
            raise ValueError('Unknown FDT token')
    raise ValueError('Missing FDT end')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--original-sha256', required=True)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for tool in ('mkimage', 'fdtput'):
        if not shutil.which(tool):
            raise SystemExit('Missing ' + tool)
    raw = args.original.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.original_sha256:
        raise SystemExit('Original boot backup checksum mismatch')
    p = properties(raw)
    if any('signature' in node and key == 'value' for node, key in p):
        raise SystemExit('Signed original FIT: requires matching signing workflow')
    args.output.mkdir(parents=True, exist_ok=True)
    def integer(node, key):
        value = p[(node, key)]
        if len(value) != 4:
            raise ValueError('Unsupported FIT integer')
        return struct.unpack('>I', value)[0]
    originals = {}
    for name in ('fdt', 'kernel', 'ramdisk', 'resource'):
        node = '/images/' + name
        start, size = integer(node, 'data-position'), integer(node, 'data-size')
        data = raw[start:start+size]
        if len(data) != size or hashlib.sha256(data).digest() != p[(node+'/hash', 'value')]:
            raise ValueError('Original FIT payload hash mismatch: ' + name)
        originals[name] = data
        (args.output / ('original-' + name + '.bin')).write_bytes(data)
    dtb = args.output / 'candidate.dtb'
    dtb.write_bytes(originals['fdt'])
    sensor = '/i2c@feaa0000/imx415@36'
    original_dt = properties(originals['fdt'])
    if original_dt.get((sensor, 'compatible')) != b'sony,imx415\0':
        raise ValueError('Original DT does not match con7 sensor path')
    subprocess.run(['fdtput', str(dtb), sensor, 'dvsense,experimental-4k60'], check=True)
    subprocess.run(['fdtput', '-t', 'i', str(dtb), sensor, 'rockchip,camera-hdr-mode', '0'], check=True)
    shutil.copyfile(args.kernel, args.output / 'candidate-kernel.bin')
    # Preserve the original initramfs and resource payload; only kernel and primary DTB change.
    # The primary DTB is copied from the actual boot partition, not a guessed SDK board DTS.
    nodes = []
    for name, file in [('fdt', 'candidate.dtb'), ('kernel', 'candidate-kernel.bin'),
                       ('ramdisk', 'original-ramdisk.bin'), ('resource', 'original-resource.bin')]:
        node = '/images/' + name
        lines = [name + ' {', 'data = /incbin/("' + file + '");']
        for key in ('type', 'arch', 'os', 'compression'):
            if (node, key) in p:
                text = p[(node, key)].rstrip(b'\0').decode('ascii')
                if not text.replace('_', '').isalnum():
                    raise ValueError('Unexpected original FIT string')
                lines.append(key + ' = "' + text + '";')
        for key in ('entry', 'load'):
            if (node, key) in p:
                lines.append(key + ' = <0x{:x}>;'.format(integer(node, key)))
        lines.append('hash { algo = "sha256"; }; };')
        nodes.append('\n'.join(lines))
    payload_files = ['candidate.dtb', 'candidate-kernel.bin', 'original-ramdisk.bin', 'original-resource.bin']
    external_size = 0x800 + sum((args.output.joinpath(file).stat().st_size + 0x1ff) & ~0x1ff for file in payload_files)
    fit_size = (external_size + 0xfff) & ~0xfff
    version = struct.unpack('>I', p[('', 'version')])[0]
    its = ('/dts-v1/; / { description = "EVM3588 B1 UNVALIDATED 4K60 candidate"; '
           'version = <0x%x>; totalsize = <0x%x>; ' % (version, fit_size) +
           '#address-cells = <1>; images {\n' + '\n'.join(nodes) + '\n}; '
           'configurations { default = "conf"; conf { rollback-index = <0>; '
           'fdt = "fdt"; kernel = "kernel"; ramdisk = "ramdisk"; multi = "resource"; }; }; };\n')
    (args.output / 'candidate.its').write_text(its)
    subprocess.run(['mkimage', '-f', 'candidate.its', '-E', '-p', '0x800', '-B', '0x200',
                    'boot-candidate.img'], cwd=args.output, check=True)
    candidate = (args.output / 'boot-candidate.img').read_bytes()
    if len(candidate) != external_size or len(candidate) > fit_size:
        raise ValueError('Unexpected mkimage external payload alignment')
    candidate += b'\0' * (fit_size - len(candidate))
    (args.output / 'boot-candidate.img').write_bytes(candidate)
    cp = properties(candidate)
    for name in ('fdt', 'kernel', 'ramdisk', 'resource'):
        node = '/images/' + name
        offset = struct.unpack('>I', cp[(node, 'data-position')])[0]
        size = struct.unpack('>I', cp[(node, 'data-size')])[0]
        if hashlib.sha256(candidate[offset:offset+size]).digest() != cp[(node+'/hash', 'value')]:
            raise ValueError('Candidate payload verification failed: ' + name)
    if len(candidate) > len(raw):
        raise ValueError('Candidate exceeds original partition size')
    report = {'status': 'UNVALIDATED_CANDIDATE_NOT_FLASHED', 'originalBootSha256': args.original_sha256,
        'candidateBootSha256': hashlib.sha256(candidate).hexdigest(), 'bytes': len(candidate),
        'partitionBytes': len(raw), 'kernelSha256': hashlib.sha256(args.kernel.read_bytes()).hexdigest(),
        'dtbSha256': hashlib.sha256(dtb.read_bytes()).hexdigest(), 'realCamera4k60Validated': False,
        'unchangedPayloads': ['ramdisk', 'resource'], 'sensorPath': sensor,
        'systemSwitchApproved': False, 'recoveryBootTested': False}
    (args.output / 'boot-candidate.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
