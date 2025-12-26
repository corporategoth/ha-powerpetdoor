# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Tests for Power Pet Door schedule logic."""
from __future__ import annotations

from datetime import time
from copy import deepcopy

import pytest

from custom_components.powerpetdoor.schedule import (
    week_0_mon_to_sun,
    week_0_sun_to_mon,
    validate_schedule_entry,
    compress_schedule,
    schedule_entry_content_key,
    compute_schedule_diff,
    schedule_template,
)
from custom_components.powerpetdoor.const import (
    FIELD_INDEX,
    FIELD_DAYSOFWEEK,
    FIELD_INSIDE,
    FIELD_OUTSIDE,
    FIELD_ENABLED,
    FIELD_INSIDE_PREFIX,
    FIELD_OUTSIDE_PREFIX,
    FIELD_START_TIME_SUFFIX,
    FIELD_END_TIME_SUFFIX,
    FIELD_HOUR,
    FIELD_MINUTE,
)


# ============================================================================
# Helper Functions Tests
# ============================================================================

class TestWeekdayConversion:
    """Tests for weekday conversion functions."""

    def test_week_0_mon_to_sun_monday(self):
        """Test Monday (0 in Mon=0 format) converts to 1 in Sun=0 format."""
        assert week_0_mon_to_sun(0) == 1

    def test_week_0_mon_to_sun_sunday(self):
        """Test Sunday (6 in Mon=0 format) converts to 0 in Sun=0 format."""
        assert week_0_mon_to_sun(6) == 0

    def test_week_0_mon_to_sun_wednesday(self):
        """Test Wednesday (2 in Mon=0 format) converts to 3 in Sun=0 format."""
        assert week_0_mon_to_sun(2) == 3

    def test_week_0_sun_to_mon_sunday(self):
        """Test Sunday (0 in Sun=0 format) converts to 6 in Mon=0 format."""
        assert week_0_sun_to_mon(0) == 6

    def test_week_0_sun_to_mon_monday(self):
        """Test Monday (1 in Sun=0 format) converts to 0 in Mon=0 format."""
        assert week_0_sun_to_mon(1) == 0

    def test_week_0_sun_to_mon_saturday(self):
        """Test Saturday (6 in Sun=0 format) converts to 5 in Mon=0 format."""
        assert week_0_sun_to_mon(6) == 5

    def test_conversion_roundtrip(self):
        """Test converting Mon->Sun->Mon returns original."""
        for day in range(7):
            assert week_0_sun_to_mon(week_0_mon_to_sun(day)) == day


# ============================================================================
# Schedule Validation Tests
# ============================================================================

