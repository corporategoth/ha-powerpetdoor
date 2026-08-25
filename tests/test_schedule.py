# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Schedule maths, and the single write path both entry points share.

Every window here is spelled with a literal `days_of_week` list rather than
built through `week_0_mon_to_sun`. The production code reads it back through
`week_0_sun_to_mon`, so a test that built the mask with the inverse helper
would cancel out a mapping bug and pass either way - and the off-by-one in
this mapping is invisible until a Sunday.

`days_of_week` is indexed from SUNDAY: [Sun, Mon, Tue, Wed, Thu, Fri, Sat].
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from powerpetdoor import Schedule, ScheduleTime
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.powerpetdoor.const import SCHEDULE_INSIDE, SCHEDULE_OUTSIDE
from custom_components.powerpetdoor.schedule import (
    SCHEDULE_PAYLOAD_SCHEMA,
    _consolidate,
    _entry_spans,
    _union,
    active_windows,
    apply_schedule,
    from_ha_format,
    is_active,
    next_event,
    summarise,
    to_ha_format,
)

# [Sun, Mon, Tue, Wed, Thu, Fri, Sat]
SUNDAY_ONLY = [True, False, False, False, False, False, False]
MONDAY_ONLY = [False, True, False, False, False, False, False]
TUESDAY_ONLY = [False, False, True, False, False, False, False]
SATURDAY_ONLY = [False, False, False, False, False, False, True]
WEEKDAYS = [False, True, True, True, True, True, False]
EVERY_DAY = [True] * 7

# 2026-08-24 is a Monday; 2026-08-23 the Sunday before it.
MONDAY = datetime(2026, 8, 24, tzinfo=UTC)
SUNDAY = datetime(2026, 8, 23, tzinfo=UTC)
TUESDAY = datetime(2026, 8, 25, tzinfo=UTC)


def _days(index: int) -> list[bool]:
    """A day mask with one day set, in the door's convention (0 is Sunday)."""
    mask = [False] * 7
    mask[index] = True
    return mask


def sched(
    days: list[bool],
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    index: int = 0,
    inside: bool = True,
    outside: bool = False,
    enabled: bool = True,
) -> Schedule:
    """One door schedule entry, spelled the way the door stores it."""
    return Schedule(
        index=index,
        enabled=enabled,
        days_of_week=days,
        inside=inside,
        outside=outside,
        start=ScheduleTime(*start),
        end=ScheduleTime(*end),
    )


def at(day: datetime, hour: int, minute: int = 0) -> datetime:
    """A moment on `day`."""
    return day.replace(hour=hour, minute=minute)


# ---------------------------------------------------------------------------
# Window arithmetic - the three shapes the door produces
# ---------------------------------------------------------------------------


def test_a_plain_window_covers_its_own_hours_only() -> None:
    """06:00-20:00 on Monday, read back as minutes from Monday midnight."""
    assert active_windows([sched(MONDAY_ONLY, (6, 0), (20, 0))], SCHEDULE_INSIDE) == [
        (0, 360, 1200)
    ]


def test_the_door_day_index_is_translated_to_pythons() -> None:
    """Sunday is 0 to the door and 6 to `datetime.weekday()`.

    This is the crossing the whole module depends on, and getting it wrong
    shifts every schedule by a day - which nothing notices until a Sunday.
    Asserted at both ends of the week because an off-by-one that wraps is
    only visible at the wrap.
    """
    assert active_windows([sched(SUNDAY_ONLY, (6, 0), (20, 0))], SCHEDULE_INSIDE) == [
        (6, 360, 1200)
    ]
    assert active_windows([sched(SATURDAY_ONLY, (6, 0), (20, 0))], SCHEDULE_INSIDE) == [
        (5, 360, 1200)
    ]
    assert active_windows([sched(MONDAY_ONLY, (6, 0), (20, 0))], SCHEDULE_INSIDE) == [
        (0, 360, 1200)
    ]


def test_a_window_ending_at_2359_stops_one_minute_short_of_the_day() -> None:
    """23:59 is an ordinary time, and is read as one.

    An earlier version special-cased it as end-of-day, reasoning that the
    factory schedule is 00:00-23:59 and plainly means "always". That was an
    inference, and an unnecessary one once the device was measured to accept
    AND preserve 24:00 - written 00:00-24:00, a real door hands back
    00:00-24:00 unchanged.

    So `start <= now < end` is taken literally everywhere now, and a door
    whose entry really does end at 23:59 is reported closed for that final
    minute. That is a claim about the door rather than a rounding choice: if
    the firmware turns out to special-case 23:59 after all, this is the test
    that should fail.
    """
    assert active_windows([sched(MONDAY_ONLY, (0, 0), (23, 59))], SCHEDULE_INSIDE) == [(0, 0, 1439)]


def test_only_hour_24_reaches_the_end_of_the_day() -> None:
    """The unambiguous spelling, and the one the device is measured to honour."""
    assert active_windows([sched(MONDAY_ONLY, (0, 0), (24, 0))], SCHEDULE_INSIDE) == [(0, 0, 1440)]


def test_the_final_minute_of_the_day_belongs_to_24_00_and_not_to_2359() -> None:
    """The boundary, asserted on both sides and for both spellings.

    23:58 is covered either way; the whole difference lives in the last
    minute, so that is the minute to assert.
    """
    to_2359 = [sched(EVERY_DAY, (0, 0), (23, 59))]
    to_2400 = [sched(EVERY_DAY, (0, 0), (24, 0))]

    assert is_active(to_2359, SCHEDULE_INSIDE, at(MONDAY, 23, 58)) is True
    assert is_active(to_2359, SCHEDULE_INSIDE, at(MONDAY, 23, 59)) is False

    assert is_active(to_2400, SCHEDULE_INSIDE, at(MONDAY, 23, 58)) is True
    assert is_active(to_2400, SCHEDULE_INSIDE, at(MONDAY, 23, 59)) is True


