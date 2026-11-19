# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from turing_dashboard import dashboard as monitor
from turing_dashboard.snapshot import publish_snapshot


class DashboardTests(unittest.TestCase):
    def setUp(self):
        monitor.configure({})
        monitor.stopping = False
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'private' / 'snapshot.json'

    def tearDown(self):
        self.folder.cleanup()
        monitor.configure({})
        monitor.stopping = False

    def publish(self, data, **kwargs):
        publish_snapshot(data, self.path, source='test-host', kind='proxmox', **kwargs)

    def read(self, **kwargs):
        return monitor.read_snapshot(self.path, source='test-host', **kwargs)

    def test_snapshot_private_and_allowlisted(self):
        self.publish({'load': '1.2', 'mem_pct': 34, 'credentials': 'never export'})
        payload = json.loads(self.path.read_text())
        self.assertEqual(payload['data'], {'load': '1.2', 'mem_pct': 34})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.read()[1], 'LIVE')

    def test_failure_retains_last_good_time(self):
        with patch('time.time', return_value=1000):
            self.publish({'load': '0.5'})
        with patch('time.time', return_value=1040):
            self.publish(None)
        self.assertEqual(self.read(now=1050), ({'load': '0.5'}, 'OFFLINE', 50))

    def test_partial_probe_is_not_fresh(self):
        self.publish({'probe_rc': 124, 'mem_pct': 0})
        self.assertEqual(self.read(), ({}, 'NO DATA', None))

    def test_stale_future_corrupt_and_missing(self):
        self.assertEqual(self.read()[1], 'UNAVAILABLE')
        with patch('time.time', return_value=1000):
            self.publish({'load': '0.5'})
        self.assertEqual(self.read(now=1091)[1], 'STALE')
        self.assertEqual(self.read(now=990)[1], 'UNAVAILABLE')
        self.path.write_text('broken')
        self.assertEqual(self.read()[1], 'UNAVAILABLE')

    def test_wrong_source_is_not_reused(self):
        self.publish({'load': '0.5'})
        self.assertEqual(monitor.read_snapshot(self.path, source='other-host')[1], 'UNAVAILABLE')
        publish_snapshot(None, self.path, source='other-host', kind='proxmox')
        self.assertIsNone(json.loads(self.path.read_text())['data'])

    def test_unsafe_directory_and_symlink_rejected(self):
        self.path.parent.mkdir(mode=0o700)
        self.path.parent.chmod(0o777)
        with self.assertRaises(OSError):
            self.publish({})
        self.path.parent.chmod(0o700)
        link = Path(self.folder.name) / 'link'
        link.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(OSError):
            publish_snapshot({}, link / 'snapshot.json', source='test-host', kind='proxmox')

    def test_runtime_support(self):
        self.assertEqual(monitor.battery_runtime(None), 'Runtime unavailable')
        battery = SimpleNamespace(power_plugged=False, percent=50, secsleft=7260)
        self.assertEqual(monitor.battery_runtime(battery), 'About 2h 01m remaining')
        battery.secsleft = -1
        self.assertEqual(monitor.battery_runtime(battery), 'Estimating remaining runtime')

    def test_all_page_kinds_render_with_missing_optional_fields(self):
        for function in (monitor.draw_ai_frame, monitor.draw_proxmox_frame):
            for status in ('LIVE', 'STALE', 'OFFLINE', 'UNAVAILABLE'):
                self.assertEqual(function({'load': '0.1'}, status, 40).size, (320, 480))
                self.assertEqual(function({}, status, None).size, (320, 480))
        self.assertEqual(monitor.draw_frame(25, None, 2)[0].size, (320, 480))

    def test_configuration_rejects_unsafe_or_invalid_values(self):
        for value in (51, float('nan'), True, -1):
            with self.assertRaises(ValueError):
                monitor.configure({'brightness': value})
        for settings in ({'pages': []}, {'refresh_seconds': 0},
                         {'reverse_portrait': 'false'}, {'pages': [{'kind': 'ssh', 'name': 'bad'}]}):
            with self.assertRaises(ValueError):
                monitor.configure(settings)

    def test_exact_port_detection(self):
        port = SimpleNamespace(vid=0x1a86, pid=0x5722,
                               serial_number='USB35INCHIPSV2', device='TEST')
        with patch.object(monitor, 'comports', return_value=[port]):
            self.assertEqual(monitor.find_port(), 'TEST')
        with patch.object(monitor, 'comports', return_value=[port, port]):
            with self.assertRaises(RuntimeError):
                monitor.find_port()

    def test_command_coordinates(self):
        self.assertEqual(monitor.command(197, ex=319, ey=479), bytes((0, 0, 4, 253, 223, 197)))

    def test_mock_serial_sends_one_correctly_oriented_frame(self):
        monitor.configure({'serial_port': 'TEST'})

        class FakeSerial:
            def __init__(self):
                self.writes = []
                self.flushes = 0
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def reset_input_buffer(self):
                pass
            def write(self, data):
                self.writes.append(bytes(data))
            def read(self, _):
                return bytes([1]) * 6
            def flush(self):
                self.flushes += 1
                if self.flushes == 3:
                    monitor.stopping = True

        fake = FakeSerial()
        with patch.object(monitor.serial, 'Serial', return_value=fake), \
             patch.object(monitor.signal, 'signal'), patch.object(monitor.time, 'sleep'):
            monitor.main()
        self.assertEqual(fake.writes[0], bytes([69]) * 6)
        self.assertEqual(fake.writes[3][5:11], bytes((121, 101, 1, 64, 1, 224)))
        self.assertEqual(fake.writes[4], monitor.command(197, ex=319, ey=479))
        self.assertEqual(sum(map(len, fake.writes[5:])), 320 * 480 * 2)


if __name__ == '__main__':
    unittest.main()
