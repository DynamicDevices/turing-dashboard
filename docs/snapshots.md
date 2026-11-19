# Reuse an existing collector

The display is a cache consumer. It must not duplicate an existing collector's
SSH/API checks, expand its credentials or widen its monitored resources.

After the existing collector has completed, call the publisher in its existing
worker (install this package in that worker's Python environment first):

```python
from turing_dashboard.snapshot import publish_snapshot

# `data` is the parsed result from the collector you already run.
# Pass None on failure; do not turn a failed probe into a dictionary of zeros.
publish_snapshot(data, '~/.cache/esl-pve-monitor/snapshot.json',
                 source='aesl-proxmox', kind='proxmox')
```

Keep calls serialized per destination. Catch publication errors separately so
an unwritable cache cannot break the original tray UI. `source` must match the
page configuration. The `proxmox` kind accepts these optional fields:

`host`, `load`, `ncores`, `mem_pct`, `uptime`, `zfs`, `containers`, `runner`,
`ct101_mem_pct`, `yocto_pct`, `yocto_free_gb`, `build_stage`, `build_target`,
`ninja_log_bytes`, `ninja_updated`.

`containers` is a mapping of guest identifiers to reported states. `load` is a
load average, **not CPU percentage**. Build fields are optional; a DD collector
does not need to know about an AESL build container. If supplied, nonzero
`probe_rc` marks an incomplete/failed probe and does not replace the last-good
sample. Keep missing fields absent rather than generating placeholder zeros.

The `ai-tools` kind accepts CPU/RAM/disk, GPU, loaded-model and selected-container
telemetry. It deliberately excludes other-host workers and tunnels. Nested
values are copied as collector data: do not include credentials, prompts, source
text, personal details or unrestricted logs in those fields.

Optional `inference: {"active_requests": 2}` must come from an actual measured
request counter with the same observation freshness. The publisher accepts it;
the display never manufactures it from loaded-model or GPU data.

## Schema v1

```json
{
  "schema_version": 1,
  "source": "dd-proxmox",
  "attempted_at": 1800000000,
  "observed_at": 1800000000,
  "ok": true,
  "data": {"load": "0.42", "ncores": 16, "mem_pct": 35, "zfs": "all pools are healthy"}
}
```

The example is synthetic. `observed_at` is the local completed-observation time,
not the time the display read the cache. On failure, `attempted_at` advances,
`ok` becomes false, and `observed_at`/`data` retain the last-good sample. A first
failure has no data. Timestamps use Unix seconds; ages use the receiving host's
clock. Source identifiers prevent accidentally displaying another host's cache.

Writes use a same-directory temporary file and atomic replace, with file mode
0600. A new dedicated directory is created with mode 0700. The publisher rejects
a directory symlink, another owner's directory or one writable by others.
This protects local privacy; it is not authentication of a remote host or a
tamper-proof boundary against the same account/root. Protect collector keys and
host verification separately. Nothing here weakens SSH host-key checking.

For an already scheduled shell collector, the module also accepts JSON on stdin:

```sh
python -m turing_dashboard.snapshot --kind proxmox --source dd-proxmox \
  --path ~/.cache/dd-pve-monitor/snapshot.json
```

Integrate this into the existing scheduled operation; do not start a second
watcher. This package ships no remote collector, private server configuration,
credentials, deployment grants or service installer.
