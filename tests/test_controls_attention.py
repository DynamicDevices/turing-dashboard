# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from turing_dashboard import dashboard
from turing_dashboard.attention import Attention, effective_brightness, inference_label
from turing_dashboard.controls import ControlServer, PageController, send


class ControlTests(unittest.TestCase):
    def test_real_local_socket_private_and_single_instance(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, XDG_RUNTIME_DIR=folder):
            with ControlServer() as server:
                self.assertEqual(server.path.stat().st_mode & 0o777, 0o600)
                send('next')
                send('pin')
                self.assertEqual(server.commands(), ['next', 'pin'])
                self.assertEqual(server.commands(), [])
                with self.assertRaises(BlockingIOError):
                    with ControlServer():
                        pass
            self.assertFalse((Path(folder) / 'turing-dashboard' / 'control.sock').exists())

    def test_control_does_not_replace_regular_file(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, XDG_RUNTIME_DIR=folder):
            directory = Path(folder) / 'turing-dashboard'
            directory.mkdir(mode=0o700)
            path = directory / 'control.sock'
            path.write_text('keep me')
            with self.assertRaises(OSError):
                with ControlServer():
                    pass
            self.assertEqual(path.read_text(), 'keep me')

    def test_next_previous_pin_and_auto(self):
        selector = PageController(3, 10, 0)
        self.assertEqual(selector.update(10), 1)
        self.assertEqual(selector.update(11, ['previous', 'pin']), 0)
        self.assertEqual(selector.update(100), 0)
        self.assertTrue(selector.pinned)
        selector.update(101, ['auto'])
        self.assertEqual(selector.update(111), 1)

    def test_alert_focus_only_on_transition_and_pin_wins(self):
        selector = PageController(3, 10, 0)
        alert = [(2, 'freshness', 'offline', 2)]
        self.assertEqual(selector.update(1, alerts=alert), 2)
        self.assertEqual(selector.update(11, alerts=alert), 0)
        selector.update(12, ['pin'])
        self.assertEqual(selector.update(13, alerts=[(1, 'hot', 'hot', 3)]), 0)


class AttentionTests(unittest.TestCase):
    def local(self, attention, now, temp=95, battery=None, free=100, disk_pct=95):
        return attention.local(now, temp, battery, SimpleNamespace(percent=20),
                               SimpleNamespace(percent=disk_pct, free=free * 2**30))

    def test_temperature_sustained_not_transient(self):
        attention = Attention({})
        self.assertEqual(self.local(attention, 0), [])
        self.assertEqual(self.local(attention, 14), [])
        self.assertEqual(self.local(attention, 15)[0][0], 'temperature')
        self.local(attention, 16, temp=70)
        self.assertEqual(self.local(attention, 17), [])

    def test_disk_requires_low_free_space_and_battery_checks_ac(self):
        attention = Attention({})
        self.assertEqual(self.local(attention, 0, temp=70, free=100), [])
        self.assertEqual(self.local(attention, 0, temp=70, free=5)[0][0], 'disk')
        battery = SimpleNamespace(percent=10, power_plugged=True)
        self.assertEqual(self.local(attention, 1, temp=70, battery=battery), [])
        battery.power_plugged = False
        self.assertEqual(self.local(attention, 2, temp=70, battery=battery)[0][0], 'battery')

    def test_zfs_is_not_declared_healthy_from_substring(self):
        attention = Attention({})
        self.assertEqual(attention.remote('proxmox', {'zfs': 'all pools are healthy'}, 'LIVE'), [])
        self.assertEqual(attention.remote('proxmox', {'zfs': 'not healthy'}, 'LIVE')[0][3 - 1], 2)
        self.assertEqual(attention.remote('proxmox', {}, 'STALE')[0][0], 'freshness')

    def test_vram_allocation_is_advisory_not_inference(self):
        attention = Attention({})
        alert = attention.remote('ai-tools', {'gpu': {'vram_pct': 96}}, 'LIVE')[0]
        self.assertEqual(alert[2], 1)
        self.assertIn('allocated', alert[1])
        self.assertEqual(inference_label({'ollama': {'name': 'loaded'}}), 'Inference: not measured')
        self.assertEqual(inference_label({'inference': {'active_requests': 2}}), 'Inference: 2 active requests')

    def test_observed_stage_time_resets_after_idle_or_unknown(self):
        attention = Attention({})
        data = {'build_stage': 'compile', 'build_target': 'example'}
        self.assertIn('0m 00s', attention.build_detail('host', data, 'LIVE', 10))
        self.assertIn('1m 05s', attention.build_detail('host', data, 'LIVE', 75))
        attention.build_detail('host', {}, 'OFFLINE', 100)
        self.assertIn('0m 00s', attention.build_detail('host', data, 'LIVE', 110))

    def test_night_dimming_crosses_midnight_and_never_increases(self):
        night = {'enabled': True, 'start_hour': 22, 'end_hour': 7, 'brightness': 10}
        self.assertEqual(effective_brightness(50, night, 22), 10)
        self.assertEqual(effective_brightness(50, night, 6), 10)
        self.assertEqual(effective_brightness(50, night, 7), 50)
        self.assertEqual(effective_brightness(5, night, 23), 5)

    def test_invalid_night_configuration_rejected(self):
        for settings in ({'night': {'brightness': 51}}, {'night': {'start_hour': 24}},
                         {'warnings': {'cpu_temperature_c': float('nan')}}):
            with self.assertRaises(ValueError):
                dashboard.configure(settings)
        dashboard.configure({})


if __name__ == '__main__':
    unittest.main()