class TestValidateScheduleEntry:
    """Tests for schedule entry validation."""

    @pytest.fixture
    def valid_schedule_entry(self):
        """Create a valid schedule entry."""
        return {
            FIELD_INDEX: 0,
            FIELD_DAYSOFWEEK: [1, 1, 1, 1, 1, 0, 0],  # Mon-Fri
            FIELD_INSIDE: True,
            FIELD_OUTSIDE: False,
            FIELD_ENABLED: True,
            FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: 6, FIELD_MINUTE: 0},
            FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: 20, FIELD_MINUTE: 0},
            FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
            FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
        }

    def test_valid_entry_passes(self, valid_schedule_entry):
        """Test valid schedule entry passes validation."""
        assert validate_schedule_entry(valid_schedule_entry) is True

    def test_missing_index_fails(self, valid_schedule_entry):
        """Test entry without index fails validation."""
        del valid_schedule_entry[FIELD_INDEX]
        assert validate_schedule_entry(valid_schedule_entry) is False

    def test_missing_daysofweek_fails(self, valid_schedule_entry):
        """Test entry without daysOfWeek fails validation."""
        del valid_schedule_entry[FIELD_DAYSOFWEEK]
        assert validate_schedule_entry(valid_schedule_entry) is False

    def test_wrong_daysofweek_length_fails(self, valid_schedule_entry):
        """Test entry with wrong daysOfWeek length fails validation."""
        valid_schedule_entry[FIELD_DAYSOFWEEK] = [1, 1, 1]  # Only 3 days
        assert validate_schedule_entry(valid_schedule_entry) is False

    def test_daysofweek_not_list_fails(self, valid_schedule_entry):
        """Test entry with non-list daysOfWeek fails validation."""
        valid_schedule_entry[FIELD_DAYSOFWEEK] = "1111100"
        assert validate_schedule_entry(valid_schedule_entry) is False

    def test_inside_missing_start_time_fails(self, valid_schedule_entry):
        """Test inside entry without start time fails validation."""
        valid_schedule_entry[FIELD_INSIDE] = True
        del valid_schedule_entry[FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX]
        assert validate_schedule_entry(valid_schedule_entry) is False

    def test_inside_missing_end_time_fails(self, valid_schedule_entry):
        """Test inside entry without end time fails validation."""
        valid_schedule_entry[FIELD_INSIDE] = True
        del valid_schedule_entry[FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX]
        assert validate_schedule_entry(valid_schedule_entry) is False

    def test_inside_missing_hour_fails(self, valid_schedule_entry):
        """Test inside entry without hour field fails validation."""
        valid_schedule_entry[FIELD_INSIDE] = True
        del valid_schedule_entry[FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_HOUR]
        assert validate_schedule_entry(valid_schedule_entry) is False

    def test_outside_entry_validates_outside_times(self, valid_schedule_entry):
        """Test outside entry validates outside time fields."""
        valid_schedule_entry[FIELD_INSIDE] = False
        valid_schedule_entry[FIELD_OUTSIDE] = True
        # Missing outside start time
        del valid_schedule_entry[FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX]
        assert validate_schedule_entry(valid_schedule_entry) is False

    def test_disabled_entry_skips_time_validation(self):
        """Test disabled entry doesn't need time fields."""
        entry = {
            FIELD_INDEX: 0,
            FIELD_DAYSOFWEEK: [0, 0, 0, 0, 0, 0, 0],
            FIELD_INSIDE: False,
            FIELD_OUTSIDE: False,
            FIELD_ENABLED: True,
        }
        assert validate_schedule_entry(entry) is True


# ============================================================================
# Schedule Compression Tests
# ============================================================================

