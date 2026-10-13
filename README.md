# FloLogic for Home Assistant

Home Assistant integration for [FloLogic](https://flologic.com/) leak-detection
water shutoff valves, built on FloLogic's official Web API through
[`pyflologic`](https://github.com/pfeffed/pyflologic).

The Web API is new and covers less of the device than the mobile app does.
[`ha-flologic-unofficial`](https://github.com/pfeffed/ha-flologic-unofficial)
speaks the app's own protocol and reaches every setting; the two use different
domains and can run side by side.

## What you need

FloLogic issues Web API credentials on request: an **API key** and a
**company ID**, and optionally a **webhook signing secret** (Dashboard → API
Manager). One config entry covers the company, and every valve it can see
becomes a device.

## Entities, per valve

| Entity | Notes |
| --- | --- |
| `valve` | Open or closed: **whether** the water is off, for any reason |
| `select`: Mode | `home` / `away` / `bypass` / `shutoff`. Disabled can be read but not set through the Web API |
| `number`: Flow sensitivity | oz/min. The only setting the Web API can write |
| `sensor`: Shutoff reason | **Why** it is off: `Shut off manually`, `Flow ran too long`, `Leak detected by sensor`, `Freeze protection`… |
| `sensor`: Problem | What else is wrong while the valve stays open |
| `sensor`: Status, Flow state, Temperature, Last flow change | |
| `binary_sensor`: Water flow detected, Connectivity | Connectivity stays available while the valve is offline |
| `event`: Event | Only with callbacks on. FloLogic's typed events and reason codes |

The settings the Web API reports but cannot change (home and away flow limits,
bypass duration, pre-alert notice, both low-temperature thresholds, and whether
each is enabled) appear as diagnostic sensors.

**Shutoff reason** is the one to automate on: a valve reports `SHUTOFF` whether
you closed it or it closed itself, and only the reason tells a leak from a
deliberate shutoff.

### Not available through the Web API

The valve's name, signal strength, firmware, battery, temperature offset,
no-flow notice, Auto Away, Delay Away, winter mode, guest mode, the
notification history, and writing any setting other than mode and flow
sensitivity. Devices are named `FloLogic <VID>`; rename them in Home
Assistant. The VID is printed on the valve.

## Updates: polling, or callbacks

The Web API has no push channel of its own, so by default the integration
polls every 60 seconds. FloLogic documents no rate limit, so 30 seconds is the
floor.

**Callbacks** make changes arrive within seconds. FloLogic calls a URL you
register whenever a valve shuts off, changes mode, goes offline, raises a
pre-alert and so on. The integration updates the valve from the callback at
once, fires the event entity and a `flologic_event` bus event, then refreshes
to confirm. To turn them on:

1. Enter the webhook signing secret, at setup or later under **Reconfigure**.
   Unsigned callbacks are never accepted.
2. Make Home Assistant reachable: **Home Assistant Cloud** (no open port
   needed), or an external HTTPS URL under Settings → System → Network.
3. **Configure** the integration and switch on **Receive callbacks**.

Callbacks belong to the FloLogic *company*, and other consumers may have
registered their own. The integration only ever adds and removes its own URL,
and withdraws it when the entry is deleted or callbacks are switched off.

Signatures are checked against the URL that was registered, not the one the
request arrives on, so a reverse proxy or the Cloud relay does not break
verification.

## Caveats worth reading before you automate

**Short flows are invisible.** On the same backend, three real auto-shutoffs on
a 30 second limit never showed any flow before the valve tripped. **Water flow
detected** may never turn on during a real event. Build leak automations on
the valve, the shutoff reason, and the `auto_shutoff` event.

**Low-temperature thresholds include the device's temperature offset**,
according to FloLogic. The app shows the raw threshold and the offset
separately, so the numbers can differ while the offset is non-zero.

**An away flow limit of 0 means water off.** Away then allows no flow at all.
The binary sensor **Away turns water off** says so.

## Upgrading from ha-flologic 0.4.x

Before 0.5.0 this repository held the app-protocol integration under the same
`flologic` domain. That integration now lives at
[`ha-flologic-unofficial`](https://github.com/pfeffed/ha-flologic-unofficial)
with the domain `flologic_unofficial`. An old entry cannot be carried over (it
holds an email and password), so Home Assistant shows a repair issue for it.
Delete it, and add **FloLogic (Unofficial)**, **FloLogic**, or both.

## Install

1. **HACS → ⋮ → Custom repositories**, add `https://github.com/pfeffed/ha-flologic`
   with category **Integration**.
2. Install **FloLogic** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → FloLogic**.

`pyflologic` is not on PyPI, so the integration ships its own copy under
`vendor/` and declares no requirements: nothing is downloaded at setup.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run python scripts/vendor.py --check   # is the vendored library current?
```

## License

MIT
