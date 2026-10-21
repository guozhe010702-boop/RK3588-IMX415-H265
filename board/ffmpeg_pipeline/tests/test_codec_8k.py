import importlib.util
from pathlib import Path
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

spec = importlib.util.spec_from_file_location("codec_8k", Path(__file__).with_name("codec_8k.py"))
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class Codec8kTests(unittest.TestCase):
    def test_decoding_errors_cannot_be_hidden_by_exit_zero(self):
        self.assertEqual(lab.frame_errors("frame=600\nVideo: hevc"), [])
        self.assertEqual(len(lab.frame_errors("Error while decoding frame\nPacket corrupt")), 2)

    def test_8k60_encode_is_rejected_instead_of_relabelled(self):
        with self.assertRaisesRegex(ValueError, "not supported"):
            lab.arguments("encode60", "raw", "movie", 600, 60000000)

    def test_encode30_has_true_raw_8k_input_and_no_fps_duplication(self):
        args = lab.arguments("encode30", "raw", "movie", 600, 60000000)
        self.assertEqual(args[args.index("-video_size") + 1], "7680x4320")
        self.assertEqual(args[args.index("-framerate") + 1], "30")
        self.assertEqual(args[args.index("-c:v") + 1], "hevc_rkmpp")
        self.assertNotIn("-vf", args)
        self.assertEqual(args[args.index("-fps_mode") + 1], "passthrough")

    def test_decode60_consumes_hardware_frames_without_changing_fps(self):
        args = lab.arguments("decode60", "movie", "unused", 600, 60000000)
        self.assertIn("drm_prime", args)
        self.assertNotIn("-framerate", args)
        self.assertNotIn("-vf", args)
        scale = lab.arguments("decode60", "movie", "unused", 600, 60000000, True)
        self.assertIn("scale_rkrga=", scale[scale.index("-vf") + 1])

    def test_throughput_uses_monotonic_counter_differences(self):
        self.assertIsNone(lab.throughput([]))
        self.assertIsNone(lab.throughput([{"frame": 1, "monotonic_s": 1}]))
        self.assertEqual(
            lab.throughput([{"frame": 30, "monotonic_s": 2}, {"frame": 330, "monotonic_s": 12}]), 30
        )


if __name__ == "__main__":
    unittest.main()
