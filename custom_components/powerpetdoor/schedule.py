# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Schedule maths shared by the schedule entities and the WebSocket API.

Home Assistant's own `schedule` integration models exactly this, and the
first version of this integration tried to reuse it by injecting an
`async_setup_entry` into `homeassistant.components.schedule` at runtime.
That was verified against HA 2026.8.3 and is still impossible without
patching core: `schedule` is a helper domain built on `EntityComponent` plus
a storage collection, it has no `async_setup_entry`, and
`async_forward_entry_setups(entry, "schedule")` therefore cannot reach it.
Monkeypatching another integration would also fail Home Assistant review
outright.

So the *entities* are ours. The parts of HA that are reusable without the
monkeypatch are reused by ordinary import: `WEEKDAY_TO_CONF` and the
`CONF_FROM`/`CONF_TO` keys below come from `homeassistant.components.schedule`,
so the shape this integration speaks is the shape the rest of Home Assistant
already speaks.

Everything about a schedule *entry* - its wire format, validation, day-mask
handling and diffing - stays in `pypowerpetdoor`. This module only answers
two questions HA needs and the library does not: "is a window open right
now" and "when does the next edge fall".
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components.schedule import CONF_FROM, CONF_TO, WEEKDAY_TO_CONF
from powerpetdoor import (
    Schedule,
    ScheduleTime,
    compute_schedule_diff,
    week_0_mon_to_sun,
    week_0_sun_to_mon,
)

from .const import SCHEDULE_INSIDE, SCHEDULE_OUTSIDE

if TYPE_CHECKING:
    from .coordinator import PowerPetDoorCoordinator


def _ha_end_minutes(value: str) -> int:
    """Minutes for a window end written in Home Assistant's shape.

    HA times are `HH:MM` with hours 0-23, so the device's `24:00` cannot be
    written here. Two spellings therefore have to mean "the end of the day":

    * `00:00`, because midnight closing a window is the day's LAST minute -
      the rule is positional, and midnight opening one is still its first;
    * `23:59`, which is what a real door's factory schedule uses and what
      `to_ha_format` emits.

    Both go to the door as `24:00`, which is measured to be honoured.
    """
    parsed = _parse_hhmm(value)
    if (parsed.hour, parsed.minute) == (0, 0):
        return _DAY
    return _minutes(parsed)


def _ends_after_it_starts(slot: dict[str, str]) -> dict[str, str]:
    """Refuse a window whose end time precedes its start.

    The device has no way to say "tomorrow". A schedule entry on the wire is
    a day mask plus a start and an end (`docs/protocol.md`), so "Saturday
    22:00 to Sunday 06:00" is not expressible as one entry however it is
    interpreted - and what the firmware does with an inverted pair is the
    one branch of `is_sensor_allowed` with no evidence behind it.

    This check is OUR policy, not the device enforcing anything. Measured
    against a real door (firmware 1.7.18): it accepted `22:00-06:00`,
    `22:00-00:00`, `09:00-09:00` and even `00:00-24:00`, and read every one
    of them back byte for byte. The schedule table is a dumb store, so
    nothing downstream of here will catch an entry whose runtime meaning we
    cannot predict - which is precisely why the boundary is here.

    Rather than write something whose meaning we are guessing at, refuse it
    and say what to write instead. Nothing is lost: the two windows the user
    means are exactly expressible, and that spelling is unambiguous.

    `<=`, not `<`. A window whose end EQUALS its start is empty too - measured
    on firmware 1.7.18, `09:00-09:00` leaves the sensor disabled - and letting
    one through is the worst outcome of the three: the door accepts it, the
    schedule sensor reports the sensor OFF with no `next_event` to turn it
    back on, and the card reads "Active 24/7 (no schedule set)" because an
    empty window set is indistinguishable from no schedule. The pet is locked
    out indefinitely while every surface says otherwise.

    Only the WRITE path is strict. `_entry_spans` still reads such an entry
    the way the door acts on it, because a door that already has one (set
    from the phone app) must still be shown accurately.
    """
    if _ha_end_minutes(slot[CONF_TO]) <= _minutes(_parse_hhmm(slot[CONF_FROM])):
        raise vol.Invalid(
            f"window {slot[CONF_FROM]}-{slot[CONF_TO]} does not cover any time; "
            f"the door cannot schedule past midnight in one window - use "
            f"{slot[CONF_FROM]}-00:00 to run to the end of the day, and a second "
            f"window starting 00:00 on the next day"
        )
    return slot


