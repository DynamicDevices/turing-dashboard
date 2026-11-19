# SPDX-License-Identifier: GPL-3.0-or-later
# Assisted-by: Briar
"""Render README images from synthetic data only; no USB or telemetry reads.

Run with the package installed: python docs/render_previews.py
"""
import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from turing_dashboard import dashboard


class DemoClock(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 1, 14, 32, 10, tzinfo=tz)


def render():
    dashboard.configure({'laptop_name': 'FRAMEWORK', 'pages': [
        {'kind': 'laptop', 'name': 'Framework'},
        {'kind': 'ai-tools', 'name': 'AI WORKSTATION', 'snapshot': 'unused', 'source': 'demo'},
        {'kind': 'proxmox', 'name': 'PROXMOX LAB', 'snapshot': 'unused', 'source': 'demo'},
    ]})
    dashboard.CPU_HISTORY.clear()
    dashboard.CPU_HISTORY.extend([18, 24, 21, 35, 46, 32, 27, 38, 42, 31, 24])
    dashboard.NET_HISTORY.clear()
    dashboard.NET_HISTORY.extend([10000, 40000, 20000, 90000, 70000, 50000])
    counters = SimpleNamespace(bytes_recv=8 * 2**20, bytes_sent=2 * 2**20)
    previous = SimpleNamespace(bytes_recv=4 * 2**20, bytes_sent=1 * 2**20)
    with (
        patch.object(dashboard.datetime, 'datetime', DemoClock),
        patch.object(dashboard.socket, 'gethostname', return_value='demo-laptop'),
        patch.object(dashboard, 'temperature', return_value='54 C'),
        patch.object(dashboard, 'network_interface', return_value='wlan-demo'),
        patch.object(dashboard.psutil, 'virtual_memory', return_value=SimpleNamespace(
            used=12 * 2**30, total=32 * 2**30, percent=38)),
        patch.object(dashboard.psutil, 'disk_usage', return_value=SimpleNamespace(
            free=280 * 2**30, percent=44)),
        patch.object(dashboard.psutil, 'net_io_counters', return_value={'wlan-demo': counters}),
        patch.object(dashboard.psutil, 'sensors_battery', return_value=SimpleNamespace(
            power_plugged=False, percent=76, secsleft=15600)),
    ):
        laptop = dashboard.draw_frame(28, ('wlan-demo', previous), 2)[0]
    ai = {
        'cpu_pct': 32, 'mem_pct': 47,
        'gpu': {'gpu_busy_pct': 61, 'vram_used_gb': 10.2,
                'vram_total_gb': 24, 'vram_pct': 42.5},
        'ollama': {'full': 'example-model:8b'},
        'docker': [{'name': 'open-webui', 'cpu': '2.4%'},
                   {'name': 'code-server', 'cpu': '0.8%'},
                   {'name': 'node-red', 'cpu': '0.1%'}],
        'disk': {'avail_gb': 420},
    }
    proxmox = {
        'load': '2.1', 'ncores': 16, 'mem_pct': 46, 'zfs': 'tank: ONLINE',
        'containers': {'201': 'running', '202': 'running', '203': 'stopped'},
        'build_stage': 'Compiling', 'runner': 'demo-worker',
        'build_target': 'example-image', 'yocto_free_gb': 184,
    }
    images = [
        dashboard.render_page(0, laptop)[0],
        dashboard.render_page(1, laptop, (ai, 'LIVE', 12))[0],
        dashboard.render_page(2, laptop, (proxmox, 'LIVE', 8),
                              detail='Stage observed for 12m 34s')[0],
    ]
    output = Path(__file__).parent / 'images'
    output.mkdir(exist_ok=True)
    gallery = Image.new('RGB', (992, 480), '#ffffff')
    for index, (name, image) in enumerate(zip(('laptop', 'ai-workstation', 'proxmox'), images)):
        image.save(output / f'{name}.png')
        gallery.paste(image, (index * 336, 0))
    gallery.save(output / 'dashboard-pages.png')
    print('Rendered 3 synthetic 320x480 pages and README gallery; no USB/cache access.')


if __name__ == '__main__':
    render()
