# SPDX-License-Identifier: GPL-3.0-or-later
# Protocol adapted from turing-smart-screen-python.
# Copyright (C) 2021 Matthieu Houdebine (mathoudebine)
# Assisted-by: Briar
"""Live laptop dashboard for the verified TURMO Rev A display.

No firmware changes or external network requests. Assisted-by: Briar.
"""
import datetime
import argparse
from collections import deque
import json
import math
from pathlib import Path
import signal
import socket
import struct
import time
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
import psutil
import serial
from serial.tools.list_ports import comports
from .attention import Attention, effective_brightness, inference_label
from .controls import COMMANDS, ControlServer, PageController, send

PORT = 'AUTO'
WIDTH, HEIGHT = 320, 480
BG, FG, MUTED, ACCENT = '#101c30', '#f1f5f9', '#94a3b8', '#5eead4'
def load_fonts(name=None):
    fonts = {}
    for size in (14, 16, 18, 22, 28):
        try:
            fonts[size] = ImageFont.truetype(name or 'DejaVuSans.ttf', size)
        except OSError:
            if name:
                raise
            fonts[size] = ImageFont.load_default(size=size)
    return fonts


FONTS = load_fonts()
SNAPSHOT = Path.home() / '.cache' / 'ai-box-monitor' / 'snapshot.json'
PAGE_SECONDS = 10
STALE_SECONDS = 90
REFRESH_SECONDS = 2
BRIGHTNESS = 50
REVERSE_PORTRAIT = True
LAPTOP_NAME = 'LAPTOP'
PAGES = [{'kind': 'laptop', 'name': 'Laptop'}]
WARNINGS = {}
NIGHT = {'enabled': False, 'start_hour': 22, 'end_hour': 7, 'brightness': 10}
TIMEZONE = None
CONTROLS = None
LAST_LOCAL = {}
CPU_HISTORY = deque(maxlen=60)
NET_HISTORY = deque(maxlen=60)
stopping = False


def stop(*_):
    global stopping
    stopping = True


def command(code, x=0, y=0, ex=0, ey=0):
    return bytes((x >> 2, ((x & 3) << 6) | (y >> 4),
                  ((y & 15) << 4) | (ex >> 6),
                  ((ex & 63) << 2) | (ey >> 8), ey & 255, code))


def temperature():
    try:
        readings = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return 'unavailable'
    for family, preferred in (('coretemp', 'Package'), ('k10temp', 'Tctl'),
                              ('cpu_thermal', '')):
        values = readings.get(family, [])
        chosen = next((v for v in values if preferred in v.label), None)
        if chosen is None and values:
            chosen = values[0]
        if chosen is not None:
            return f'{chosen.current:.0f} C'
    return 'unavailable'


def network_interface():
    routes = []
    try:
        lines = Path('/proc/net/route').read_text().splitlines()[1:]
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) >= 7 and fields[1] == '00000000' and int(fields[3], 16) & 1:
            routes.append((int(fields[6]), fields[0]))
    return min(routes)[1] if routes else None


def rate(value):
    if value >= 1024 * 1024:
        return f'{value / (1024 * 1024):.1f} MB/s'
    return f'{value / 1024:.0f} KB/s'


def battery_runtime(battery):
    if battery is None:
        return 'Runtime unavailable'
    if battery.power_plugged:
        return 'Fully charged' if battery.percent >= 99 else 'Charging / external power'
    if battery.secsleft < 0:
        return 'Estimating remaining runtime'
    hours, minutes = divmod(int(battery.secsleft) // 60, 60)
    return f'About {hours}h {minutes:02d}m remaining'


def sparkline(draw, history, box, ceiling=None):
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill='#17263d')
    if len(history) < 2:
        return
    ceiling = ceiling or max(1, max(history))
    points = [(x0 + i * (x1 - x0) / (len(history) - 1),
               y1 - min(1, max(0, value) / ceiling) * (y1 - y0))
              for i, value in enumerate(history)]
    draw.line(points, fill=ACCENT, width=2)


