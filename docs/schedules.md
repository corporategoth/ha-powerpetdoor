# Schedules

The door can enable each sensor on a weekly schedule — for example, let the
cat out from 06:00 but not overnight. The schedule lives **on the door** and
is applied by the door itself, so it keeps working if Home Assistant is
down.

`switch.<name>_schedule_enabled` is the master switch. With it off, the door
ignores its schedule and both sensors are always live.

> **Careful:** the door applies a schedule by switching the sensors
> themselves on and off, and turning the master switch back off does **not**
> put them back. If a schedule leaves a sensor disabled, that is where it
> stays until something enables it — so if your pets lose access after
> editing a schedule, check `switch.<name>_inside_sensor` and
> `switch.<name>_outside_sensor`.

## Viewing

Each sensor has a binary sensor that is **on** while a window is open:

- `binary_sensor.<name>_inside_schedule`
- `binary_sensor.<name>_outside_schedule`

Their attributes carry the whole schedule, including a readable summary
(`schedule_entries`) and when the state next changes (`next_event`). See
[entities.md](entities.md#schedules).

Use them in automations like any other binary sensor:

```yaml
automation:
  - alias: Tell me when the cat door opens for the day
    triggers:
      - trigger: state
        entity_id: binary_sensor.power_pet_door_outside_schedule
        to: "on"
    actions:
      - action: notify.mobile_app
        data:
          message: The cat door is now open.
```

## Editing with the card

The Lovelace card is the practical way to edit a schedule. Install it as
described in [installation.md](installation.md#install-the-schedule-card),
then:

- **Drag on an empty area** of a day column to create a window.
- **Drag a window's top or bottom edge** to resize it.
- **Click a window** to edit its exact times, or delete it.
- **Click a day's heading** to copy that day's windows onto other days.
- **Copy from the other sensor** using the link under the grid, when both
  schedule sensors are enabled.
- A red line shows the current time; the window covering it is highlighted.

Dragging an edge towards a neighbouring window stops at its border, and
letting go there merges the two into one. Drag clear past the neighbour and
it turns red — releasing then absorbs it. The door stores one table for both
sensors, so windows that end up touching, or that end up identical on
several days or on both sensors, are combined into a single entry before
they are written.

> **Check the entity id first.** The ids in this page assume a device named
> "Power Pet Door" with no area. Home Assistant builds an entity's id from
> the device, and since 2026.8 it prefixes a *newly created* entity with the
> device's **area** — so a door in "Breakfast Area" gets
> `binary_sensor.breakfast_area_power_pet_door_inside_schedule`. Entities
> that existed before the 0.5.0 upgrade are migrated in place and keep their
> original ids, so a system can legitimately hold a mix of both. Copy the
> real id from **Settings → Devices & services → Power Pet Door**.

```yaml
type: custom:powerpetdoor-schedule-card
entity: binary_sensor.power_pet_door_inside_schedule
# Optional, all accept any CSS colour or variable:
slot_color: var(--primary-color)
active_slot_color: var(--warning-color)
removal_color: var(--error-color)
```

The card edits one sensor at a time. Add two cards to manage both.

## Editing from an automation

The card talks to Home Assistant over a WebSocket API, which only a browser
can call. For automations there is an action that does exactly the same
thing:

```yaml
action: powerpetdoor.set_schedule
target:
  entity_id: binary_sensor.power_pet_door_inside_schedule
data:
  schedule:
    monday:
      - from: "06:00:00"
        to: "20:00:00"
    saturday:
      - from: "08:00:00"
        to: "22:00:00"
```

Notes:

- The payload is Home Assistant's own schedule format, the same shape the
  core `schedule` helper uses.
- **Days you omit are cleared.** Send the whole week you want, not a delta.
- It replaces the schedule for the **targeted** sensor only; the other
  sensor's windows are preserved untouched.
- The action and the card share one implementation, so they cannot drift
  into doing different things to the door.

A worked example — a summer and a winter schedule:

```yaml
automation:
  - alias: Winter cat hours
    triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.seasons
    conditions:
      - condition: template
        value_template: "{{ trigger.calendar_event.summary == 'Winter' }}"
    actions:
      - action: powerpetdoor.set_schedule
        target:
          entity_id: binary_sensor.power_pet_door_outside_schedule
        data:
          schedule:
            monday: [{from: "08:00:00", to: "17:00:00"}]
            tuesday: [{from: "08:00:00", to: "17:00:00"}]
            wednesday: [{from: "08:00:00", to: "17:00:00"}]
            thursday: [{from: "08:00:00", to: "17:00:00"}]
            friday: [{from: "08:00:00", to: "17:00:00"}]
            saturday: [{from: "09:00:00", to: "17:00:00"}]
            sunday: [{from: "09:00:00", to: "17:00:00"}]
```

## Editing with the vendor app

The door accepts **one client at a time**. To use the manufacturer's app,
turn `switch.<name>_connection` **off** first, and back on when you are
done. Home Assistant picks up whatever the app changed on reconnect.

## How the door stores schedules

Worth knowing, because it explains some behaviour:

- A schedule is a numbered list of **entries**. Each entry has a day mask, a
  start and end time, and a flag saying whether it gates the inside or the
  outside sensor. One entry drives one sensor.
- The door numbers days from **Sunday**; Home Assistant numbers them from
  Monday. The conversion is handled for you.
- Windows are **inclusive of the start, exclusive of the end**. The door's
  rule is exactly `start <= now < end`. This was measured against real
  firmware (1.7.18), not read off a spec, and three consequences surprise
  people:
  - **A window cannot cross midnight.** An end earlier than its start does
    *not* wrap round — not later that day, and not into the next morning.
    The door stores such an entry perfectly and then never acts on it. To
    let a pet out from 22:00 to 06:00 you need **two** windows: `22:00` to
    the end of the day, and `00:00`–`06:00` on the following day. This
    integration refuses to save a window that ends before it starts, rather
    than writing one that silently does nothing.
  - **A window whose start equals its end is empty**, not "all day". `09:00`
    to `09:00` gates the sensor off completely.
  - **`00:00` as an *end* means the end of the day.** Midnight opening a
    window is the day's first minute; midnight closing one is its last. So
    `22:00`–`00:00` is "22:00 until midnight" and works, and `00:00`–`00:00`
    is a whole day. (On the wire the door calls this `24:00`, which Home
    Assistant's `HH:MM` fields cannot type — the conversion is handled for
    you.)
  - **`23:59` is not a synonym for that.** It is the last *minute* of the
    day, so a window ending there is one minute short and the sensor is off
    for that minute. A door set up by the vendor app often ships
    `00:00`–`23:59`, which really does have a one-minute nightly gap; this
    integration reports it rather than rounding it away, and leaves the
    entry alone rather than silently rewriting your door.
- Writes are **diffed**, not cleared-and-rewritten. The door acknowledges
  each write separately, so clearing the whole table first would leave the
  sensors ungated for the length of the rewrite.
- There is a finite number of slots. Freed slots are reused before new ones
  are taken.

### Timezones

The door evaluates its schedule against **its own clock and timezone**, not
Home Assistant's. If schedules fire an hour out, check:

1. `sensor.<name>_door_clock` (disabled by default) — the door's own time.
2. `select.<name>_timezone` (disabled by default) — set it, or pick
   *Use Home Assistant timezone* to copy Home Assistant's.

The door stores a POSIX TZ string like `EST5EDT,M3.2.0,M11.1.0`, and several
IANA zones map onto the same one. The select remembers which name you chose
so it does not appear to change under you; the raw string is in the entity's
`posix_tz` attribute.

## Why not the core `schedule` helper?

Home Assistant's `schedule` helper looks like the right fit, and earlier
versions of this integration tried to reuse it — by injecting an
`async_setup_entry` into `homeassistant.components.schedule` at runtime.

That does not work without patching Home Assistant itself. `schedule` is a
helper domain built on an `EntityComponent` and a storage collection; it has
no config-entry support, so a device-backed schedule cannot be registered
into it. Monkeypatching another integration would also fail Home Assistant's
review outright, and it broke in ways that were hard to diagnose.

The entities here are therefore this integration's own. What *can* be reused
is reused by ordinary import: the day names and the `from`/`to` keys come
from `homeassistant.components.schedule`, so the format above is the format
the rest of Home Assistant already speaks.