def test_the_write_path_refuses_a_window_that_covers_no_time() -> None:
    """Both spellings of empty, refused before they reach the door.

    Reading one accurately is not enough. A door that ACCEPTS an empty window
    reports the sensor off with no `next_event` to bring it back, while the
    card reads "Active 24/7 (no schedule set)" - a schedule whose windows are
    all empty is indistinguishable from no schedule at all. The pet is shut
    out indefinitely and nothing on any screen says so.
    """
    for window in (("09:00", "09:00"), ("23:59", "23:59"), ("23:00", "01:00")):
        with pytest.raises(vol.Invalid):
            SCHEDULE_PAYLOAD_SCHEMA({"monday": [{"from": window[0], "to": window[1]}]})


def test_the_refusal_says_how_to_write_it_correctly() -> None:
    """Pinned by literal, because the advice was wrong and nothing caught it.

    The message used to recommend `<start>-23:59`, which under this repo's own
    semantics leaves 23:59:00-23:59:59 uncovered every night - it steered the
    user into the one spelling that quietly does not do what they asked. The
    end that actually runs to the end of the day is `00:00`, measured to be
    sent as `24:00` and honoured.

    Asserting the text matters: a parametrize LABEL reading "ends before it
    starts" looks like this assertion in a test report and is not one.
    """
    with pytest.raises(vol.Invalid) as excinfo:
        SCHEDULE_PAYLOAD_SCHEMA({"monday": [{"from": "23:00", "to": "01:00"}]})

    message = str(excinfo.value)
    assert "does not cover any time" in message
    assert "23:00-23:59" not in message, "steers the user into a nightly gap"
    assert "use 23:00-00:00 to run to the end of the day" in message


def test_a_window_whose_start_equals_its_end_is_no_window_at_all() -> None:
    """Coinciding ends are EMPTY, not a whole day.

    This asserted the opposite until it was measured. On firmware 1.7.18 with
    `timersEnabled` on, entries of `16:01-16:01` and `21:01-21:01` both leave
    the sensor DISABLED - the engine is `start <= now < end`, so a window
    whose end does not exceed its start matches no minute of any day. The
    door stores it perfectly and never acts on it.

    Reporting it as a whole day told the user their pet had access around the
    clock while the door was refusing every trigger.
    """
    assert active_windows([sched(MONDAY_ONLY, (0, 0), (0, 0))], SCHEDULE_INSIDE) == []
    assert active_windows([sched(MONDAY_ONLY, (9, 0), (9, 0))], SCHEDULE_INSIDE) == []


def test_a_window_ending_before_it_starts_is_no_window_at_all() -> None:
    """22:00-06:00 does not wrap. Not within the day, not into the next.

    Measured: an entry of `23:00-21:30` leaves the sensor disabled BOTH on
    the day it names and on the day after, so it is neither a same-day wrap
    nor a spill into tomorrow.

    Overnight access needs TWO entries - `22:00-24:00` on the day and
    `00:00-06:00` on the next - which is why the write path refuses this
    shape rather than storing something that silently never fires.
    """
    assert active_windows([sched(MONDAY_ONLY, (22, 0), (6, 0))], SCHEDULE_INSIDE) == []


def test_a_stored_window_ending_at_midnight_does_nothing() -> None:
    """Reading is faithful to the device, even where the spelling is a mistake.

    `22:00-00:00` is what someone means by "22:00 until midnight", but it is
    not what the door does with it: measured, the entry is stored perfectly
    and the sensor stays DISABLED, because the engine compares the raw
    numbers and an end of 0 never exceeds a start of 1320.

    So this reports nothing, which is the truth about that door right now.
    The translation to `24:00` belongs on the way TO the device - see
    `test_a_window_ending_at_midnight_is_sent_as_end_of_day` - so a user who
    writes it through Home Assistant gets what they meant, while a door that
    already holds it is described accurately rather than optimistically.
    """
    assert active_windows([sched(MONDAY_ONLY, (22, 0), (0, 0))], SCHEDULE_INSIDE) == []


def test_a_window_ending_at_midnight_is_sent_as_end_of_day() -> None:
    """The other half: what the user writes becomes what they meant.

    Midnight is positional - opening a window it is the day's first minute,
    closing one it is the day's last - so an end of 00:00 leaves here as
    24:00, which the device is measured to honour.
    """
    rebuilt = from_ha_format({"monday": [{"from": "22:00", "to": "00:00"}]}, SCHEDULE_INSIDE)

    assert len(rebuilt) == 1
    assert (rebuilt[0].end.hour, rebuilt[0].end.minute) == (24, 0)
    assert active_windows(rebuilt, SCHEDULE_INSIDE) == [(0, 1320, 1440)]


def test_hour_24_is_the_end_of_the_day() -> None:
    """`24:00` is the unambiguous end-of-day, and the device honours it.

    Measured: `20:00-24:00` reports the sensor enabled at 21:07 and
    `00:00-24:00` enables it outright.
    """
    assert active_windows([sched(MONDAY_ONLY, (0, 0), (24, 0))], SCHEDULE_INSIDE) == [(0, 0, 1440)]
    assert active_windows([sched(MONDAY_ONLY, (22, 0), (24, 0))], SCHEDULE_INSIDE) == [
        (0, 1320, 1440)
    ]


def test_a_disabled_entry_gates_nothing() -> None:
    """`enabled: false` is how the door says "ignore this entry"."""
    assert (
        active_windows([sched(MONDAY_ONLY, (6, 0), (20, 0), enabled=False)], SCHEDULE_INSIDE) == []
    )


def test_an_entry_for_the_other_sensor_is_not_this_sensors_window() -> None:
    """One table covers both sensors; each kind reads only its own flag."""
    inside_only = [sched(MONDAY_ONLY, (6, 0), (20, 0), inside=True, outside=False)]

    assert active_windows(inside_only, SCHEDULE_INSIDE) == [(0, 360, 1200)]
    assert active_windows(inside_only, SCHEDULE_OUTSIDE) == []


