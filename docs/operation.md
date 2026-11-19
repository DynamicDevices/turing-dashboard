# Controls, warnings and daily use

## Page controls

While the display is running, use another terminal in the same login session:

```sh
turing-dashboard --control next
turing-dashboard --control previous
turing-dashboard --control pin
turing-dashboard --control auto
```

Use the full path to your virtual environment's executable if it is not on PATH.
Controls arrive on a same-user mode0600 Unix datagram socket in a mode0700
runtime directory. An exclusive lock prevents two controllers claiming it.
The commands do not open USB, contact a server or capture global keyboard input.
Pin holds the current page until `auto`; next/previous preserve pin state.
Optional desktop keyboard shortcuts can invoke these exact commands. The program
does not replace existing system shortcuts or change accessibility permissions.

## Warnings

Defaults are configurable through a `warnings` object:

| Reading | Default behaviour |
| --- | --- |
| CPU temperature | 90 C sustained for 15 seconds |
| Battery | At/below 15%, while discharging |
| Disk | At least 90% used **and** less than 20 GiB free |
| RAM | 90% used, advisory |
| VRAM | 95% allocated, advisory; not evidence of inference or exhaustion |
| Source freshness | Non-LIVE telemetry is visibly flagged |
| ZFS | Display reported state; do not treat “not healthy” as healthy |

A new higher-priority warning focuses its page for the normal page interval.
It does not continuously force the same page or override a manually pinned page.
The footer distinguishes AUTO/PIN and uses amber or red for the selected warning.
This is an informational dashboard, not a guaranteed alarm or thermal controller.
Missing temperature data does not become zero. Stale data remains labelled.

AI activity is shown only when a collector provides an `inference` object with
a numeric nonnegative `active_requests` count. Otherwise it says **Inference:
not measured**. The current example AI collector reports loaded models, not that
counter; no model activity is inferred from CPU, GPU or VRAM.

An active Proxmox build stage may show “Stage observed for …”. That measures how
long this application has continuously observed the same reported stage/target,
not the true job start time or percentage complete. Idle/offline/unknown resets
that observation; no unmeasured completion estimate is invented.

## Night dimming

Example local configuration:

```json
{
  "timezone": "Europe/London",
  "night": {"enabled": true, "start_hour": 22, "end_hour": 7, "brightness": 10}
}
```

Night brightness never exceeds daytime brightness. Normal 50% device limit still
applies. Without this configuration, night dimming is disabled. The transition
is applied on the next frame; it does not change host power settings.

## Optional login startup

`examples/turing-dashboard.service` is a systemd **user** service example. Its
paths assume a venv at `~/.local/share/turing-dashboard/venv` and private config
at `~/.config/turing-dashboard/config.json`. Create/install those first, then:

```sh
mkdir -p ~/.config/systemd/user
cp examples/turing-dashboard.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now turing-dashboard.service
```

Do not run a second foreground copy. Stop the prior display owner before enabling
the service. This does not enable lingering or root access; it starts with the
user manager/login. Transient USB failures get two immediate reconnect retries;
the optional service restarts failed runs after ten seconds. Configuration and
unexpected-device errors exit with status2 and are not restart-looped.

```sh
systemctl --user status turing-dashboard.service
systemctl --user disable --now turing-dashboard.service
```

Disabling it leaves the last image on screen and does not stop the existing tray
collectors. Keep collector cadence/credentials independent. Protect local logs
and screenshots; they may contain host/workload names and readings.
