# SPDX-License-Identifier: GPL-3.0-or-later
"""Truthful warning and observed-work state, separate from rendering."""
import math


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def effective_brightness(day, night, hour):
    if not night.get('enabled', False):
        return day
    start, end = night['start_hour'], night['end_hour']
    active = start <= hour < end if start < end else hour >= start or hour < end
    return min(day, night['brightness']) if active else day


class Attention:
    def __init__(self, settings):
        self.settings = settings
        self.hot_since = None
        self.stages = {}

    def local(self, now, temperature, battery, memory, disk):
        alerts = []
        if number(temperature) and temperature >= self.settings.get('cpu_temperature_c', 90):
            if self.hot_since is None:
                self.hot_since = now
            if now - self.hot_since >= self.settings.get('temperature_hold_seconds', 15):
                alerts.append(('temperature', f'CPU hot: {temperature:.0f} C', 2))
        else:
            self.hot_since = None
        if memory.percent >= self.settings.get('ram_percent', 90):
            alerts.append(('ram', f'RAM: {memory.percent:.0f}% used', 1))
        if disk.percent >= self.settings.get('disk_percent', 90) and disk.free / 2**30 < self.settings.get('disk_free_gb', 20):
            alerts.append(('disk', f'Disk low: {disk.free / 2**30:.0f} GB free', 2))
        if battery is not None and not battery.power_plugged and battery.percent <= self.settings.get('battery_percent', 15):
            alerts.append(('battery', f'Battery low: {battery.percent:.0f}%', 2))
        return alerts

    def remote(self, kind, data, status):
        if status != 'LIVE':
            return [('freshness', f'Telemetry {status.lower()}', 2)]
        alerts = []
        gpu = data.get('gpu')
        gpu = gpu if isinstance(gpu, dict) else {}
        vram = gpu.get('vram_pct')
        if number(vram) and vram >= self.settings.get('vram_percent', 95):
            # Allocation is useful context, not proof of inference or exhaustion.
            alerts.append(('vram', f'VRAM {vram:.0f}% allocated', 1))
        if kind == 'proxmox':
            zfs = str(data.get('zfs', 'unknown')).strip().lower()
            if zfs in ('unknown', 'probe timed out', ''):
                alerts.append(('zfs', 'ZFS health not reported', 1))
            elif zfs != 'all pools are healthy':
                alerts.append(('zfs', 'ZFS: check reported state', 2))
        return alerts

    def build_detail(self, key, data, status, now):
        if status != 'LIVE':
            self.stages.pop(key, None)
            return 'Build observation unavailable'
        stage, target = data.get('build_stage'), data.get('build_target')
        if not stage or stage in ('idle', 'unknown') or 'timed out' in str(stage).lower():
            self.stages.pop(key, None)
            return 'No active build stage reported'
        identity = (stage, target)
        previous = self.stages.get(key)
        if previous is None or previous[0] != identity:
            previous = (identity, now)
            self.stages[key] = previous
        elapsed = max(0, int(now - previous[1]))
        return f'Stage observed for {elapsed // 60}m {elapsed % 60:02d}s'


def inference_label(data):
    value = data.get('inference')
    if not isinstance(value, dict) or not number(value.get('active_requests')) or value['active_requests'] < 0:
        return 'Inference: not measured'
    return f'Inference: {value["active_requests"]:.0f} active requests'
