# Entities

One device per door, with 34 entities. Entity IDs below use the default name
`power_pet_door`; yours follow whatever you named the device.

Several entities are **disabled by default** — they are diagnostic, or
settings almost nobody changes. Enable one from the device page.

## The door itself

> **Check the entity id first.** The ids in this page assume a device named
> "Power Pet Door" with no area. Home Assistant builds an entity's id from
> the device, and since 2026.8 it prefixes a *newly created* entity with the
> device's **area** — so a door in "Breakfast Area" gets
> `binary_sensor.breakfast_area_power_pet_door_inside_schedule`. Entities
> that existed before the 0.5.0 upgrade are migrated in place and keep their
> original ids, so a system can legitimately hold a mix of both. Copy the
> real id from **Settings → Devices & services → Power Pet Door**.

| Entity | Type | Notes |
|---|---|---|
| `cover.power_pet_door_door` | Cover | Open **and hold**, or close. Reports position (0/33/66/100) and whether it is opening or closing. |
| `sensor.power_pet_door_door_status` | Sensor (diagnostic) | The raw state machine: idle, closed, rising, slowing, holding, held open, closing, closing from top, closing from middle. Closing has three states -- `closing` is the motor starting before the flap moves. The cover collapses several of these into "open"; this does not. |

### Buttons

| Entity | What it sends |
|---|---|
| `button.power_pet_door_cycle` | Opens, waits the hold-open time, closes — exactly as if a pet had triggered a sensor. |
| `button.power_pet_door_toggle` | Opens if closed, closes if open, does nothing mid-travel. |

> **There is no Open or Close button**, on purpose. Those are exactly what
> `cover.open_cover` and `cover.close_cover` already do on
> `cover.power_pet_door_door`, and a second control for the same action is
> one more thing to keep in sync on a dashboard. Use the cover.
>
> **Open vs. Cycle.** These are different commands, not synonyms. Open the
> cover to prop the door open; use *Cycle* to let a pet through once.

## Sensors and controls

| Entity | Type | Default | Notes |
|---|---|---|---|
| `switch.power_pet_door_power` | Switch | enabled | The door's motor power. With this off the door keeps answering but will not move, so the motor-driven entities go unavailable. |
| `switch.power_pet_door_inside_sensor` | Switch (config) | enabled | Enables the sensor that lets a pet out. |
| `switch.power_pet_door_outside_sensor` | Switch (config) | enabled | Enables the sensor that lets a pet in. |
| `switch.power_pet_door_schedule_enabled` | Switch (config) | enabled | Whether the door applies its schedule at all. Off means both sensors are always live. |
| `switch.power_pet_door_outside_safety_lock` | Switch (config) | **disabled** | Blocks the outside sensor in bright sunlight, which can false-trigger it. |
| `switch.power_pet_door_auto_retract` | Switch (config) | **disabled** | Whether the door retracts when it meets an obstruction while closing. |
| `switch.power_pet_door_pet_proximity_keep_open` | Switch (config) | **disabled** | Holds the door open while a pet is still detected nearby. (On the wire this is an inverted "command lockout" flag; the library presents it the way you would describe it.) |
| `number.power_pet_door_hold_open_time` | Number (config) | enabled | How long the door stays open after a trigger. Range configurable in the integration options. |
| `number.power_pet_door_sensor_trigger_voltage` | Number (config) | **disabled** | Sensor sensitivity threshold, in volts. Changing this can stop the door detecting your pet — leave it alone unless you know why you are changing it. |
| `number.power_pet_door_sleep_sensor_trigger_voltage` | Number (config) | **disabled** | The same threshold while the door is asleep. |
| `select.power_pet_door_timezone` | Select (config) | **disabled** | The door's timezone, which is what its schedule is evaluated against. Includes a *Use Home Assistant timezone* option. See [schedules.md](schedules.md#timezones). |

## Schedules

| Entity | Type | Notes |
|---|---|---|
| `binary_sensor.power_pet_door_inside_schedule` | Binary sensor | **On** while a schedule window for the inside sensor is open. |
| `binary_sensor.power_pet_door_outside_schedule` | Binary sensor | The same for the outside sensor. |

