"""Exercise guards and rollback on ordinary temporary files, never devices."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('boot_guard', Path(__file__).parents[1] / 'switch_boot.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class BootSwitchTests(unittest.TestCase):
    def test_wrong_identity_is_rejected(self):
        for model, path, start, sectors in [
            ('Another board', '/dev/mmcblk0p3', 32768, 131072),
            ('Rockchip RK3588 EVM3588 B1 Board', '/dev/mmcblk0p6', 32768, 131072),
            ('Rockchip RK3588 EVM3588 B1 Board', '/dev/mmcblk0p3', 16384, 131072),
            ('Rockchip RK3588 EVM3588 B1 Board', '/dev/mmcblk0p3', 32768, 262144),
        ]:
            with self.subTest(model=model, path=path, start=start, sectors=sectors):
                with self.assertRaises(guard.SwitchError):
                    guard.validate_identity(model, path, start, sectors)

    def test_wrong_length_or_hash_is_rejected(self):
        expected = hashlib.sha256(b'abcd').hexdigest()
        for value in [b'abc', b'abce']:
            with self.assertRaises(guard.SwitchError):
                guard.verify_blob(value, expected, size=4)

    def test_short_read_is_rejected(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(b'abc'); stream.flush()
            with self.assertRaises(guard.SwitchError):
                guard.hash_fd(stream.fileno(), 4)

    def test_partial_writes_are_completed(self):
        data = b'candidate' * 1000
        with tempfile.TemporaryFile() as stream:
            def partial(fd, view):
                return os.write(fd, view[:17])
            guard.write_verified(stream.fileno(), data, lambda fd: None, partial)
            self.assertEqual(guard.hash_fd(stream.fileno(), len(data)), hashlib.sha256(data).hexdigest())

    def test_write_failure_restores_original(self):
        before, after = b'A' * 8192, b'B' * 8192
        with tempfile.TemporaryFile() as stream:
            stream.write(before); stream.flush()
            def failing(fd, view):
                os.write(fd, view[:100])
                raise OSError('injected interrupted write')
            with self.assertRaisesRegex(guard.SwitchError, 'original boot restored and verified'):
                guard.apply_transaction(stream.fileno(), before, after, lambda fd: None, failing)
            self.assertEqual(guard.hash_fd(stream.fileno(), len(before)), hashlib.sha256(before).hexdigest())

    def test_corrupt_readback_restores_original(self):
        before, after = b'A' * 8192, b'B' * 8192
        with tempfile.TemporaryFile() as stream:
            stream.write(before); stream.flush()
            def corrupting(fd, view):
                return os.write(fd, b'X' + bytes(view[1:]))
            with self.assertRaisesRegex(guard.SwitchError, 'original boot restored and verified'):
                guard.apply_transaction(stream.fileno(), before, after, lambda fd: None, corrupting)
            self.assertEqual(guard.hash_fd(stream.fileno(), len(before)), hashlib.sha256(before).hexdigest())


if __name__ == '__main__':
    unittest.main()
