# Troubleshooting

## First: collect diagnostics

**Settings → Devices & services → Power Pet Door → ⋮ → Download diagnostics.**

This dumps everything the integration knows about the door — connection
state, firmware, every setting, the battery, statistics and the full
schedule. The host address is redacted, so it is safe to attach to a public
issue.

Attach it to any bug report. It answers most of the questions a maintainer
would otherwise have to ask.

## Enable debug logging

```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.powerpetdoor: debug
    powerpetdoor: debug
```

Both matter: `custom_components.powerpetdoor` is this integration,
`powerpetdoor` is the protocol library underneath it. A protocol problem
shows up only in the second.

## Setup fails: "Could not reach the door at that address"

The integration connects before creating the entry, so this means the door
did not answer.

1. Ping the door's IP from the machine running Home Assistant.
2. Check the port — `3000` unless you changed it.
3. Is something else already connected? **The door accepts one client at a
   time.** Close the phone app and try again.
4. Confirm it is a **WiFi** model. Bluetooth-only doors cannot work with
   this integration.

## Everything is unavailable

Check `switch.<name>_connection` first.

| It shows | Meaning |
|---|---|
| **Off** | Home Assistant is disconnected. Turn it on. If you turned it off to use the phone app, this is expected. |
| **On** | The connection is up; the problem is elsewhere — read on. |

Then check `switch.<name>_power`. With the door's motor power off, the
motor-driven entities are unavailable on purpose. The power switch itself
stays available so you can turn it back on.

> **If you are on a version before 0.5.0**: disabling the *Latency* sensor
> could take the whole integration offline, because the connection was owned
> by an entity ([issue #18](https://github.com/corporategoth/ha-powerpetdoor/issues/18)).
> Re-enable it, or upgrade — from 0.5.0 the connection belongs to the
> integration and no entity can affect it.

## The door drops out and does not come back

Symptoms: latency flatlines, entities go unavailable, and the log shows
`The server closed the connection. Reconnecting...` repeatedly.

The door is a small embedded device on WiFi and does drop connections. The
library reconnects automatically with a backoff.

If it does **not** recover:

1. Toggle `switch.<name>_connection` off and on. This is faster than
   reloading the integration and does not need a restart.
2. Check WiFi signal at the door. `sensor.<name>_latency` rising before a
   drop points at the link rather than the integration.
3. Give the door a static IP or DHCP reservation. A changed address looks
   exactly like a dead door.

> A `KeyError` traceback from `client.py` alongside these drops was
> [issue #16](https://github.com/corporategoth/ha-powerpetdoor/issues/16),
> caused by a reply arriving after its request had already timed out. Fixed
> in the library — if you still see it, you are on an old version.

## Schedules fire at the wrong time

The door applies schedules using **its own clock**, not Home Assistant's.

1. Enable `sensor.<name>_door_clock` and compare it with your local time.
2. Enable `select.<name>_timezone` and set it — or pick *Use Home Assistant
   timezone*.

See [schedules.md](schedules.md#timezones).

## Schedule edits do not stick

- Check `switch.<name>_schedule_enabled` is on. With it off the door ignores
  its schedule entirely.
- The door has a finite number of schedule slots. A very fragmented schedule
  (many short windows on many days) can fill them. Consolidating windows
  helps.
- Remember that `powerpetdoor.set_schedule` **replaces** the targeted
  sensor's schedule — days you omit are cleared.

## The card looks wrong, or does not appear

1. **Hard-refresh** the browser (Ctrl/Cmd + Shift + R). Home Assistant caches
   `/local/` aggressively, so an updated card is a commonly-missed cause.
2. Check the browser console — the card logs its version on load. If that is
   not the version you installed, it is a cache problem.
3. Confirm the dashboard resource is registered as a **JavaScript module**,
   not a stylesheet.
4. Confirm the `entity:` in the card config is one of the two
   `binary_sensor.…_schedule` entities.

## Known limitations

- **One client at a time.** Home Assistant and the vendor app cannot both be
  connected. Use `switch.<name>_connection` to hand the door over.
- **No discovery.** The door announces itself on no protocol — no mDNS, no
  SSDP, no recognisable DHCP hostname. The address has to be entered by hand.
- **No authentication.** The door's protocol has none; anything on your
  network that can reach port 3000 can control the door. This is a property
  of the device, not of this integration.
- **Battery percentage is coarse** and reported by the door itself.
- **The door's schedule is the door's.** Editing it from the vendor app or
  the door's own controls is picked up on the next refresh, not instantly.

## Reporting a bug

Include:

1. The **diagnostics download**.
2. Your Home Assistant version and this integration's version.
3. Debug logs covering the problem, with both loggers above enabled.
4. What you expected, and what happened.

Issues: <https://github.com/corporategoth/ha-powerpetdoor/issues>

If the problem is in protocol handling rather than in the entities, it may
belong in the library instead:
<https://github.com/corporategoth/py-powerpetdoor/issues>. If you are not
sure, file it here.
