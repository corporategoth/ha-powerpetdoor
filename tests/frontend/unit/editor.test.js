/**
 * The visual card editor, and the live "now" line.
 *
 * The editor is how the card is configured from the Lovelace UI at all.
 * Finding F9 was that its entity dropdown filtered for `schedule.` - a
 * domain this integration has never created an entity in - so the list was
 * always empty or full of unrelated core schedule helpers, every one of
 * which the API rejects. The card simply could not be configured visually.
 */

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const INSIDE = 'binary_sensor.power_pet_door_inside_schedule';
const OUTSIDE = 'binary_sensor.power_pet_door_outside_schedule';

const mountEditor = async (config = {}, states = null) => {
  loadCard();
  const editor = document.createElement('powerpetdoor-schedule-card-editor');
  editor.setConfig(config);
  editor.hass = makeHass({
    states: states || {
      [INSIDE]: {
        entity_id: INSIDE,
        state: 'on',
        attributes: { friendly_name: 'Inside schedule' },
      },
      [OUTSIDE]: {
        entity_id: OUTSIDE,
        state: 'on',
        attributes: { friendly_name: 'Outside schedule' },
      },
      'light.kitchen': { entity_id: 'light.kitchen', state: 'on', attributes: {} },
      'schedule.core_helper': {
        entity_id: 'schedule.core_helper',
        state: 'on',
        attributes: {},
      },
    },
  });
  document.body.appendChild(editor);
  await flush();
  return editor;
};

describe('the entity dropdown', () => {
  test('lists the integration schedule entities', async () => {
    // Finding F9: filtered on `schedule.`, so it could never list a valid
    // entity and the card was unconfigurable from the UI.
    const editor = await mountEditor({ entity: '' });
    const values = [...editor.shadowRoot.querySelectorAll('option')].map((o) => o.value);

    expect(values).toContain(INSIDE);
    expect(values).toContain(OUTSIDE);
  });

  test('excludes entities that are not schedules', async () => {
    const editor = await mountEditor({ entity: '' });
    const values = [...editor.shadowRoot.querySelectorAll('option')].map((o) => o.value);

    expect(values).not.toContain('light.kitchen');
    // A core `schedule.` helper is NOT one of ours - the WebSocket API
    // refuses it - so offering it would be offering a guaranteed failure.
    expect(values).not.toContain('schedule.core_helper');
  });

  test('offers a placeholder so an unconfigured card is obvious', async () => {
    const editor = await mountEditor({ entity: '' });
    const first = editor.shadowRoot.querySelector('option');

    expect(first.value).toBe('');
    expect(first.textContent).toContain('Select a schedule entity');
  });

  test('marks the configured entity as selected', async () => {
    const editor = await mountEditor({ entity: OUTSIDE });
    const selected = [...editor.shadowRoot.querySelectorAll('option')].find(
      (option) => option.selected,
    );

    expect(selected.value).toBe(OUTSIDE);
  });

  test('choosing an entity tells Lovelace the config changed', async () => {
    // Without the event the picker shows the new value and the dashboard
    // never stores it, so the choice is lost on close.
    const editor = await mountEditor({ entity: '' });
    const changes = [];
    editor.addEventListener('config-changed', (event) => changes.push(event.detail.config));

    const select = editor.shadowRoot.getElementById('entity-select');
    select.value = INSIDE;
    select.dispatchEvent(new Event('change', { bubbles: true }));

    expect(changes).toHaveLength(1);
    expect(changes[0].entity).toBe(INSIDE);
  });

  test('the config-changed event crosses the shadow boundary', async () => {
    // Lovelace listens on an ancestor outside the editor's shadow root, so
    // an event that neither bubbles nor is composed never reaches it.
    const editor = await mountEditor({ entity: '' });
    const seen = [];
    document.body.addEventListener('config-changed', (event) => seen.push(event));

    const select = editor.shadowRoot.getElementById('entity-select');
    select.value = INSIDE;
    select.dispatchEvent(new Event('change', { bubbles: true }));

    expect(seen).toHaveLength(1);
    expect(seen[0].composed).toBe(true);
  });
});