class TestCompressSchedule:
    """Tests for schedule compression algorithm."""

    def create_schedule_entry(self, index, days, inside=False, outside=False,
                              in_start=(0, 0), in_end=(0, 0),
                              out_start=(0, 0), out_end=(0, 0)):
        """Helper to create schedule entries."""
        return {
            FIELD_INDEX: index,
            FIELD_DAYSOFWEEK: days,
            FIELD_INSIDE: inside,
            FIELD_OUTSIDE: outside,
            FIELD_ENABLED: True,
            FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {
                FIELD_HOUR: in_start[0], FIELD_MINUTE: in_start[1]
            },
            FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {
                FIELD_HOUR: in_end[0], FIELD_MINUTE: in_end[1]
            },
            FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {
                FIELD_HOUR: out_start[0], FIELD_MINUTE: out_start[1]
            },
            FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {
                FIELD_HOUR: out_end[0], FIELD_MINUTE: out_end[1]
            },
        }

    def test_compress_empty_schedule(self):
        """Test compressing empty schedule returns empty."""
        result = compress_schedule([])
        assert result == []

    def test_compress_single_entry(self):
        """Test compressing single entry preserves it."""
        entry = self.create_schedule_entry(
            0, [1, 1, 1, 1, 1, 0, 0],
            inside=True, in_start=(6, 0), in_end=(20, 0)
        )
        result = compress_schedule([entry])
        assert len(result) == 1
        assert result[0][FIELD_INSIDE] is True
        assert result[0][FIELD_DAYSOFWEEK] == [1, 1, 1, 1, 1, 0, 0]

    def test_compress_combines_same_time_different_days(self):
        """Test combining entries with same time on different days."""
        entries = [
            self.create_schedule_entry(
                0, [1, 0, 0, 0, 0, 0, 0],  # Sunday only
                inside=True, in_start=(8, 0), in_end=(17, 0)
            ),
            self.create_schedule_entry(
                1, [0, 1, 0, 0, 0, 0, 0],  # Monday only
                inside=True, in_start=(8, 0), in_end=(17, 0)
            ),
        ]
        result = compress_schedule(entries)
        assert len(result) == 1
        assert result[0][FIELD_DAYSOFWEEK] == [1, 1, 0, 0, 0, 0, 0]  # Sun + Mon

    def test_compress_merges_overlapping_times(self):
        """Test merging overlapping time periods on same day."""
        entries = [
            self.create_schedule_entry(
                0, [1, 0, 0, 0, 0, 0, 0],  # Sunday
                inside=True, in_start=(6, 0), in_end=(12, 0)
            ),
            self.create_schedule_entry(
                1, [1, 0, 0, 0, 0, 0, 0],  # Sunday (overlapping)
                inside=True, in_start=(10, 0), in_end=(18, 0)
            ),
        ]
        result = compress_schedule(entries)
        assert len(result) == 1
        # Merged to 6:00-18:00
        in_start = result[0][FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX]
        in_end = result[0][FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX]
        assert in_start[FIELD_HOUR] == 6
        assert in_end[FIELD_HOUR] == 18

    def test_compress_keeps_non_overlapping_separate(self):
        """Test non-overlapping times stay separate."""
        entries = [
            self.create_schedule_entry(
                0, [1, 0, 0, 0, 0, 0, 0],  # Sunday
                inside=True, in_start=(6, 0), in_end=(10, 0)
            ),
            self.create_schedule_entry(
                1, [1, 0, 0, 0, 0, 0, 0],  # Sunday
                inside=True, in_start=(14, 0), in_end=(18, 0)
            ),
        ]
        result = compress_schedule(entries)
        assert len(result) == 2

    def test_compress_combines_inside_and_outside(self):
        """Test combining inside and outside entries with same time/days."""
        entries = [
            self.create_schedule_entry(
                0, [1, 1, 0, 0, 0, 0, 0],
                inside=True, in_start=(8, 0), in_end=(17, 0)
            ),
            self.create_schedule_entry(
                1, [1, 1, 0, 0, 0, 0, 0],
                outside=True, out_start=(8, 0), out_end=(17, 0)
            ),
        ]
        result = compress_schedule(entries)
        assert len(result) == 1
        assert result[0][FIELD_INSIDE] is True
        assert result[0][FIELD_OUTSIDE] is True

    def test_compress_swaps_inverted_times(self):
        """Test times are swapped if end < start."""
        entries = [
            self.create_schedule_entry(
                0, [1, 0, 0, 0, 0, 0, 0],
                inside=True, in_start=(18, 0), in_end=(6, 0)  # Inverted
            ),
        ]
        result = compress_schedule(entries)
        assert len(result) == 1
        in_start = result[0][FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX]
        in_end = result[0][FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX]
        assert in_start[FIELD_HOUR] == 6  # Swapped
        assert in_end[FIELD_HOUR] == 18

    def test_compress_assigns_sequential_indices(self):
        """Test compressed entries have sequential indices."""
        entries = [
            self.create_schedule_entry(
                5, [1, 0, 0, 0, 0, 0, 0],
                inside=True, in_start=(6, 0), in_end=(10, 0)
            ),
            self.create_schedule_entry(
                10, [0, 1, 0, 0, 0, 0, 0],
                inside=True, in_start=(14, 0), in_end=(18, 0)
            ),
        ]
        result = compress_schedule(entries)
        assert result[0][FIELD_INDEX] == 0
        assert result[1][FIELD_INDEX] == 1


