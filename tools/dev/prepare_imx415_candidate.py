"""Generate an opt-in, UNVALIDATED 5.10 BSP candidate; never touches a board.

GPL-2.0: register sequence adapted from Miloslav Mrvik's GPL-2.0 patch, pinned
below. Existing Rockchip copyright and driver defaults are preserved.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_COMMIT = 'a779a49f70a7cd3b3732366d02c76f4b48f5a9d4'
REFERENCE_URL = ('https://raw.githubusercontent.com/bambooCZ/rk3588-imx415-4k60/'
                 + REFERENCE_COMMIT + '/imx415-60fps.patch')
MEMBER = 'evm3588_linux_v1.0.3/kernel/drivers/media/i2c/imx415.c'


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('BSP source differs at anchor: ' + old[:80])
    return text.replace(old, new, 1)


def candidate(original, reference):
    # Extract the complete register table, not an FPS-only declaration.
    added = '\n'.join(line[1:] for line in reference.splitlines()
                      if line.startswith('+') and not line.startswith('+++'))
    table = re.search(r'static __maybe_unused const struct regval imx415_linear_10bit_3864x2192_1485M_regs\[\] = \{.*?\n\};', added, re.S)
    if not table:
        raise ValueError('Pinned reference has no expected 1485M table')
    comment = ('/* EXPERIMENTAL: ported from bambooCZ/rk3588-imx415-4k60 @\n'
               ' * ' + REFERENCE_COMMIT + '. GPL-2.0, Miloslav Mrvik.\n'
               ' * 1485 Mbps sensor / 1520 Mbps receiver calibration workaround.\n'
               ' * NOT validated on EVM3588-B 5.10; requires explicit DT opt-in. */\n')
    text = once(original, 'static const struct imx415_mode supported_modes[] = {',
                comment + table[0] + '\n\nstatic const struct imx415_mode supported_modes[] = {')
    mode = '''
	/* Candidate only: 37.125 MHz XVCLK, four lanes, linear RAW10. */
	{
		.bus_fmt = MEDIA_BUS_FMT_SGBRG10_1X10,
		.width = 3864,
		.height = 2192,
		.max_fps = { .numerator = 10000, .denominator = 600000 },
		.exp_def = 0x0928 - 0x08,
		.hts_def = 4324,
		.vts_def = 0x0928,
		.global_reg_list = imx415_global_10bit_3864x2192_regs,
		.reg_list = imx415_linear_10bit_3864x2192_1485M_regs,
		.hdr_mode = NO_HDR,
		.mipi_freq_idx = 4,
		.bpp = 10,
		.vc[PAD0] = V4L2_MBUS_CSI2_CHANNEL_0,
	},
'''
    text = once(text, '\n};\n\nstatic const s64 link_freq_items[] = {', mode + '};\n\nstatic const s64 link_freq_items[] = {')
    text = once(text, '\tMIPI_FREQ_891M,\n};', '\tMIPI_FREQ_891M,\n\t760000000, /* experimental receiver calibration rate, NOT sensor lane rate */\n};')
    text = once(text, '\tu32\t\t\tcfg_num;', '\tu32\t\t\tcfg_num;\n\tbool experimental_4k60;')
    needle = '\tfor (i = 0; i < imx415->cfg_num; i++) {\n\t\tdist = imx415_get_reso_dist'
    text = once(text, needle, '\tif (imx415->experimental_4k60)\n\t\treturn &supported_modes[ARRAY_SIZE(supported_modes) - 1];\n\n' + needle)
    text = once(text, '\t\thdr = (struct rkmodule_hdr_cfg *)arg;\n\t\tw = imx415->cur_mode->width;',
        '\t\thdr = (struct rkmodule_hdr_cfg *)arg;\n'
        '\t\t/* Keep AIQ NO_HDR negotiation on the candidate; reject HDR switches. */\n'
        '\t\tif (imx415->experimental_4k60)\n'
        '\t\t\treturn hdr->hdr_mode == NO_HDR ? 0 : -EINVAL;\n'
        '\t\tw = imx415->cur_mode->width;')
    text = once(text, '\timx415->cfg_num = ARRAY_SIZE(supported_modes);',
        '\timx415->experimental_4k60 = of_property_read_bool(node, "dvsense,experimental-4k60");\n'
        '\tif (imx415->experimental_4k60 && hdr_mode != NO_HDR)\n\t\treturn -EINVAL;\n'
        '\timx415->cfg_num = ARRAY_SIZE(supported_modes) - !imx415->experimental_4k60;')
    text = once(text, '\t\tvblank_min = (mode->height + 46) - mode->height;',
        '\t\tvblank_min = imx415->experimental_4k60 ? vblank_def : 46;\n'
        '\t\t/* Preserve >=1 ms blanking for the experimental online ISP path. */')
    text = once(text, '\timx415->is_thunderboot = IS_ENABLED(CONFIG_VIDEO_ROCKCHIP_THUNDER_BOOT_ISP);',
        '\tif (imx415->experimental_4k60)\n'
        '\t\timx415->cur_mode = &supported_modes[ARRAY_SIZE(supported_modes) - 1];\n\n'
        '\timx415->is_thunderboot = IS_ENABLED(CONFIG_VIDEO_ROCKCHIP_THUNDER_BOOT_ISP);')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--reference', type=Path, help='Previously downloaded pinned patch')
    args = parser.parse_args()
    # This vendor archive is uncompressed USTAR despite its .tar.gz extension.
    with tarfile.open(args.sdk, 'r:*') as archive:
        original = archive.extractfile(MEMBER).read()
    reference = args.reference.read_bytes() if args.reference else urllib.request.urlopen(REFERENCE_URL, timeout=30).read()
    expected_reference = 'e085c1cfaa765f0c4b90666ff53c1dabbb8a4462fd786daa8cbfe9e4e32f75b9'
    if hashlib.sha256(reference).hexdigest() != expected_reference:
        raise ValueError('Pinned reference checksum mismatch')
    old = original.decode('utf-8')
    new = candidate(old, reference.decode('utf-8'))
    output = ROOT / 'board/bsp/imx415-4k60'
    output.mkdir(parents=True, exist_ok=True)
    patch = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
        fromfile='a/drivers/media/i2c/imx415.c', tofile='b/drivers/media/i2c/imx415.c'))
    (output / '0001-experimental-mode.patch').write_text(patch, encoding='utf-8', newline='\n')
    manifest = {'status': 'UNVALIDATED_CANDIDATE', 'kernelBuilt': False, 'bootImageBuilt': False,
        'boardTested': False, 'sdkArchive': args.sdk.name, 'sourceMember': MEMBER,
        'sourceSha256': hashlib.sha256(original).hexdigest(), 'sourceBytes': len(original),
        'candidateSourceSha256': hashlib.sha256(new.encode()).hexdigest(),
        'referenceUrl': REFERENCE_URL, 'referenceSha256': hashlib.sha256(reference).hexdigest(),
        'patchSha256': hashlib.sha256(patch.encode()).hexdigest(),
        'originalFps': [int(d)/int(n) for n, d in re.findall(r'\.numerator\s*=\s*(\d+),\s*\.denominator\s*=\s*(\d+)', old)],
        'candidate': {'sensorSize': [3864, 2192], 'fps': 60, 'bitDepth': 10,
            'sensorLaneMbps': 1485, 'receiverReportedMbps': 1520, 'hmax': 528,
            'vmax': 2344, 'htsReported': 4324, 'xvclkHz': 37125000,
            'enableProperty': 'dvsense,experimental-4k60'}}
    (output / 'candidate.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    cache = ROOT / '.cache/bsp'
    cache.mkdir(parents=True, exist_ok=True)
    (cache / 'imx415-candidate.c').write_text(new, encoding='utf-8', newline='\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
