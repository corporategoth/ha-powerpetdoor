/**
 * Copyright (c) 2025 Preston Elder
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 *
 * Power Pet Door Schedule Card v1.15.2
 * A custom Lovelace card for viewing and editing Power Pet Door schedules.
 */

const DAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];

// How the end of the day is spelled in Home Assistant's schedule shape.
//
// The device's end-of-day is 24:00, which <input type="time"> and HA's HH:MM
// format cannot express, so midnight stands in for it. The rule is
// positional and applies throughout: midnight OPENING a window is the day's
// first minute, midnight CLOSING one is its last.
//
// 23:59 is deliberately not special. The device is measured to accept and
// preserve 24:00, so there is no need to read a literal 23:59 as anything
// other than 23:59 - and a window that really does end there really does
// leave the sensor off for that final minute.
const ALL_DAY_END = '00:00';
const DAY_LABELS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const DAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// ---------------------------------------------------------------------------
// Translations
//
// Home Assistant's own translation machinery covers integrations, not custom
// cards: there is no `strings.json` a card can register, and `hass.localize`
// only resolves keys HA itself shipped. So a card that wants to be
// translatable has to carry its own catalogue, which is what this is.
//
// English lives here as the fallback, so a missing language renders English
// rather than a raw key. Add a language by adding a key to STRINGS; every
// entry it omits falls through to `en`.
//
// scripts/check_translations.py reads this object and fails the build on a
// `t()` call whose key is missing, or on user-facing prose that never
// entered it.
// ---------------------------------------------------------------------------

const STRINGS = {
  en: {
    no_entity: 'Please define an entity',
    load_failed: 'Failed to load schedule',
    save_failed: 'Failed to save schedule',
    inside_sensor: 'Inside Sensor',
    outside_sensor: 'Outside Sensor',
    inside_short: 'Inside',
    outside_short: 'Outside',
    always_active: 'Active 24/7 (no schedule set)',
    no_windows: 'No window is open for this sensor',
    active: 'Active',
    inactive: 'Inactive',
    am: 'AM',
    pm: 'PM',
    am_short: 'a',
    pm_short: 'p',
    summary: '{slots} time slot{slots_plural} across {days} day{days_plural}',
    schedule_entity: 'Schedule Entity',
    select_entity: 'Select a schedule entity...',
    slot_color: 'Slot Color',
    slot_color_hint: '(time slots)',
    active_slot_color: 'Active Slot Color',
    active_slot_color_hint: '(currently active time)',
    removal_color: 'Removal Color',
    removal_color_hint: '(when shrinking slots)',
    color_placeholder: 'CSS color or variable',
    color_swatch: 'swatch',
    sensor: 'Sensor',
    saved: 'Schedule saved',
    to: 'to',
    active_now: 'active now',
    add_window: 'Add a window to',
    loading: 'Loading schedule...',
    hint: 'Click or drag to create. Drag edges to resize. Click slot to edit. Click day to copy to another day.',
    hint_readonly: 'You have read-only access to this schedule.',
    timers_disabled:
      'Schedules are switched off on the door, so these windows are not being applied and both sensors stay live. Turn on the Schedule enabled switch to use them.',
    reload: 'Reload from device',
    from_label: 'From:',
    to_label: 'To:',
    delete: 'Delete',
    cancel: 'Cancel',
    save: 'Save',
    reset: 'Reset',
    end_before_start:
      'That window does not cover any time. The end must be later than the start, and the door cannot schedule past midnight in one window - use 00:00 as the end to run to the end of the day, then add a second window on the next day.',
    new_slot: 'New Time Slot',
    edit_slot: 'Edit Time Slot',
    copy_from: 'Copy from {sensor}',
    copy_from_confirm:
      'Replace this schedule with the one from {sensor}? The windows currently shown will be lost.',
    copy_day: 'Copy {day} to other days',
    copy_day_title: 'Copy {day} to',
    copy_day_confirm: 'Copy',
    copy_day_none: 'Choose at least one day.',
    select_all: 'All',
    select_none: 'None',
  },
};

/**
 * Look up `key` for the user's language, falling back to English.
 *
 * `replacements` are substituted as `{name}`. Never throws: an unknown key
 * returns the key itself, which is visible in the UI but does not blank the
 * card the way an exception in a render path would.
 */
