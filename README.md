# FloLogic for Home Assistant

Home Assistant integration for [FloLogic](https://flologic.com/) leak-detection
water shutoff valves, built on [`pyflologic`](https://github.com/pfeffed/pyflologic).

Unofficial and not affiliated with FloLogic. It speaks the same cloud protocol
as the mobile app, reverse-engineered from its traffic, so a server-side change
could break it.

## One entry per account, every valve

A FloLogic account often holds several valves — and a G-Connect gateway or leak
sensors in the same device list. **One config entry covers the whole account**
and creates a device per controllable valve. Gateways, sensors and repeaters are
recognised and skipped.

## Entities, per valve

| Entity | Notes |
| --- | --- |
| `valve` | Open/close the water. Closed for *any* shutoff condition, not just a manual one |
| `select` — Mode | `home` / `away` / `bypass` / `shutoff` / `disabled` |
| `sensor` — Status | Headline state, with the decoded mode bits as attributes |
| `sensor` — Current flow | oz/min, matching the app's own unit |
| `sensor` — Temperature | |
| `sensor` — Shutoff countdown | See the caveat below |
| `binary_sensor` — Water off | On for any condition that closed the valve |
| `binary_sensor` — Warning / Critical fault | Grouped from the mode bitfield |
| `binary_sensor` — Water flowing | See the caveat below |
| `binary_sensor` — Connectivity | Stays available while the valve is offline |
| `event` — Notification | FloLogic's own log: shutoffs, mode changes, notices |

Read-only diagnostics (signal strength, elapsed flow, active flow limit) are
present but disabled by default.

### Settings you can change

| Entity | Notes |
| --- | --- |
| `number` — Home / Away flow limit | Minutes. Sub-minute values are normal: 0.5 is "30 seconds" |
| `number` — Bypass duration, Flow sensitivity, Pre-alert notice | |
| `switch` + `number` — Auto Away, Delay Away, Winter mode | A switch and its value, as in the app |
| `switch` + `number` — Low temperature alert / shutoff | Shown in your units; FloLogic stores Fahrenheit |

FloLogic disables these settings by *negating* the stored value rather than
clearing it, so switching one off keeps the value it would use when switched
back on — and changing a value does not switch anything on. That is why each
is a pair rather than a single entity.

**These are safety thresholds.** An automation that widens a flow limit or
turns off a freeze shutoff has disabled part of your leak protection, silently.
They are exposed because the app exposes them; treat them accordingly.

## Two caveats worth reading before you automate

These come from live testing, not from guesswork.

**Short flows are invisible.** FloLogic's cloud reports flow with tens of
seconds of latency. In three consecutive real auto-shutoffs on a 30-second Away
limit, `flowState` never left "no flow" — the valve shut itself off with no
observable flow beforehand. So **Water flowing** may never turn on, and
**Shutoff countdown** may stay unknown, during an actual leak event. Both are
useful for long draws and absent for brief ones. Do not build "is there a leak
right now" on them; use **Water off** and **Status**, which are driven by the
mode bitfield and are reliable.

**A closed valve does not mean dry taps.** Downstream pipes drain for tens of
seconds after the valve closes — longer on a hot line, where the water heater
sits below the valve and keeps delivering its tank. The `valve` entity reports
the valve, not the plumbing.

## Install

HACS → Custom repositories → `https://github.com/pfeffed/ha-flologic`,
category Integration. Then **Settings → Devices & services → Add integration →
FloLogic**, and sign in.

Your password is stored in Home Assistant's config entry and sent only to
FloLogic. If it stops working, the integration prompts you to re-authenticate
rather than failing silently.

## Options

**Polling interval** — a backstop only. Updates normally arrive by push within
about a second, so the default is deliberately long. Polling harder risks rate
limiting and gains nothing.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

Tests run against a mocked client; no account needed. Protocol-level work
belongs in `pyflologic`.

## License

MIT
