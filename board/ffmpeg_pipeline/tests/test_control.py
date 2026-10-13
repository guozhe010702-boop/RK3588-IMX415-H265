import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import io

spec=importlib.util.spec_from_file_location('avctl',Path(__file__).resolve().parents[1]/'avctl.py')
avctl=importlib.util.module_from_spec(spec); spec.loader.exec_module(avctl)

class ControlTests(unittest.TestCase):
    def test_configuration_rejects_unsafe_or_invalid_values(self):
        for value in [{'device':'/dev/video44; touch /tmp/x'}, {'codec':'libx265'}, {'width':1919},
                      {'fps':True},{'fps':0},{'bitrate':-1},{'gop':0},{'output':'/tmp/file'},None]:
            with self.subTest(value=value),self.assertRaises(avctl.ControlError):
                avctl.validate_config(value)
        self.assertEqual(avctl.validate_config({'codec':'h264'})['codec'],'h264')

    def test_recording_blocks_stream_reconfiguration(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory)
            controller.recorder=object()
            with self.assertRaisesRegex(avctl.ControlError,'finalize'):
                controller.start({'bitrate':4000000})
            self.assertEqual(controller.config,avctl.DEFAULTS)

    def test_busy_camera_never_launches_encoder(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory)
            with patch.object(avctl.subprocess,'run') as call,patch.object(avctl.subprocess,'Popen') as launch:
                call.return_value.stdout='1234'
                call.return_value.returncode=0
                with self.assertRaisesRegex(avctl.ControlError,'Camera busy'):
                    controller.begin_capture()
                launch.assert_not_called()

    def test_snapshot_requires_ready_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory)
            with patch.object(controller,'status',return_value={'state':'stopped'}),patch.object(avctl.subprocess,'run') as call:
                with self.assertRaises(avctl.ControlError): controller.snapshot()
                call.assert_not_called()

    def test_low_space_refuses_new_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory)
            with patch.object(controller,'status',return_value={'state':'running'}),patch.object(avctl.shutil,'disk_usage',return_value=SimpleNamespace(free=avctl.MIN_FREE-1)),patch.object(controller,'spawn_logged') as launch:
                with self.assertRaisesRegex(avctl.ControlError,'1 GiB'): controller.record_start()
                launch.assert_not_called()

    def test_low_space_monitor_finalizes_recording_and_keeps_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory)
            controller.recorder=object(); controller.capture=object(); original=controller.capture
            controller.want_capture=True
            with patch.object(avctl.time,'sleep',side_effect=lambda _:setattr(controller,'closed',True)),patch.object(controller,'active',return_value=True),patch.object(avctl.shutil,'disk_usage',return_value=SimpleNamespace(free=avctl.MIN_FREE-1)),patch.object(controller,'record_stop') as finalize,patch.object(controller,'status',return_value={'state':'running'}),patch.object(controller,'begin_capture') as restart:
                controller.monitor()
                finalize.assert_called_once()
                restart.assert_not_called()
                self.assertIs(controller.capture,original)
                self.assertTrue(controller.want_capture)

    def test_failed_reconfigure_restores_previous_config_and_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory); controller.capture=object(); controller.want_preview=True
            with patch.object(controller,'active',return_value=True),patch.object(controller,'stop_child'),patch.object(controller,'launch_ready',side_effect=[avctl.ControlError('new configuration failed'),{'state':'running'}]) as launch:
                with self.assertRaises(avctl.ControlError) as raised: controller.start({'bitrate':4000000})
                self.assertTrue(raised.exception.recovery['restored'])
                self.assertEqual(controller.config,avctl.DEFAULTS)
                self.assertTrue(controller.want_preview)
                self.assertEqual(launch.call_args_list[1].args[0],avctl.DEFAULTS)

    def test_failed_recovery_reports_stopped_state_without_hiding_error(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory); controller.capture=object()
            with patch.object(controller,'active',return_value=True),patch.object(controller,'stop_child'),patch.object(controller,'launch_ready',side_effect=avctl.ControlError('unavailable')):
                with self.assertRaises(avctl.ControlError) as raised: controller.start({'bitrate':4000000})
                self.assertFalse(raised.exception.recovery['restored'])
                self.assertIn('error',raised.exception.recovery)
                self.assertIsNone(controller.capture)

    def test_lower_output_fps_drops_frames_using_actual_sensor_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory); controller.config=dict(avctl.DEFAULTS,fps=15)
            process=SimpleNamespace(stdout=io.StringIO(''))
            with patch.object(avctl,'camera_owners',return_value=[]),patch.object(avctl,'sensor_frame_rate',return_value=30.0),patch.object(controller,'check',return_value={'encoders':['hevc_rkmpp']}),patch.object(controller,'spawn_logged',return_value=process) as launch:
                controller.begin_capture()
                arguments=launch.call_args.args[0]
                self.assertEqual(arguments[arguments.index('-framerate')+1],'30.0')
                self.assertEqual(arguments[arguments.index('-vf')+1],'setpts=N/(30.0*TB),fps=fps=15:start_time=0')

    def test_sensor_fps_limit_rejected_before_existing_stream_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            controller=avctl.Controller(directory); controller.capture=object()
            with patch.object(controller,'active',return_value=True),patch.object(avctl,'sensor_frame_rate',return_value=30),patch.object(controller,'stop_child') as stop:
                with self.assertRaisesRegex(avctl.ControlError,'actual sensor'): controller.start({'fps':60})
                stop.assert_not_called()

if __name__=='__main__': unittest.main()