def test_an_entry_gating_both_sensors_appears_in_both() -> None:
    """The factory default sets both flags on one entry."""
    both = [sched(EVERY_DAY, (0, 0), (23, 59), inside=True, outside=True)]

    assert len(active_windows(both, SCHEDULE_INSIDE)) == 7
    assert len(active_windows(both, SCHEDULE_OUTSIDE)) == 7


# ---------------------------------------------------------------------------
# is_active
# ---------------------------------------------------------------------------


def test_a_door_with_no_schedule_leaves_the_sensor_on() -> None:
    """No entries means the door never gates the sensor.

    Reporting False here would tell the user their pet cannot get in when it
    can - and this is the out-of-box state for a door whose schedule was
    cleared.
    """
    assert is_active([], SCHEDULE_INSIDE, MONDAY) is True


def test_a_door_whose_only_entry_is_disabled_blocks_the_sensor() -> None:
    """A table of disabled entries is NOT an empty table.

    The door tests the table itself - `is_sensor_allowed_by_schedule` does
    `if not self.schedules: return True` - and a table holding one disabled
    row is not empty. It falls through to the per-window check, finds
    nothing that permits the sensor, and blocks.

    So switching every window off, which is how a user pauses a schedule
    without deleting it, closes the door to the pet. Reporting it as "on"
    told them the opposite of what their door was doing.
    """
    assert (
        is_active([sched(EVERY_DAY, (6, 0), (20, 0), enabled=False)], SCHEDULE_INSIDE, MONDAY)
        is False
    )


def test_a_disabled_entry_does_not_re_open_a_sensor_another_entry_gates() -> None:
    """The boundary between the two rules above.

    One disabled row and one enabled row: the table is non-empty either way,
    so the answer must come from the enabled row alone. Asserted on both
    sides of its window, because "always on" and "correctly gated" agree
    everywhere except outside it.
    """
    schedules = [
        sched(EVERY_DAY, (6, 0), (20, 0), enabled=False),
        sched(EVERY_DAY, (9, 0), (17, 0)),
    ]
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 8, 59)) is False
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 9, 0)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 16, 59)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 17, 0)) is False


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (at(MONDAY, 5, 59), False),
        (at(MONDAY, 6, 0), True),
        (at(MONDAY, 19, 59), True),
        (at(MONDAY, 20, 0), False),
    ],
)
def test_a_window_is_open_from_its_start_up_to_but_not_including_its_end(
    when: datetime, expected: bool
) -> None:
    """Both sides of both edges of a 06:00-20:00 window.

    The start is inclusive and the end exclusive, and a test that only
    sampled the middle would pass with either edge inverted.
    """
    assert is_active([sched(MONDAY_ONLY, (6, 0), (20, 0))], SCHEDULE_INSIDE, when) is expected


def test_a_mondays_window_does_not_open_on_tuesday() -> None:
    """The day mask actually gates the window."""
    schedules = [sched(MONDAY_ONLY, (6, 0), (20, 0))]

    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 12)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(TUESDAY, 12)) is False


# ---------------------------------------------------------------------------
# Midnight crossing - regression for finding B4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("when", "why"),
    [
        (at(MONDAY, 0, 0), "Monday midnight"),
        (at(MONDAY, 5, 59), "where a same-day wrap would have put the tail"),
        (at(MONDAY, 6, 0), "the nominal end"),
        (at(MONDAY, 21, 59), "before the nominal start"),
        (at(MONDAY, 22, 0), "the nominal start"),
        (at(MONDAY, 23, 59), "Monday night"),
        (at(TUESDAY, 0, 0), "where a next-day spill would have put the tail"),
        (at(TUESDAY, 5, 59), "and its last minute"),
    ],
)
def test_a_monday_window_ending_before_it_starts_is_never_active(when: datetime, why: str) -> None:
    """Not at ANY minute, on either day. Measured, not reasoned.

    Rounds 1 and 2 both got this wrong in opposite directions - round 1 read
    Mon 22:00 -> Tue 06:00, round 2 read it as two spans on Monday and
    "verified" that over 576,800 samples against the SIMULATOR, which was
    itself wrong.

    A real door settles it: an entry of `23:00-21:30` leaves the sensor
    DISABLED both on the day it names and on the following day. The engine is
    `start <= now < end` with no wrapping, so an inverted window matches
    nothing at all.

    Every sample below is False, which is the point: the two earlier readings
    each predicted True for some of these, so this parametrisation is what
    tells all three apart.
    """
    assert is_active([sched(MONDAY_ONLY, (22, 0), (6, 0))], SCHEDULE_INSIDE, when) is False, why


def test_the_two_entries_an_overnight_schedule_actually_needs() -> None:
    """How to express "22:00 until 06:00" so the door honours it.

    The device cannot do it in one entry, so it takes two: the evening half
    running to the end of Monday, and the morning half opening Tuesday. This
    is the shape the write path steers users to when it refuses an inverted
    window, so it has to actually work.
    """
    schedules = [
        sched(MONDAY_ONLY, (22, 0), (24, 0)),
        sched(TUESDAY_ONLY, (0, 0), (6, 0)),
    ]

    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 21, 59)) is False
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 22, 0)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 23, 59)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(TUESDAY, 0, 0)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(TUESDAY, 5, 59)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(TUESDAY, 6, 0)) is False


def test_a_sunday_window_ending_before_it_starts_is_never_active() -> None:
    """The same case at the week's wrap, where the day mapping folds.

    Sunday is the door's day 0 and Python's day 6, so this is where an
    implementation that spilled into the next day would get the weekday
    arithmetic wrong as well as the semantics. It does neither, because it
    is not active at all.
    """
    schedules = [sched(SUNDAY_ONLY, (22, 0), (6, 0))]

    assert is_active(schedules, SCHEDULE_INSIDE, at(SUNDAY, 23, 0)) is False
    assert is_active(schedules, SCHEDULE_INSIDE, at(SUNDAY, 5, 0)) is False
    assert is_active(schedules, SCHEDULE_INSIDE, at(SUNDAY, 7, 0)) is False
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 5, 0)) is False