# ============================================================================
# Schedule Content Key Tests
# ============================================================================

class TestScheduleEntryContentKey:
    """Tests for schedule entry content key generation."""

    def test_same_entries_same_key(self):
        """Test entries with same content produce same key."""
        entry1 = {
            FIELD_INDEX: 0,
            FIELD_DAYSOFWEEK: [1, 1, 1, 1, 1, 0, 0],
            FIELD_INSIDE: True,
            FIELD_OUTSIDE: False,
            FIELD_ENABLED: True,
            FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: 6, FIELD_MINUTE: 0},
            FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: 20, FIELD_MINUTE: 0},
            FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
            FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
        }
        entry2 = deepcopy(entry1)
        entry2[FIELD_INDEX] = 5  # Different index

        assert schedule_entry_content_key(entry1) == schedule_entry_content_key(entry2)

    def test_different_times_different_key(self):
        """Test entries with different times produce different keys."""
        entry1 = {
            FIELD_INDEX: 0,
            FIELD_DAYSOFWEEK: [1, 1, 1, 1, 1, 0, 0],
            FIELD_INSIDE: True,
            FIELD_OUTSIDE: False,
            FIELD_ENABLED: True,
            FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: 6, FIELD_MINUTE: 0},
            FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: 20, FIELD_MINUTE: 0},
        }
        entry2 = deepcopy(entry1)
        entry2[FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX][FIELD_HOUR] = 7  # Different start

        assert schedule_entry_content_key(entry1) != schedule_entry_content_key(entry2)

    def test_different_days_different_key(self):
        """Test entries with different days produce different keys."""
        entry1 = {
            FIELD_INDEX: 0,
            FIELD_DAYSOFWEEK: [1, 1, 1, 1, 1, 0, 0],
            FIELD_INSIDE: True,
        }
        entry2 = deepcopy(entry1)
        entry2[FIELD_DAYSOFWEEK] = [0, 1, 1, 1, 1, 0, 0]  # Different days

        assert schedule_entry_content_key(entry1) != schedule_entry_content_key(entry2)

    def test_different_inside_outside_different_key(self):
        """Test entries with different inside/outside produce different keys."""
        entry1 = {FIELD_INSIDE: True, FIELD_OUTSIDE: False, FIELD_DAYSOFWEEK: [1, 0, 0, 0, 0, 0, 0]}
        entry2 = {FIELD_INSIDE: False, FIELD_OUTSIDE: True, FIELD_DAYSOFWEEK: [1, 0, 0, 0, 0, 0, 0]}

        assert schedule_entry_content_key(entry1) != schedule_entry_content_key(entry2)

    def test_key_handles_missing_fields(self):
        """Test key handles entries with missing optional fields."""
        entry = {
            FIELD_DAYSOFWEEK: [1, 0, 0, 0, 0, 0, 0],
        }
        # Should not raise, uses defaults
        key = schedule_entry_content_key(entry)
        assert key is not None


# ============================================================================
# Schedule Diff Tests
# ============================================================================

