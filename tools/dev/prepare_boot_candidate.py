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


def resource_entries(blob):
    """Validate Rockchip RSCE v0 directory and every content checksum."""
    if len(blob) < 512 or blob[:12] != b'RSCE\0\0\0\0\x01\x01\x01\0':
        raise ValueError('Unsupported resource header')
    count, = struct.unpack_from('<I', blob, 12)
    if not 0 < count <= 128 or (count + 1) * 512 > len(blob):
        raise ValueError('Invalid resource directory size')
    entries, names, ranges = [], set(), []
    for index in range(count):
        entry = 512 * (index + 1)
        if blob[entry:entry + 4] != b'ENTR':
            raise ValueError('Invalid resource entry')
        name = blob[entry + 4:entry + 224].split(b'\0', 1)[0].decode('ascii')
        hash_size, sector, size = struct.unpack_from('<III', blob, entry + 256)
        start, end = sector * 512, sector * 512 + size
        if not name or name in names or hash_size not in (20, 32):
            raise ValueError('Invalid resource name/hash')
        if start < (count + 1) * 512 or end > len(blob) or not size:
            raise ValueError('Resource content out of bounds')
        if any(start < b and end > a for a, b in ranges):
            raise ValueError('Overlapping resource content')
        digest = hashlib.new('sha1' if hash_size == 20 else 'sha256', blob[start:end]).digest()
        if digest != blob[entry + 224:entry + 224 + hash_size]:
            raise ValueError('Resource content checksum mismatch: ' + name)
        entries.append((name, entry, start, size, hash_size))
        names.add(name); ranges.append((start, end))
    return entries


def replace_resource_entry(blob, name, content):
    """Replace exactly one entry inside its existing allocated sector range."""
    entries = resource_entries(blob)
    matches = [e for e in entries if e[0] == name]
    if len(matches) != 1:
        raise ValueError('Resource target not found')
    _, entry, start, size, hash_size = matches[0]
    limit = min([e[2] for e in entries if e[2] > start] + [len(blob)])
    if not content or start + len(content) > limit:
        raise ValueError('Replacement exceeds allocated resource range')
    out = bytearray(blob)
    out[start:start + max(size, len(content))] = content + b'\0' * max(0, size - len(content))
    out[entry + 224:entry + 224 + hash_size] = hashlib.new(
        'sha1' if hash_size == 20 else 'sha256', content).digest()
    struct.pack_into('<I', out, entry + 264, len(content))
    resource_entries(out)
    return bytes(out)


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
    # EVM3588 B1 U-Boot selects this resource DT by SARADC channel 5. Merely
    # changing FIT /images/fdt leaves the actual running sensor DT unchanged.
    resource_name = 'evm3588#_saradc_ch5=3754.dtb'
    entries = resource_entries(originals['resource'])
    selected = [e for e in entries if e[0] == resource_name]
    if len(selected) != 1:
        raise ValueError('Missing board-specific B1 resource DTB')
    _, _, start, size, _ = selected[0]
    original_b1 = originals['resource'][start:start + size]
    if properties(original_b1).get(('', 'model')) != b'Rockchip RK3588 EVM3588 B1 Board\0':
        raise ValueError('Resource DTB is not the actual B1 board')
    dtb = args.output / 'candidate.dtb'
    dtb.write_bytes(original_b1)
    sensor = '/i2c@feaa0000/imx415@36'
    original_dt = properties(original_b1)
    if original_dt.get((sensor, 'compatible')) != b'sony,imx415\0':
        raise ValueError('Original DT does not match con7 sensor path')
    subprocess.run(['fdtput', str(dtb), sensor, 'dvsense,experimental-4k60'], check=True)
    subprocess.run(['fdtput', '-t', 'i', str(dtb), sensor, 'rockchip,camera-hdr-mode', '0'], check=True)
    patched = dtb.read_bytes()
    expected_dt = dict(original_dt)
    expected_dt[(sensor, 'dvsense,experimental-4k60')] = b''
    expected_dt[(sensor, 'rockchip,camera-hdr-mode')] = struct.pack('>I', 0)
    if properties(patched) != expected_dt:
        raise ValueError('DT patch modified unexpected board properties')
    resource = replace_resource_entry(originals['resource'], resource_name, patched)
    (args.output / 'candidate-resource.bin').write_bytes(resource)
    shutil.copyfile(args.kernel, args.output / 'candidate-kernel.bin')
    # Preserve initramfs, all other board DTBs and logos; use the same B1 DTB in
    # the primary FIT slot and the resource entry actually chosen by U-Boot.
    nodes = []
    for name, file in [('fdt', 'candidate.dtb'), ('kernel', 'candidate-kernel.bin'),
                       ('ramdisk', 'original-ramdisk.bin'), ('resource', 'candidate-resource.bin')]:
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
    payload_files = ['candidate.dtb', 'candidate-kernel.bin', 'original-ramdisk.bin', 'candidate-resource.bin']
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
        'unchangedPayloads': ['ramdisk'], 'sensorPath': sensor,
        'resourceDtbEntry': resource_name, 'packagingRevision': 2,
        'resourceSha256': hashlib.sha256(resource).hexdigest(),
        'systemSwitchApproved': False, 'recoveryBootTested': False}
    (args.output / 'boot-candidate.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
