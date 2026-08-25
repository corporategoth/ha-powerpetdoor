# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Randomized input to the schedule maths and the payload schema.

Two surfaces, for two different reasons:

* **What the door sends us.** The door is a cheap embedded device and has
  been observed to emit malformed frames - issue #16 (`keyerror 905`) is a
  real report of exactly that. The read path must never raise on anything a
  `Schedule` can hold, however nonsensical, because raising in a property
  takes the whole entity out rather than degrading one value.
* **What callers send in.** The WebSocket command and the `set_schedule`
  action share one schema, and it is reachable by any logged-in user. A
  payload it accepts must be one the write path can actually build.

These are properties, not examples: each says something that must hold for
EVERY input, which is what makes a fuzz test different from a test with
random data in it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import voluptuous as vol
from hypothesis import assume, example, given
from hypothesis import strategies as st
from powerpetdoor import Schedule, ScheduleTime, week_0_mon_to_sun

from custom_components.powerpetdoor.const import SCHEDULE_INSIDE, SCHEDULE_OUTSIDE
from custom_components.powerpetdoor.schedule import (
    SCHEDULE_PAYLOAD_SCHEMA,
    _entry_spans,
    _ha_end_minutes,
    _minutes,
    _parse_hhmm,
    _union,
    active_windows,
    from_ha_format,
    is_active,
    next_event,
    summarise,
    to_ha_format,
)

DAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@st.composite
def schedule_times(draw: st.DrawFn) -> ScheduleTime:
    """A time the door could report.

    Hours up to 24 and minutes up to 60 on purpose: `coerce_schedule_time`
    accepts hour 24 on the read path because other firmware is thought to
    spell end-of-day that way, so those values genuinely reach us.
    """
    return ScheduleTime(hour=draw(st.integers(0, 24)), minute=draw(st.integers(0, 60)))


@st.composite
def schedules(draw: st.DrawFn) -> Schedule:
    """One schedule entry, including shapes a sane door would not produce."""
    return Schedule(
        index=draw(st.integers(0, 255)),
        enabled=draw(st.booleans()),
        days_of_week=draw(st.lists(st.booleans(), min_size=7, max_size=7)),
        inside=draw(st.booleans()),
        outside=draw(st.booleans()),
        start=draw(schedule_times()),
        end=draw(schedule_times()),
    )


#: A factory door: all day, every seven days, both sensors. The union never
#: closes, so `next_event` must be None. Random generation reaches this shape
#: only by luck - all seven day bits AND an end-of-day spelling - so it is
#: pinned as an explicit example rather than left to chance. This is the
#: table the phantom-edge bug lived in.
ALWAYS_OPEN = [
    Schedule(
        index=0,
        enabled=True,
        days_of_week=[True] * 7,
        inside=True,
        outside=True,
        start=ScheduleTime(0, 0),
        end=ScheduleTime(23, 59),
    )
]

moments = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2040, 1, 1),
).map(lambda value: value.replace(tzinfo=UTC))


# ---------------------------------------------------------------------------
# The read path must survive anything the door can hold
# ---------------------------------------------------------------------------


@given(table=st.lists(schedules(), max_size=8), now=moments)
def test_is_active_always_answers_yes_or_no(table: list[Schedule], now: datetime) -> None:
    """Never raises, and never returns anything but a bool.

    `is_active` is read from a property on a binary sensor. An exception
    there does not degrade one attribute - Home Assistant drops the whole
    entity, so a single malformed entry from the door would take the user's
    schedule sensor off their dashboard entirely.
    """
    assert is_active(table, SCHEDULE_INSIDE, now) in (True, False)


@given(table=st.lists(schedules(), max_size=8), now=moments)
def test_next_event_is_never_in_the_past(table: list[Schedule], now: datetime) -> None:
    """An edge that has already happened is not an upcoming one.

    The schedule sensor arms a timer on this value. A time in the past makes
    Home Assistant fire it immediately and then re-arm on the same past
    time, which is a busy loop that pins a core.
    """
    upcoming = next_event(table, SCHEDULE_INSIDE, now)

    assert upcoming is None or upcoming > now