class TestComputeScheduleDiff:
    """Tests for schedule diff computation."""

    def create_entry(self, index, days, inside=True, start_hour=8, end_hour=17):
        """Helper to create schedule entries."""
        return {
            FIELD_INDEX: index,
            FIELD_DAYSOFWEEK: days,
            FIELD_INSIDE: inside,
            FIELD_OUTSIDE: False,
            FIELD_ENABLED: True,
            FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: start_hour, FIELD_MINUTE: 0},
            FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: end_hour, FIELD_MINUTE: 0},
            FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
            FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX: {FIELD_HOUR: 0, FIELD_MINUTE: 0},
        }

    def test_no_changes_returns_empty(self):
        """Test identical schedules returns no changes."""
        current = [self.create_entry(0, [1, 0, 0, 0, 0, 0, 0])]
        new = [self.create_entry(0, [1, 0, 0, 0, 0, 0, 0])]

        to_delete, to_add = compute_schedule_diff(current, new)
        assert to_delete == []
        assert to_add == []

    def test_add_new_entry(self):
        """Test adding new entry is detected."""
        current = []
        new = [self.create_entry(0, [1, 0, 0, 0, 0, 0, 0])]

        to_delete, to_add = compute_schedule_diff(current, new)
        assert to_delete == []
        assert len(to_add) == 1

    def test_delete_existing_entry(self):
        """Test removing entry is detected."""
        current = [self.create_entry(0, [1, 0, 0, 0, 0, 0, 0])]
        new = []

        to_delete, to_add = compute_schedule_diff(current, new)
        assert to_delete == [0]  # Index to delete
        assert to_add == []

    def test_modify_entry_detected_as_delete_and_add(self):
        """Test modifying entry is detected as delete + add."""
        current = [self.create_entry(0, [1, 0, 0, 0, 0, 0, 0], start_hour=8)]
        new = [self.create_entry(0, [1, 0, 0, 0, 0, 0, 0], start_hour=9)]  # Different time

        to_delete, to_add = compute_schedule_diff(current, new)
        assert to_delete == [0]
        assert len(to_add) == 1

    def test_ignores_index_differences(self):
        """Test same content at different indices is not a change."""
        current = [self.create_entry(0, [1, 0, 0, 0, 0, 0, 0])]
        new = [self.create_entry(5, [1, 0, 0, 0, 0, 0, 0])]  # Same content, different index

        to_delete, to_add = compute_schedule_diff(current, new)
        assert to_delete == []
        assert to_add == []

    def test_multiple_changes(self):
        """Test multiple additions and deletions."""
        current = [
            self.create_entry(0, [1, 0, 0, 0, 0, 0, 0]),
            self.create_entry(1, [0, 1, 0, 0, 0, 0, 0]),
        ]
        new = [
            self.create_entry(0, [0, 1, 0, 0, 0, 0, 0]),  # Keep Monday
            self.create_entry(1, [0, 0, 1, 0, 0, 0, 0]),  # Add Tuesday
        ]

        to_delete, to_add = compute_schedule_diff(current, new)
        assert len(to_delete) == 1  # Sunday removed
        assert len(to_add) == 1  # Tuesday added


# ============================================================================
# Schedule Template Tests
# ============================================================================

class TestScheduleTemplate:
    """Tests for schedule template."""

    def test_template_has_required_fields(self):
        """Test template has all required fields."""
        assert FIELD_INDEX in schedule_template
        assert FIELD_DAYSOFWEEK in schedule_template
        assert FIELD_INSIDE in schedule_template
        assert FIELD_OUTSIDE in schedule_template
        assert FIELD_ENABLED in schedule_template

    def test_template_has_time_fields(self):
        """Test template has all time fields."""
        assert FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX in schedule_template
        assert FIELD_INSIDE_PREFIX + FIELD_END_TIME_SUFFIX in schedule_template
        assert FIELD_OUTSIDE_PREFIX + FIELD_START_TIME_SUFFIX in schedule_template
        assert FIELD_OUTSIDE_PREFIX + FIELD_END_TIME_SUFFIX in schedule_template

    def test_template_defaults(self):
        """Test template default values."""
        assert schedule_template[FIELD_INDEX] == 0
        assert schedule_template[FIELD_DAYSOFWEEK] == [0, 0, 0, 0, 0, 0, 0]
        assert schedule_template[FIELD_INSIDE] is False
        assert schedule_template[FIELD_OUTSIDE] is False
        assert schedule_template[FIELD_ENABLED] is True

    def test_template_time_defaults(self):
        """Test template time field defaults."""
        in_start = schedule_template[FIELD_INSIDE_PREFIX + FIELD_START_TIME_SUFFIX]
        assert in_start[FIELD_HOUR] == 0
        assert in_start[FIELD_MINUTE] == 0