def read_snapshot(path=None, now=None, source='ai-tools'):
    now = time.time() if now is None else now
    try:
        snapshot = json.loads((path or SNAPSHOT).read_text())
        if snapshot.get('schema_version') != 1 or snapshot.get('source') != source:
            raise ValueError('Wrong snapshot source or schema')
        observed = snapshot.get('observed_at')
        data = snapshot.get('data')
        if not isinstance(data, dict) or isinstance(observed, bool) or not isinstance(observed, (int, float)):
            return {}, 'NO DATA', None
        if not math.isfinite(observed) or observed > now + 5:
            raise ValueError('Invalid snapshot timestamp')
        age = max(0, int(now - observed))
        status = 'OFFLINE' if snapshot.get('ok') is not True else 'STALE' if age > STALE_SECONDS else 'LIVE'
        return data, status, age
    except (OSError, ValueError, TypeError, AttributeError):
        return {}, 'UNAVAILABLE', None


def draw_ai_frame(data, status, age, name='AI-TOOLS'):
    image = Image.new('RGB', (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    def text(x, y, value, size=18, colour=FG):
        draw.text((x, y), str(value), font=FONTS[size], fill=colour)

    def fit(value, width=284, size=18):
        value = str(value).replace('\n', ' ')
        if draw.textlength(value, font=FONTS[size]) <= width:
            return value
        while value and draw.textlength(value + '...', font=FONTS[size]) > width:
            value = value[:-1]
        return value + '...'

    def percent(value):
        return f'{value:.0f}%' if isinstance(value, (int, float)) and math.isfinite(value) else '?'

    def bar(y, value):
        draw.rectangle((18, y, 302, y + 8), fill='#29374c')
        if isinstance(value, (int, float)) and math.isfinite(value):
            draw.rectangle((18, y, 18 + 284 * max(0, min(100, value)) / 100, y + 8),
                           fill=ACCENT if value < 85 else '#fbbf24')

    colour = ACCENT if status == 'LIVE' else '#fbbf24'
    text(18, 10, fit(name.upper(), width=175, size=22), 22, ACCENT)
    text(205, 15, status, 14, colour)
    age_text = f'{age}s ago' if age is not None else 'waiting for collector'
    text(18, 43, f'Last good sample: {age_text}', 14, MUTED)
    draw.line((18, 68, 302, 68), fill='#334155')
    if not data:
        text(18, 105, 'No telemetry yet', 22)
        text(18, 150, 'Using existing tray collector', 16, MUTED)
        text(18, 180, 'No extra SSH checks', 16, MUTED)
    else:
        text(18, 79, 'CPU', 16, MUTED)
        text(18, 102, percent(data.get('cpu_pct')), 28)
        text(160, 109, 'RAM ' + percent(data.get('mem_pct')), 18)
        bar(143, data.get('cpu_pct'))
        gpu = data.get('gpu') if isinstance(data.get('gpu'), dict) else {}
        text(18, 166, 'GPU ' + percent(gpu.get('gpu_busy_pct')), 22)
        used, total = gpu.get('vram_used_gb'), gpu.get('vram_total_gb')
        text(18, 198, f'VRAM {used} / {total} GB' if used is not None and total is not None else 'VRAM unavailable', 18)
        bar(226, gpu.get('vram_pct'))
        text(18, 244, 'MODEL LOADED', 14, MUTED)
        model = data.get('ollama')
        text(18, 267, fit(model.get('full', model.get('name', '?'))) if isinstance(model, dict) else 'None reported', 18)
        text(18, 294, fit(inference_label(data), size=14), 14, MUTED)
        text(18, 318, 'SERVICES / CPU', 14, MUTED)
        containers = data.get('docker')
        containers = containers if isinstance(containers, list) else []
        for index, name in enumerate(('open-webui', 'code-server', 'node-red')):
            item = next((entry for entry in containers if isinstance(entry, dict) and entry.get('name') == name), None)
            label = f'{name}: {item.get("cpu", "?")}' if item is not None else f'{name}: not reported'
            text(18, 342 + index * 24, fit(label), 16)
        disk = data.get('disk')
        disk = disk if isinstance(disk, dict) else {}
        text(18, 422, f'Disk: {disk.get("avail_gb", "?")} GB free', 18)
    text(18, 456, f'{status}  |  cached telemetry', 14, colour)
    return image


def draw_proxmox_frame(data, status, age, name='PROXMOX', detail=None):
    image = Image.new('RGB', (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    def text(y, value, size=18, colour=FG):
        value = str(value).replace('\n', ' ')
        while value and draw.textlength(value, font=FONTS[size]) > 280:
            value = value[:-1]
        draw.text((18, y), value, font=FONTS[size], fill=colour)

    text(10, name.upper(), 22, ACCENT)
    text(44, f'{status} | sample {age}s ago' if age is not None else status, 14,
         ACCENT if status == 'LIVE' else '#fbbf24')
    draw.line((18, 68, 302, 68), fill='#334155')
    if data:
        text(82, f'Load {data.get("load", "?")} / {data.get("ncores", "?")} cores', 22)
        text(120, f'RAM {data.get("mem_pct", "?")}%', 22)
        text(165, 'ZFS HEALTH', 14, MUTED)
        text(188, data.get('zfs', 'Not reported'), 16)
        text(226, 'GUESTS', 14, MUTED)
        containers = data.get('containers')
        containers = containers if isinstance(containers, dict) else {}
        guests = [f'{key}:{value}' for key, value in sorted(containers.items())]
        text(249, '  '.join(guests[:2]) or 'Not reported', 16)
        text(272, '  '.join(guests[2:4]) + (f' (+{len(guests) - 4})' if len(guests) > 4 else ''), 16)
        text(302, 'BUILD / RUNNER', 14, MUTED)
        text(326, data.get('build_stage', 'Not reported'), 18)
        text(354, f'Runner: {data.get("runner", "Not reported")}', 16)
        text(381, detail or 'Build observation unavailable', 14, MUTED)
        text(402, data.get('build_target', ''), 14, MUTED)
        free = data.get('yocto_free_gb')
        text(425, f'Build disk: {free} GB free' if free is not None else 'Build disk: not reported', 16)
    else:
        text(110, 'Waiting for existing collector', 18)
        text(150, 'No remote probes from display', 16, MUTED)
    return image


def draw_frame(cpu, previous, elapsed):
    image = Image.new('RGB', (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    def text(x, y, value, size=18, colour=FG):
        draw.text((x, y), str(value), font=FONTS[size], fill=colour)

    def bar(y, percent):
        draw.rounded_rectangle((18, y, 302, y + 8), radius=3, fill='#29374c')
        if percent > 0:
            draw.rounded_rectangle((18, y, 18 + max(6, 284 * min(percent, 100) / 100), y + 8),
                                   radius=3, fill=ACCENT if percent < 85 else '#fbbf24')

    title = LAPTOP_NAME
    while title and draw.textlength(title, font=FONTS[22]) > 175:
        title = title[:-1]
    text(18, 10, title, 22, ACCENT)
    text(200, 14, datetime.datetime.now().strftime('%H:%M:%S'), 18)
    text(18, 41, socket.gethostname()[:28], 14, MUTED)
    draw.line((18, 68, 302, 68), fill='#334155')

    text(18, 79, 'CPU', 18, MUTED)
    text(18, 102, f'{cpu:.0f}%', 28)
    temp = temperature()
    text(160, 110, temp, 18)
    CPU_HISTORY.append(cpu)
    sparkline(draw, CPU_HISTORY, (18, 140, 302, 157), ceiling=100)

    memory = psutil.virtual_memory()
    text(18, 165, 'RAM', 18, MUTED)
    text(18, 190, f'{memory.used / 2**30:.1f} / {memory.total / 2**30:.1f} GB', 22)
    text(247, 194, f'{memory.percent:.0f}%', 18)
    bar(224, memory.percent)

    disk = psutil.disk_usage('/')
    text(18, 245, f'Disk: {disk.free / 2**30:.0f} GB free ({disk.percent:.0f}%)', 18)

    interface = network_interface()
    counters = psutil.net_io_counters(pernic=True).get(interface)
    text(18, 283, f'NETWORK  {interface or "offline"}'[:29], 16, MUTED)
    if counters is not None and previous is not None and interface == previous[0] and previous[1] is not None:
        rx = max(0, counters.bytes_recv - previous[1].bytes_recv) / elapsed
        tx = max(0, counters.bytes_sent - previous[1].bytes_sent) / elapsed
        text(18, 309, f'Down {rate(rx)}', 18)
        text(18, 334, f'Up     {rate(tx)}', 18)
        NET_HISTORY.append(rx + tx)
    else:
        text(18, 309, 'Collecting...' if counters else 'No default route', 18)
        NET_HISTORY.append(0)
    sparkline(draw, NET_HISTORY, (18, 364, 302, 383))

    draw.line((18, 396, 302, 396), fill='#334155')
    battery = psutil.sensors_battery()
    if battery is None:
        battery_text = 'Battery unavailable'
    else:
        status = 'on AC' if battery.power_plugged else 'on battery'
        battery_text = f'{battery.percent:.0f}%  {status}'
    text(18, 404, battery_text, 22)
    text(18, 435, battery_runtime(battery), 14, MUTED)
    text(18, 459, f'LIVE | {REFRESH_SECONDS:g}s refresh', 14, MUTED)
    try:
        numeric_temperature = float(temp.split()[0])
    except ValueError:
        numeric_temperature = None
    LAST_LOCAL.update(temperature=numeric_temperature, battery=battery, memory=memory, disk=disk)
    return image, (interface, counters), temp


def render_page(page, laptop_image, observation=None, detail=None, alerts=(), pinned=False, dimmed=False):
    settings = PAGES[page]
    kind = settings['kind']
    if kind == 'laptop':
        image, status = laptop_image.copy(), 'LIVE'
    else:
        path = Path(settings['snapshot']).expanduser()
        data, status, age = observation if observation is not None else read_snapshot(path, source=settings['source'])
        draw_page = draw_ai_frame if kind == 'ai-tools' else draw_proxmox_frame
        image = draw_page(data, status, age, settings['name'], detail) if kind == 'proxmox' else draw_page(data, status, age, settings['name'])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 453, WIDTH, HEIGHT), fill=BG)
    mode = 'PIN' if pinned else 'AUTO'
    warning = max(alerts, key=lambda item: item[2]) if alerts else None
    footer = f'{page + 1}/{len(PAGES)} {mode} | ' + (warning[1] if warning else status + (' / DIM' if dimmed else ''))
    while footer and draw.textlength(footer, font=FONTS[14]) > 284:
        footer = footer[:-1]
    draw.text((18, 459), footer, font=FONTS[14], fill=('#fb7185' if warning[2] >= 2 else '#fbbf24') if warning else MUTED)
    return image, status


def find_port():
    if PORT != 'AUTO':
        return PORT
    matches = [port.device for port in comports()
               if port.vid == 0x1a86 and port.pid == 0x5722
               and port.serial_number in ('USB35INCHIPS', 'USB35INCHIPSV2')]
    if not matches:
        raise serial.SerialException('No matching Revision A display found')
    if len(matches) != 1:
        raise RuntimeError('Expected one matching Rev A display; set serial_port explicitly')
    return matches[0]


def main():
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with serial.Serial(find_port(), 115200, timeout=2, write_timeout=5,
                       rtscts=True, exclusive=True) as screen:
        screen.reset_input_buffer()
        screen.write(bytes([69]) * 6)
        screen.flush()
        if screen.read(6) != bytes([1]) * 6:
            raise RuntimeError('Unexpected handshake; no display commands sent')
        screen.write(command(109))
        hour = datetime.datetime.now(TIMEZONE).hour
        brightness = effective_brightness(BRIGHTNESS, NIGHT, hour)
        screen.write(command(110, x=int(255 - brightness * 255 / 100)))
        orientation = bytearray(16)
        orientation[5:11] = bytes((121, 101 if REVERSE_PORTRAIT else 100, 1, 64, 1, 224))
        screen.write(orientation)
        screen.flush()
        time.sleep(0.1)
        previous = None
        last_sample = time.monotonic()
        psutil.cpu_percent()
        first = True
        epoch = time.monotonic()
        selector = PageController(len(PAGES), PAGE_SECONDS, epoch)
        attention = Attention(WARNINGS)
        announced = set()
        while not stopping:
            started = time.monotonic()
            cpu = psutil.cpu_percent()
            image, previous, temp = draw_frame(cpu, previous, max(0.01, started - last_sample))
            last_sample = started
            current_brightness = effective_brightness(BRIGHTNESS, NIGHT, datetime.datetime.now(TIMEZONE).hour)
            if current_brightness != brightness:
                screen.write(command(110, x=int(255 - current_brightness * 255 / 100)))
                brightness = current_brightness
            observations, details, page_alerts, all_alerts = {}, {}, {}, []
            for index, settings in enumerate(PAGES):
                if settings['kind'] == 'laptop':
                    warnings = attention.local(started, **LAST_LOCAL)
                else:
                    data, state, age = read_snapshot(Path(settings['snapshot']).expanduser(), source=settings['source'])
                    observations[index] = (data, state, age)
                    warnings = attention.remote(settings['kind'], data, state)
                    if settings['kind'] == 'proxmox':
                        details[index] = attention.build_detail(settings['source'], data, state, started)
                page_alerts[index] = warnings
                all_alerts.extend((index, key, message, severity) for key, message, severity in warnings)
            commands = CONTROLS.commands() if CONTROLS is not None else ()
            page = selector.update(started, commands, all_alerts if WARNINGS.get('focus_new_alerts', True) else ())
            image, status = render_page(page, image, observations.get(page), details.get(page),
                                       page_alerts[page], selector.pinned, brightness < BRIGHTNESS)
            if commands:
                print(f'CONTROL: {commands[-1]}; page={page + 1}; pinned={selector.pinned}', flush=True)
            pixels = bytearray()
            values = image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()
            for red, green, blue in values:
                pixels.extend(struct.pack('<H', ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)))
            screen.write(command(197, ex=WIDTH - 1, ey=HEIGHT - 1))
            for offset in range(0, len(pixels), WIDTH * 8):
                screen.write(pixels[offset:offset + WIDTH * 8])
            screen.flush()
            if first:
                print(f'RUNNING: dashboard; first frame sent; CPU temperature {temp}', flush=True)
                first = False
            if page not in announced:
                print(f'PAGE SENT: {PAGES[page]["name"]} ({status})', flush=True)
                announced.add(page)
            # Workload refresh cadence, not an agent status-check loop.
            time.sleep(max(0, REFRESH_SECONDS - (time.monotonic() - started)))
        print('Stopped; last image retained on the display.', flush=True)


def configure(settings):
    global PORT, BRIGHTNESS, PAGE_SECONDS, REFRESH_SECONDS, STALE_SECONDS
    global LAPTOP_NAME, REVERSE_PORTRAIT, PAGES, FONTS
    global WARNINGS, NIGHT, TIMEZONE
    for key, default in (('brightness', 50), ('refresh_seconds', 2),
                         ('page_seconds', 10), ('stale_seconds', 90)):
        value = settings.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be a finite number')
        if value < 0 or (key != 'brightness' and value == 0):
            raise ValueError(f'{key} must be positive (brightness may be zero)')
    if settings.get('brightness', 50) > 50:
        raise ValueError('Revision A brightness must be at most 50%: upstream heat warning')
    pages = settings.get('pages', [{'kind': 'laptop', 'name': 'Laptop'}])
    if not isinstance(pages, list) or not pages:
        raise ValueError('Configure at least one page')
    for page in pages:
        if not isinstance(page, dict) or page.get('kind') not in ('laptop', 'ai-tools', 'proxmox'):
            raise ValueError('Unknown page kind')
        if not isinstance(page.get('name'), str) or not page['name']:
            raise ValueError('Each page needs a name')
        if page['kind'] != 'laptop' and any(not isinstance(page.get(key), str) or not page[key]
                                           for key in ('source', 'snapshot')):
            raise ValueError('Remote pages need snapshot and source strings')
    PORT = settings.get('serial_port', 'AUTO')
    if not isinstance(PORT, str) or not PORT:
        raise ValueError('serial_port must be AUTO or a port path')
    BRIGHTNESS = settings.get('brightness', 50)
    PAGE_SECONDS = settings.get('page_seconds', 10)
    REFRESH_SECONDS = settings.get('refresh_seconds', 2)
    STALE_SECONDS = settings.get('stale_seconds', 90)
    LAPTOP_NAME = str(settings.get('laptop_name', 'LAPTOP'))
    REVERSE_PORTRAIT = settings.get('reverse_portrait', True)
    if not isinstance(REVERSE_PORTRAIT, bool):
        raise ValueError('reverse_portrait must be true or false')
    PAGES = pages
    FONTS = load_fonts(settings.get('font'))
    WARNINGS = settings.get('warnings', {})
    if not isinstance(WARNINGS, dict):
        raise ValueError('warnings must be an object')
    for key, value in WARNINGS.items():
        if key == 'focus_new_alerts':
            if not isinstance(value, bool):
                raise ValueError('focus_new_alerts must be true or false')
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Warning thresholds must be finite nonnegative numbers')
    night = settings.get('night', {})
    if not isinstance(night, dict):
        raise ValueError('night must be an object')
    NIGHT = dict(enabled=False, start_hour=22, end_hour=7, brightness=10)
    NIGHT.update(night)
    if not isinstance(NIGHT['enabled'], bool):
        raise ValueError('night.enabled must be true or false')
    for key in ('start_hour', 'end_hour'):
        if type(NIGHT[key]) is not int or not 0 <= NIGHT[key] <= 23:
            raise ValueError('Night hours must be integers from 0 to 23')
    value = NIGHT['brightness']
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 50:
        raise ValueError('Night brightness must be between 0 and 50')
    timezone = settings.get('timezone')
    TIMEZONE = ZoneInfo(timezone) if timezone else None


def cli():
    global CONTROLS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Local JSON configuration')
    parser.add_argument('--preview-dir', type=Path, help='Render all pages without opening USB')
    parser.add_argument('--control', choices=COMMANDS, help='Control the running display without opening USB')
    args = parser.parse_args()
    if args.control:
        send(args.control)
        print(f'Sent {args.control}')
        return
    try:
        settings = json.loads(args.config.read_text()) if args.config else {}
        if not isinstance(settings, dict):
            raise ValueError('Configuration must be a JSON object')
        configure(settings)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(str(error))
    if args.preview_dir:
        args.preview_dir.mkdir(parents=True, exist_ok=True)
        laptop_image, _, _ = draw_frame(psutil.cpu_percent(interval=0.1), None, 2)
        for index in range(len(PAGES)):
            image, status = render_page(index, laptop_image)
            path = args.preview_dir / f'page-{index + 1}.png'
            image.save(path)
            print(f'{path}: {status}')
        return
    with ControlServer() as controls:
        CONTROLS = controls
        try:
            # Recover a transient dock/USB re-enumeration without changing firmware.
            for attempt in range(3):
                try:
                    main()
                    break
                except (serial.SerialException, OSError) as error:
                    if stopping or attempt == 2:
                        raise
                    print(f'USB connection lost; reconnect attempt {attempt + 1}/2: {error}', flush=True)
                    time.sleep(2)
                except RuntimeError as error:
                    parser.error(str(error))
        finally:
            CONTROLS = None


if __name__ == '__main__':
    cli()