#: One time slot as the card and the `set_schedule` action send it.
#:
#: The hour is bounded to 0-23, so 24:00 - which the card used to synthesise
#: - is refused here rather than reaching `time(24, 0)` deep in the write
#: path. 23:59 is the device's own end-of-day and the largest end it takes.
_SLOT_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(CONF_FROM): vol.Match(r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$"),
            vol.Required(CONF_TO): vol.Match(r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$"),
        }
    ),
    _ends_after_it_starts,
)

#: `{"monday": [{"from": "06:00", "to": "22:00"}], ...}`.
#:
#: Lives here rather than in websocket.py because BOTH entry points must use
#: it. They did not: the WebSocket command validated and the `set_schedule`
#: action took a bare `dict`, so payloads the card could never produce -
#: a slot missing "to", a mapping where a list belongs, an integer in place
#: of a slot - escaped an automation as a raw KeyError or TypeError instead
#: of a translated error.
#:
#: Unknown day names are rejected rather than ignored: silently dropping a
#: misspelled day would look to the user like the save worked and then lose
#: their edit.
SCHEDULE_PAYLOAD_SCHEMA = vol.Schema(
    {
        vol.In(
            (
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            )
        ): [_SLOT_SCHEMA]
    }
)

#: Minutes in a day.
_DAY = 24 * 60

#: The device's own end-of-day, and the only end that exceeds the last minute
#: of the day. **Measured against firmware 1.7.18**: a window of `20:00-24:00`
#: reports the sensor enabled at 21:07, so hour 24 is honoured, not merely
#: tolerated.
_HOUR_24 = (24, 0)

#: End-of-day as Home Assistant's schedule shape spells it.
#:
#: HA times are `HH:MM` with hours 0-23, so the device's `24:00` cannot be
#: written here and midnight stands in for it. That is not a fudge - it is
#: the same positional rule the device forces everywhere else: midnight
#: opening a window is the day's FIRST minute, midnight closing one is its
#: LAST. `from_ha_format` sends it to the door as `24:00`.
#:
#: `23:59` is deliberately NOT special. An earlier version treated it as
#: end-of-day, reasoning that the factory schedule is `00:00-23:59` and
#: plainly means "always". That was always an inference, and an unnecessary
#: one now that the device is measured to accept and preserve `24:00`: it
#: stores what you write and hands back `00:00-24:00` unchanged. So `23:59`
#: is just a time, the engine's `start <= now < end` is taken literally, and
#: a door whose factory entry really does end at `23:59` is reported as
#: closed for that final minute - which is what such a door actually does.
_MIDNIGHT_HHMM = "00:00"


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _entry_applies(entry: Schedule, kind: str) -> bool:
    """Whether this entry gates the inside or the outside sensor."""
    return entry.inside if kind == SCHEDULE_INSIDE else entry.outside


def _entry_spans(entry: Schedule) -> list[tuple[int, int]]:
    """Return the entry's window as [start, end) minutes, or nothing at all.

    At most ONE span, because a window cannot cross midnight. This is
    measured behaviour, not a reading of the protocol document: the schedule
    engine writes its verdict through to the sensor enable flags, so a real
    door reports its own answer, and firmware 1.7.18 answers

        active  iff  start <= now < end        (24:00 is a legal end = 1440)

    with no wrapping of any kind. An entry of `23:00-21:30` leaves the sensor
    disabled BOTH on the day it names and on the day after, so it is neither
    a same-day wrap nor a spill into tomorrow. It is nothing.

    Two earlier readings of this function were therefore wrong, and both
    made Home Assistant report a sensor as open while the door had it shut:

    * an inverted window used to produce two spans on the same day;
    * `start == end` used to mean the whole day. Measured, `16:01-16:01` and
      `21:01-21:01` both leave the sensor DISABLED. A whole day is
      `00:00-24:00`.

    Only `24:00` is end-of-day. `23:59` is an ordinary time, so an entry
    ending there really does leave the sensor off for that final minute -
    see `_MIDNIGHT_HHMM`.
    """
    start = _minutes(time(entry.start.hour % 24, entry.start.minute % 60))
    if (entry.end.hour, entry.end.minute) == _HOUR_24:
        return [(start, _DAY)] if start < _DAY else []
    end = _minutes(time(entry.end.hour % 24, entry.end.minute % 60))
    if end <= start:
        # Stored by the door and never acted on. Reporting it as a window -
        # of any length, on any day - claims the pet can get through when it
        # cannot.
        return []
    return [(start, end)]


