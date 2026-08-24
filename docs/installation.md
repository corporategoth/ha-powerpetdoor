# Installation

## Requirements

- **Home Assistant 2025.4.0 or newer.**
- A **WiFi** Power Pet Door, reachable from Home Assistant on your network.
- The door's IP address. Give it a **static IP or a DHCP reservation** — if
  the address changes, Home Assistant loses the door until you reconfigure
  it.

The door speaks a plain TCP protocol on port 3000. There is no cloud service
and no account; if Home Assistant can reach the door's address, it works.

## Install through HACS (recommended)

This integration is in the **HACS default repository**. Earlier versions had
to be added as a custom repository — that is no longer necessary, and if you
added it that way you can remove the custom repository entry.

1. Open **HACS**.
2. Search for **Power Pet Door**.
3. Click **Download**.
4. **Restart Home Assistant.**

## Manual installation

If you do not use HACS:

1. Download the latest release.
2. Copy `custom_components/powerpetdoor/` into your Home Assistant
   configuration directory, so you end up with
   `<config>/custom_components/powerpetdoor/manifest.json`.
3. Copy `www/powerpetdoor-schedule-card.js` into `<config>/www/` if you want
   the schedule card.
4. **Restart Home Assistant.**

## Add your door

1. **Settings → Devices & services → Add integration**.
2. Search for **Power Pet Door**.
3. Enter:

   | Field | Notes |
   |---|---|
   | **Name** | What the device is called in Home Assistant. |
   | **Host** | The door's IP address or hostname. |
   | **Port** | `3000` unless you have changed it. |

Home Assistant connects to the door before creating the entry, so if the
address is wrong you find out immediately rather than getting a device full
of unavailable entities.

Repeat for each door — several are supported, and they do not share state.

### Options

After setup, **Settings → Devices & services → Power Pet Door → Configure**:

| Option | Default | What it does |
|---|---|---|
| Command timeout | 10s | How long to wait for the door to answer. |
| Reconnect delay | 5s | How long to wait before reconnecting after a drop. |
| Keepalive interval | 30s | How often to ping the door. `0` disables it. |
| Refresh interval | 300s | How often to ask for full state. The door pushes changes as they happen, so this is only a safety net. |
| Hold-open min / max / step | 2 / 8 / 2s | The range offered by the hold-open time control. The door's own app offers 2–8s, but the hardware accepts much more. |

Changing any option reloads the integration.

## Install the schedule card

The card is optional — everything works without it — but it is the only way
to edit the door's schedule from Home Assistant by hand.

**Via HACS:** the card is included with the integration download and is
placed in `www/` for you.

**Manually:** copy `www/powerpetdoor-schedule-card.js` into `<config>/www/`.

Then register it once:

1. **Settings → Dashboards → ⋮ → Resources → Add resource**
2. URL: `/local/powerpetdoor-schedule-card.js`
3. Type: **JavaScript module**

Add it to a dashboard with **Add card → Custom: Power Pet Door Schedule**,
or in YAML:

```yaml
type: custom:powerpetdoor-schedule-card
entity: binary_sensor.power_pet_door_inside_schedule
```

See [schedules.md](schedules.md) for what the card can do.

> **If the card looks wrong after an update**, your browser has cached the
> old copy. Hard-refresh (Ctrl/Cmd + Shift + R). The card logs its version to
> the browser console on load, so you can check which copy you are running.

## Moving the door to a new address

Do **not** delete and re-add the integration — you would lose all history and
every automation referencing its entities.

Instead: **Settings → Devices & services → Power Pet Door → ⋮ →
Reconfigure**, and enter the new address. Entities, history and automations
are preserved.

## Removing the integration

**Settings → Devices & services → Power Pet Door → ⋮ → Delete**. This
removes the device, all its entities and its history, and disconnects from
the door.

If you installed through HACS, also remove the download from HACS, and delete
the dashboard resource for the card if you added one. Nothing is left behind
on the door itself — the integration never writes anything to it that
survives a delete.
