# SPDX-License-Identifier: GPL-3.0-or-later
"""Private, atomic telemetry export for an existing collector; no remote access."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

FIELDS = {
    'ai-tools': ('cpu_pct', 'load', 'ncores', 'mem_pct', 'uptime', 'ollama',
                 'ollama_cpu', 'gpu', 'docker', 'disk', 'inference'),
    'proxmox': ('host', 'load', 'ncores', 'mem_pct', 'uptime', 'zfs', 'containers',
                'runner', 'ct101_mem_pct', 'yocto_pct', 'yocto_free_gb',
                'build_stage', 'build_target', 'ninja_log_bytes', 'ninja_updated'),
}


def publish_snapshot(data, path, *, source, kind):
    """Call once after each existing probe; None records a failed probe.

    Serialize calls for each destination in the caller. A failed or partial
    probe never refreshes the timestamp of the retained last-good sample.
    """
    if kind not in FIELDS or not isinstance(source, str) or not source:
        raise ValueError('Specify a supported kind and a source identifier')
    path = Path(path).expanduser()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = path.parent.lstat()
    if path.parent.is_symlink() or directory.st_uid != os.getuid() or directory.st_mode & 0o022:
        raise OSError('Snapshot directory must be user-owned and not writable by others')
    previous = {}
    if path.exists() and not path.is_symlink():
        try:
            previous = json.loads(path.read_text())
            if not isinstance(previous, dict) or previous.get('source') != source:
                previous = {}
        except (OSError, ValueError):
            pass
    ok = isinstance(data, dict) and data.get('probe_rc', 0) == 0
    now = time.time()
    payload = {
        'schema_version': 1, 'source': source, 'attempted_at': now,
        'ok': ok, 'observed_at': now if ok else previous.get('observed_at'),
        'data': {key: data[key] for key in FIELDS[kind] if key in data}
        if ok else previous.get('data'),
    }
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent,
                                         prefix='.snapshot-', delete=False) as handle:
            temporary = handle.name
            json.dump(payload, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--kind', required=True, choices=FIELDS)
    parser.add_argument('--path', type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = None
    publish_snapshot(data, args.path, source=args.source, kind=args.kind)


if __name__ == '__main__':
    cli()