def active_windows(schedules: list[Schedule], kind: str) -> list[tuple[int, int, int]]:
    """Return enabled windows for `kind` as (python_weekday, start_min, end_min).

    `python_weekday` is Monday=0, matching `datetime.weekday()`. The door
    numbers its days from Sunday, so every crossing goes through the
    library's `week_0_sun_to_mon` rather than an inline `(d + 6) % 7` - the
    off-by-one here is invisible in testing until a Sunday.
    """
    windows: list[tuple[int, int, int]] = []
    for entry in schedules:
        if not entry.enabled or not _entry_applies(entry, kind):
            continue
        for start, end in _entry_spans(entry):
            for door_day, on in enumerate(entry.days_of_week):
                if on:
                    windows.append((week_0_sun_to_mon(door_day), start, end))
    return windows


def _occurrences(windows: list[tuple[int, int, int]], now: datetime) -> list[tuple[datetime, int]]:
    """Every window edge around `now`, as (when, +1 opening / -1 closing).

    Signed rather than boolean because the door ORs its entries together -
    `simulator/state.py` returns True if *any* schedule allows the sensor -
    so overlapping windows have to be counted, not toggled. With a boolean
    "last edge wins" the earlier-closing of two overlapping windows turned
    the sensor off while the door still had it on.

    A window whose end exceeds 1440 is emitted relative to its own day and
    allowed to spill forward, which is what makes midnight-crossing windows
    sort correctly: the close edge lands after the open edge instead of
    before it.
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    edges: list[tuple[datetime, int]] = []
    # Yesterday through a week ahead: yesterday matters because a window that
    # crosses midnight is still open this morning.
    for offset in range(-1, 8):
        day = midnight + timedelta(days=offset)
        for weekday, start, end in windows:
            if day.weekday() != weekday:
                continue
            edges.append((day + timedelta(minutes=start), 1))
            edges.append((day + timedelta(minutes=end), -1))
    # Sorted by time, and by delta so that a window closing exactly as
    # another opens never dips to zero: +1 sorts before -1 at equal times.
    return sorted(edges, key=lambda edge: (edge[0], -edge[1]))


def _depth_at(windows: list[tuple[int, int, int]], now: datetime) -> int:
    """How many windows cover `now`.

    Summed rather than accumulated up to an early `break`: `_occurrences`
    spans nine days around `now`, so with any window at all there is always
    an edge still in the future and the loop could never run to completion.
    That made the loop-exhausted path unreachable - a branch no test could
    honestly cover.
    """
    return sum(delta for when, delta in _occurrences(windows, now) if when <= now)


def is_active(schedules: list[Schedule], kind: str, now: datetime) -> bool:
    """Whether a window for `kind` is open at `now`.

    The door's "no schedule means always enabled" default is a property of
    the WHOLE table, not of one sensor: `state.py` returns True early only
    `if not self.schedules`. So a table that holds outside windows but no
    inside ones leaves the INSIDE sensor blocked, not open.

    Keying that default off "no windows for this kind" - as this did - meant
    that clearing just the inside schedule made Home Assistant report the
    inside sensor wide open while the door was refusing the pet entry.

    `schedules`, not the enabled subset. The door asks whether the TABLE is
    empty; a table holding only disabled rows is not empty, so it falls
    through to the per-window check, finds nothing that permits the sensor,
    and blocks. Filtering first turned "every window switched off" - which
    is how a user pauses a schedule without deleting it - into "no schedule
    at all", i.e. wide open.
    """
    if not schedules:
        return True
    return _depth_at(active_windows(schedules, kind), now) > 0


def next_event(schedules: list[Schedule], kind: str, now: datetime) -> datetime | None:
    """When the state of `kind` next changes, or None if it never does."""
    windows = active_windows(schedules, kind)
    if not windows:
        # Either the table is empty (permanently on) or this kind has no
        # windows (permanently off). Either way the state never changes.
        return None

    depth = _depth_at(windows, now)
    active = depth > 0
    # A schedule repeats weekly, so a change that has not happened within a
    # week never will. Edges beyond that horizon are skipped rather than
    # searched: `_occurrences` stops emitting days at some point, and the
    # final day's closing edge therefore has no opening edge after it to
    # keep the union up. On a factory door - all day, every day, which never
    # changes at all - that phantom edge was reported as the next event, so
    # the schedule sensor published a change roughly a week out that arrived
    # to find its own state identical.
    horizon = now + timedelta(days=7)
    for when, delta in _occurrences(windows, now):
        if when <= now or when > horizon:
            continue
        depth += delta
        # Report the moment the *union* flips, not every individual edge: a
        # window opening inside another window changes nothing the user can
        # see, and waking for it would make the sensor rewrite an identical
        # state.
        if (depth > 0) != active:
            return when
    return None


def to_ha_format(schedules: list[Schedule], kind: str) -> dict[str, list[dict[str, str]]]:
    """Windows for `kind` in Home Assistant's schedule shape.

    `{"monday": [{"from": "06:00", "to": "22:00"}], ...}` - the same shape
    HA's own schedule helper and its frontend use, so the Lovelace card in
    www/ does not have to learn a bespoke one. Days with no window are
    omitted rather than emitted empty, matching HA.
    """
    result: dict[str, list[dict[str, str]]] = {}
    for weekday, start, end in sorted(active_windows(schedules, kind)):
        day = WEEKDAY_TO_CONF[weekday]
        result.setdefault(day, []).append(
            {
                CONF_FROM: f"{start // 60:02d}:{start % 60:02d}",
                # 1440 is the end of the day, which Home Assistant's HH:MM
                # shape cannot write as 24:00. Midnight stands in for it, and
                # `from_ha_format` turns it back into the 24:00 the device
                # actually honours. The rule is positional, so this is not
                # ambiguous with a 00:00 START.
                CONF_TO: _MIDNIGHT_HHMM if end >= _DAY else f"{end // 60:02d}:{end % 60:02d}",
            }
        )
    return result


def _union(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping and abutting spans. `[start, end)` throughout."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        # `<=`, not `<`: 06:00-08:00 followed by 08:00-10:00 touch without
        # overlapping, and the door covers the same minutes with one entry.
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _consolidate(entries: list[Schedule]) -> list[Schedule]:
    """Express the same coverage in as few door entries as possible.

    The door holds a finite number of slots on a single-connection,
    rate-limited link, so an entry that says nothing new is a real cost. A
    table is equivalent to any other that covers the same minutes, so this
    reduces to: work out what is covered, then say it the short way.

    Three things collapse, and they have to happen together because each
    creates opportunities for the others:

    * **Windows that touch or overlap, on the same days and sensors.**
      06:00-08:00 and 08:00-10:00 become 06:00-10:00.
    * **The same window on several days.** One entry with a day mask.
    * **The same window on both sensors.** One entry with `inside` and
      `outside` both set, rather than two.

    The pre-rewrite code got this from the library's `compress_schedule`,
    which is not usable here: it contains
    `if in_end < in_start: in_start, in_end = in_end, in_start`, turning an
    inverted window into its complement - 22:00-06:00 would become
    06:00-22:00, the precise inverse of what was asked for.

    Two classes of entry are passed through untouched rather than folded in,
    because neither can be expressed as coverage: disabled entries (they
    cover nothing now but the user may re-enable them) and entries whose
    window is empty (`end <= start`, which the door stores and never acts
    on). Rewriting either would be this function deciding something the user
    did not ask it to decide.
    """
    passthrough: list[Schedule] = []
    #: (day index, "inside"/"outside") -> covered spans
    coverage: dict[tuple[int, str], list[tuple[int, int]]] = {}

    for entry in entries:
        spans = _entry_spans(entry)
        if not entry.enabled or not spans:
            passthrough.append(entry)
            continue
        for day, on in enumerate(entry.days_of_week):
            if not on:
                continue
            for sensor in (SCHEDULE_INSIDE, SCHEDULE_OUTSIDE):
                if getattr(entry, sensor):
                    coverage.setdefault((day, sensor), []).extend(spans)

    #: (start, end) -> day -> the sensors covered for that day
    by_span: dict[tuple[int, int], dict[int, set[str]]] = {}
    for (day, sensor), spans in coverage.items():
        for span in _union(spans):
            by_span.setdefault(span, {}).setdefault(day, set()).add(sensor)

    rebuilt: list[Schedule] = []
    for (start, end), days in sorted(by_span.items()):
        # Days whose sensor set matches share an entry; at most three per
        # window (inside only, outside only, both), usually one.
        grouped: dict[frozenset[str], list[int]] = {}
        for day, sensors in days.items():
            grouped.setdefault(frozenset(sensors), []).append(day)
        for sensor_set, members in sorted(grouped.items(), key=lambda kv: sorted(kv[0])):
            mask = [False] * 7
            for day in members:
                mask[day] = True
            rebuilt.append(
                Schedule(
                    enabled=True,
                    days_of_week=mask,
                    inside=SCHEDULE_INSIDE in sensor_set,
                    outside=SCHEDULE_OUTSIDE in sensor_set,
                    start=ScheduleTime(start // 60, start % 60),
                    end=ScheduleTime(end // 60, end % 60),
                )
            )
    return [*rebuilt, *passthrough]


def from_ha_format(config: dict[str, list[dict[str, str]]], kind: str) -> list[Schedule]:
    """Turn Home Assistant's schedule shape back into door schedule entries.

    Indices are left at 0: assigning them requires knowing which slots the
    door currently has free, which is the caller's business (and is what
    `pypowerpetdoor.compute_schedule_diff` exists for).
    """
    by_conf = {conf: weekday for weekday, conf in WEEKDAY_TO_CONF.items()}
    entries: list[Schedule] = []
    for day, slots in config.items():
        weekday = by_conf.get(day)
        if weekday is None:
            continue
        for slot in slots:
            start = _parse_hhmm(slot[CONF_FROM])
            # The door's end-of-day is 24:00, which HA's shape cannot write,
            # so both spellings that mean it here are sent as 24:00. That is
            # measured to be honoured, where an end of 00:00 is stored and
            # never fires.
            end_minutes = _ha_end_minutes(slot[CONF_TO])
            days = [False] * 7
            days[week_0_mon_to_sun(weekday)] = True
            entries.append(
                Schedule(
                    enabled=True,
                    days_of_week=days,
                    inside=kind == SCHEDULE_INSIDE,
                    outside=kind != SCHEDULE_INSIDE,
                    start=ScheduleTime(start.hour, start.minute),
                    end=ScheduleTime(end_minutes // 60, end_minutes % 60),
                )
            )
    return _consolidate(entries)


def _parse_hhmm(value: str | time) -> time:
    """Accept "06:00", "06:00:00" or an already-parsed time."""
    if isinstance(value, time):
        return value
    hour, _, rest = value.partition(":")
    minute = rest.partition(":")[0]
    return time(int(hour), int(minute))


#: Abbreviations for the summary line. Deliberately not localised: they are
#: joined into a single free-text attribute rather than being an entity
#: state, and Home Assistant has no mechanism for translating attribute
#: *values*. Anything user-facing that CAN be translated is.
_SHORT_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def summarise(schedules: list[Schedule], kind: str) -> list[str]:
    """Human-readable lines like "Mon, Wed, Fri: 06:00-20:00".

    Requested in PR #19: the structured `schedule` attribute is what the
    card consumes, but it is unreadable in the "attributes" panel and in a
    template. Windows are grouped by time so a schedule covering five days
    reads as one line rather than five.
    """
    by_window: dict[tuple[int, int], list[int]] = {}
    for weekday, start, end in active_windows(schedules, kind):
        by_window.setdefault((start, end), []).append(weekday)

    lines = []
    for (start, end), weekdays in sorted(by_window.items()):
        days = ", ".join(_SHORT_DAYS[day] for day in sorted(set(weekdays)))
        lines.append(
            f"{days}: {start // 60:02d}:{start % 60:02d}-{(end // 60) % 24:02d}:{end % 60:02d}"
        )
    return lines


async def apply_schedule(
    coordinator: PowerPetDoorCoordinator,
    kind: str,
    config: dict[str, list[dict[str, str]]],
) -> None:
    """Make the door's schedule for `kind` match `config`.

    The single write path, shared by the WebSocket command the Lovelace card
    calls and the `powerpetdoor.set_schedule` action an automation calls. If
    these were two implementations they would drift, and the UI and an
    automation would do different things to the same door.

    Two behaviours worth stating:

    * The door holds ONE table covering both sensors, so writing the inside
      schedule must preserve outside coverage untouched - while still
      clearing this kind's flag from entries that gate both.
    * It is diffed rather than cleared and rewritten. The door stores
      schedules in numbered slots and acknowledges each write separately, so
      a delete-everything-then-add leaves the sensors ungated for the length
      of the rewrite - a window where the door is open when the user's
      schedule says it should not be.
    """
    # Held across the whole read-modify-write. Two of these interleaving
    # both rebuild the other kind from the same pre-edit table, and the last
    # writer resurrects the other's old windows - one edit vanishes with no
    # error anywhere. See `PowerPetDoorCoordinator.schedule_lock`.
    async with coordinator.schedule_lock:
        await _apply_schedule_locked(coordinator, kind, config)


async def _apply_schedule_locked(
    coordinator: PowerPetDoorCoordinator,
    kind: str,
    config: dict[str, list[dict[str, str]]],
) -> None:
    """Run the body of `apply_schedule`, with the lock already held."""
    # Read the door's CURRENT table first. `coordinator.schedules` is a
    # cache and may predate an edit made from the phone app or the door's
    # own controls; building the desired table from stale entries would
    # resurrect windows the user already removed elsewhere.
    current = await coordinator.door.refresh_schedules()

    # The door holds ONE table covering both sensors, so writing the inside
    # schedule must preserve outside coverage untouched. An entry can gate
    # BOTH - the factory default is exactly that, `inside:1 outside:1`
    # 00:00-23:59 every day - so entries cannot simply be kept whole:
    # keeping that one verbatim would leave the inside sensor enabled all
    # day no matter what the user just asked for, which is a first-use
    # failure of the headline feature. Clear this kind's flag instead and
    # keep whatever the other kind still needs.
    other = SCHEDULE_OUTSIDE if kind == SCHEDULE_INSIDE else SCHEDULE_INSIDE
    keep = []
    for entry in current:
        if not _entry_applies(entry, other):
            continue
        if kind == SCHEDULE_INSIDE:
            keep.append(replace(entry, inside=False))
        else:
            keep.append(replace(entry, outside=False))

    # Consolidated across BOTH sensors, which `from_ha_format` cannot do on
    # its own - it is called for one kind at a time, so an inside window and
    # an identical outside window only meet here. This is also where windows
    # that touch get folded together.
    desired = _consolidate([*keep, *from_ha_format(config, kind)])

    to_delete, to_add = compute_schedule_diff(
        [entry.to_dict() for entry in current],
        [entry.to_dict() for entry in desired],
    )

    for index in to_delete:
        await coordinator.door.delete_schedule(index)

    # The indices come from `compute_schedule_diff`, which documents that
    # `entries_to_set` are copies "with their index field reassigned" and
    # already reuses freed slots first. Recomputing them here - as this did
    # - handed out an index the library had reserved, so an edited window
    # was written to a NEW slot while the old one survived: the door ended
    # up gating the union of both, and with several edits two entries could
    # collide on one index and silently lose a window.
    for payload in to_add:
        await coordinator.door.set_schedule(Schedule.from_dict(payload))

    await coordinator.door.refresh_schedules()
    coordinator.async_update_listeners()
