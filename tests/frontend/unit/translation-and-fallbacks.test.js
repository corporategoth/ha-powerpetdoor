/**
 * Translation lookup and the defensive defaults around it.
 *
 * Home Assistant's translation machinery covers integrations, not custom
 * cards: there is no `strings.json` a card can register and `hass.localize`
 * only resolves keys HA itself shipped. So the card carries its own
 * catalogue, and `t()` is on every render path - which means it must never
 * throw. A missing key has to render as something, because an exception
 * here blanks the whole card rather than one label.
 *
 * scripts/check_translations.py reads the same table and fails the build on
 * a `t()` call whose key is missing; this asserts the runtime behaviour when
 * one slips through anyway.
 */

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const ENTITY = 'binary_sensor.power_pet_door_inside_schedule';

/** `t` is module-private, so it is reached through a method that uses it. */
const translateVia = (card, hass, key) => {
  card._hass = hass;
  // _getSensorType() maps a kind onto exactly one catalogue key.
  card._kind = key;
  return card._getSensorType();
};

describe('translation lookup', () => {
  let card;

  beforeEach(() => {
    loadCard();
    card = document.createElement('powerpetdoor-schedule-card');
  });

  test('an English user gets the English string', () => {
    expect(translateVia(card, makeHass({ language: 'en' }), 'inside')).toBe('Inside Sensor');
  });

  test('a language with no catalogue falls back to English', () => {
    // Adding a language must never be able to blank the card for everyone
    // who does not speak it.
    expect(translateVia(card, makeHass({ language: 'fr' }), 'inside')).toBe('Inside Sensor');
  });

  test('a hass with no language at all still renders', () => {
    // `hass.language` is unset early in the frontend's startup, and the card
    // renders during that window.
    expect(translateVia(card, makeHass({ language: undefined }), 'inside')).toBe(
      'Inside Sensor',
    );
  });

  test('no hass at all still renders', () => {
    // setConfig runs before `hass` is assigned, and it calls render().
    card._hass = null;
    card._kind = 'inside';
    expect(card._getSensorType()).toBe('Inside Sensor');
  });

  test('an unconfigured card with no hass throws a readable setConfig error', () => {
    // The message reaches the Lovelace editor as the card's error text, so
    // it has to come out of the catalogue's English fallback rather than as
    // a raw key or an exception about `hass` being null.
    const fresh = document.createElement('powerpetdoor-schedule-card');
    expect(() => fresh.setConfig({})).toThrow('Please define an entity');
  });

  test('a kind the API has never sent falls back to a generic label', () => {
    // A third sensor kind would otherwise render as `undefined` in the
    // card's title.
    expect(translateVia(card, makeHass(), 'something_new')).toBe('Sensor');
  });

  test('placeholders are substituted, and every one of them', () => {
    // The summary line has four. A loop that stopped at the first would
    // leave literal `{days}` on the dashboard.
    card._hass = makeHass();
    card._schedule = {
      monday: [{ from: '06:00', to: '20:00' }],
      tuesday: [{ from: '06:00', to: '20:00' }],
    };
    const summary = card._getScheduleSummary();

    expect(summary).toBe('2 time slots across 2 days');
    expect(summary).not.toMatch(/[{}]/);
  });
});

describe('defensive rendering paths', () => {
  test('a load failure with no message still shows something', async () => {
    // `callWS` can reject with a bare object rather than an Error - Home
    // Assistant's own WebSocket layer does exactly that for some failures -
    // so `err.message` is undefined and the card must not render "undefined".
    const hass = makeHass();
    hass.callWS = jest.fn().mockRejectedValue({});

    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    expect(card._error).toBe('Failed to load schedule');
    expect(card.shadowRoot.querySelector('.error').textContent).toContain(
      'Failed to load schedule',
    );
  });

  test('a save failure with no message still raises a readable toast', async () => {
    const hass = makeHass();
    hass.callWS = jest.fn().mockImplementation((msg) =>
      msg.type === 'powerpetdoor/schedule/get'
        ? Promise.resolve({ entity_id: ENTITY, kind: 'inside', schedule: { monday: [{ from: '06:00', to: '20:00' }] } })
        : Promise.reject('plain string rejection'),
    );
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    const messages = [];
    card.addEventListener('hass-notification', (event) => messages.push(event.detail.message));

    card._handleSlotUpdate('monday', 0, '07:00', '21:00');
    await flush();
    await flush();

    expect(messages.some((message) => message.includes('plain string rejection'))).toBe(true);
    expect(messages.every((message) => !message.includes('undefined'))).toBe(true);
  });

  test('a get that answers without a schedule is treated as an empty one', async () => {
    // A door whose slot table is empty answers with no `schedule` key at
    // all. Reading `.schedule` off that must not throw, and the card must
    // fall back to the implied all-day view rather than a blank grid.
    const hass = makeHass();
    hass.callWS = jest.fn().mockResolvedValue({ entity_id: ENTITY });

    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    expect(card._schedule).toEqual({});
    expect(card._kind).toBeNull();
  });

  test('updating the time line before the grid exists does nothing bad', async () => {
    // The interval can fire between a config change and the next render.
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    card.setConfig({ entity: ENTITY });
    card._hass = makeHass();

    expect(() => card._updateCurrentTime()).not.toThrow();
  });

  test('a card with no entity configured never asks the backend anything', async () => {
    // `hass` is assigned before `setConfig` in some Lovelace paths, and a
    // `schedule/get` with an empty entity_id is a guaranteed error toast.
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    const hass = makeHass();
    card._config = {};
    card.hass = hass;
    await flush();

    expect(hass.callWS).not.toHaveBeenCalled();
  });

  test('a slot label for an unknown day names the day rather than crashing', async () => {
    // `_slotLabel` is fed from the effective schedule, and a door that sent
    // a day key the card does not know would otherwise index DAY_LABELS
    // with -1 and announce "undefined".
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    card.setConfig({ entity: ENTITY });
    card._hass = makeHass();

    const label = card._slotLabel('funday', { from: '06:00', to: '20:00' });

    expect(label).toContain('funday');
    expect(label).not.toContain('undefined');
  });

  test('a window covering now is announced as active', async () => {
    jest.useFakeTimers().setSystemTime(new Date(2026, 7, 24, 12, 0, 0));
    try {
      loadCard();
      const card = document.createElement('powerpetdoor-schedule-card');
      card.setConfig({ entity: ENTITY });
      card._hass = makeHass();

      const covering = card._slotLabel('monday', { from: '06:00', to: '20:00' });
      const notCovering = card._slotLabel('monday', { from: '01:00', to: '02:00' });

      expect(covering).toContain('active now');
      expect(notCovering).not.toContain('active now');
    } finally {
      jest.useRealTimers();
    }
  });

  test('a drag preview on a day with no preview element is harmless', async () => {
    // The preview lives inside the grid, which only exists once expanded.
    // A drag started against a collapsed card must not throw.
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    card.setConfig({ entity: ENTITY });
    card._hass = makeHass();
    document.body.appendChild(card);

    expect(() => card._hideDragPreview('monday')).not.toThrow();
    expect(() => card._showDragPreview('monday')).not.toThrow();
  });

  test('a mouse move with no drag in progress is ignored', async () => {
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');
    card.setConfig({ entity: ENTITY });
    card._hass = makeHass();

    expect(() =>
      card._handleMouseMove(new MouseEvent('mousemove', { clientY: 100 })),
    ).not.toThrow();
    expect(card._dragCurrentMinutes).toBeNull();
  });
});