@given(table=st.lists(schedules(), max_size=8), now=moments)
@example(table=ALWAYS_OPEN, now=datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
def test_next_event_is_within_a_week(table: list[Schedule], now: datetime) -> None:
    """A weekly schedule cannot have its next change further out than a week.

    This is the property the phantom-edge fix restored: an all-day, every-day
    schedule used to report a change roughly eight days out that never came.
    A bound of exactly seven days is the strongest thing that is true here.
    """
    upcoming = next_event(table, SCHEDULE_INSIDE, now)

    assert upcoming is None or upcoming <= now + timedelta(days=7)


@given(table=st.lists(schedules(), max_size=8), now=moments)
@example(table=ALWAYS_OPEN, now=datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
def test_the_state_really_does_change_at_the_reported_edge(
    table: list[Schedule], now: datetime
) -> None:
    """`next_event` must name a moment the sensor actually flips.

    The strongest property in this file, and the one that catches a phantom
    edge: sampled a second before and a second after, `is_active` must
    disagree. An edge that reports a change which does not happen makes the
    sensor rewrite an identical state and lies in the `next_event`
    attribute that automations read.
    """
    upcoming = next_event(table, SCHEDULE_INSIDE, now)
    assume(upcoming is not None)

    before = is_active(table, SCHEDULE_INSIDE, upcoming - timedelta(seconds=1))
    after = is_active(table, SCHEDULE_INSIDE, upcoming)

    assert before != after


@given(table=st.lists(schedules(), max_size=8))
def test_every_window_is_a_forward_interval_inside_two_days(
    table: list[Schedule],
) -> None:
    """Windows are (weekday, start, end) with end after start.

    `end` may exceed 1440 - that is how a midnight-crossing window is
    represented - but it must never precede `start`, or `_occurrences` emits
    a closing edge before its opening edge and the depth count goes
    negative, which reads as "permanently off".
    """
    for weekday, start, end in active_windows(table, SCHEDULE_INSIDE):
        assert 0 <= weekday <= 6
        assert 0 <= start < 1440
        assert start < end <= 2880


@given(table=st.lists(schedules(), max_size=8))
def test_the_home_assistant_shape_is_always_renderable(table: list[Schedule]) -> None:
    """Every emitted time is a real clock time the card can parse.

    The card feeds these straight into `<input type="time">`, which silently
    renders blank for anything it cannot parse - and a blank From field with
    a live Save button is how finding F1 lost the user's first edit.
    """
    for day, slots in to_ha_format(table, SCHEDULE_INSIDE).items():
        assert day in DAY_NAMES
        for slot in slots:
            for value in (slot["from"], slot["to"]):
                hour, _, minute = value.partition(":")
                assert 0 <= int(hour) <= 23
                assert 0 <= int(minute) <= 59


@given(table=st.lists(schedules(), max_size=8))
def test_the_summary_is_always_one_line_per_distinct_window(
    table: list[Schedule],
) -> None:
    """`summarise` is a state attribute, so it must be plain strings.

    A non-string here is dropped by Home Assistant's state serialisation and
    the attribute silently disappears from templates.
    """
    lines = summarise(table, SCHEDULE_INSIDE)

    assert all(isinstance(line, str) for line in lines)
    assert len(lines) == len(
        {(start, end) for _, start, end in active_windows(table, SCHEDULE_INSIDE)}
    )


@given(table=st.lists(schedules(), max_size=8))
def test_the_two_kinds_are_read_independently(table: list[Schedule]) -> None:
    """An entry only ever appears under the kind whose flag it carries.

    One table drives both sensors, so a read that leaked between them would
    gate the inside sensor on the outside sensor's schedule - and the user
    would see a door that opens at the wrong times with a schedule that
    looks correct.
    """
    inside = active_windows(table, SCHEDULE_INSIDE)
    outside = active_windows(table, SCHEDULE_OUTSIDE)

    # An entry contributes one window per active day only if its window
    # covers time at all. Measured on firmware 1.7.18: `end <= start` is an
    # EMPTY window the door stores and never acts on, so it must contribute
    # nothing - stated here independently of `_entry_spans` rather than
    # borrowed from it, or this would assert the implementation against
    # itself.
    def covers_time(entry: Schedule) -> bool:
        # The `% 24` / `% 60` mirror the read path's clamping: this strategy
        # generates hour 24 and minute 60 on purpose, because a real door's
        # replies can carry them.
        start = (entry.start.hour % 24) * 60 + (entry.start.minute % 60)
        if (entry.end.hour, entry.end.minute) == (24, 0):
            return True  # end of day, and a clamped start is always before it
        end = (entry.end.hour % 24) * 60 + (entry.end.minute % 60)
        return end > start

    expected_inside = sum(
        sum(entry.days_of_week)
        for entry in table
        if entry.enabled and entry.inside and covers_time(entry)
    )
    expected_outside = sum(
        sum(entry.days_of_week)
        for entry in table
        if entry.enabled and entry.outside and covers_time(entry)
    )
    assert len(inside) == expected_inside
    assert len(outside) == expected_outside


# ---------------------------------------------------------------------------
# The payload schema, and what it lets through
# ---------------------------------------------------------------------------


times = st.builds(
    lambda hour, minute: f"{hour:02d}:{minute:02d}",
    st.integers(0, 23),
    st.integers(0, 59),
)

payloads = st.dictionaries(
    st.sampled_from(DAY_NAMES),
    st.lists(
        st.builds(lambda start, end: {"from": start, "to": end}, times, times),
        max_size=4,
    ),
    max_size=7,
)


@given(payload=payloads)
def test_every_payload_the_schema_accepts_can_be_written_to_the_door(
    payload: dict[str, list[dict[str, str]]],
) -> None:
    """The schema is the contract, so what it accepts must be buildable.

    A payload that validates and then raises deeper in the write path is the
    exact failure finding S1 was about: the user gets a stack trace instead
    of an error, and on the WebSocket side the card's promise never settles.
    """
    try:
        validated = SCHEDULE_PAYLOAD_SCHEMA(payload)
    except vol.Invalid:
        # The property is about what the schema ACCEPTS. A refusal is the
        # schema doing its job - the generator produces windows covering no
        # time (`end <= start`), which a real door stores and never acts on.
        return
    entries = from_ha_format(validated, SCHEDULE_INSIDE)

    # What must be preserved is the COVERAGE, not the entry count.
    # `from_ha_format` consolidates: days that share a window collapse into
    # one day-masked entry, and windows that touch or overlap on the same
    # day union into one. So counting (day, window) pairs is wrong - two
    # slots of 06:00-08:00 and 08:00-10:00 legitimately become one entry.
    #
    # Coverage is the property that actually matters: the minutes the door
    # will gate must be exactly the minutes asked for. Losing one is an edit
    # that appears to save and then partly vanishes; gaining one opens the
    # door when the user said closed.
    wanted: dict[int, list[tuple[int, int]]] = {}
    for day, slots in validated.items():
        index = DAY_NAMES.index(day)
        for slot in slots:
            start = _minutes(_parse_hhmm(slot["from"]))
            # `days_of_week` is the DOOR's convention (index 0 is Sunday);
            # DAY_NAMES is Home Assistant's (index 0 is Monday). Comparing
            # them unconverted made every single-day payload look like it
            # had moved to the wrong day.
            door_day = week_0_mon_to_sun(index)
            wanted.setdefault(door_day, []).append((start, _ha_end_minutes(slot["to"])))

    got: dict[int, list[tuple[int, int]]] = {}
    for entry in entries:
        for index, on in enumerate(entry.days_of_week):
            if on:
                got.setdefault(index, []).extend(_entry_spans(entry))

    assert {day: _union(spans) for day, spans in wanted.items()} == {
        day: _union(spans) for day, spans in got.items()
    }
    for entry in entries:
        assert entry.inside is True
        assert sum(entry.days_of_week) >= 1
        # Round-trips through the wire format the door actually receives.
        assert Schedule.from_dict(entry.to_dict()).start == entry.start


@given(payload=payloads)
def test_a_validated_payload_survives_a_round_trip_through_both_shapes(
    payload: dict[str, list[dict[str, str]]],
) -> None:
    """What the user asked for is what the schedule sensor reports back.

    Converted in, then out again, the set of windows must be identical.
    A drop here is an edit that appears to save and then partly vanishes -
    which is how "3 schedules became 1" was reported.
    """
    try:
        validated = SCHEDULE_PAYLOAD_SCHEMA(payload)
    except vol.Invalid:
        return  # refused at the edge; nothing to round-trip
    entries = from_ha_format(validated, SCHEDULE_INSIDE)
    round_tripped = from_ha_format(to_ha_format(entries, SCHEDULE_INSIDE), SCHEDULE_INSIDE)

    assert set(active_windows(round_tripped, SCHEDULE_INSIDE)) == set(
        active_windows(entries, SCHEDULE_INSIDE)
    )


@given(
    day=st.text(max_size=12).filter(lambda value: value not in DAY_NAMES),
    start=times,
    end=times,
)
def test_the_schema_rejects_any_day_name_it_does_not_know(day: str, start: str, end: str) -> None:
    """Unknown days are refused rather than dropped.

    Silently ignoring a misspelled day would look to the user like the save
    worked, and then lose that day's windows with no error anywhere.
    """
    try:
        SCHEDULE_PAYLOAD_SCHEMA({day: [{"from": start, "to": end}]})
    except vol.Invalid:
        return
    raise AssertionError(f"schema accepted the unknown day {day!r}")


@given(
    text=st.text(max_size=16).filter(
        lambda value: not __import__("re").fullmatch(r"([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?", value)
    )
)
def test_the_schema_rejects_anything_that_is_not_a_clock_time(text: str) -> None:
    """Only a 24-hour clock time gets through.

    "24:00" is the case with history: the card used to synthesise it, and it
    reached `time(24, 0)` deep in the write path and raised there instead of
    being refused at the edge (findings F1 and S1).
    """
    try:
        SCHEDULE_PAYLOAD_SCHEMA({"monday": [{"from": text, "to": "20:00"}]})
    except vol.Invalid:
        return
    raise AssertionError(f"schema accepted the non-time {text!r}")
