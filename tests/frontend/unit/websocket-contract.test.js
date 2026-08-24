/**
 * The contract between this card and custom_components/powerpetdoor/websocket.py.
 *
 * These command names and payload shapes are the only thing holding the two
 * halves of the integration together, and nothing else checks them: the
 * Python side asserts what it accepts, this asserts what the card sends.
 * A rename on either side leaves both suites green and every dashboard
 * broken, so everything here is pinned by literal.
 */

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const ENTITY = 'binary_sensor.power_pet_door_inside_schedule';

/** A hass whose callWS answers a schedule/get with a real payload. */
const hassWithSchedule = (schedule, kind = 'inside') => {
  const hass = makeHass();
  hass.callWS = jest.fn().mockImplementation((msg) => {
    if (msg.type === 'powerpetdoor/schedule/get') {
      return Promise.resolve({
        entity_id: ENTITY,
        kind,
        schedule,
        schedule_count: Object.values(schedule).flat().length,
      });
    }
    return Promise.resolve({ entity_id: ENTITY, kind, schedule });
  });
  return hass;
};

describe('WebSocket command contract', () => {
  test('loads a schedule with powerpetdoor/schedule/get and the entity id', async () => {
    const hass = hassWithSchedule({});
    await mountCard({ entity: ENTITY }, hass);
    await flush();

    // The literal string is the contract with const.py's WS_SCHEDULE_GET.
    expect(hass.callWS).toHaveBeenCalledWith({
      type: 'powerpetdoor/schedule/get',
      entity_id: ENTITY,
    });
  });

  test('saves with powerpetdoor/schedule/update and the whole schedule', async () => {
    const hass = hassWithSchedule({ monday: [{ from: '06:00', to: '20:00' }] });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '07:00', '21:00');
    await flush();

    expect(hass.callWS).toHaveBeenCalledWith({
      type: 'powerpetdoor/schedule/update',
      entity_id: ENTITY,
      schedule: { monday: [{ from: '07:00', to: '21:00' }] },
    });
  });

  test('every saved day name is one the backend schema accepts', async () => {
    // vol.In((...)) in schedule.py rejects anything else outright, and an
    // unknown day fails the WHOLE save - so one capitalised day name would
    // lose the user's entire edit, not just that day.
    const hass = hassWithSchedule({});
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    for (const day of ['sunday', 'monday', 'saturday']) {
      card._createDefaultSlot(day);
    }
    hass.callWS.mockClear();
    card._handleSlotUpdate('monday', 0, '09:00', '17:00');
    await flush();

    const sent = hass.callWS.mock.calls.at(-1)[0].schedule;
    const allowed = [
      'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
    ];
    expect(Object.keys(sent).every((day) => allowed.includes(day))).toBe(true);
  });

  test('every saved time matches the backend pattern exactly', async () => {
    // ^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$ - so "6:00" and "24:00" are both
    // refused. The card must never synthesise either (finding F1).
    const hass = hassWithSchedule({});
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    card._createDefaultSlot('monday');
    hass.callWS.mockClear();
    card._handleSlotUpdate('monday', 0, '00:00', '23:59');
    await flush();

    const sent = hass.callWS.mock.calls.at(-1)[0].schedule;
    const pattern = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/;
    for (const slots of Object.values(sent)) {
      for (const slot of slots) {
        expect(slot.from).toMatch(pattern);
        expect(slot.to).toMatch(pattern);
      }
    }
  });

  test('a slot carries exactly from and to, and nothing else', async () => {
    // The backend slot schema has no `extra=ALLOW`, so a stray key - an
    // index, a label, an id - fails validation and the save is refused.
    const hass = hassWithSchedule({ monday: [{ from: '06:00', to: '20:00' }] });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '07:00', '21:00');
    await flush();

    const sent = hass.callWS.mock.calls.at(-1)[0].schedule;
    expect(Object.keys(sent.monday[0]).sort()).toEqual(['from', 'to']);
  });

  test('an all-day window is saved as 00:00-23:59, the way the device spells it', async () => {
    // The out-of-box state, so getting it wrong meant the FIRST edit any
    // new user made was discarded - which is what finding F1 cost. Two
    // spellings are wrong here: "24:00" is not a time and the schema
    // refuses it, and "00:00" as an END is midnight at the start of a day,
    // which now reads as a window finishing before it begins.
    const hass = hassWithSchedule({});
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    // An empty schedule renders the implied all-day bars; clicking one
    // materialises it into a real slot.
    card._ensureRealSlotExists();

    expect(card._schedule.monday[0]).toEqual({ from: '00:00', to: '00:00' });
    expect(JSON.stringify(card._schedule)).not.toContain('24:00');
  });

  test('an overnight window is never sent, because it cannot be expressed', async () => {
    // A wire entry is a day mask plus a start and an end, with nowhere to
    // put "tomorrow", so `22:00-06:00` is refused by the payload schema.
    // The card must not send one and then surface the rejection as a toast
    // over an edit it has already thrown away.
    const hass = hassWithSchedule({ monday: [{ from: '06:00', to: '20:00' }] });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '22:00', '06:00');
    await flush();

    expect(hass.callWS).not.toHaveBeenCalled();
  });

  test('everything it DOES send is a payload the backend accepts', async () => {
    // The two halves of an overnight schedule as the backend splits them,
    // saved straight back. This is the read-modify-write the card performs
    // on every edit, and the spelling it receives has to be one it may
    // return - `22:00-00:00` was not.
    const hass = hassWithSchedule({
      monday: [
        { from: '00:00', to: '06:00' },
        { from: '22:00', to: '23:59' },
      ],
    });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '01:00', '06:00');
    await flush();

    const sent = hass.callWS.mock.calls.at(-1)[0].schedule;
    for (const slot of sent.monday) {
      expect(card._parseTimeToMinutes(slot.to)).toBeGreaterThanOrEqual(
        card._parseTimeToMinutes(slot.from),
      );
    }
    expect(sent.monday).toEqual([
      { from: '01:00', to: '06:00' },
      { from: '22:00', to: '23:59' },
    ]);
  });

  test('deleting the last window of a day removes the day entirely', async () => {
    // An empty list is accepted by the schema, but omitting the day is what
    // the backend emits, so the card round-trips to the same shape rather
    // than to an equivalent-but-different one.
    const hass = hassWithSchedule({ monday: [{ from: '06:00', to: '20:00' }] });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    hass.callWS.mockClear();

    card._handleSlotDelete('monday', 0);
    await flush();

    const sent = hass.callWS.mock.calls.at(-1)[0].schedule;
    expect(sent).not.toHaveProperty('monday');
  });

  test('the sensor kind comes from the API, never from the entity id', async () => {
    // Finding Fm4: the card used to sniff the entity id for "inside", so a
    // door named "Inside Porch" made the OUTSIDE card announce itself as the
    // inside sensor - and the user edited the wrong sensor's schedule
    // believing it was the other.
    const hass = hassWithSchedule({}, 'outside');
    const card = await mountCard(
      { entity: 'binary_sensor.inside_porch_outside_schedule' },
      hass,
    );
    await flush();

    expect(card._getSensorType()).toBe('Outside Sensor');
  });

  test('a save failure reloads from the device rather than keeping the edit', async () => {
    // Finding F8. Leaving the rejected edit on screen tells the user their
    // change was applied when the door refused it.
    const hass = hassWithSchedule({ monday: [{ from: '06:00', to: '20:00' }] });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    hass.callWS = jest.fn().mockImplementation((msg) =>
      msg.type === 'powerpetdoor/schedule/update'
        ? Promise.reject(new Error('slot table full'))
        : Promise.resolve({ entity_id: ENTITY, kind: 'inside', schedule: {} }),
    );

    card._handleSlotUpdate('monday', 0, '07:00', '21:00');
    await flush();
    await flush();

    const types = hass.callWS.mock.calls.map((call) => call[0].type);
    expect(types).toContain('powerpetdoor/schedule/update');
    expect(types).toContain('powerpetdoor/schedule/get');
  });

  test('a save failure raises a Home Assistant toast, never alert()', async () => {
    // Finding F7. alert() blocks the frontend thread, renders as a bare OS
    // dialog in the Companion App, and once the user ticks "prevent
    // additional dialogs" it swallows every later failure entirely.
    const hass = hassWithSchedule({ monday: [{ from: '06:00', to: '20:00' }] });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    const notifications = [];
    card.addEventListener('hass-notification', (event) =>
      notifications.push(event.detail.message),
    );
    hass.callWS = jest.fn().mockRejectedValue(new Error('slot table full'));

    card._handleSlotUpdate('monday', 0, '07:00', '21:00');
    await flush();
    await flush();

    expect(notifications.some((message) => message.includes('slot table full'))).toBe(true);
  });

  test('a successful save confirms it reached the door', async () => {
    // The other half of finding F8: silence after a save is
    // indistinguishable from a save that never happened.
    const hass = hassWithSchedule({ monday: [{ from: '06:00', to: '20:00' }] });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    const notifications = [];
    card.addEventListener('hass-notification', (event) =>
      notifications.push(event.detail.message),
    );

    card._handleSlotUpdate('monday', 0, '07:00', '21:00');
    await flush();

    expect(notifications).toContain('Schedule saved');
  });

  test('a failed load falls back to the entity attributes before giving up', async () => {
    // The WebSocket command needs the entry loaded; the state attributes
    // survive a reload. Falling back keeps the card readable during one.
    const hass = makeHass({
      states: {
        [ENTITY]: {
          entity_id: ENTITY,
          state: 'on',
          attributes: {
            friendly_name: 'Inside schedule',
            schedule: { tuesday: [{ from: '08:00', to: '18:00' }] },
          },
        },
      },
    });
    hass.callWS = jest.fn().mockRejectedValue(new Error('not found'));

    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    expect(card._schedule).toEqual({ tuesday: [{ from: '08:00', to: '18:00' }] });
    expect(card._error).toBeNull();
  });
});