# ---------------------------------------------------------------------------
# Overlapping windows - regression for finding B3
# ---------------------------------------------------------------------------


def test_two_overlapping_windows_stay_open_until_the_later_one_closes() -> None:
    """Regression for finding B3.

    The door ORs its entries: `is_sensor_allowed` returns True if ANY entry
    allows the sensor. The old "last edge wins" implementation turned the
    sensor off at 12:00 - when the FIRST window closed - while the door
    still had it on for another eight hours. 12:30 is the minute that tells
    the two implementations apart.
    """
    schedules = [
        sched(MONDAY_ONLY, (6, 0), (12, 0), index=0),
        sched(MONDAY_ONLY, (10, 0), (20, 0), index=1),
    ]

    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 11)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 12, 30)) is True
    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 20, 0)) is False


def test_two_abutting_windows_never_dip_between_them() -> None:
    """A window closing exactly as another opens leaves no gap.

    06:00-12:00 and 12:00-20:00 share an edge. Sorting the closing edge
    first would show a one-instant closed state at 12:00, which is a state
    the door is never in and which an automation would see as a real event.
    """
    schedules = [
        sched(MONDAY_ONLY, (6, 0), (12, 0), index=0),
        sched(MONDAY_ONLY, (12, 0), (20, 0), index=1),
    ]

    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 12, 0)) is True


def test_a_window_fully_inside_another_does_not_close_it_early() -> None:
    """Containment is the other overlap shape.

    A 10:00-11:00 window nested in a 06:00-20:00 one must not end the outer
    window at 11:00. Counted depth handles this; a boolean toggle does not.
    """
    schedules = [
        sched(MONDAY_ONLY, (6, 0), (20, 0), index=0),
        sched(MONDAY_ONLY, (10, 0), (11, 0), index=1),
    ]

    assert is_active(schedules, SCHEDULE_INSIDE, at(MONDAY, 11, 30)) is True


# ---------------------------------------------------------------------------
# next_event
# ---------------------------------------------------------------------------


def test_the_next_event_is_the_windows_opening_when_it_is_shut() -> None:
    """From 05:00 on Monday, the next change is 06:00 the same day."""
    upcoming = next_event([sched(MONDAY_ONLY, (6, 0), (20, 0))], SCHEDULE_INSIDE, at(MONDAY, 5))

    assert upcoming == at(MONDAY, 6)


def test_the_next_event_is_the_windows_closing_when_it_is_open() -> None:
    """From inside the window, the next change is its end."""
    upcoming = next_event([sched(MONDAY_ONLY, (6, 0), (20, 0))], SCHEDULE_INSIDE, at(MONDAY, 12))

    assert upcoming == at(MONDAY, 20)


def test_the_next_event_skips_an_edge_that_changes_nothing() -> None:
    """An overlap's inner edges are not events (finding B3, read side).

    From 11:00 with 06:00-12:00 and 10:00-20:00 running, 12:00 is an edge
    but not a change - the union stays open. Reporting it would make the
    sensor rewrite an identical state and wake a timer for nothing.
    """
    schedules = [
        sched(MONDAY_ONLY, (6, 0), (12, 0), index=0),
        sched(MONDAY_ONLY, (10, 0), (20, 0), index=1),
    ]

    assert next_event(schedules, SCHEDULE_INSIDE, at(MONDAY, 11)) == at(MONDAY, 20)


def test_a_door_with_no_schedule_has_no_next_event() -> None:
    """Nothing will ever change, so there is nothing to wake up for."""
    assert next_event([], SCHEDULE_INSIDE, MONDAY) is None


def test_a_schedule_that_is_always_open_has_no_next_event() -> None:
    """An all-week, all-day schedule never flips.

    The distinction that matters: this is NOT "no windows" - there are seven
    of them - so the answer has to come from the union never changing, and
    a timer must not be armed for a transition that cannot happen.
    """
    assert next_event([sched(EVERY_DAY, (0, 0), (24, 0))], SCHEDULE_INSIDE, at(MONDAY, 12)) is None


def test_the_next_event_after_a_window_closes_is_its_next_days_opening() -> None:
    """A weekday schedule rolls forward to tomorrow, not back to today."""
    upcoming = next_event([sched(WEEKDAYS, (6, 0), (20, 0))], SCHEDULE_INSIDE, at(MONDAY, 21))

    assert upcoming == at(TUESDAY, 6)


# ---------------------------------------------------------------------------
# to_ha_format / from_ha_format
# ---------------------------------------------------------------------------


def test_windows_are_reported_in_home_assistants_own_schedule_shape() -> None:
    """`{"monday": [{"from": ..., "to": ...}]}` - what the card consumes."""
    result = to_ha_format([sched(WEEKDAYS, (6, 0), (20, 0))], SCHEDULE_INSIDE)

    assert result == {
        "monday": [{"from": "06:00", "to": "20:00"}],
        "tuesday": [{"from": "06:00", "to": "20:00"}],
        "wednesday": [{"from": "06:00", "to": "20:00"}],
        "thursday": [{"from": "06:00", "to": "20:00"}],
        "friday": [{"from": "06:00", "to": "20:00"}],
    }


def test_a_day_with_no_window_is_omitted_rather_than_emitted_empty() -> None:
    """Matching Home Assistant, whose own schedule helper omits them."""
    result = to_ha_format([sched(MONDAY_ONLY, (6, 0), (20, 0))], SCHEDULE_INSIDE)

    assert set(result) == {"monday"}


def test_an_all_day_window_is_reported_the_way_the_factory_spells_it() -> None:
    """1440 is the end of the day, and the device writes that 23:59.

    Not 00:00. That is midnight at the START of a day, so as an end it says
    the opposite of what is meant - and the device's own factory schedule is
    00:00-23:59 on all seven days. Emitting 00:00 meant the factory
    schedule did not survive a round trip: it came back as 00:00-00:00, so
    saving any edit rewrote every all-day entry the door already had.
    """
    assert to_ha_format([sched(MONDAY_ONLY, (0, 0), (23, 59))], SCHEDULE_INSIDE) == {
        "monday": [{"from": "00:00", "to": "23:59"}]
    }