Both carry the whole schedule in their attributes:

| Attribute | Example |
|---|---|
| `schedule` | `{"monday": [{"from": "06:00", "to": "20:00"}]}` — Home Assistant's own schedule format |
| `schedule_entries` | `["Mon, Wed, Fri: 06:00-20:00"]` — readable summary, grouped by window |
| `schedule_count` | `3` |
| `next_event` | When this sensor next turns on or off |

> With **no** schedule entries at all, the door leaves the sensor permanently
> enabled — so these report **on**, not off.

See [schedules.md](schedules.md) for editing.

## Notifications

| Entity | Default |
|---|---|
| `switch.power_pet_door_notify_inside_sensor_on` | **disabled** |
| `switch.power_pet_door_notify_inside_sensor_off` | **disabled** |
| `switch.power_pet_door_notify_outside_sensor_on` | **disabled** |
| `switch.power_pet_door_notify_outside_sensor_off` | **disabled** |
| `switch.power_pet_door_notify_low_battery` | **disabled** |

> **These control push notifications in the manufacturer's phone app.** They
> do **not** call Home Assistant's `notify` service and they do not create
> Home Assistant notifications — they toggle a setting stored on the door,
> which the vendor app then acts on. (This answers
> [issue #8](https://github.com/corporategoth/ha-powerpetdoor/issues/8).)
>
> To get a Home Assistant notification instead, write an automation
> triggered on `binary_sensor.power_pet_door_inside_schedule`,
> `sensor.power_pet_door_battery`, or `cover.power_pet_door_door`.

## Power and battery

| Entity | Type | Default | Notes |
|---|---|---|---|
| `sensor.power_pet_door_battery` | Sensor | enabled | Battery percentage. Reports *unknown* rather than 0% when no battery is fitted, so it will not fire low-battery automations on a mains-only door. |
| `binary_sensor.power_pet_door_mains_power` | Binary sensor (diagnostic) | enabled | Whether the door is on mains rather than battery. |
| `binary_sensor.power_pet_door_battery_charging` | Binary sensor (diagnostic) | **disabled** | Whether the battery is charging. |

## Diagnostics

| Entity | Default | Notes |
|---|---|---|
| `switch.power_pet_door_connection` | enabled | Whether Home Assistant holds the connection. **The door accepts one client at a time**, so turn this off to free the door for the phone app, and back on when you are done — no restart needed. Stays available while disconnected, because it is the way back. |
| `sensor.power_pet_door_latency` | enabled | Round-trip time to the door, in ms. Useful for spotting a flaky WiFi link. Safe to disable — unlike in older versions, nothing depends on it. |
| `sensor.power_pet_door_total_open_cycles` | **disabled** | Lifetime open count. |
| `sensor.power_pet_door_total_auto_retracts` | **disabled** | Lifetime count of obstruction retractions. A rising number means something keeps getting caught in the door. |
| `sensor.power_pet_door_door_clock` | **disabled** | The door's own clock. Worth checking if schedules fire at the wrong time. |
| `binary_sensor.power_pet_door_remote_paired` | **disabled** | Whether a remote is paired. |
| `binary_sensor.power_pet_door_remote_key_set` | **disabled** | Whether a remote key is set. |

Firmware and hardware versions are on the **device** page, not separate
entities.

## When entities go unavailable

| Situation | What happens |
|---|---|
| Door unreachable | Everything except `switch.…_connection` is unavailable. |
| `switch.…_connection` turned off | The same — deliberately. Turn it back on. |
| `switch.…_power` turned off | The motor-driven entities (cover, buttons, sensor switches, schedules) go unavailable. Configuration the door still remembers, the power switch, notifications and diagnostics stay available. |
| An entity disabled | **Nothing else is affected.** In versions before 0.5.0 disabling the latency sensor could take the whole integration offline; the connection now belongs to the integration itself, not to any entity ([issue #18](https://github.com/corporategoth/ha-powerpetdoor/issues/18)). |
