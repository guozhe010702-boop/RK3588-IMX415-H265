"""Resource-directory corruption must fail before creating a boot candidate."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('boot_candidate', Path(__file__).parents[1] / 'dev/prepare_boot_candidate.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


def fixture():
    blob = bytearray(5 * 512)
    blob[:12] = b'RSCE\0\0\0\0\x01\x01\x01\0'
    struct.pack_into('<I', blob, 12, 2)
    for i, (name, data) in enumerate([('b1.dtb', b'board DT'), ('logo.bmp', b'logo')]):
        offset = (i + 1) * 512
        blob[offset:offset + 4] = b'ENTR'
        blob[offset + 4:offset + 4 + len(name)] = name.encode()
        blob[offset + 224:offset + 244] = hashlib.sha1(data).digest()
        struct.pack_into('<III', blob, offset + 256, 20, 3 + i, len(data))
        blob[(3 + i) * 512:(3 + i) * 512 + len(data)] = data
    return bytes(blob)


class ResourceTests(unittest.TestCase):
    def test_replacement_preserves_other_resource_and_directory(self):
        before = fixture()
        after = candidate.replace_resource_entry(before, 'b1.dtb', b'longer patched DT')
        self.assertEqual(len(after), len(before))
        self.assertEqual(after[1024:1536], before[1024:1536])
        self.assertEqual(after[2048:], before[2048:])
        self.assertEqual(candidate.resource_entries(after)[0][3], 17)

    def test_oversize_and_unknown_target_rejected(self):
        for name, data in [('b1.dtb', bytes(513)), ('absent', b'data')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                candidate.replace_resource_entry(fixture(), name, data)

    def test_corruption_bounds_overlap_and_hash_rejected(self):
        for field, value in [(512 + 256, 7), (512 + 260, 100), (1024 + 260, 3)]:
            blob = bytearray(fixture());struct.pack_into('<I', blob, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                candidate.resource_entries(blob)
        blob = bytearray(fixture());blob[1536] ^= 1
        with self.assertRaises(ValueError):
            candidate.resource_entries(blob)


if __name__ == '__main__':
    unittest.main()
