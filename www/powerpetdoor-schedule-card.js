/**
 * Copyright (c) 2025 Preston Elder
 *
 * This software is released under the MIT License.
 * https://opensource.org/licenses/MIT
 *
 * Power Pet Door Schedule Card v1.6.0
 * A custom Lovelace card for viewing and editing Power Pet Door schedules.
 */

const DAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
const DAY_LABELS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const DAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// Default colors
const DEFAULT_SLOT_COLOR = 'var(--primary-color, #03a9f4)';
const DEFAULT_ACTIVE_SLOT_COLOR = 'var(--warning-color, #ff9800)';
const DEFAULT_REMOVAL_COLOR = 'var(--error-color, #f44336)';

class PowerPetDoorScheduleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
    this._hass = null;
    this._schedule = {};
    this._loading = true;
    this._error = null;
    this._expanded = false;
    this._editingSlot = null;
    this._isNewSlot = false; // Track if editing a newly created slot

    // Drag state
    this._isDragging = false;
    this._dragType = null; // 'create', 'resize-top', 'resize-bottom'
    this._dragDay = null;
    this._dragStartMinutes = null;
    this._dragCurrentMinutes = null;
    this._dragSlotIndex = null;
    this._dragOriginalSlot = null;
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

    const daySlots = this._schedule[currentDay] || [];
    daySlots.forEach((slot, index) => {
      const startMin = this._parseTimeToMinutes(slot.from);
      const endMin = this._parseTimeToMinutes(slot.to);
      if (currentMinutes >= startMin && currentMinutes < endMin) {
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
      throw new Error('Please define an entity');
    }
    this._config = config;
    this.render();
  }

  _getSlotColor() {
    return this._config.slot_color || DEFAULT_SLOT_COLOR;
  }

  _getActiveSlotColor() {
    return this._config.active_slot_color || DEFAULT_ACTIVE_SLOT_COLOR;
  }

  _getRemovalColor() {
    return this._config.removal_color || DEFAULT_REMOVAL_COLOR;
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

    try {
      const result = await this._hass.callWS({
        type: 'powerpetdoor/schedule/get',
        entity_id: this._config.entity,
      });
      this._schedule = result.schedule || {};
      this._loading = false;
      this._error = null;
    } catch (err) {
      // Fallback to entity state attributes
      const state = this._hass.states[this._config.entity];
      if (state && state.attributes && state.attributes.schedule) {
        this._schedule = JSON.parse(JSON.stringify(state.attributes.schedule));
        this._loading = false;
        this._error = null;
      } else {
        this._error = err.message || 'Failed to load schedule';
        this._loading = false;
      }
    }
    this.render();
  }

  async _saveSchedule() {
    if (!this._hass || !this._config.entity) return;

    try {
      await this._hass.callWS({
        type: 'powerpetdoor/schedule/update',
        entity_id: this._config.entity,
        schedule: this._schedule,
      });
    } catch (err) {
      alert('Failed to save schedule: ' + (err.message || err));
      this._loadSchedule(); // Reload on failure
    }
  }

  _getSensorType() {
    const entityId = this._config.entity.toLowerCase();
    if (entityId.includes('inside')) return 'Inside Sensor';
    if (entityId.includes('outside')) return 'Outside Sensor';
    return 'Sensor';
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
    // If no schedule is set, the sensor is active 24/7
    // Return a schedule with all days having 00:00-24:00 slots
    if (!this._hasSchedule()) {
      const allDay = { from: '00:00', to: '24:00' };
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

  _ensureRealSlotExists(day, index) {
    // If the schedule is empty (showing implied 24/7), materialize the slot
    if (!this._hasSchedule()) {
      // Create real 24/7 entries for all days
      const allDay = { from: '00:00', to: '24:00' };
      this._schedule = {
        sunday: [{ ...allDay }],
        monday: [{ ...allDay }],
        tuesday: [{ ...allDay }],
        wednesday: [{ ...allDay }],
        thursday: [{ ...allDay }],
        friday: [{ ...allDay }],
        saturday: [{ ...allDay }],
      };
      return;
    }
    // If the specific day doesn't exist, create it from effective schedule
    if (!this._schedule[day] || !this._schedule[day][index]) {
      const effectiveSlot = this._getEffectiveSchedule()[day]?.[index];
      if (effectiveSlot) {
        if (!this._schedule[day]) {
          this._schedule[day] = [];
        }
        this._schedule[day][index] = { ...effectiveSlot };
      }
    }
  }

  _getScheduleSummary() {
    if (!this._hasSchedule()) return 'Active 24/7 (no schedule set)';

    let totalSlots = 0;
    let activeDays = 0;
    for (const [day, slots] of Object.entries(this._schedule)) {
      if (slots && slots.length > 0) {
        totalSlots += slots.length;
        activeDays++;
      }
    }
    return `${totalSlots} time slot${totalSlots !== 1 ? 's' : ''} across ${activeDays} day${activeDays !== 1 ? 's' : ''}`;
  }

  _formatTime(time) {
    if (!time) return '';
    const [hours, minutes] = time.split(':').map(Number);
    const ampm = hours >= 12 ? 'PM' : 'AM';
    const h = hours % 12 || 12;
    return `${h}:${minutes.toString().padStart(2, '0')} ${ampm}`;
  }

  _formatTimeShort(time) {
    if (!time) return '';
    const [hours, minutes] = time.split(':').map(Number);
    const ampm = hours >= 12 ? 'p' : 'a';
    const h = hours % 12 || 12;
    return `${h}:${minutes.toString().padStart(2, '0')}${ampm}`;
  }

  _parseTimeToMinutes(time) {
    if (!time) return 0;
    const [hours, minutes] = time.split(':').map(Number);
    return hours * 60 + minutes;
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

  _getSlotStyle(slot) {
    const startMinutes = this._parseTimeToMinutes(slot.from);
    const endMinutes = this._parseTimeToMinutes(slot.to);
    const top = (startMinutes / 1440) * 100;
    const height = Math.max(((endMinutes - startMinutes) / 1440) * 100, 1.5);
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

    // Materialize implied slots into real schedule if needed
    this._ensureRealSlotExists(day, index);

    this._editingSlot = { day, index };
    this._isNewSlot = false;
    this.render();
  }

  _handleDayMouseDown(day, event) {
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
    event.stopPropagation();
    event.preventDefault();

    const column = this.shadowRoot.querySelector(`.day-column[data-day="${day}"]`);
    if (!column) return;

    const rect = column.getBoundingClientRect();
    this._columnRects[day] = rect;

    // Materialize implied slots into real schedule if needed
    this._ensureRealSlotExists(day, index);

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

    if (this._dragType === 'create') {
      this._dragCurrentMinutes = minutes;
    } else if (this._dragType === 'resize-top') {
      const slot = this._schedule[this._dragDay][this._dragSlotIndex];
      const bottomMinutes = this._parseTimeToMinutes(slot.to);
      this._dragCurrentMinutes = Math.min(minutes, bottomMinutes - 15);
    } else if (this._dragType === 'resize-bottom') {
      const slot = this._schedule[this._dragDay][this._dragSlotIndex];
      const topMinutes = this._parseTimeToMinutes(slot.from);
      this._dragCurrentMinutes = Math.max(minutes, topMinutes + 15);
    }

    this._updateDragPreview();
  }

  _handleMouseUp(event) {
    document.removeEventListener('mousemove', this._handleMouseMove);
    document.removeEventListener('mouseup', this._handleMouseUp);

    if (!this._isDragging) return;

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
        // Click to create: use the start position, add 15 minutes
        finalStartMin = this._roundToInterval(startMin);
        finalEndMin = Math.min(finalStartMin + 15, 1440);
      }

      const startTime = this._minutesToTime(finalStartMin);
      const endTime = this._minutesToTime(finalEndMin);

      if (!this._schedule[day]) {
        this._schedule[day] = [];
      }

      this._schedule[day].push({ from: startTime, to: endTime });
      this._schedule[day].sort((a, b) =>
        this._parseTimeToMinutes(a.from) - this._parseTimeToMinutes(b.from)
      );

      const sortedIndex = this._schedule[day].findIndex(
        s => s.from === startTime && s.to === endTime
      );

      // Reset drag state BEFORE opening dialog
      this._isDragging = false;
      this._dragType = null;
      this._dragDay = null;
      this._dragStartMinutes = null;
      this._dragCurrentMinutes = null;
      this._dragSlotIndex = null;
      this._dragOriginalSlot = null;

      // Open edit dialog for the new slot
      this._editingSlot = { day, index: sortedIndex };
      this._isNewSlot = true;
      this.render();
      return;

    } else if (this._dragType === 'resize-top' || this._dragType === 'resize-bottom') {
      const slot = this._schedule[this._dragDay][this._dragSlotIndex];
      if (this._dragType === 'resize-top') {
        slot.from = this._minutesToTime(this._dragCurrentMinutes);
      } else {
        slot.to = this._minutesToTime(this._dragCurrentMinutes);
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

    this.render();
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
    if (from && to && from < to) {
      this._schedule[day][index] = { from, to };
      this._editingSlot = null;
      this._isNewSlot = false;
      this._saveSchedule();
      this.render();
    }
  }

  _closeDialog() {
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
    this._editingSlot = null;
    this._isNewSlot = false;
    this.render();
  }

  render() {
    if (!this.shadowRoot) return;

    const sensorType = this._getSensorType();
    const isActive = this._isActive();
    const summary = this._getScheduleSummary();

    // Get current time for the line
    const now = new Date();
    const currentMinutes = now.getHours() * 60 + now.getMinutes();
    const currentTimePct = (currentMinutes / 1440) * 100;

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
        .hint {
          font-size: 11px;
          color: var(--secondary-text-color, #727272);
          margin-top: 8px;
          text-align: center;
        }
        .hint a {
          color: ${this._getSlotColor()};
          cursor: pointer;
          text-decoration: none;
        }
        .hint a:hover {
          text-decoration: underline;
        }

        /* Dialog styles */
        .dialog-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0,0,0,0.5);
          z-index: 999;
          display: flex;
          align-items: center;
          justify-content: center;
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
        <div class="header" id="header">
          <div class="header-left">
            <div class="status-indicator"></div>
            <div class="header-text">
              <div class="title">${sensorType}</div>
              <div class="subtitle">${isActive ? 'Active' : 'Inactive'} · ${summary}</div>
            </div>
          </div>
          <svg class="expand-icon" width="24" height="24" viewBox="0 0 24 24">
            <path fill="currentColor" d="M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z"/>
          </svg>
        </div>

        <div class="content">
          ${this._loading ? `
            <div class="loading">Loading schedule...</div>
          ` : this._error ? `
            <div class="error">${this._error}</div>
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
                  <div class="day-header">${DAY_SHORT[dayIndex]}</div>
                  <div class="day-column" data-day="${day}">
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
            <div class="hint">Click or drag to create. Drag edges to resize. Click slot to edit. <a id="refresh-link">Reload from device</a></div>
          `}
        </div>
      </ha-card>

      ${this._editingSlot ? this._renderEditDialog() : ''}
    `;

    this._attachEventListeners();

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

    return `
      <div class="dialog-overlay" id="dialog-overlay">
        <div class="edit-dialog" id="edit-dialog">
          <div class="dialog-title">${this._isNewSlot ? 'New Time Slot' : 'Edit Time Slot'} - ${sensorType} - ${dayLabel}</div>
          <div class="dialog-row">
            <label for="edit-from">From:</label>
            <input type="time" id="edit-from" value="${slot.from}">
          </div>
          <div class="dialog-row">
            <label for="edit-to">To:</label>
            <input type="time" id="edit-to" value="${slot.to}">
          </div>
          <div class="dialog-buttons">
            ${!this._isNewSlot ? `<button class="delete-btn" id="dialog-delete">Delete</button>` : ''}
            <button class="cancel-btn" id="dialog-cancel">Cancel</button>
            <button class="save-btn" id="dialog-save">Save</button>
          </div>
        </div>
      </div>
    `;
  }

  _attachEventListeners() {
    // Header click to expand/collapse
    const header = this.shadowRoot.getElementById('header');
    if (header) {
      header.addEventListener('click', () => this._handleHeaderClick());
    }

    // Day column mouse events for creating new slots
    this.shadowRoot.querySelectorAll('.day-column').forEach(col => {
      col.addEventListener('mousedown', (e) => {
        if (!e.target.classList.contains('slot-edge')) {
          this._handleDayMouseDown(col.dataset.day, e);
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

    // Time slot clicks for editing
    this.shadowRoot.querySelectorAll('.time-slot').forEach(slot => {
      slot.addEventListener('click', (e) => {
        if (!e.target.classList.contains('slot-edge')) {
          this._handleSlotClick(slot.dataset.day, parseInt(slot.dataset.index), e);
        }
      });
    });

    // Refresh link
    const refreshLink = this.shadowRoot.getElementById('refresh-link');
    if (refreshLink) {
      refreshLink.addEventListener('click', (e) => {
        e.preventDefault();
        this._loadSchedule();
      });
    }

    // Dialog events
    this._attachDialogListeners();
  }

  _attachDialogListeners() {
    const dialogOverlay = this.shadowRoot.getElementById('dialog-overlay');
    const editDialog = this.shadowRoot.getElementById('edit-dialog');
    const dialogCancel = this.shadowRoot.getElementById('dialog-cancel');
    const dialogSave = this.shadowRoot.getElementById('dialog-save');
    const dialogDelete = this.shadowRoot.getElementById('dialog-delete');
    const fromInput = this.shadowRoot.getElementById('edit-from');
    const toInput = this.shadowRoot.getElementById('edit-to');

    if (dialogOverlay) {
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

    const scheduleEntities = Object.keys(this._hass.states)
      .filter(id => id.startsWith('schedule.'));

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
        <label>Schedule Entity</label>
        <select id="entity-select">
          <option value="">Select a schedule entity...</option>
          ${scheduleEntities.map(id => `
            <option value="${id}" ${this._config.entity === id ? 'selected' : ''}>
              ${this._hass.states[id]?.attributes?.friendly_name || id}
            </option>
          `).join('')}
        </select>
      </div>

      <div class="row">
        <label>Slot Color <span class="label-hint">(time slots)</span></label>
        <div class="color-row">
          <input type="color" id="slot-color-picker" value="${this._getColorValue(this._config.slot_color, '#03a9f4')}">
          <input type="text" id="slot-color-text" placeholder="CSS color or variable" value="${this._config.slot_color || ''}">
          <button class="reset-btn" id="slot-color-reset">Reset</button>
        </div>
      </div>

      <div class="row">
        <label>Active Slot Color <span class="label-hint">(currently active time)</span></label>
        <div class="color-row">
          <input type="color" id="active-color-picker" value="${this._getColorValue(this._config.active_slot_color, '#ff9800')}">
          <input type="text" id="active-color-text" placeholder="CSS color or variable" value="${this._config.active_slot_color || ''}">
          <button class="reset-btn" id="active-color-reset">Reset</button>
        </div>
      </div>

      <div class="row">
        <label>Removal Color <span class="label-hint">(when shrinking slots)</span></label>
        <div class="color-row">
          <input type="color" id="removal-color-picker" value="${this._getColorValue(this._config.removal_color, '#f44336')}">
          <input type="text" id="removal-color-text" placeholder="CSS color or variable" value="${this._config.removal_color || ''}">
          <button class="reset-btn" id="removal-color-reset">Reset</button>
        </div>
      </div>
    `;

    // Entity select
    this.shadowRoot.getElementById('entity-select').addEventListener('change', (e) => {
      this._config = { ...this._config, entity: e.target.value };
      this._fireConfigChanged();
    });

    // Slot color
    this.shadowRoot.getElementById('slot-color-picker').addEventListener('input', (e) => {
      this._config = { ...this._config, slot_color: e.target.value };
      this.shadowRoot.getElementById('slot-color-text').value = e.target.value;
      this._fireConfigChanged();
    });
    this.shadowRoot.getElementById('slot-color-text').addEventListener('change', (e) => {
      this._config = { ...this._config, slot_color: e.target.value || undefined };
      this._fireConfigChanged();
    });
    this.shadowRoot.getElementById('slot-color-reset').addEventListener('click', () => {
      delete this._config.slot_color;
      this._fireConfigChanged();
      this.render();
    });

    // Active slot color
    this.shadowRoot.getElementById('active-color-picker').addEventListener('input', (e) => {
      this._config = { ...this._config, active_slot_color: e.target.value };
      this.shadowRoot.getElementById('active-color-text').value = e.target.value;
      this._fireConfigChanged();
    });
    this.shadowRoot.getElementById('active-color-text').addEventListener('change', (e) => {
      this._config = { ...this._config, active_slot_color: e.target.value || undefined };
      this._fireConfigChanged();
    });
    this.shadowRoot.getElementById('active-color-reset').addEventListener('click', () => {
      delete this._config.active_slot_color;
      this._fireConfigChanged();
      this.render();
    });

    // Removal color
    this.shadowRoot.getElementById('removal-color-picker').addEventListener('input', (e) => {
      this._config = { ...this._config, removal_color: e.target.value };
      this.shadowRoot.getElementById('removal-color-text').value = e.target.value;
      this._fireConfigChanged();
    });
    this.shadowRoot.getElementById('removal-color-text').addEventListener('change', (e) => {
      this._config = { ...this._config, removal_color: e.target.value || undefined };
      this._fireConfigChanged();
    });
    this.shadowRoot.getElementById('removal-color-reset').addEventListener('click', () => {
      delete this._config.removal_color;
      this._fireConfigChanged();
      this.render();
    });
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
  '%c POWERPETDOOR-SCHEDULE-CARD %c v1.5.0 ',
  'color: white; background: #03a9f4; font-weight: bold;',
  'color: #03a9f4; background: white; font-weight: bold;'
);