def test_the_factory_schedule_survives_a_round_trip_unchanged() -> None:
    """Read it, write it back, and the door sees no change at all.

    The consequence that made the spelling matter. `compute_schedule_diff`
    works on the entries `from_ha_format` rebuilds, so an end time that
    came back different was a write to a single-connection device for an
    edit the user never made.
    """
    original = sched(MONDAY_ONLY, (0, 0), (23, 59))
    rebuilt = from_ha_format(to_ha_format([original], SCHEDULE_INSIDE), SCHEDULE_INSIDE)

    assert len(rebuilt) == 1
    # Byte for byte, 23:59 included. Nothing is normalised on the way
    # through, so a door that already holds this entry is not rewritten by
    # an edit the user made to some other day.
    assert (rebuilt[0].start.hour, rebuilt[0].start.minute) == (0, 0)
    assert (rebuilt[0].end.hour, rebuilt[0].end.minute) == (23, 59)
    assert active_windows(rebuilt, SCHEDULE_INSIDE) == active_windows([original], SCHEDULE_INSIDE)


def test_a_whole_day_survives_a_round_trip_as_hour_24() -> None:
    """The same for the spelling that really does mean the whole day.

    Home Assistant carries it as midnight, and it has to come back as 24:00
    or the door would be sent a window that never fires.
    """
    original = sched(MONDAY_ONLY, (0, 0), (24, 0))
    as_ha = to_ha_format([original], SCHEDULE_INSIDE)
    rebuilt = from_ha_format(as_ha, SCHEDULE_INSIDE)

    assert as_ha == {"monday": [{"from": "00:00", "to": "00:00"}]}
    assert (rebuilt[0].end.hour, rebuilt[0].end.minute) == (24, 0)
    assert active_windows(rebuilt, SCHEDULE_INSIDE) == [(0, 0, 1440)]


def test_an_inverted_window_is_reported_as_no_window_at_all() -> None:
    """22:00-06:00 on Monday shows nothing, because it DOES nothing.

    Earlier versions rendered it as two blocks, on the belief that the door
    wrapped it within the day. Measured, it does not wrap at all: the sensor
    stays disabled on the day it names and on the next. Drawing two bars for
    it told the user their pet had access for eight hours a night that it
    did not have.

    The door still holds the entry - `active_windows` reads what the door
    DOES, not what it stores - and the write path refuses to create another
    one, pointing at the two-entry spelling instead.
    """
    assert to_ha_format([sched(MONDAY_ONLY, (22, 0), (6, 0))], SCHEDULE_INSIDE) == {}


def test_an_evening_window_is_reported_to_the_end_of_its_day() -> None:
    """The half of an overnight schedule that lives on this day.

    `22:00-24:00` is emitted as `22:00-00:00` because Home Assistant's shape
    has no hour 24, and `from_ha_format` sends it back as `24:00`.
    """
    assert to_ha_format([sched(MONDAY_ONLY, (22, 0), (24, 0))], SCHEDULE_INSIDE) == {
        "monday": [{"from": "22:00", "to": "00:00"}]
    }


def test_everything_the_door_can_report_is_something_we_may_write_back() -> None:
    """The read path is permissive and the write path is strict, so the two
    have to meet: anything `to_ha_format` emits must pass the payload schema.

    Asserted over the awkward entries specifically - all-day both ways, a
    window ending at midnight, and one that wraps - because those are the
    spellings where the two paths disagreed.
    """
    for entry in (
        sched(MONDAY_ONLY, (0, 0), (23, 59)),
        sched(MONDAY_ONLY, (0, 0), (24, 0)),
        sched(MONDAY_ONLY, (0, 0), (0, 0)),
        sched(MONDAY_ONLY, (22, 0), (24, 0)),
        sched(MONDAY_ONLY, (22, 0), (0, 0)),
        sched(MONDAY_ONLY, (22, 0), (6, 0)),
        sched(MONDAY_ONLY, (6, 0), (20, 0)),
    ):
        SCHEDULE_PAYLOAD_SCHEMA(to_ha_format([entry], SCHEDULE_INSIDE))


def test_home_assistant_windows_become_door_entries_for_the_right_sensor() -> None:
    """The inside kind sets `inside` and clears `outside`, and vice versa."""
    payload = {"monday": [{"from": "06:00", "to": "20:00"}]}

    inside = from_ha_format(payload, SCHEDULE_INSIDE)
    assert len(inside) == 1
    assert inside[0].inside is True
    assert inside[0].outside is False
    assert inside[0].days_of_week == MONDAY_ONLY
    assert inside[0].start == ScheduleTime(6, 0)
    assert inside[0].end == ScheduleTime(20, 0)

    outside = from_ha_format(payload, SCHEDULE_OUTSIDE)
    assert outside[0].inside is False
    assert outside[0].outside is True


def test_an_unknown_day_name_produces_no_entry() -> None:
    """A day the schedule shape has no place for is dropped, not guessed.

    The payload schema rejects unknown days before this is reached from
    either entry point; this is the belt to that braces, and it must not
    invent a Monday out of "funday".
    """
    assert from_ha_format({"funday": [{"from": "06:00", "to": "20:00"}]}, SCHEDULE_INSIDE) == []


def test_seconds_in_a_time_are_accepted_and_dropped() -> None:
    """Home Assistant writes "06:00:00"; the door has no seconds field."""
    entries = from_ha_format({"monday": [{"from": "06:00:00", "to": "20:30:00"}]}, SCHEDULE_INSIDE)

    assert entries[0].start == ScheduleTime(6, 0)
    assert entries[0].end == ScheduleTime(20, 30)