describe.each([
  ['slot', 'slot_color', 'slot-color-picker', 'slot-color-text', 'slot-color-reset'],
  ['active slot', 'active_slot_color', 'active-color-picker', 'active-color-text', 'active-color-reset'],
  ['removal', 'removal_color', 'removal-color-picker', 'removal-color-text', 'removal-color-reset'],
])('the %s colour field', (_label, key, pickerId, textId, resetId) => {
  test('the picker writes the config and mirrors into the text field', async () => {
    // The two inputs edit one value, so leaving them out of step shows the
    // user a colour the card is not using.
    const editor = await mountEditor({ entity: INSIDE });
    const changes = [];
    editor.addEventListener('config-changed', (event) => changes.push(event.detail.config));

    const picker = editor.shadowRoot.getElementById(pickerId);
    picker.value = '#123456';
    picker.dispatchEvent(new Event('input', { bubbles: true }));

    expect(changes.at(-1)[key]).toBe('#123456');
    expect(editor.shadowRoot.getElementById(textId).value).toBe('#123456');
  });

  test('the text field accepts a CSS variable the picker cannot express', async () => {
    // The whole reason there are two inputs: `var(--primary-color)` follows
    // the user's theme and a colour picker can only produce a fixed hex.
    const editor = await mountEditor({ entity: INSIDE });
    const changes = [];
    editor.addEventListener('config-changed', (event) => changes.push(event.detail.config));

    const text = editor.shadowRoot.getElementById(textId);
    text.value = 'var(--my-color)';
    text.dispatchEvent(new Event('change', { bubbles: true }));

    expect(changes.at(-1)[key]).toBe('var(--my-color)');
  });

  test('clearing the text field drops the override rather than storing empty', async () => {
    // An empty string is falsy but still a key in the config, and it would
    // be written to the dashboard YAML as `slot_color: ''`.
    const editor = await mountEditor({ entity: INSIDE, [key]: '#ff0000' });
    const changes = [];
    editor.addEventListener('config-changed', (event) => changes.push(event.detail.config));

    const text = editor.shadowRoot.getElementById(textId);
    text.value = '';
    text.dispatchEvent(new Event('change', { bubbles: true }));

    expect(changes.at(-1)[key]).toBeUndefined();
  });

  test('reset removes the override and re-renders the default', async () => {
    const editor = await mountEditor({ entity: INSIDE, [key]: '#ff0000' });
    const changes = [];
    editor.addEventListener('config-changed', (event) => changes.push(event.detail.config));

    editor.shadowRoot.getElementById(resetId).click();
    await flush();

    expect(changes.at(-1)[key]).toBeUndefined();
    expect(editor.shadowRoot.getElementById(textId).value).toBe('');
  });

  test('a stored hex colour pre-fills the picker', async () => {
    const editor = await mountEditor({ entity: INSIDE, [key]: '#abcdef' });

    expect(editor.shadowRoot.getElementById(pickerId).value).toBe('#abcdef');
    expect(editor.shadowRoot.getElementById(textId).value).toBe('#abcdef');
  });

  test('a stored CSS variable leaves the picker on its default', async () => {
    // `<input type="color">` only accepts hex; assigning a var() would make
    // it silently fall back to #000000 and show black as the current colour.
    const editor = await mountEditor({ entity: INSIDE, [key]: 'var(--accent-color)' });

    expect(editor.shadowRoot.getElementById(pickerId).value).toMatch(/^#[0-9a-f]{6}$/);
    expect(editor.shadowRoot.getElementById(pickerId).value).not.toBe('#000000');
    expect(editor.shadowRoot.getElementById(textId).value).toBe('var(--accent-color)');
  });
});

describe('the editor before hass arrives', () => {
  test('setConfig alone does not throw', () => {
    // Lovelace calls setConfig before assigning hass, so a render that
    // assumed hass would blank the whole editor pane.
    loadCard();
    const editor = document.createElement('powerpetdoor-schedule-card-editor');

    expect(() => editor.setConfig({ entity: INSIDE })).not.toThrow();
    expect(editor.shadowRoot.innerHTML).toBe('');
  });
});

describe('the current-time line', () => {
  test('an expanded card starts tracking the time when it is attached', async () => {
    // connectedCallback runs on re-attach - switching dashboard views does
    // exactly this - and an expanded card must resume its minute timer or
    // the red line freezes where it was.
    jest.useFakeTimers();
    try {
      loadCard();
      const card = document.createElement('powerpetdoor-schedule-card');
      card.setConfig({ entity: INSIDE });
      card.hass = makeHass();
      card._expanded = true;
      card.render();

      document.body.appendChild(card);

      expect(card._currentTimeInterval).not.toBeNull();
      card.remove();
      expect(card._currentTimeInterval).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  test('a collapsed card does not run a timer', async () => {
    // A hidden card ticking every minute on every dashboard is wasted work
    // in a page that may hold dozens of cards.
    jest.useFakeTimers();
    try {
      loadCard();
      const card = document.createElement('powerpetdoor-schedule-card');
      card.setConfig({ entity: INSIDE });
      card.hass = makeHass();
      document.body.appendChild(card);

      expect(card._currentTimeInterval).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  test('the line is positioned at the current time of day', async () => {
    jest.useFakeTimers().setSystemTime(new Date(2026, 7, 24, 6, 0, 0));
    try {
      loadCard();
      const card = document.createElement('powerpetdoor-schedule-card');
      card.setConfig({ entity: INSIDE });
      card.hass = makeHass();
      document.body.appendChild(card);
      // Let _loadSchedule settle before rendering the grid. `flush()` is
      // setTimeout-based and fake timers freeze it, so drain microtasks.
      await Promise.resolve();
      await Promise.resolve();
      card._handleHeaderClick();

      card._updateCurrentTime();

      // 06:00 is a quarter of the way down the day.
      expect(card.shadowRoot.querySelector('.current-time-line').style.top).toBe('25%');
    } finally {
      jest.useRealTimers();
    }
  });

  test('the window covering now is highlighted, and only that one', async () => {
    // Finding Fm1: the highlight read `_schedule` while the grid drew
    // `_getEffectiveSchedule()`, so on a door with no schedule the implied
    // all-day bars were never highlighted at all.
    jest.useFakeTimers().setSystemTime(new Date(2026, 7, 24, 12, 0, 0)); // a Monday
    try {
      loadCard();
      const card = document.createElement('powerpetdoor-schedule-card');
      card.setConfig({ entity: INSIDE });
      const hass = makeHass();
      hass.callWS = jest.fn().mockResolvedValue({
        entity_id: INSIDE,
        kind: 'inside',
        schedule: {
          monday: [{ from: '06:00', to: '20:00' }, { from: '21:00', to: '22:00' }],
        },
      });
      card.hass = hass;
      document.body.appendChild(card);
      await Promise.resolve();
      await Promise.resolve();
      card._handleHeaderClick();

      card._updateActiveSlotHighlight();

      const active = [...card.shadowRoot.querySelectorAll('.time-slot.active-now')];
      expect(active).toHaveLength(1);
      expect(active[0].dataset.day).toBe('monday');
      expect(active[0].dataset.index).toBe('0');
    } finally {
      jest.useRealTimers();
    }
  });

  test('a door with no schedule highlights its implied all-day window', async () => {
    jest.useFakeTimers().setSystemTime(new Date(2026, 7, 24, 12, 0, 0));
    try {
      loadCard();
      const card = document.createElement('powerpetdoor-schedule-card');
      card.setConfig({ entity: INSIDE });
      card.hass = makeHass();
      document.body.appendChild(card);
      await Promise.resolve();
      await Promise.resolve();
      card._handleHeaderClick();

      card._updateActiveSlotHighlight();

      const active = [...card.shadowRoot.querySelectorAll('.time-slot.active-now')];
      expect(active).toHaveLength(1);
      expect(active[0].dataset.day).toBe('monday');
    } finally {
      jest.useRealTimers();
    }
  });
});

describe('materialising an implied window', () => {
  test('editing one implied day turns the whole week into real windows', async () => {
    // A door with no schedule is on 24/7 and the grid draws that. Editing
    // one of those bars has to write the other six days out too, or saving
    // would switch the sensor off for every day the user did not touch.
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    card.setConfig({ entity: INSIDE });
    card.hass = makeHass();

    card._ensureRealSlotExists();

    expect(Object.keys(card._schedule).sort()).toEqual([
      'friday', 'monday', 'saturday', 'sunday', 'thursday', 'tuesday', 'wednesday',
    ]);
    expect(card._schedule.monday).toEqual([{ from: '00:00', to: '00:00' }]);
  });

  test('a day absent from a real schedule gains nothing', async () => {
    // Once any real window exists the implied all-day state is gone, so a
    // day with no window stays that way. Inventing one would add coverage
    // the user never asked for - and would silently re-enable a sensor they
    // had just switched off for that day.
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    card.setConfig({ entity: INSIDE });
    card.hass = makeHass();
    card._schedule = { monday: [{ from: '06:00', to: '20:00' }] };

    card._ensureRealSlotExists();

    expect(card._schedule.tuesday).toBeUndefined();
    expect(card._schedule.monday).toEqual([{ from: '06:00', to: '20:00' }]);
  });

  test('a second window on a day is inserted in time order', async () => {
    // The grid indexes windows by position, so an unsorted list makes a
    // click on one open the editor for another.
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    card.setConfig({ entity: INSIDE });
    card.hass = makeHass();
    card._schedule = { monday: [{ from: '06:00', to: '08:00' }] };

    card._createDefaultSlot('monday');

    expect(card._schedule.monday.map((slot) => slot.from)).toEqual(['06:00', '09:00']);
    expect(card._editingSlot).toEqual({ day: 'monday', index: 1 });
  });

  test('an existing window is left exactly as it is', async () => {
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    card.setConfig({ entity: INSIDE });
    card.hass = makeHass();
    card._schedule = { monday: [{ from: '06:00', to: '20:00' }] };

    card._ensureRealSlotExists();

    expect(card._schedule.monday).toEqual([{ from: '06:00', to: '20:00' }]);
  });
});

describe('every editor control has a name of its own', () => {
  // The editor is nine controls, six of which carry no text: three colour
  // swatches, three free-text fields and three buttons that all read
  // "Reset". The only labelling was a <label> with no `for`, which names
  // nothing at all - so a screen reader user configuring the card was
  // offered "edit text, edit text, edit text, button Reset, button Reset,
  // button Reset" and could not tell which colour any of them set.

  /** The accessible name of a control, by the two rules the editor uses. */
  const accessibleName = (shadowRoot, id) => {
    const element = shadowRoot.getElementById(id);
    const label = element.getAttribute('aria-label');
    if (label) return label;
    const explicit = shadowRoot.querySelector(`label[for="${id}"]`);
    return explicit ? explicit.textContent.trim().replace(/\s+/g, ' ') : null;
  };

  const CONTROL_IDS = [
    'entity-select',
    'slot-color-picker',
    'slot-color-text',
    'slot-color-reset',
    'active-color-picker',
    'active-color-text',
    'active-color-reset',
    'removal-color-picker',
    'removal-color-text',
    'removal-color-reset',
  ];

  test('nothing in the editor is unnamed', async () => {
    const editor = await mountEditor({ entity: INSIDE });

    for (const id of CONTROL_IDS) {
      expect(accessibleName(editor.shadowRoot, id)).toBeTruthy();
    }
  });

  test('no two controls share a name', async () => {
    // The point of the finding: three buttons called "Reset" are three
    // buttons the user cannot choose between.
    const editor = await mountEditor({ entity: INSIDE });
    const names = CONTROL_IDS.map((id) => accessibleName(editor.shadowRoot, id));

    expect(new Set(names).size).toBe(CONTROL_IDS.length);
  });

  test('each name says which colour it belongs to', async () => {
    const editor = await mountEditor({ entity: INSIDE });

    expect(accessibleName(editor.shadowRoot, 'slot-color-reset')).toBe('Reset Slot Color');
    expect(accessibleName(editor.shadowRoot, 'active-color-picker')).toBe(
      'Active Slot Color swatch',
    );
    expect(accessibleName(editor.shadowRoot, 'removal-color-text')).toBe(
      'Removal Color (when shrinking slots)',
    );
  });
});