function t(hass, key, replacements) {
  const language = (hass && hass.language) || 'en';
  const table = STRINGS[language] || {};
  let text = table[key] || STRINGS.en[key] || key;
  if (replacements) {
    for (const [name, value] of Object.entries(replacements)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

// Default colors
const DEFAULT_SLOT_COLOR = 'var(--primary-color, #03a9f4)';
const DEFAULT_ACTIVE_SLOT_COLOR = 'var(--warning-color, #ff9800)';
const DEFAULT_REMOVAL_COLOR = 'var(--error-color, #f44336)';

// ---------------------------------------------------------------------------
// Interpolation safety
//
// The card builds its DOM with `innerHTML` on template literals, so every
// interpolated value is parsed as HTML. Most are numbers this file computed
// and are safe by construction; these two helpers exist for the values that
// are NOT ours - an error string that carries the door's own words, and an
// entity's name or id.
//
// The threat model in .claude/CLAUDE.md states the rule directly: the card
// renders device-supplied text, and the door is a cheap embedded device
// that has been observed to send malformed frames (issue #16).
// ---------------------------------------------------------------------------

/** Escape a value for use as HTML text or inside a double-quoted attribute. */
function escapeHtml(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * A colour safe to interpolate into a `<style>` block.
 *
 * escapeHtml is no use here: a style block is CDATA, so `&lt;` is NOT
 * decoded back to `<` and the escaping would merely corrupt the colour
 * while `</style>` still ended the block. The only defence is to refuse the
 * characters a colour never contains - so anything outside the CSS colour
 * alphabet falls back to the default rather than reaching the stylesheet.
 */
function cssColor(value, fallback) {
  const text = String(value === null || value === undefined ? '' : value).trim();
  return text && /^[#a-zA-Z0-9(),.%\s_-]+$/.test(text) ? text : fallback;
}

class PowerPetDoorScheduleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
    this._hass = null;
    this._schedule = {};
    this._kind = null;
    // The door's master switch. Assumed on until the API says otherwise,
    // so a card that never loaded does not accuse the user of a setting
    // they have not made.
    this._timersEnabled = true;
    this._loading = true;
    this._error = null;
    this._expanded = false;
    this._editingSlot = null;
    this._isNewSlot = false; // Track if editing a newly created slot
    this._dialogError = null; // Why the last Save was refused, if it was

    // Drag state
    this._isDragging = false;
    this._dragMoved = false;
    this._materialised = false;
    this._dragType = null; // 'create', 'resize-top', 'resize-bottom'
    this._dragDay = null;
    this._dragStartMinutes = null;
    this._dragCurrentMinutes = null;
    this._dragSlotIndex = null;
    this._dragOriginalSlot = null;
    this._dragMergeWith = null;
    this._dragDoomed = [];
    this._counterpart = null;
    this._copyingDay = null;
    this._confirmCopyFrom = false;
    this._columnRects = {}; // Store rects for all columns

    // Current time tracking
    this._currentTimeInterval = null;

    // Bind methods
    this._handleMouseMove = this._handleMouseMove.bind(this);
    this._handleMouseUp = this._handleMouseUp.bind(this);
    this._updateCurrentTime = this._updateCurrentTime.bind(this);
  }

  connectedCallback() {
    // Start current time updates when expanded
    if (this._expanded) {
      this._startCurrentTimeUpdates();
    }
  }

  disconnectedCallback() {
    this._stopCurrentTimeUpdates();
    // A drag adds listeners to `document`, not to this element, so removing
    // the card mid-drag (switching dashboard views, a config change) left
    // them attached for the life of the page - pinning the card and its
    // shadow DOM, and letting the next mouseup ANYWHERE run _handleMouseUp
    // on a detached card, which for a resize writes a schedule to the door
    // the user has already navigated away from.
    this._releaseDragListeners();
    this._isDragging = false;
  }

  _releaseDragListeners() {
    document.removeEventListener('mousemove', this._handleMouseMove);
    document.removeEventListener('mouseup', this._handleMouseUp);
  }

  _startCurrentTimeUpdates() {
    if (!this._currentTimeInterval) {
      this._updateCurrentTime();
      this._currentTimeInterval = setInterval(this._updateCurrentTime, 60000); // Update every minute
    }
  }

  _stopCurrentTimeUpdates() {
    if (this._currentTimeInterval) {
      clearInterval(this._currentTimeInterval);
      this._currentTimeInterval = null;
    }
  }

  _updateCurrentTime() {
    const timeLine = this.shadowRoot?.querySelector('.current-time-line');
    const now = new Date();
    const minutes = now.getHours() * 60 + now.getMinutes();
    const pct = (minutes / 1440) * 100;

    if (timeLine) {
      timeLine.style.top = `${pct}%`;
    }

    // Update active slot highlighting
    this._updateActiveSlotHighlight();
  }

  _updateActiveSlotHighlight() {
    const now = new Date();
    const currentDay = DAYS[now.getDay()];
    const currentMinutes = now.getHours() * 60 + now.getMinutes();

    this.shadowRoot?.querySelectorAll('.time-slot').forEach(slot => {
      slot.classList.remove('active-now');
    });

    // _getEffectiveSchedule, not _schedule: the grid renders the implied
    // all-day bars for a door with no schedule, and highlighting read from
    // a different source meant those bars were never highlighted at all -
    // contradicting the documented red-line behaviour.
    const daySlots = this._getEffectiveSchedule()[currentDay] || [];
    daySlots.forEach((slot, index) => {
      if (this._slotCovers(slot, currentMinutes)) {
        const slotEl = this.shadowRoot?.querySelector(
          `.time-slot[data-day="${currentDay}"][data-index="${index}"]`
        );
        if (slotEl) {
          slotEl.classList.add('active-now');
        }
      }
    });
  }

  static getConfigElement() {
    return document.createElement('powerpetdoor-schedule-card-editor');
  }

  static getStubConfig() {
    return { entity: '' };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error(t(this._hass, 'no_entity'));
    }
    // Home Assistant REUSES the element when only the config changed - the
    // card editor's live preview does it on every keystroke. Without
    // discarding the loaded state, pointing a card at the other sensor left
    // the previous sensor's schedule and title on screen, welded to the new
    // entity's on/off state, and nothing ever refetched: `set hass` only
    // reloads when the state OBJECT changes, which it does not for an
    // entity that was already in `states`.
    const changedEntity = this._config.entity && this._config.entity !== config.entity;
    this._config = config;
    if (changedEntity) {
      this._schedule = {};
      this._kind = null;
      this._timersEnabled = true;
      this._error = null;
      this._loading = true;
      this._editingSlot = null;
      this._isNewSlot = false;
      this._materialised = false;
      this._loadSchedule();
      return;
    }
    this.render();
  }

  _getSlotColor() {
    return cssColor(this._config.slot_color, DEFAULT_SLOT_COLOR);
  }

  _getActiveSlotColor() {
    return cssColor(this._config.active_slot_color, DEFAULT_ACTIVE_SLOT_COLOR);
  }

  _getRemovalColor() {
    return cssColor(this._config.removal_color, DEFAULT_REMOVAL_COLOR);
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Only reload schedule if entity changed or first load
    if (!oldHass || oldHass.states[this._config.entity] !== hass.states[this._config.entity]) {
      if (this._config.entity && !this._isDragging && !this._editingSlot) {
        this._loadSchedule();
      }
    }
  }

  async _loadSchedule() {
    if (!this._hass || !this._config.entity) return;

    // Two state changes in quick succession start two loads, and nothing
    // says the first to be sent is the first to come back. Whichever
    // resolved last used to win, so a stale reply could overwrite a fresh
    // one and leave the card showing a schedule the door no longer has -
    // the same symptom that made changing the card's entity look broken.
    // Only the most recently STARTED load is allowed to publish.
    const token = (this._loadToken = (this._loadToken || 0) + 1);

    let schedule;
    // `undefined` means "leave it alone": the attribute fallback below can
    // supply a schedule but never a kind, and clearing it there would drop
    // the card's title back to the generic "Sensor" on a transient failure.
    let kind;
    // Same "leave it alone" rule: the attribute fallback cannot supply it.
    let timersEnabled;
    // Same again: the attribute fallback cannot name the other sensor, and
    // forgetting it there would hide the copy button on a transient failure.
    let counterpart;
    let error = null;
    try {
      const result = await this._hass.callWS({
        type: 'powerpetdoor/schedule/get',
        entity_id: this._config.entity,
      });
      schedule = result.schedule || {};
      kind = result.kind || null;
      timersEnabled = result.timers_enabled !== false;
      counterpart = result.counterpart || null;
    } catch (err) {
      // Fallback to entity state attributes
      const state = this._hass.states[this._config.entity];
      if (state && state.attributes && state.attributes.schedule) {
        schedule = JSON.parse(JSON.stringify(state.attributes.schedule));
      } else {
        error = err.message || t(this._hass, 'load_failed');
      }
    }

    if (token !== this._loadToken) return;

    if (schedule !== undefined) this._schedule = schedule;
    if (kind !== undefined) this._kind = kind;
    if (timersEnabled !== undefined) this._timersEnabled = timersEnabled;
    if (counterpart !== undefined) this._counterpart = counterpart;
    this._error = error;
    this._loading = false;
    this.render();
  }

  /** The other sensor's label, for the copy button. */
  _counterpartLabel() {
    return t(this._hass, this._kind === 'inside' ? 'outside_short' : 'inside_short');
  }

  /**
   * Replace this sensor's schedule with the other sensor's.
   *
   * Read fresh over the WebSocket rather than from anything cached: the
   * other sensor may have been edited in another tab, or by an automation,
   * since this card loaded, and copying a stale view would quietly undo
   * that.
   */
  async _copyFromCounterpart() {
    if (!this._hass || !this._counterpart) return;
    try {
      const result = await this._hass.callWS({
        type: 'powerpetdoor/schedule/get',
        entity_id: this._counterpart,
      });
      this._schedule = JSON.parse(JSON.stringify(result.schedule || {}));
    } catch (err) {
      this._notify(`${t(this._hass, 'load_failed')}: ${err.message || err}`);
      return;
    }
    // Deliberately not `_materialised`: this IS a schedule, so the card is
    // no longer describing a door with none.
    this._materialised = false;
    await this._saveSchedule();
    this.render();
  }

  /**
   * Copy one day's windows onto other days, replacing whatever they had.
   *
   * Replace rather than merge: "copy Monday to Tuesday" means Tuesday
   * looks like Monday. Merging would make the button non-idempotent -
   * pressing it twice would give a different answer from pressing it once.
   */
  async _copyDayTo(fromDay, toDays) {
    const source = this._schedule[fromDay] || [];
    for (const day of toDays) {
      if (day === fromDay) continue;
      this._schedule[day] = source.map((slot) => ({ ...slot }));
    }
    this._materialised = false;
    await this._saveSchedule();
    this.render();
  }

  async _saveSchedule() {
    if (!this._hass || !this._config.entity) return;

    // Before the await, not after. `_materialised` records that Cancel
    // still has an unscheduled door to restore; once the schedule is on its
    // way to the door there is nothing left to undo. Clearing it after the
    // round trip left a window in which opening a second dialog and
    // cancelling wiped `_schedule` back to {}, and the card then reported
    // "Active 24/7 (no schedule set)" for a door that had just been given
    // one.
    this._materialised = false;

    try {
      await this._hass.callWS({
        type: 'powerpetdoor/schedule/update',
        entity_id: this._config.entity,
        schedule: this._schedule,
      });
      this._notify(t(this._hass, 'saved'));
    } catch (err) {
      // Home Assistant's own toast, not alert(). alert() blocks the whole
      // frontend thread, renders as a bare OS dialog in the Companion App,
      // and - once a user ticks the browser's "prevent additional dialogs",
      // which they will after seeing two - swallows every later failure
      // entirely, so edits revert with no explanation at all.
      this._notify(`${t(this._hass, 'save_failed')}: ${err.message || err}`);
      this._loadSchedule(); // Reload on failure
    }
  }

  /** Raise a Home Assistant toast. */
  _notify(message) {
    this.dispatchEvent(new CustomEvent('hass-notification', {
      detail: { message },
      bubbles: true,
      composed: true,
    }));
  }

  /**
   * A spoken description of one window: "Monday, 6:00 AM to 8:00 PM".
   *
   * The grid shows only the start time, and the end time lived in `title`,
   * which never reaches a touch user and is not reliably announced. Without
   * this a screen-reader user could not read the schedule at all.
   */
  _slotLabel(day, slot) {
    const index = DAYS.indexOf(day);
    const label = index >= 0 ? DAY_LABELS[index] : day;
    // On THIS day, not merely at this time. The check took `day` and threw
    // it away, so on a Wednesday afternoon every one of the seven days'
    // windows announced itself as "active now" - while the visual
    // highlight, which does filter by day, marked only Wednesday's. A
    // screen-reader user was told the opposite of what the screen showed.
    const now = new Date();
    const active =
      DAYS[now.getDay()] === day &&
      this._slotCovers(slot, now.getHours() * 60 + now.getMinutes());
    const when = `${label}, ${this._formatTime(slot.from)} ${t(this._hass, 'to')} ${this._formatTime(slot.to)}`;
    return active ? `${when}, ${t(this._hass, 'active_now')}` : when;
  }

  _getSensorType() {
    // From the API's `kind`, not by sniffing the entity id for the word
    // "inside": a door named "Inside Porch" made the OUTSIDE schedule card
    // announce itself as the inside sensor, so the user edited the wrong
    // sensor's schedule believing it was the other.
    if (this._kind === 'inside') return t(this._hass, 'inside_sensor');
    if (this._kind === 'outside') return t(this._hass, 'outside_sensor');
    return t(this._hass, 'sensor');
  }

  _isActive() {
    const state = this._hass?.states[this._config.entity];
    return state?.state === 'on';
  }

  _hasSchedule() {
    return Object.keys(this._schedule).length > 0 &&
           Object.values(this._schedule).some(slots => slots && slots.length > 0);
  }

  _getEffectiveSchedule() {
    // If no schedule is set, the sensor is active 24/7.
    //
    // Spelled 00:00-23:59, which is how the device's own factory schedule
    // spells it, and NOT 00:00-24:00 ("24:00" is not a valid time: <input
    // type="time"> refuses it, so the dialog's To field rendered blank and
    // Save was a dead button) nor 00:00-00:00 (00:00 is midnight at the
    // START of a day, so as an end it reads as a window finishing before it
    // begins - which the backend now refuses). This is the out-of-box
    // state, so getting it wrong made the FIRST edit any new user tried
    // fail.
    if (!this._hasSchedule()) {
      const allDay = { from: '00:00', to: ALL_DAY_END };
      return {
        sunday: [allDay],
        monday: [allDay],
        tuesday: [allDay],
        wednesday: [allDay],
        thursday: [allDay],
        friday: [allDay],
        saturday: [allDay],
      };
    }
    return this._schedule;
  }

  /**
   * Turn the implied all-day schedule into real windows before editing one.
   *
   * A door with no schedule is enabled 24/7 and the grid draws that as seven
   * all-day bars. Editing one of those has to write the other six days out
   * too: saving a single window while the rest stayed absent would switch
   * the sensor off for every day the user never touched.
   *
   * Once a real schedule exists there is nothing to materialise -
   * `_getEffectiveSchedule()` returns `_schedule` itself, so a day missing
   * from it has no implied window to copy from either.
   */
  /**
   * Turn the implied "always on" schedule into real entries.
   *
   * A door with no schedule is on 24/7, and the grid draws seven implied
   * all-day bars for it. Saving is wholesale - `apply_schedule` replaces
   * this sensor's entries with exactly what the card sends - so a payload
   * containing only the day the user touched switches the sensor OFF on
   * the other six. That is the out-of-box path: every new user's first
   * edit did it.
   *
   * `except` is the day being edited. Giving that day an all-day entry too
   * is the opposite bug: the door ORs its entries, so the user's new
   * restriction is swallowed by an all-day window sitting underneath it and
   * nothing changes. Both failures are silent, and the card previously had
   * one on the mouse path and the other on the keyboard path.
   *
   * Returns true if it materialised, so a Cancel can undo it.
   */
  _ensureRealSlotExists(except = null) {
    if (this._hasSchedule()) return false;

    // See _getEffectiveSchedule for why the end is 23:59.
    const allDay = { from: '00:00', to: ALL_DAY_END };
    this._schedule = {};
    for (const day of DAYS) {
      if (day !== except) this._schedule[day] = [{ ...allDay }];
    }
    return true;
  }

  _getScheduleSummary() {
    if (!this._hasSchedule()) return t(this._hass, 'always_active');

    let totalSlots = 0;
    let activeDays = 0;
    for (const slots of Object.values(this._schedule)) {
      if (slots && slots.length > 0) {
        totalSlots += slots.length;
        activeDays++;
      }
    }
    return t(this._hass, 'summary', {
      slots: totalSlots,
      slots_plural: totalSlots !== 1 ? 's' : '',
      days: activeDays,
      days_plural: activeDays !== 1 ? 's' : '',
    });
  }

  _formatTime(time) {
    if (!time) return '';
    const [hours, minutes] = time.split(':').map(Number);
    // Translated, because a 12-hour clock is not universal and neither are
    // these two markers. They reach the user through every window's
    // aria-label and the edit dialog's title.
    const ampm = hours >= 12 ? t(this._hass, 'pm') : t(this._hass, 'am');
    const h = hours % 12 || 12;
    return `${h}:${minutes.toString().padStart(2, '0')} ${ampm}`;
  }

  _formatTimeShort(time) {
    if (!time) return '';
    const [hours, minutes] = time.split(':').map(Number);
    // The compact markers the grid uses, translated for the same reason as
    // the long ones. Lower case is not universal either.
    const ampm = hours >= 12 ? t(this._hass, 'pm_short') : t(this._hass, 'am_short');
    const h = hours % 12 || 12;
    return `${h}:${minutes.toString().padStart(2, '0')}${ampm}`;
  }

  _parseTimeToMinutes(time) {
    if (!time) return 0;
    const [hours, minutes] = time.split(':').map(Number);
    return hours * 60 + minutes;
  }

  /**
   * A window END as text, where 1440 is the end of the day.
   *
   * `_minutesToTime` clamps to 23:59 because that is the last real minute,
   * which is right for a start and wrong for an end: a window dragged or
   * clicked to the bottom of the column means "to the end of the day", and
   * spelled 23:59 it is a minute short of it. Midnight is how Home
   * Assistant's HH:MM shape says 24:00.
   */
  _endMinutesToTime(minutes) {
    return minutes >= 1440 ? ALL_DAY_END : this._minutesToTime(minutes);
  }

  _minutesToTime(minutes) {
    const clamped = Math.max(0, Math.min(1439, minutes));
    const h = Math.floor(clamped / 60);
    const m = clamped % 60;
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
  }

  _roundToInterval(minutes, interval = 15) {
    return Math.round(minutes / interval) * interval;
  }

  /**
   * Minutes a window spans, treating end <= start as running past midnight.
   *
   * The backend produces these deliberately: `start == end` is the door's
   * own spelling of all-day, and an overnight window ("let the cat out at
   * 22:00, in at 06:00") is stored exactly that way. Subtracting naively
   * gave a negative height that clamped to a 14px stub pinned at the start
   * time, so an all-day or overnight window looked like a sliver.
   */
  /**
   * A window's end in minutes, with 23:59 meaning the end of the day.
   *
   * The final minute is INSIDE the window: the device's factory schedule is
   * 00:00-23:59 on all seven days, plainly meaning "always", so reading the
   * end as exclusive switches the sensor off for exactly the minute 23:59.
   * `schedule.py::_entry_spans` says the same thing on the Python side, and
   * an all-day window is now spelled this way - so without this, a door
   * with no schedule at all would have reported itself shut every night at
   * 23:59.
   */
  _slotEndMinutes(slot) {
    // Midnight is positional: opening a window it is the day's first minute,
    // closing one it is the day's last. That is the only end that reaches
    // past 23:59, because Home Assistant's HH:MM shape cannot write the
    // device's 24:00.
    const end = this._parseTimeToMinutes(slot.to);
    return end === 0 ? 1440 : end;
  }

  _slotSpanMinutes(slot) {
    const start = this._parseTimeToMinutes(slot.from);
    const end = this._slotEndMinutes(slot);
    // No wrapping. Measured against firmware 1.7.18: the schedule engine is
    // `start <= now < end`, so a window whose end does not exceed its start
    // matches no minute at all - not later that day, and not the next
    // morning. The door stores it and never acts on it.
    return end <= start ? 0 : end - start;
  }

  /** Whether `minutes` falls inside a window. Windows cannot cross midnight. */
  _slotCovers(slot, minutes) {
    const start = this._parseTimeToMinutes(slot.from);
    const end = this._slotEndMinutes(slot);
    return minutes >= start && minutes < end;
  }

  /**
   * Where a window sits in its column, as a percentage.
   *
   * One rectangle per window, because a window cannot cross midnight: the
   * device has no way to express "tomorrow", the write path refuses an end
   * earlier than its start, and `to_ha_format` splits anything a door
   * reports into separate same-day windows before the card ever sees it.
   */
  /**
   * What a resize drag should do about the OTHER windows in its column.
   *
   * Dragging an edge towards a neighbour has three outcomes, and which one
   * you get depends only on where the pointer is relative to that
   * neighbour:
   *
   * - short of it: nothing, the edge follows the pointer;
   * - inside it: the edge stops at the neighbour's near border, because
   *   the two are about to become one window and drawing the dragged one
   *   crossing into the other says nothing true. Released here, they merge;
   * - past its far border: the neighbour is wholly covered, so the edge
   *   follows the pointer again and the neighbour is marked doomed - it is
   *   drawn in the removal colour and is gone once the drag is applied.
   *
   * Walking outwards in order matters: passing one neighbour entirely can
   * put the pointer inside the next one, and that one then stops the edge.
   *
   * @returns {{minutes: number, mergeWith: number|null, doomed: number[]}}
   *   `minutes` is where the edge should be DRAWN; `mergeWith` is the index
   *   the released drag should absorb; `doomed` are indices it removes.
   */
  _resolveResize(day, index, edge, pointerMinutes) {
    const slots = this._schedule[day] || [];
    const own = slots[index];
    if (!own) return { minutes: pointerMinutes, mergeWith: null, doomed: [] };

    const ownStart = this._parseTimeToMinutes(own.from);
    const ownEnd = this._slotEndMinutes(own);
    const doomed = [];

    // Neighbours in the direction of travel, nearest first.
    const ordered = slots
      .map((slot, at) => ({ at, start: this._parseTimeToMinutes(slot.from), end: this._slotEndMinutes(slot) }))
      .filter((n) => n.at !== index)
      .filter((n) => (edge === 'bottom' ? n.start >= ownStart : n.end <= ownEnd))
      .sort((a, b) => (edge === 'bottom' ? a.start - b.start : b.end - a.end));

    for (const neighbour of ordered) {
      if (edge === 'bottom') {
        if (pointerMinutes <= neighbour.start) break;
        if (pointerMinutes < neighbour.end) {
          return { minutes: neighbour.start, mergeWith: neighbour.at, doomed };
        }
      } else {
        if (pointerMinutes >= neighbour.end) break;
        if (pointerMinutes > neighbour.start) {
          return { minutes: neighbour.end, mergeWith: neighbour.at, doomed };
        }
      }
      doomed.push(neighbour.at);
    }
    return { minutes: pointerMinutes, mergeWith: null, doomed };
  }

  _getSlotStyle(slot) {
    const start = this._parseTimeToMinutes(slot.from);
    const top = (start / 1440) * 100;
    // The 1.5% floor keeps a very short window clickable; see the comment
    // on .time-slot's min-height.
    const height = Math.max((this._slotSpanMinutes(slot) / 1440) * 100, 1.5);
    return `top: ${top}%; height: ${height}%;`;
  }

  _yToMinutes(y, rect) {
    const relY = Math.max(0, Math.min(y - rect.top, rect.height));
    return Math.floor((relY / rect.height) * 1440);
  }

  _handleHeaderClick() {
    this._expanded = !this._expanded;
    this.render();

    if (this._expanded) {
      this._startCurrentTimeUpdates();
    } else {
      this._stopCurrentTimeUpdates();
    }
  }

  _handleSlotClick(day, index, event) {
    event.stopPropagation();
    event.preventDefault();

    // Don't open dialog if we were dragging
    if (this._isDragging) return;

    // Materialize implied slots into real schedule if needed. Recorded so
    // Cancel can undo it: a user who opens the editor on an unscheduled
    // door and backs out must leave it unscheduled.
    this._materialised = this._ensureRealSlotExists() || this._materialised;

    this._editingSlot = { day, index };
    this._isNewSlot = false;
    this.render();
  }

  _handleDayMouseDown(day, event) {
    this._dragMoved = false;
    // Ignore if clicking on a slot (handled separately)
    if (event.target.closest('.time-slot')) return;

    event.preventDefault();

    const column = event.currentTarget;
    const rect = column.getBoundingClientRect();
    this._columnRects[day] = rect;

    const minutes = this._roundToInterval(this._yToMinutes(event.clientY, rect));

    this._isDragging = true;
    this._dragType = 'create';
    this._dragDay = day;
    this._dragStartMinutes = minutes;
    this._dragCurrentMinutes = minutes;

    document.addEventListener('mousemove', this._handleMouseMove);
    document.addEventListener('mouseup', this._handleMouseUp);

    this._showDragPreview(day);
  }

  _handleSlotEdgeMouseDown(day, index, edge, event) {
    this._dragMoved = false;
    event.stopPropagation();
    event.preventDefault();

    const column = this.shadowRoot.querySelector(`.day-column[data-day="${day}"]`);
    if (!column) return;

    const rect = column.getBoundingClientRect();
    this._columnRects[day] = rect;

    // Materialize implied slots into real schedule if needed. Recorded so
    // Cancel can undo it: a user who opens the editor on an unscheduled
    // door and backs out must leave it unscheduled.
    this._materialised = this._ensureRealSlotExists() || this._materialised;

    const slot = this._schedule[day][index];

    this._isDragging = true;
    this._dragType = edge === 'top' ? 'resize-top' : 'resize-bottom';
    this._dragDay = day;
    this._dragSlotIndex = index;
    this._dragOriginalSlot = { ...slot };
    this._dragStartMinutes = edge === 'top'
      ? this._parseTimeToMinutes(slot.from)
      : this._parseTimeToMinutes(slot.to);
    this._dragCurrentMinutes = this._dragStartMinutes;

    document.addEventListener('mousemove', this._handleMouseMove);
    document.addEventListener('mouseup', this._handleMouseUp);

    this._showDragPreview(day);
  }

  _handleMouseMove(event) {
    if (!this._isDragging) return;

    const rect = this._columnRects[this._dragDay];
    if (!rect) return;

    const minutes = this._roundToInterval(this._yToMinutes(event.clientY, rect));
    // Distinguishes a drag from a click that happened to land on an 8px
    // resize edge; see _handleMouseUp.
    if (minutes !== this._dragStartMinutes) this._dragMoved = true;

    if (this._dragType === 'create') {
      this._dragCurrentMinutes = minutes;
    } else if (this._dragType === 'resize-top') {
      const slot = this._schedule[this._dragDay][this._dragSlotIndex];
      const bottomMinutes = this._slotEndMinutes(slot);
      const resolved = this._resolveResize(this._dragDay, this._dragSlotIndex, 'top', minutes);
      this._dragMergeWith = resolved.mergeWith;
      this._dragDoomed = resolved.doomed;
      this._dragCurrentMinutes = Math.min(resolved.minutes, bottomMinutes - 15);
    } else if (this._dragType === 'resize-bottom') {
      const slot = this._schedule[this._dragDay][this._dragSlotIndex];
      const topMinutes = this._parseTimeToMinutes(slot.from);
      const resolved = this._resolveResize(this._dragDay, this._dragSlotIndex, 'bottom', minutes);
      this._dragMergeWith = resolved.mergeWith;
      this._dragDoomed = resolved.doomed;
      this._dragCurrentMinutes = Math.max(resolved.minutes, topMinutes + 15);
    }

    this._updateDragPreview();
  }

  _handleMouseUp(_event) {
    this._releaseDragListeners();

    if (!this._isDragging) return;

    // A slot under ~2 hours is ~14px tall and its two 8px resize edges
    // leave a 6px band in the middle, so most clicks aimed at a slot land
    // on an edge instead. That started a resize, and the immediate mouseup
    // wrote the slot back unchanged - a WebSocket round trip and a
    // schedule read on the door - then re-rendered, which destroyed the
    // node before the pending click could reach _handleSlotClick. The user
    // clicked their window and nothing happened, every time.
    //
    // A resize that never moved is a click. Drop it and let the click
    // through, rather than saving an unchanged slot.
    if (this._dragType !== 'create' && !this._dragMoved) {
      this._hideDragPreview(this._dragDay);
      this._isDragging = false;
      this._dragType = null;
      this._dragDay = null;
      this._dragSlotIndex = null;
      return;
    }

    const day = this._dragDay;
    const startMin = this._dragStartMinutes;
    const currentMin = this._dragCurrentMinutes;

    if (this._dragType === 'create') {
      const topMin = Math.min(startMin, currentMin);
      const bottomMin = Math.max(startMin, currentMin);
      const duration = bottomMin - topMin;

      // If barely dragged (less than 15 min), create a 15-min slot (click behavior)
      let finalStartMin = topMin;
      let finalEndMin = bottomMin;

      if (duration < 15) {
        // Click to create: use the start position, add 15 minutes.
        //
        // The start is pulled back off the bottom of the column first. A
        // click on its last pixel rounds to 1440, and 1440 for both ends
        // becomes 23:59-23:59 once `_minutesToTime` clamps them - which is
        // start == end, the door's spelling of ALL DAY. The user asked for
        // a quarter of an hour, got the sensor enabled around the clock,
        // and saw it drawn as a sliver at the bottom of the day.
        finalStartMin = Math.min(this._roundToInterval(startMin), 1425);
        finalEndMin = finalStartMin + 15;
      }

      const startTime = this._minutesToTime(finalStartMin);
      const endTime = this._endMinutesToTime(finalEndMin);

      // Materialise the OTHER six days before adding this window, or the
      // save - which is wholesale - switches the sensor off on every day
      // the user never touched. `day` is excluded because an all-day entry
      // beneath the new window would be OR'd with it and swallow the
      // restriction entirely.
      this._materialised = this._ensureRealSlotExists(day);

      if (!this._schedule[day]) {
        this._schedule[day] = [];
      }

      const created = { from: startTime, to: endTime };
      this._schedule[day].push(created);
      this._schedule[day].sort((a, b) =>
        this._parseTimeToMinutes(a.from) - this._parseTimeToMinutes(b.from)
      );

      // indexOf on the object we just made, NOT findIndex by value. A drag
      // that rounds into the same 15-minute bucket as an existing window
      // produces two value-identical slots, and findIndex returned the
      // FIRST - so the dialog then edited the pre-existing window and left
      // the newly created duplicate behind untouched.
      const sortedIndex = this._schedule[day].indexOf(created);

      // Reset drag state BEFORE opening dialog
      this._isDragging = false;
      this._dragType = null;
      this._dragDay = null;
      this._dragStartMinutes = null;
      this._dragCurrentMinutes = null;
      this._dragSlotIndex = null;
      this._dragOriginalSlot = null;
    this._dragMergeWith = null;
    this._dragDoomed = [];

      // Open edit dialog for the new slot
      this._editingSlot = { day, index: sortedIndex };
      this._isNewSlot = true;
      this.render();
      return;

    } else if (this._dragType === 'resize-top' || this._dragType === 'resize-bottom') {
      const slots = this._schedule[this._dragDay];
      const slot = slots[this._dragSlotIndex];

      // The dragged window's new extent, before absorbing anything.
      let top = this._dragType === 'resize-top'
        ? this._dragCurrentMinutes
        : this._parseTimeToMinutes(slot.from);
      let bottom = this._dragType === 'resize-bottom'
        ? this._dragCurrentMinutes
        : this._slotEndMinutes(slot);

      // Absorb the neighbour the edge came to rest against, and every one
      // it passed over entirely. Their spans are inside the new extent by
      // construction except for the merge target, which extends it - that
      // IS the merge: two windows that meet become one covering both.
      const absorbing = [...this._dragDoomed];
      if (this._dragMergeWith !== null) absorbing.push(this._dragMergeWith);
      for (const at of absorbing) {
        const other = slots[at];
        if (!other) continue;
        top = Math.min(top, this._parseTimeToMinutes(other.from));
        bottom = Math.max(bottom, this._slotEndMinutes(other));
      }

      slot.from = this._minutesToTime(top);
      slot.to = this._endMinutesToTime(bottom);

      // Descending, so each removal cannot shift an index still to be
      // removed - and the dragged slot is never among them.
      for (const at of [...new Set(absorbing)].sort((a, b) => b - a)) {
        slots.splice(at, 1);
      }

      this._saveSchedule();
    }

    // Reset drag state
    this._isDragging = false;
    this._dragType = null;
    this._dragDay = null;
    this._dragStartMinutes = null;
    this._dragCurrentMinutes = null;
    this._dragSlotIndex = null;
    this._dragOriginalSlot = null;
    this._dragMergeWith = null;
    this._dragDoomed = [];

    this.render();
  }

  _hideDragPreview(day = this._dragDay) {
    const column = this.shadowRoot?.querySelector(`.day-column[data-day="${day}"]`);
    if (!column) return;
    for (const selector of ['.drag-preview', '.removal-preview', '.drag-time-display']) {
      const element = column.querySelector(selector);
      if (element) element.style.display = 'none';
    }
  }

  /** Keyboard path for "add a window": create one, then open its editor. */
  _createDefaultSlot(day) {
    // No permission check here on purpose: the only caller is the
    // day-column keydown listener, which _attachEventListeners only binds
    // after its own `if (!this._canEdit()) return;`. A second check would
    // be unreachable code that reads like a security boundary.
    // Same rule as the mouse create path, and it has to be the same or the
    // two input methods produce different schedules from identical input:
    // every OTHER day keeps its implied all-day window (else saving - which
    // is wholesale - switches the sensor off on days the user never
    // touched), while THIS day gets only what the user asked for (else the
    // door ORs an all-day entry with the new one and the restriction does
    // nothing).
    this._materialised = this._ensureRealSlotExists(day);
    if (!this._schedule[day]) this._schedule[day] = [];
    const slot = { from: '09:00', to: '17:00' };
    this._schedule[day].push(slot);
    this._schedule[day].sort((a, b) =>
      this._parseTimeToMinutes(a.from) - this._parseTimeToMinutes(b.from)
    );
    this._isNewSlot = true;
    this._editingSlot = { day, index: this._schedule[day].indexOf(slot) };
    this.render();
  }

  /** Whether this user may change the schedule; the API requires admin. */
  _canEdit() {
    return this._hass?.user?.is_admin !== false;
  }

  _showDragPreview(day) {
    const preview = this.shadowRoot.querySelector(`.day-column[data-day="${day}"] .drag-preview`);
    const removalPreview = this.shadowRoot.querySelector(`.day-column[data-day="${day}"] .removal-preview`);
    const timeDisplay = this.shadowRoot.querySelector(`.day-column[data-day="${day}"] .drag-time-display`);

    if (preview) {
      preview.style.display = 'block';
    }
    if (removalPreview) {
      removalPreview.style.display = 'none'; // Will be shown by _updateDragPreview if shrinking
    }
    if (timeDisplay) {
      timeDisplay.style.display = 'block';
    }

    this._updateDragPreview();
  }

  _updateDragPreview() {
    if (!this._isDragging || !this._dragDay) return;

    const preview = this.shadowRoot.querySelector(`.day-column[data-day="${this._dragDay}"] .drag-preview`);
    const removalPreview = this.shadowRoot.querySelector(`.day-column[data-day="${this._dragDay}"] .removal-preview`);
    const timeDisplay = this.shadowRoot.querySelector(`.day-column[data-day="${this._dragDay}"] .drag-time-display`);

    if (!preview) return;

    let topMin, bottomMin;
    let removalTopMin = null, removalBottomMin = null;

    if (this._dragType === 'create') {
      topMin = Math.min(this._dragStartMinutes, this._dragCurrentMinutes);
      bottomMin = Math.max(this._dragStartMinutes, this._dragCurrentMinutes);
      // Minimum preview height
      if (bottomMin - topMin < 15) {
        bottomMin = topMin + 15;
      }
    } else if (this._dragType === 'resize-top') {
      const originalTop = this._parseTimeToMinutes(this._dragOriginalSlot.from);
      topMin = this._dragCurrentMinutes;
      bottomMin = this._parseTimeToMinutes(this._schedule[this._dragDay][this._dragSlotIndex].to);

      // If shrinking (dragging top down), show removal zone
      if (topMin > originalTop) {
        removalTopMin = originalTop;
        removalBottomMin = topMin;
      }
    } else if (this._dragType === 'resize-bottom') {
      const originalBottom = this._parseTimeToMinutes(this._dragOriginalSlot.to);
      topMin = this._parseTimeToMinutes(this._schedule[this._dragDay][this._dragSlotIndex].from);
      bottomMin = this._dragCurrentMinutes;

      // If shrinking (dragging bottom up), show removal zone
      if (bottomMin < originalBottom) {
        removalTopMin = bottomMin;
        removalBottomMin = originalBottom;
      }
    }

    const topPct = (topMin / 1440) * 100;
    const heightPct = Math.max(((bottomMin - topMin) / 1440) * 100, 1);

    preview.style.top = `${topPct}%`;
    preview.style.height = `${heightPct}%`;

    // A window the drag has passed over completely is about to be absorbed,
    // so say so while there is still time to drag back off it. Repainted
    // every move rather than toggled, because the doomed set shrinks as
    // well as grows.
    const column = this.shadowRoot.querySelector(`.day-column[data-day="${this._dragDay}"]`);
    if (column) {
      const doomed = new Set(this._dragDoomed || []);
      column.querySelectorAll(".time-slot").forEach((node) => {
        node.classList.toggle('doomed', doomed.has(Number(node.dataset.index)));
      });
    }

    // Show/hide removal preview
    if (removalPreview) {
      if (removalTopMin !== null && removalBottomMin !== null) {
        const removalTopPct = (removalTopMin / 1440) * 100;
        const removalHeightPct = ((removalBottomMin - removalTopMin) / 1440) * 100;
        removalPreview.style.top = `${removalTopPct}%`;
        removalPreview.style.height = `${removalHeightPct}%`;
        removalPreview.style.display = 'block';
      } else {
        removalPreview.style.display = 'none';
      }
    }

    if (timeDisplay) {
      timeDisplay.textContent = `${this._formatTimeShort(this._minutesToTime(topMin))} - ${this._formatTimeShort(this._minutesToTime(bottomMin))}`;
      timeDisplay.style.top = `${topPct + heightPct / 2}%`;
    }
  }

  _handleSlotDelete(day, index) {
    this._schedule[day].splice(index, 1);
    if (this._schedule[day].length === 0) {
      delete this._schedule[day];
    }
    this._editingSlot = null;
    this._isNewSlot = false;
    this._saveSchedule();
    this.render();
  }

  _handleSlotUpdate(day, index, from, to) {
    if (!from || !to) return;

    // The end is resolved first, so 22:00-00:00 means "to the end of the
    // day" and passes, while 23:00-01:00 is refused. The device cannot
    // express a window that runs into the next day at all - measured, an
    // inverted window is stored verbatim and then never fires, on the day it
    // names and on the day after - so the honest answer is to refuse it and
    // say what to write instead.
    //
    // `<=`, so an end EQUAL to the start is refused as well: that is also an
    // empty window on a real door, and it is the worst of the three to let
    // through. The door takes it, the schedule sensor goes off with no next
    // event to bring it back, and this card reads "Active 24/7 (no schedule
    // set)" - because a schedule with no open windows looks exactly like no
    // schedule. The pet is shut out and nothing says so.
    //
    // The door itself will not stop us: it accepts anything and simply does
    // nothing with the nonsense. This is the only place it gets caught.
    //
    // Refused HERE rather than left to the backend so the user finds out
    // with the dialog still open and their times still in it, instead of
    // via a toast after the save has already been discarded.
    if (this._slotEndMinutes({ to }) <= this._parseTimeToMinutes(from)) {
      this._dialogError = t(this._hass, 'end_before_start');
      this.render();
      return;
    }

    this._dialogError = null;
    this._schedule[day][index] = { from, to };
    this._editingSlot = null;
    this._isNewSlot = false;
    this._saveSchedule();
    this.render();
  }

  _closeDialog() {
    this._dialogError = null;
    if (this._editingSlot && this._isNewSlot) {
      // Remove the newly created slot if user cancels
      const { day, index } = this._editingSlot;
      if (this._schedule[day] && this._schedule[day][index]) {
        this._schedule[day].splice(index, 1);
        if (this._schedule[day].length === 0) {
          delete this._schedule[day];
        }
      }
    }
    // Undo a materialisation this interaction performed but never saved.
    // Without this, opening the editor on a door with no schedule and
    // pressing Cancel left seven real all-day entries in `_schedule` - so
    // the collapsed card reported "7 time slots across 7 days" for a door
    // that has no schedule and received no write, and a later edit was
    // built on top of entries the user never asked for.
    if (this._materialised) {
      this._schedule = {};
      this._materialised = false;
    }
    this._editingSlot = null;
    this._isNewSlot = false;
    this.render();
  }

  /**
   * Remember which element has focus, so render() can put it back.
   *
   * `render()` replaces the whole shadow root, which destroys the focused
   * node - so every keyboard activation dropped focus to `<body>`. A
   * keyboard user had to Tab all the way back in after each one, and since
   * the dialog is the only route to editing, resizing or deleting, that
   * toll was paid on every edit. It also defeated the native <dialog>'s
   * focus restore, because showModal() recorded a previously-focused
   * element that render() had already destroyed.
   *
   * Returns a selector rather than the node itself: the node will not
   * survive. Null when nothing inside the card has focus, so the card can
   * never STEAL focus it did not already hold.
   */
  _focusSelector() {
    const active = this.shadowRoot?.activeElement;
    if (!active) return null;
    if (active.id) return `#${CSS.escape(active.id)}`;
    if (!active.dataset.day) return null;
    const base = `.${active.classList[0]}[data-day="${active.dataset.day}"]`;
    return active.dataset.index === undefined
      ? base
      : `${base}[data-index="${active.dataset.index}"]`;
  }

  render() {
    if (!this.shadowRoot) return;
    const restoreFocusTo = this._focusSelector();

    const sensorType = this._getSensorType();
    const isActive = this._isActive();
    // A failed load leaves _schedule empty, which _getScheduleSummary reads
    // as "no schedule set" and reports as "Active 24/7". Collapsed, the card
    // then read "Inactive - Active 24/7 (no schedule set)": a confident,
    // self-contradictory claim that you had to expand the card to discover
    // was wrong.
    // ...and a THIRD cause, which that fix did not reach: a table that gates
    // only the OTHER sensor. `to_ha_format` returns {} for this one, which is
    // indistinguishable from "no schedule" - so the commonest asymmetric
    // setup ("inside any time, outside only during the day") read
    // "Inactive - Active 24/7 (no schedule set)" on the outside card all
    // night. When the entity itself says the sensor is shut, say that
    // instead of guessing from an empty window set.
    const summary = this._loading
      ? t(this._hass, 'loading')
      : this._error
        ? t(this._hass, 'load_failed')
        : !isActive && !this._hasSchedule()
          ? t(this._hass, 'no_windows')
          : this._getScheduleSummary();

    // Get current time for the line
    const now = new Date();
    const currentMinutes = now.getHours() * 60 + now.getMinutes();
    const currentTimePct = (currentMinutes / 1440) * 100;

    // The header below carries no aria-label deliberately. On a
    // role="button", aria-label REPLACES the element's content for assistive
    // tech, so the sensor name, the active state and the slot-count summary
    // nested inside it were announced as nothing at all. The header's own
    // text is a better label than any string we could write, and it stays
    // correct as the schedule changes.
    //
    // The windows in the grid are the opposite case, and read-only ones get
    // role="img". A window carries no text a screen reader can use - only a
    // start time, and only when it is tall enough - so its aria-label is the
    // whole of its meaning. On a non-admin's card there is nothing to
    // activate, so the editable role="button" is wrong; but dropping the
    // role entirely leaves a generic element, and ARIA ignores a label
    // there, which silenced the grid completely for exactly the user who
    // cannot see the schedule any other way.
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          overflow: visible;
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 16px;
          cursor: pointer;
          user-select: none;
        }
        .header:hover {
          background: var(--secondary-background-color, rgba(0,0,0,0.05));
        }
        .header-left {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .status-indicator {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          background: ${isActive ? 'var(--success-color, #4caf50)' : 'var(--disabled-color, #bdbdbd)'};
          flex-shrink: 0;
        }
        .header-text {
          display: flex;
          flex-direction: column;
        }
        .title {
          font-size: 1em;
          font-weight: 500;
        }
        .subtitle {
          font-size: 0.85em;
          color: var(--secondary-text-color, #727272);
        }
        .expand-icon {
          transition: transform 0.2s;
          transform: rotate(${this._expanded ? '180deg' : '0deg'});
          flex-shrink: 0;
        }
        .content {
          display: ${this._expanded ? 'block' : 'none'};
          padding: 0 16px 16px;
        }
        .schedule-grid {
          display: grid;
          grid-template-columns: 35px repeat(7, 1fr);
          gap: 1px;
          background: var(--divider-color, #e0e0e0);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 4px;
          overflow: visible;
          font-size: 12px;
        }
        .time-labels {
          display: flex;
          flex-direction: column;
          background: var(--card-background-color, white);
        }
        .time-label-header {
          height: 24px;
          background: var(--card-background-color, white);
        }
        .time-label {
          font-size: 9px;
          color: var(--secondary-text-color, #727272);
          display: flex;
          align-items: flex-start;
          justify-content: flex-end;
          padding-right: 4px;
          box-sizing: border-box;
        }
        /* The day header doubles as the copy-to-other-days button when the
           user can edit, so it has to look like a header and behave like a
           button. */
        button.day-header {
          border: none;
          font: inherit;
          cursor: pointer;
          width: 100%;
        }
        .hint-actions {
          display: flex;
          justify-content: center;
          gap: 12px;
          margin-top: 2px;
        }
        .copy-day-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
          margin: 8px 0;
        }
        .copy-day-option {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
        }
        .day-header {
          text-align: center;
          padding: 4px 2px;
          font-weight: 500;
          font-size: 11px;
          background: var(--card-background-color, white);
          height: 24px;
          box-sizing: border-box;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .day-column:focus-visible,
        .header:focus-visible {
          outline: 2px solid var(--primary-text-color, #212121);
          outline-offset: -2px;
        }
        /* Outward, unlike the two above. A slot is filled with a colour the
           user chooses, and the default green against --primary-text-color
           on a dark theme is 2.8:1 - under WCAG 1.4.11's 3:1, so a keyboard
           user could not see which window they were on. Offsetting the ring
           outward lands it on the day column instead, where the pair is the
           theme's own text-on-card contrast and is legible by construction
           whatever slot colour is configured. */
        .time-slot:focus-visible {
          outline: 2px solid var(--primary-text-color, #212121);
          outline-offset: 2px;
        }
        .day-column {
          position: relative;
          height: 200px;
          background: var(--card-background-color, white);
          cursor: crosshair;
        }
        .hour-line {
          position: absolute;
          left: 0;
          right: 0;
          height: 1px;
          background: var(--divider-color, #e0e0e0);
          opacity: 0.4;
          pointer-events: none;
        }
        .hour-line.major {
          opacity: 0.8;
        }
        .current-time-line {
          position: absolute;
          left: 0;
          right: 0;
          height: 2px;
          background: var(--error-color, #f44336);
          pointer-events: none;
          z-index: 15;
        }
        .time-slot {
          position: absolute;
          left: 2px;
          right: 2px;
          background: ${this._getSlotColor()};
          border-radius: 3px;
          font-size: 9px;
          color: white;
          overflow: visible;
          cursor: pointer;
          min-height: 14px;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 1px;
          box-shadow: 0 1px 2px rgba(0,0,0,0.2);
          z-index: 5;
        }
        .time-slot.active-now {
          background: ${this._getActiveSlotColor()};
          box-shadow: 0 0 8px ${this._getActiveSlotColor()};
        }
        .time-slot .time-range {
          /* 9px white on --primary-color measures 2.65:1, and on
             --warning-color 2.17:1; AA wants 4.5:1 and 9px is too small for
             the large-text exemption. A shadow works against any colour the
             user configures, which a fixed foreground would not. */
          text-shadow: 0 1px 2px rgba(0, 0, 0, 0.9);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          pointer-events: none;
        }
        .slot-edge {
          position: absolute;
          left: 0;
          right: 0;
          height: 8px;
          cursor: ns-resize;
          z-index: 6;
        }
        .slot-edge.top {
          top: -4px;
        }
        .slot-edge.bottom {
          bottom: -4px;
        }
        .slot-edge:hover {
          background: rgba(255,255,255,0.3);
        }
        .drag-preview {
          position: absolute;
          left: 2px;
          right: 2px;
          background: ${this._getSlotColor()};
          opacity: 0.5;
          border-radius: 3px;
          pointer-events: none;
          display: none;
          z-index: 10;
          min-height: 4px;
        }
        /* A window the current drag would swallow. Uses the same colour
           as the shrink zone, because it means the same thing: this is
           what applying the drag removes. */
        .time-slot.doomed {
          background: ${this._getRemovalColor()} !important;
          opacity: 0.7;
        }
        .removal-preview {
          position: absolute;
          left: 2px;
          right: 2px;
          background: ${this._getRemovalColor()};
          opacity: 0.6;
          border-radius: 3px;
          pointer-events: none;
          display: none;
          z-index: 11;
          min-height: 4px;
        }
        .drag-time-display {
          position: absolute;
          left: 50%;
          transform: translate(-50%, -50%);
          background: rgba(0,0,0,0.85);
          color: white;
          padding: 3px 8px;
          border-radius: 3px;
          font-size: 11px;
          white-space: nowrap;
          pointer-events: none;
          display: none;
          z-index: 20;
        }
        /* Says the windows below are not in force. role="status" rather than
           "alert": it is a standing condition the user chose, not an error,
           so it should be announced without interrupting. */
        .notice {
          font-size: 12px;
          margin-top: 8px;
          padding: 8px;
          border-radius: 4px;
          background: var(--warning-color, #ffa726);
          color: var(--text-primary-color, #fff);
        }
        .hint {
          font-size: 11px;
          color: var(--secondary-text-color, #727272);
          margin-top: 8px;
          text-align: center;
        }
        /* A real button that looks like a link, not a link wearing
           role="button". With the role, a screen reader tells the user to
           press Space - and on an <a> Space scrolls the dashboard instead,
           so the one control the card offers a stuck user did nothing. */
        .hint .link-button {
          background: none;
          border: none;
          padding: 0;
          font: inherit;
          color: ${this._getSlotColor()};
          cursor: pointer;
          text-decoration: none;
        }
        .hint .link-button:hover {
          text-decoration: underline;
        }

        /* Dialog styles */
        .dialog-overlay {
          border: none;
          padding: 0;
          background: transparent;
          max-width: 90vw;
        }
        .dialog-overlay::backdrop {
          background: rgba(0, 0, 0, 0.5);
        }
        .edit-dialog {
          background: var(--card-background-color, white);
          padding: 20px;
          border-radius: 8px;
          box-shadow: 0 4px 20px rgba(0,0,0,0.3);
          min-width: 280px;
          max-width: 90vw;
        }
        .dialog-title {
          font-size: 1.1em;
          font-weight: 500;
          margin-bottom: 16px;
          color: var(--primary-text-color);
        }
        .dialog-row {
          display: flex;
          gap: 12px;
          margin-bottom: 12px;
          align-items: center;
        }
        .dialog-row label {
          min-width: 50px;
          color: var(--primary-text-color);
        }
        .dialog-row input[type="time"] {
          flex: 1;
          padding: 8px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 4px;
          font-size: 14px;
          background: var(--card-background-color, white);
          color: var(--primary-text-color);
        }
        /* role="alert" carries this to a screen reader on its own, so the
           user is told why Save did nothing whether or not they can see the
           dialog. */
        .dialog-error {
          color: var(--error-color, #f44336);
          font-size: 0.85em;
          margin-bottom: 8px;
        }
        .dialog-buttons {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          margin-top: 16px;
        }
        button {
          padding: 8px 16px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
        }
        .save-btn {
          background: ${this._getSlotColor()};
          color: white;
        }
        .cancel-btn {
          background: var(--secondary-background-color, #e0e0e0);
          color: var(--primary-text-color);
        }
        .delete-btn {
          background: var(--error-color, #f44336);
          color: white;
          margin-right: auto;
        }
        .loading, .error {
          text-align: center;
          padding: 20px;
          color: var(--secondary-text-color, #727272);
        }
        .error {
          color: var(--error-color, #f44336);
        }
      </style>

      <ha-card>
        <div class="header" id="header" role="button" tabindex="0"
             aria-expanded="${this._expanded}">
          <div class="header-left">
            <div class="status-indicator"></div>
            <div class="header-text">
              <div class="title">${sensorType}</div>
              <div class="subtitle">${t(this._hass, isActive ? 'active' : 'inactive')} · ${summary}</div>
            </div>
          </div>
          <svg class="expand-icon" width="24" height="24" viewBox="0 0 24 24">
            <path fill="currentColor" d="M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z"/>
          </svg>
        </div>

        <div class="content">
          ${this._loading ? `
            <div class="loading">${t(this._hass, 'loading')}</div>
          ` : this._error ? `
            <div class="error">${escapeHtml(this._error)}</div>
          ` : `
            <div class="schedule-grid">
              <!-- Time labels column -->
              <div class="time-labels">
                <div class="time-label-header"></div>
                ${[0, 3, 6, 9, 12, 15, 18, 21].map(h => `
                  <div class="time-label" style="height: 25px;">
                    ${h === 0 ? '12a' : h < 12 ? h + 'a' : h === 12 ? '12p' : (h - 12) + 'p'}
                  </div>
                `).join('')}
              </div>

              <!-- Day columns -->
              ${DAYS.map((day, dayIndex) => `
                <div style="display: flex; flex-direction: column;">
                  ${this._canEdit() ? `
                    <button type="button" class="day-header day-copy"
                            data-day="${day}"
                            title="${escapeHtml(t(this._hass, 'copy_day', { day: DAY_LABELS[dayIndex] }))}"
                            aria-label="${escapeHtml(t(this._hass, 'copy_day', { day: DAY_LABELS[dayIndex] }))}">
                      ${DAY_SHORT[dayIndex]}
                    </button>
                  ` : `<div class="day-header">${DAY_SHORT[dayIndex]}</div>`}
                  <div class="day-column" data-day="${day}"
                       ${this._canEdit() ? `tabindex="0" role="button" aria-label="${t(this._hass, 'add_window')} ${DAY_LABELS[dayIndex]}"` : ''}>
                    ${[0, 6, 12, 18].map(h => `
                      <div class="hour-line major" style="top: ${(h / 24) * 100}%"></div>
                    `).join('')}
                    ${[3, 9, 15, 21].map(h => `
                      <div class="hour-line" style="top: ${(h / 24) * 100}%"></div>
                    `).join('')}
                    <div class="current-time-line" style="top: ${currentTimePct}%"></div>
                    ${(this._getEffectiveSchedule()[day] || []).map((slot, slotIndex) => `
                      <div class="time-slot"
                           style="${this._getSlotStyle(slot)}"
                           data-day="${day}"
                           data-index="${slotIndex}"
                           ${this._canEdit() ? 'tabindex="0" role="button"' : 'role="img"'}
                           aria-label="${escapeHtml(this._slotLabel(day, slot))}"
                           title="${this._formatTime(slot.from)} - ${this._formatTime(slot.to)}">
                        <div class="slot-edge top" data-edge="top" data-day="${day}" data-index="${slotIndex}"></div>
                        <span class="time-range">${this._formatTimeShort(slot.from)}</span>
                        <div class="slot-edge bottom" data-edge="bottom" data-day="${day}" data-index="${slotIndex}"></div>
                      </div>
                    `).join('')}
                    <div class="drag-preview"></div>
                    <div class="removal-preview"></div>
                    <div class="drag-time-display"></div>
                  </div>
                </div>
              `).join('')}
            </div>
            ${this._timersEnabled ? '' : `<div class="notice" role="status">${t(this._hass, 'timers_disabled')}</div>`}
            <div class="hint">${this._canEdit() ? t(this._hass, 'hint') : t(this._hass, 'hint_readonly')}</div>
            <div class="hint hint-actions">${this._canEdit() && this._counterpart ? `<button type="button" class="link-button" id="copy-from-link">${escapeHtml(t(this._hass, 'copy_from', { sensor: this._counterpartLabel() }))}</button>` : ''}<button type="button" class="link-button" id="refresh-link">${t(this._hass, 'reload')}</button></div>
          `}
        </div>
      </ha-card>

      ${this._editingSlot ? this._renderEditDialog() : ''}
      ${this._copyingDay ? this._renderCopyDayDialog() : ''}
      ${this._confirmCopyFrom ? this._renderCopyFromDialog() : ''}
    `;

    this._attachEventListeners();

    // A slot the user just deleted simply will not match, which degrades to
    // the old behaviour rather than throwing.
    if (restoreFocusTo) {
      this.shadowRoot.querySelector(restoreFocusTo)?.focus();
    }

    // Update active slot highlight after render
    if (this._expanded) {
      setTimeout(() => this._updateActiveSlotHighlight(), 0);
    }
  }

  _renderEditDialog() {
    const { day, index } = this._editingSlot;
    const slot = this._schedule[day]?.[index];
    if (!slot) return '';

    const dayIndex = DAYS.indexOf(day);
    const dayLabel = DAY_LABELS[dayIndex];
    const sensorType = this._getSensorType();

    // A native <dialog>, opened with showModal(). That is where Escape,
    // the focus trap, initial focus, focus restore on close and top-layer
    // rendering all come from - for free, and correctly. Hand-rolling them
    // on a <div> overlay is about the same amount of code and gets the
    // focus behaviour subtly wrong; the previous version had none of it, so
    // Escape did nothing and focus fell to <body> behind the scrim.
    return `
      <dialog class="dialog-overlay" id="dialog-overlay"
              aria-labelledby="dialog-title">
        <div class="edit-dialog" id="edit-dialog">
          <div class="dialog-title" id="dialog-title">${this._isNewSlot ? t(this._hass, 'new_slot') : t(this._hass, 'edit_slot')} - ${sensorType} - ${dayLabel}</div>
          <div class="dialog-row">
            <label for="edit-from">${t(this._hass, 'from_label')}</label>
            <input type="time" id="edit-from" value="${escapeHtml(slot.from)}">
          </div>
          <div class="dialog-row">
            <label for="edit-to">${t(this._hass, 'to_label')}</label>
            <input type="time" id="edit-to" value="${escapeHtml(slot.to)}">
          </div>
          ${this._dialogError ? `<div class="dialog-error" id="dialog-error" role="alert">${escapeHtml(this._dialogError)}</div>` : ''}
          <div class="dialog-buttons">
            ${!this._isNewSlot ? `<button class="delete-btn" id="dialog-delete">${t(this._hass, 'delete')}</button>` : ''}
            <button class="cancel-btn" id="dialog-cancel">${t(this._hass, 'cancel')}</button>
            <button class="save-btn" id="dialog-save">${t(this._hass, 'save')}</button>
          </div>
        </div>
      </dialog>
    `;
  }

  /**
   * The day picker for "copy Monday to...".
   *
   * A <dialog> for the same reasons as the edit dialog: the focus trap,
   * initial focus, focus restore and top-layer rendering come with it.
   * The source day is checked and disabled - it is the thing being copied
   * FROM, and unchecking it would suggest it could be excluded.
   */
  _renderCopyDayDialog() {
    const fromDay = this._copyingDay;
    const fromLabel = DAY_LABELS[DAYS.indexOf(fromDay)];
    return `
      <dialog class="dialog-overlay" id="copy-day-overlay"
              aria-labelledby="copy-day-title">
        <div class="edit-dialog" id="copy-day-dialog">
          <div class="dialog-title" id="copy-day-title">${escapeHtml(t(this._hass, 'copy_day_title', { day: fromLabel }))}</div>
          <div class="copy-day-list">
            ${DAYS.map((day, index) => `
              <label class="copy-day-option">
                <input type="checkbox" name="copy-day" value="${day}"
                       ${day === fromDay ? 'checked disabled' : ''}>
                <span>${DAY_LABELS[index]}</span>
              </label>
            `).join('')}
          </div>
          ${this._dialogError ? `<div class="dialog-error" id="copy-day-error" role="alert">${escapeHtml(this._dialogError)}</div>` : ''}
          <div class="dialog-buttons">
            <button class="cancel-btn" id="copy-day-all">${t(this._hass, 'select_all')}</button>
            <button class="cancel-btn" id="copy-day-none">${t(this._hass, 'select_none')}</button>
            <button class="cancel-btn" id="copy-day-cancel">${t(this._hass, 'cancel')}</button>
            <button class="save-btn" id="copy-day-confirm">${t(this._hass, 'copy_day_confirm')}</button>
          </div>
        </div>
      </dialog>
    `;
  }

  /** Confirmation for replacing this schedule with the other sensor's. */
  _renderCopyFromDialog() {
    return `
      <dialog class="dialog-overlay" id="copy-from-overlay"
              aria-labelledby="copy-from-title">
        <div class="edit-dialog" id="copy-from-dialog">
          <div class="dialog-title" id="copy-from-title">${escapeHtml(t(this._hass, 'copy_from', { sensor: this._counterpartLabel() }))}</div>
          <div class="dialog-row">${escapeHtml(t(this._hass, 'copy_from_confirm', { sensor: this._counterpartLabel() }))}</div>
          <div class="dialog-buttons">
            <button class="cancel-btn" id="copy-from-cancel">${t(this._hass, 'cancel')}</button>
            <button class="save-btn" id="copy-from-confirm">${t(this._hass, 'copy_day_confirm')}</button>
          </div>
        </div>
      </dialog>
    `;
  }

  _attachEventListeners() {
    // Header click to expand/collapse
    const header = this.shadowRoot.getElementById('header');
    if (header) {
      header.addEventListener('click', () => this._handleHeaderClick());
      header.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          this._handleHeaderClick();
        }
      });
    }

    // Reading and reloading are available to everyone; only the editing
    // listeners below are gated.
    const refreshLink = this.shadowRoot.getElementById('refresh-link');
    if (refreshLink) {
      refreshLink.addEventListener('click', () => this._loadSchedule());
    }

    // Editing is admin-only: ws_update_schedule is @require_admin. Without
    // this guard a non-admin household member got a fully interactive card,
    // made a change, watched it apply, and then had it revert with an
    // "unauthorized" toast - once per attempt, with nothing ever telling
    // them the card is read-only for them. The hint line says so instead.
    if (!this._canEdit()) return;

    // Day column mouse events for creating new slots
    this.shadowRoot.querySelectorAll('.day-column').forEach(col => {
      col.addEventListener('mousedown', (e) => {
        if (!e.target.classList.contains('slot-edge')) {
          this._handleDayMouseDown(col.dataset.day, e);
        }
      });
      // Keyboard equivalent of click-to-create: a default 9-to-5 window the
      // user then edits in the dialog. Dragging cannot be expressed with a
      // key, so the created window has to have sensible bounds rather than
      // depending on where a pointer was.
      col.addEventListener('keydown', (e) => {
        if (e.target !== col) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          this._createDefaultSlot(col.dataset.day);
        }
      });
    });

    // Slot edge drag for resizing
    this.shadowRoot.querySelectorAll('.slot-edge').forEach(edge => {
      edge.addEventListener('mousedown', (e) => {
        this._handleSlotEdgeMouseDown(
          edge.dataset.day,
          parseInt(edge.dataset.index),
          edge.dataset.edge,
          e
        );
      });
    });

    // Time slot clicks for editing.
    //
    // Deliberately NOT excluding `.slot-edge`. A window under ~2 hours is
    // 14px tall, and its two 8px edges leave a 6px band, so most clicks
    // aimed at such a window land on an edge - and excluding them meant the
    // click was swallowed and nothing opened. _handleMouseUp already drops
    // a resize that never moved, so an edge click arrives here as a click.
    this.shadowRoot.querySelectorAll('.time-slot').forEach(slot => {
      slot.addEventListener('click', (e) => {
        if (this._dragMoved) return;
        this._handleSlotClick(slot.dataset.day, parseInt(slot.dataset.index), e);
      });
      // Enter/Space opens the edit dialog, which is what makes editing,
      // RESIZING (via its time fields) and deleting reachable without a
      // mouse - so no arrow-key resize gesture is needed.
      slot.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          e.stopPropagation();
          this._handleSlotClick(slot.dataset.day, parseInt(slot.dataset.index), e);
        }
      });
    });

    // Dialog events
    this._attachDialogListeners();
  }

  _attachDialogListeners() {
    // -- copy from the other sensor ----------------------------------------
    const copyFromLink = this.shadowRoot.getElementById('copy-from-link');
    if (copyFromLink) {
      copyFromLink.addEventListener('click', () => {
        this._confirmCopyFrom = true;
        this.render();
      });
    }

    const copyFromOverlay = this.shadowRoot.getElementById('copy-from-overlay');
    if (copyFromOverlay) {
      if (!copyFromOverlay.open) copyFromOverlay.showModal();
      const close = () => {
        this._confirmCopyFrom = false;
        this.render();
      };
      copyFromOverlay.addEventListener('close', () => {
        if (this._confirmCopyFrom) close();
      });
      this.shadowRoot.getElementById('copy-from-cancel')
        ?.addEventListener('click', close);
      this.shadowRoot.getElementById('copy-from-confirm')
        ?.addEventListener('click', async () => {
          this._confirmCopyFrom = false;
          await this._copyFromCounterpart();
        });
    }

    // -- copy one day onto others -----------------------------------------
    this.shadowRoot.querySelectorAll('.day-copy').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        this._copyingDay = button.dataset.day;
        this._dialogError = null;
        this.render();
      });
    });

    const copyDayOverlay = this.shadowRoot.getElementById('copy-day-overlay');
    if (copyDayOverlay) {
      if (!copyDayOverlay.open) copyDayOverlay.showModal();
      const close = () => {
        this._copyingDay = null;
        this._dialogError = null;
        this.render();
      };
      copyDayOverlay.addEventListener('close', () => {
        if (this._copyingDay) close();
      });
      const boxes = () => Array.from(
        this.shadowRoot.querySelectorAll('input[name="copy-day"]:not(:disabled)'),
      );
      this.shadowRoot.getElementById('copy-day-cancel')
        ?.addEventListener('click', close);
      this.shadowRoot.getElementById('copy-day-all')
        ?.addEventListener('click', () => boxes().forEach((b) => { b.checked = true; }));
      this.shadowRoot.getElementById('copy-day-none')
        ?.addEventListener('click', () => boxes().forEach((b) => { b.checked = false; }));
      this.shadowRoot.getElementById('copy-day-confirm')
        ?.addEventListener('click', async () => {
          const chosen = boxes().filter((b) => b.checked).map((b) => b.value);
          if (chosen.length === 0) {
            // Refused rather than treated as "no days", which would look
            // exactly like a successful copy that did nothing.
            this._dialogError = t(this._hass, 'copy_day_none');
            this.render();
            return;
          }
          const fromDay = this._copyingDay;
          this._copyingDay = null;
          await this._copyDayTo(fromDay, chosen);
        });
    }

    const dialogOverlay = this.shadowRoot.getElementById('dialog-overlay');
    const editDialog = this.shadowRoot.getElementById('edit-dialog');
    const dialogCancel = this.shadowRoot.getElementById('dialog-cancel');
    const dialogSave = this.shadowRoot.getElementById('dialog-save');
    const dialogDelete = this.shadowRoot.getElementById('dialog-delete');
    const fromInput = this.shadowRoot.getElementById('edit-from');
    const toInput = this.shadowRoot.getElementById('edit-to');

    if (dialogOverlay) {
      // showModal(), not an `open` attribute: only the modal form puts the
      // dialog in the top layer and activates Escape and the focus trap.
      if (!dialogOverlay.open) dialogOverlay.showModal();
      // Escape (and any other close) must run the same teardown Cancel does,
      // or _editingSlot stays set and the card re-renders the dialog.
      dialogOverlay.addEventListener('close', () => {
        if (this._editingSlot) this._closeDialog();
      });
      dialogOverlay.addEventListener('mousedown', (e) => {
        if (e.target === dialogOverlay) {
          e.preventDefault();
          e.stopPropagation();
          this._closeDialog();
        }
      });
    }

    if (editDialog) {
      editDialog.addEventListener('mousedown', (e) => {
        e.stopPropagation();
      });
    }

    if (dialogCancel) {
      dialogCancel.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this._closeDialog();
      });
    }

    if (dialogSave) {
      dialogSave.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const from = fromInput?.value;
        const to = toInput?.value;
        if (from && to && this._editingSlot) {
          const { day, index } = this._editingSlot;
          this._handleSlotUpdate(day, index, from, to);
        }
      });
    }

    if (dialogDelete) {
      dialogDelete.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (this._editingSlot) {
          const { day, index } = this._editingSlot;
          this._handleSlotDelete(day, index);
        }
      });
    }
  }

  getCardSize() {
    return this._expanded ? 4 : 1;
  }
}

// Card Editor
// The three colours the card lets a user override, and everything the editor
// needs to render and wire one: the config key it writes, the id prefix its
// three controls share, its label and hint strings, and the colour the card
// falls back to when the setting is absent.
const COLOR_FIELDS = [
  {
    key: 'slot_color',
    id: 'slot-color',
    label: 'slot_color',
    hint: 'slot_color_hint',
    fallback: '#03a9f4',
  },
  {
    key: 'active_slot_color',
    id: 'active-color',
    label: 'active_slot_color',
    hint: 'active_slot_color_hint',
    fallback: '#ff9800',
  },
  {
    key: 'removal_color',
    id: 'removal-color',
    label: 'removal_color',
    hint: 'removal_color_hint',
    fallback: '#f44336',
  },
];

class PowerPetDoorScheduleCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
  }

  setConfig(config) {
    this._config = config;
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  _fireConfigChanged() {
    this.dispatchEvent(new CustomEvent('config-changed', {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    }));
  }

  render() {
    if (!this.shadowRoot || !this._hass) return;

    // `binary_sensor.<door>_..._schedule`, NOT `schedule.` - that prefix is
    // residue from the removed core-schedule design, and the integration
    // has never created an entity in that domain. The dropdown was
    // therefore always empty (or listed unrelated core schedule helpers,
    // every one of which the API rejects), so the card could not be
    // configured through the UI at all.
    const scheduleEntities = Object.keys(this._hass.states)
      .filter(id => id.startsWith('binary_sensor.') && id.endsWith('_schedule'))
      .sort();

    this.shadowRoot.innerHTML = `
      <style>
        .row {
          display: flex;
          flex-direction: column;
          margin-bottom: 16px;
        }
        label {
          font-weight: 500;
          margin-bottom: 4px;
        }
        .label-hint {
          font-weight: normal;
          font-size: 0.85em;
          color: var(--secondary-text-color);
        }
        select, input[type="text"] {
          padding: 8px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 4px;
          background: var(--card-background-color, white);
          color: var(--primary-text-color);
        }
        .color-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .color-row input[type="color"] {
          width: 40px;
          height: 32px;
          padding: 2px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 4px;
          cursor: pointer;
        }
        .color-row input[type="text"] {
          flex: 1;
        }
        .reset-btn {
          padding: 4px 8px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 4px;
          background: var(--secondary-background-color, #f0f0f0);
          color: var(--primary-text-color);
          cursor: pointer;
          font-size: 12px;
        }
        .reset-btn:hover {
          background: var(--divider-color, #e0e0e0);
        }
      </style>

      <div class="row">
        <label for="entity-select">${t(this._hass, 'schedule_entity')}</label>
        <select id="entity-select">
          <option value="">${t(this._hass, 'select_entity')}</option>
          ${scheduleEntities.map(id => `
            <option value="${escapeHtml(id)}" ${this._config.entity === id ? 'selected' : ''}>
              ${escapeHtml(this._hass.states[id]?.attributes?.friendly_name || id)}
            </option>
          `).join('')}
        </select>
      </div>

      ${COLOR_FIELDS.map(field => this._renderColorRow(field)).join('')}
    `;

    // Entity select
    this.shadowRoot.getElementById('entity-select').addEventListener('change', (e) => {
      this._config = { ...this._config, entity: e.target.value };
      this._fireConfigChanged();
    });

    for (const field of COLOR_FIELDS) {
      const picker = this.shadowRoot.getElementById(`${field.id}-picker`);
      const text = this.shadowRoot.getElementById(`${field.id}-text`);

      picker.addEventListener('input', (e) => {
        this._config = { ...this._config, [field.key]: e.target.value };
        text.value = e.target.value;
        this._fireConfigChanged();
      });
      text.addEventListener('change', (e) => {
        this._config = { ...this._config, [field.key]: e.target.value || undefined };
        this._fireConfigChanged();
      });
      this.shadowRoot.getElementById(`${field.id}-reset`).addEventListener('click', () => {
        delete this._config[field.key];
        this._fireConfigChanged();
        this.render();
      });
    }
  }

  /** Render one colour setting: a swatch, a free-text field and a reset.
   *
   * Every control here needs a name of its own. The three rows used to be
   * three copies of this markup whose only labelling was a <label> with no
   * `for`, which names nothing - so the editor presented six unnamed fields
   * and three buttons all called "Reset", and a screen reader user had no
   * way to tell which colour any of them set.
   */
  _renderColorRow(field) {
    const name = t(this._hass, field.label);
    return `
      <div class="row">
        <label for="${field.id}-text">${name} <span class="label-hint">${t(this._hass, field.hint)}</span></label>
        <div class="color-row">
          <input type="color" id="${field.id}-picker"
                 aria-label="${escapeHtml(`${name} ${t(this._hass, 'color_swatch')}`)}"
                 value="${escapeHtml(this._getColorValue(this._config[field.key], field.fallback))}">
          <input type="text" id="${field.id}-text"
                 placeholder="${t(this._hass, 'color_placeholder')}"
                 value="${escapeHtml(this._config[field.key] || '')}">
          <button class="reset-btn" id="${field.id}-reset"
                  aria-label="${escapeHtml(`${t(this._hass, 'reset')} ${name}`)}">${t(this._hass, 'reset')}</button>
        </div>
      </div>
    `;
  }

  _getColorValue(configValue, defaultHex) {
    // If it's a hex color, return it directly
    if (configValue && configValue.startsWith('#')) {
      return configValue;
    }
    // Otherwise return the default for the color picker
    return defaultHex;
  }
}

customElements.define('powerpetdoor-schedule-card', PowerPetDoorScheduleCard);
customElements.define('powerpetdoor-schedule-card-editor', PowerPetDoorScheduleCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'powerpetdoor-schedule-card',
  name: 'Power Pet Door Schedule',
  description: 'A card to view and edit Power Pet Door schedules',
  preview: true,
});

console.info(
  '%c POWERPETDOOR-SCHEDULE-CARD %c v1.15.2 ',
  'color: white; background: #03a9f4; font-weight: bold;',
  'color: #03a9f4; background: white; font-weight: bold;'
);