def test_an_already_parsed_time_object_is_accepted() -> None:
    """HA's own schedule helper stores `datetime.time`, not strings.

    A template or a script reading a core schedule entity and passing it
    straight through arrives here with real time objects, and re-parsing
    those as strings would raise.
    """
    entries = from_ha_format(
        {"monday": [{"from": time(6, 0), "to": time(20, 30)}]}, SCHEDULE_INSIDE
    )

    assert entries[0].start == ScheduleTime(6, 0)
    assert entries[0].end == ScheduleTime(20, 30)


def test_a_window_survives_a_round_trip_through_both_conversions() -> None:
    """The two directions are inverses for every shape the door produces.

    Asserted as a set of windows rather than of entries, because
    `from_ha_format` emits one entry per day where the door may have used
    one entry for five - the same schedule, differently packed.
    """
    original = [
        sched(WEEKDAYS, (6, 0), (20, 0), index=0),
        sched(SATURDAY_ONLY, (22, 0), (6, 0), index=1),
    ]
    ha = to_ha_format(original, SCHEDULE_INSIDE)

    assert set(active_windows(from_ha_format(ha, SCHEDULE_INSIDE), SCHEDULE_INSIDE)) == set(
        active_windows(original, SCHEDULE_INSIDE)
    )


# ---------------------------------------------------------------------------
# summarise
# ---------------------------------------------------------------------------


def test_days_sharing_a_window_are_summarised_on_one_line() -> None:
    """PR #19: five days must read as one line, not five."""
    assert summarise([sched(WEEKDAYS, (6, 0), (20, 0))], SCHEDULE_INSIDE) == [
        "Mon, Tue, Wed, Thu, Fri: 06:00-20:00"
    ]


def test_different_windows_are_summarised_on_separate_lines_in_time_order() -> None:
    """Two distinct windows stay distinct, earliest first."""
    schedules = [
        sched(SATURDAY_ONLY, (8, 0), (22, 0), index=1),
        sched(WEEKDAYS, (6, 0), (20, 0), index=0),
    ]

    assert summarise(schedules, SCHEDULE_INSIDE) == [
        "Mon, Tue, Wed, Thu, Fri: 06:00-20:00",
        "Sat: 08:00-22:00",
    ]


def test_an_all_day_window_summarises_as_midnight_to_midnight() -> None:
    """Consistent with `to_ha_format`, so the card and the text agree."""
    assert summarise([sched(MONDAY_ONLY, (0, 0), (24, 0))], SCHEDULE_INSIDE) == ["Mon: 00:00-00:00"]


def test_a_door_with_no_schedule_summarises_as_nothing() -> None:
    """An empty list, not a line saying "none" - the attribute is a list."""
    assert summarise([], SCHEDULE_INSIDE) == []


# ---------------------------------------------------------------------------
# apply_schedule - the shared write path
# ---------------------------------------------------------------------------


async def test_editing_a_window_reuses_its_slot_instead_of_adding_a_second(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Regression for finding B1.

    `compute_schedule_diff` documents that `entries_to_set` are copies "with
    their index field reassigned", and it already reuses freed slots first.
    Recomputing the indices here handed out an index the library had
    reserved, so an edited window was written to a NEW slot while the old
    one survived - the door then gated the union of both, and the user's
    06:00 window was still in force after they moved it to 07:00.

    The assertion is the index, not the call count: writing once to the
    wrong slot is exactly the bug.
    """
    mock_door.refresh_schedules.return_value = [sched(MONDAY_ONLY, (6, 0), (20, 0), index=0)]

    await apply_schedule(
        setup_integration.runtime_data,
        SCHEDULE_INSIDE,
        {"monday": [{"from": "07:00", "to": "21:00"}]},
    )

    assert mock_door.set_schedule.await_count == 1
    written = mock_door.set_schedule.await_args.args[0]
    assert written.index == 0
    assert written.start == ScheduleTime(7, 0)
    # Nothing was deleted, because slot 0 was overwritten in place. A delete
    # would have left the sensor ungated for the length of the rewrite.
    mock_door.delete_schedule.assert_not_awaited()


async def test_editing_one_of_two_windows_leaves_the_other_in_its_slot(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The multi-entry form of finding B1.

    With several edits, recomputed indices could collide on one slot and
    silently lose a window. Here Monday is edited and Tuesday is not: the
    untouched entry must not be rewritten at all, and the edited one must
    land in a slot that is not Tuesday's.
    """
    mock_door.refresh_schedules.return_value = [
        sched(MONDAY_ONLY, (6, 0), (20, 0), index=0),
        sched(TUESDAY_ONLY, (9, 0), (17, 0), index=1),
    ]

    await apply_schedule(
        setup_integration.runtime_data,
        SCHEDULE_INSIDE,
        {
            "monday": [{"from": "07:00", "to": "21:00"}],
            "tuesday": [{"from": "09:00", "to": "17:00"}],
        },
    )

    written = [call.args[0] for call in mock_door.set_schedule.await_args_list]
    # Tuesday matched by content and was left alone.
    assert len(written) == 1
    assert written[0].days_of_week == MONDAY_ONLY
    assert written[0].index == 0
    mock_door.delete_schedule.assert_not_awaited()


async def test_restricting_the_inside_sensor_clears_only_its_own_flag(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Regression for finding B2.

    A factory door ships ONE entry with `inside:1 outside:1` 00:00-23:59 on
    every day. `keep` used to retain such an entry whole, so the inside
    sensor stayed enabled all day no matter what the user asked for - a
    first-use failure of the headline feature, and one that looks like the
    save silently did nothing.

    The outside sensor's all-day coverage must survive untouched; only the
    inside flag comes off it.
    """
    mock_door.refresh_schedules.return_value = [
        sched(EVERY_DAY, (0, 0), (23, 59), index=0, inside=True, outside=True)
    ]

    await apply_schedule(
        setup_integration.runtime_data,
        SCHEDULE_INSIDE,
        {"monday": [{"from": "06:00", "to": "20:00"}]},
    )

    written = [call.args[0] for call in mock_door.set_schedule.await_args_list]

    # Nothing written may still gate the inside sensor all day - that is the
    # bug stated directly.
    assert not [
        entry
        for entry in written
        if entry.inside and (entry.start, entry.end) == (ScheduleTime(0, 0), ScheduleTime(23, 59))
    ]

    surviving_outside = [entry for entry in written if entry.outside]
    assert len(surviving_outside) == 1
    assert surviving_outside[0].inside is False
    assert surviving_outside[0].days_of_week == EVERY_DAY
    assert surviving_outside[0].end == ScheduleTime(23, 59)

    new_inside = [entry for entry in written if entry.inside]
    assert len(new_inside) == 1
    assert new_inside[0].outside is False
    assert new_inside[0].days_of_week == MONDAY_ONLY
    assert new_inside[0].start == ScheduleTime(6, 0)


async def test_restricting_the_outside_sensor_clears_only_its_own_flag(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The mirror of finding B2, decided by the `kind == SCHEDULE_INSIDE` branch.

    Only running the inside case would leave the outside branch of that
    `if` unexecuted, and an inverted copy-paste there would clear the wrong
    flag - silently disabling the sensor the user was not editing.
    """
    mock_door.refresh_schedules.return_value = [
        sched(EVERY_DAY, (0, 0), (23, 59), index=0, inside=True, outside=True)
    ]

    await apply_schedule(
        setup_integration.runtime_data,
        SCHEDULE_OUTSIDE,
        {"monday": [{"from": "06:00", "to": "20:00"}]},
    )

    written = [call.args[0] for call in mock_door.set_schedule.await_args_list]

    surviving_inside = [entry for entry in written if entry.inside]
    assert len(surviving_inside) == 1
    assert surviving_inside[0].outside is False
    assert surviving_inside[0].end == ScheduleTime(23, 59)


async def test_an_entry_gating_only_the_other_sensor_is_left_completely_alone(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """Writing the inside schedule must not disturb outside-only entries.

    They match by content, so they are neither deleted nor rewritten - the
    outside sensor is not ungated for even the length of one round trip.
    """
    mock_door.refresh_schedules.return_value = [
        sched(MONDAY_ONLY, (8, 0), (18, 0), index=0, inside=False, outside=True)
    ]

    await apply_schedule(
        setup_integration.runtime_data,
        SCHEDULE_INSIDE,
        {"monday": [{"from": "06:00", "to": "20:00"}]},
    )

    written = [call.args[0] for call in mock_door.set_schedule.await_args_list]
    assert [entry for entry in written if entry.outside] == []
    mock_door.delete_schedule.assert_not_awaited()


async def test_clearing_a_schedule_deletes_the_slot_it_occupied(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """An empty payload removes the window rather than leaving it behind.

    This is the one path that legitimately deletes: there is no replacement
    entry to reuse the slot, so it has to be freed or the door keeps gating
    on a schedule the user just cleared.
    """
    mock_door.refresh_schedules.return_value = [sched(MONDAY_ONLY, (6, 0), (20, 0), index=0)]

    await apply_schedule(setup_integration.runtime_data, SCHEDULE_INSIDE, {})

    mock_door.delete_schedule.assert_awaited_once_with(0)
    mock_door.set_schedule.assert_not_awaited()


async def test_the_write_path_reads_the_door_before_diffing_it(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The current table comes off the door, not out of the cache.

    The cache may predate an edit made from the phone app or the door's own
    controls, and diffing against it would resurrect windows the user
    already removed elsewhere.
    """
    mock_door.schedules = [sched(MONDAY_ONLY, (6, 0), (20, 0), index=0)]
    mock_door.refresh_schedules.return_value = []

    await apply_schedule(
        setup_integration.runtime_data,
        SCHEDULE_INSIDE,
        {"monday": [{"from": "06:00", "to": "20:00"}]},
    )

    # The door reported an EMPTY table, so despite the stale cache holding
    # an identical window there is nothing to match against and the entry is
    # written. Reading the cache instead would have matched and written
    # nothing at all.
    mock_door.set_schedule.assert_awaited_once()


async def test_the_write_path_re_reads_the_door_afterwards(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_door: MagicMock
) -> None:
    """The entity shows what the door accepted, not what was requested.

    Once before the diff and once after the writes. Without the second read
    the schedule sensor would report the user's request even if the door
    silently clamped or rejected part of it.
    """
    mock_door.refresh_schedules.return_value = []

    await apply_schedule(
        setup_integration.runtime_data,
        SCHEDULE_INSIDE,
        {"monday": [{"from": "06:00", "to": "20:00"}]},
    )

    assert mock_door.refresh_schedules.await_count == 2


# ---------------------------------------------------------------------------
# Slot economy - regression for finding B9
# ---------------------------------------------------------------------------


def test_a_whole_week_of_identical_windows_becomes_one_entry() -> None:
    """Regression for finding B9.

    `to_ha_format` explodes an entry into one slot per day, so a round trip
    used to turn ONE factory entry into EIGHT - eight writes to a device
    that is single-connection and rate-limited, and eight rows in the user's
    phone app where the factory shipped one. The door also has a finite
    number of slots.
    """
    every_day = {
        day: [{"from": "06:00", "to": "20:00"}]
        for day in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
    }

    entries = from_ha_format(every_day, SCHEDULE_INSIDE)

    assert len(entries) == 1
    assert entries[0].days_of_week == [True] * 7


def test_merging_preserves_exactly_the_windows_it_started_with() -> None:
    """Fewer entries, identical coverage - the merge must be lossless.

    Asserted as the resulting window set rather than as entries: the point
    is that packing changed and meaning did not.
    """
    config = {
        "monday": [{"from": "06:00", "to": "08:00"}, {"from": "17:00", "to": "19:00"}],
        "tuesday": [{"from": "06:00", "to": "08:00"}],
        "saturday": [{"from": "09:00", "to": "12:00"}],
    }

    entries = from_ha_format(config, SCHEDULE_INSIDE)

    # 4 (day, window) pairs collapse to 3 entries: the 06:00-08:00 window is
    # shared by Monday and Tuesday.
    assert len(entries) == 3
    assert to_ha_format(entries, SCHEDULE_INSIDE) == config


def test_windows_that_differ_are_never_merged() -> None:
    """Only entries agreeing on window AND sensor flags may combine.

    Merging on the day mask alone would silently move a window to a day the
    user never chose - the opposite failure, and a much worse one.
    """
    config = {
        "monday": [{"from": "06:00", "to": "08:00"}],
        "tuesday": [{"from": "07:00", "to": "08:00"}],
    }

    entries = from_ha_format(config, SCHEDULE_INSIDE)

    assert len(entries) == 2
    assert to_ha_format(entries, SCHEDULE_INSIDE) == config


# ---------------------------------------------------------------------------
# Consolidation
# ---------------------------------------------------------------------------


def _spans_by_day(entries: list[Schedule]) -> dict[int, list[tuple[int, int]]]:
    """Covered minutes per door-convention day index, for the inside sensor."""
    out: dict[int, list[tuple[int, int]]] = {}
    for entry in entries:
        if not entry.inside:
            continue
        for day, on in enumerate(entry.days_of_week):
            if on:
                out.setdefault(day, []).extend(_entry_spans(entry))
    return {day: _union(spans) for day, spans in out.items()}


class TestConsolidation:
    """The door has a finite number of slots on a rate-limited link.

    An entry that says nothing a shorter table could say is a real cost, and
    the user's phone app lists every one of them. The pre-rewrite code got
    this from the library's `compress_schedule`, which cannot be used here -
    it swaps an inverted window's ends, turning 22:00-06:00 into 06:00-22:00,
    the precise inverse of what was asked for.
    """

    def test_windows_that_touch_become_one(self):
        """06:00-08:00 then 08:00-10:00 is 06:00-10:00, in one entry.

        Abutment, not overlap: the windows share a single instant and no
        minutes at all, so a merge rule written with `<` instead of `<=`
        leaves both and the door burns two slots saying one thing.
        """
        merged = _consolidate(
            [
                sched(_days(1), (6, 0), (8, 0)),
                sched(_days(1), (8, 0), (10, 0)),
            ]
        )

        assert len(merged) == 1
        assert (merged[0].start.hour, merged[0].start.minute) == (6, 0)
        assert (merged[0].end.hour, merged[0].end.minute) == (10, 0)

    def test_windows_that_overlap_become_one(self):
        merged = _consolidate(
            [
                sched(_days(1), (6, 0), (9, 0)),
                sched(_days(1), (8, 0), (10, 0)),
            ]
        )

        assert len(merged) == 1
        assert (merged[0].start.hour, merged[0].end.hour) == (6, 10)

    def test_windows_with_a_gap_are_left_alone(self):
        """The boundary the merge rule turns on, asserted from both sides.

        One minute apart is still two windows: merging them would open the
        door for a minute the user did not ask for.
        """
        merged = _consolidate(
            [
                sched(_days(1), (6, 0), (8, 0)),
                sched(_days(1), (8, 1), (10, 0)),
            ]
        )

        assert len(merged) == 2

    def test_the_same_window_on_both_sensors_becomes_one_entry(self):
        """Two entries differing only in which sensor they gate.

        The door's entry carries both flags, so this is one slot, not two -
        and it is the shape the factory default ships in.
        """
        merged = _consolidate(
            [
                sched(_days(1), (6, 0), (8, 0), inside=True, outside=False),
                sched(_days(1), (6, 0), (8, 0), inside=False, outside=True),
            ]
        )

        assert len(merged) == 1
        assert merged[0].inside is True
        assert merged[0].outside is True

    def test_the_same_window_on_several_days_becomes_one_masked_entry(self):
        merged = _consolidate(
            [
                sched(_days(1), (6, 0), (8, 0)),
                sched(_days(2), (6, 0), (8, 0)),
                sched(_days(3), (6, 0), (8, 0)),
            ]
        )

        assert len(merged) == 1
        assert sum(merged[0].days_of_week) == 3

    def test_days_that_differ_are_not_forced_together(self):
        """Monday gains a window Tuesday does not; they cannot share an entry."""
        merged = _consolidate(
            [
                sched(_days(1), (6, 0), (8, 0)),
                sched(_days(1), (8, 0), (10, 0)),
                sched(_days(2), (6, 0), (8, 0)),
            ]
        )

        assert _spans_by_day(merged) == {1: [(360, 600)], 2: [(360, 480)]}

    def test_a_disabled_entry_is_carried_through_untouched(self):
        """It covers nothing now, but the user may switch it back on.

        Folding it into coverage would silently delete a window the user
        parked; rewriting it as enabled would silently switch it on.
        """
        disabled = sched(_days(1), (6, 0), (8, 0), enabled=False)

        merged = _consolidate([disabled])

        assert merged == [disabled]

    def test_an_empty_window_is_carried_through_untouched(self):
        """`end <= start` covers no time; the door stores it and never acts.

        It cannot be expressed as coverage, so it cannot be rebuilt from
        coverage. Dropping it would be this function deciding something the
        user did not ask it to decide.
        """
        empty = sched(_days(1), (8, 0), (8, 0))

        merged = _consolidate([empty])

        assert merged == [empty]

    def test_a_disabled_entry_does_not_absorb_an_enabled_one(self):
        """Both arms in one table, which is the case that actually ships."""
        disabled = sched(_days(1), (6, 0), (8, 0), enabled=False)

        merged = _consolidate([disabled, sched(_days(1), (6, 0), (8, 0))])

        assert disabled in merged
        assert len(merged) == 2

    def test_end_of_day_survives_consolidation_as_24_00(self):
        """1440 minutes must come back as 24:00, which the door honours.

        An end of 00:00 is a spelling the door stores and never acts on, so
        rebuilding the span with `divmod` has to produce hour 24, not 0.
        """
        merged = _consolidate([sched(_days(1), (22, 0), (24, 0))])

        assert (merged[0].end.hour, merged[0].end.minute) == (24, 0)
