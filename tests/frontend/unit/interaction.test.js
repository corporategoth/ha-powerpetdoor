/**
 * Creating, resizing, editing and deleting a window with a pointer and a key.
 *
 * This is where findings F1 to F4 and F11 lived, and every one of them was a
 * gesture that appeared to work and silently did nothing. The tests below
 * drive real DOM events rather than calling handlers where they can, because
 * three of those findings were in the wiring - which listener was attached
 * to which element - rather than in the maths.
 */

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const ENTITY = 'binary_sensor.power_pet_door_inside_schedule';

/** A card, expanded, holding `schedule`. */
const openCard = async (schedule = {}, hassOverrides = {}) => {
  const hass = makeHass(hassOverrides);
  hass.callWS = jest.fn().mockImplementation((msg) =>
    msg.type === 'powerpetdoor/schedule/get'
      ? Promise.resolve({ entity_id: ENTITY, kind: 'inside', schedule })
      : Promise.resolve({ entity_id: ENTITY, kind: 'inside', schedule }),
  );
  const card = await mountCard({ entity: ENTITY }, hass);
  await flush();
  card._handleHeaderClick();
  await flush();
  return { card, hass };
};

/** Dispatch a mouse event at a y offset inside a 480px-tall column. */
const mouse = (target, type, clientY) =>
  target.dispatchEvent(
    new MouseEvent(type, { clientY, clientX: 10, bubbles: true, cancelable: true }),
  );

describe('expanding the card', () => {
  test('a collapsed card hides the grid and says so', async () => {
    // The grid is always in the DOM and `_expanded` toggles its CSS display,
    // so the assertion is on the style rule and on aria-expanded - the two
    // things a user and a screen reader respectively actually observe.
    const hass = makeHass();
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    expect(card.shadowRoot.getElementById('header').getAttribute('aria-expanded')).toBe(
      'false',
    );
    expect(card.shadowRoot.querySelector('style').textContent).toContain(
      '.content {\n          display: none;',
    );
  });

  test('expanding shows the grid and all seven days', async () => {
    const { card } = await openCard();

    expect(card.shadowRoot.getElementById('header').getAttribute('aria-expanded')).toBe(
      'true',
    );
    expect(card.shadowRoot.querySelector('style').textContent).toContain(
      '.content {\n          display: block;',
    );
    expect(card.shadowRoot.querySelectorAll('.day-column')).toHaveLength(7);
  });

  test('collapsing again hides it', async () => {
    const { card } = await openCard();
    card._handleHeaderClick();
    await flush();

    expect(card.shadowRoot.getElementById('header').getAttribute('aria-expanded')).toBe(
      'false',
    );
  });

  test('the card reports a taller size when expanded', async () => {
    // Lovelace lays out a masonry column from this; a card that always
    // claimed one row would overlap whatever is beneath it once opened.
    const { card } = await openCard();
    expect(card.getCardSize()).toBe(4);

    card._handleHeaderClick();
    await flush();
    expect(card.getCardSize()).toBe(1);
  });
});

describe('creating a window by dragging', () => {
  test('a drag down the column creates a window spanning what was dragged', async () => {
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    // 480px tall = 1440 minutes, so 1px = 3 minutes. 120px is 06:00.
    mouse(column, 'mousedown', 120);
    mouse(document, 'mousemove', 240);
    mouse(document, 'mouseup', 240);
    await flush();

    expect(card._schedule.monday).toEqual([{ from: '06:00', to: '12:00' }]);
  });

  test('a drag UPWARD creates the same window as the equivalent drag down', async () => {
    // The drag is normalised with min/max. Without that, dragging upward
    // produced a window whose end preceded its start, which the backend
    // reads as a midnight-crossing window - so an upward drag from noon to
    // 6am silently created an 18-hour overnight window.
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    mouse(column, 'mousedown', 240);
    mouse(document, 'mousemove', 120);
    mouse(document, 'mouseup', 120);
    await flush();

    expect(card._schedule.monday).toEqual([{ from: '06:00', to: '12:00' }]);
  });

  test('a click without dragging creates a fifteen-minute window', async () => {
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="tuesday"]');

    mouse(column, 'mousedown', 120);
    mouse(document, 'mouseup', 120);
    await flush();

    expect(card._schedule.tuesday).toEqual([{ from: '06:00', to: '06:15' }]);
  });

  test('a drag to the very top of the column starts at midnight', async () => {
    // The boundary at 00:00. An off-by-one here would produce "-00:15",
    // which the backend refuses outright.
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    mouse(column, 'mousedown', 0);
    mouse(document, 'mousemove', 60);
    mouse(document, 'mouseup', 60);
    await flush();

    expect(card._schedule.monday[0].from).toBe('00:00');
  });

  test('a drag past the bottom of the column ends at midnight, not 24:00', async () => {
    // The other boundary, and the one finding F1 was about: "24:00" is not
    // a time Home Assistant's format can carry, so a window ending there
    // could never be saved. Midnight is how that shape spells it - and it
    // has to be midnight rather than 23:59, or a drag to the very bottom
    // silently stops a minute short of the day it plainly reached.
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    mouse(column, 'mousedown', 400);
    mouse(document, 'mousemove', 5000);
    mouse(document, 'mouseup', 5000);
    await flush();

    expect(card._schedule.monday[0].to).toBe('00:00');
    expect(card._slotEndMinutes(card._schedule.monday[0])).toBe(1440);
  });

  test('a new window opens its editor rather than saving straight away', async () => {
    // A window created by dragging has arbitrary bounds; saving it
    // immediately would write a rough guess to the door.
    const { card, hass } = await openCard();
    hass.callWS.mockClear();
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    mouse(column, 'mousedown', 120);
    mouse(document, 'mousemove', 240);
    mouse(document, 'mouseup', 240);
    await flush();

    expect(card.shadowRoot.getElementById('edit-dialog')).not.toBeNull();
    expect(hass.callWS).not.toHaveBeenCalled();
  });

  test('cancelling a new window removes it again', async () => {
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');
    mouse(column, 'mousedown', 120);
    mouse(document, 'mousemove', 240);
    mouse(document, 'mouseup', 240);
    await flush();

    card.shadowRoot.getElementById('dialog-cancel').click();
    await flush();

    expect(card._schedule.monday).toBeUndefined();
  });

  test('windows are kept in time order', async () => {
    // The grid indexes slots by position, so an unsorted list makes a click
    // on one window open the editor for another.
    const { card } = await openCard({ monday: [{ from: '18:00', to: '20:00' }] });
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    mouse(column, 'mousedown', 120);
    mouse(document, 'mousemove', 240);
    mouse(document, 'mouseup', 240);
    await flush();

    expect(card._schedule.monday.map((slot) => slot.from)).toEqual(['06:00', '18:00']);
  });
});

describe('resizing a window', () => {
  test('dragging the top edge moves the start and saves', async () => {
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.top[data-day="monday"][data-index="0"]',
    );
    hass.callWS.mockClear();

    mouse(edge, 'mousedown', 120);
    mouse(document, 'mousemove', 240);
    mouse(document, 'mouseup', 240);
    await flush();

    expect(card._schedule.monday[0]).toEqual({ from: '12:00', to: '20:00' });
    expect(hass.callWS).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'powerpetdoor/schedule/update' }),
    );
  });

  test('dragging the bottom edge moves the end and saves', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 400);
    mouse(document, 'mousemove', 300);
    mouse(document, 'mouseup', 300);
    await flush();

    expect(card._schedule.monday[0]).toEqual({ from: '06:00', to: '15:00' });
  });

  test('the top edge cannot be dragged past the bottom', async () => {
    // Without the clamp this inverts the window, which the backend reads as
    // a midnight-crossing one - so shrinking a window to nothing silently
    // turned it into an all-night window instead.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.top[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 120);
    mouse(document, 'mousemove', 400);
    mouse(document, 'mouseup', 400);
    await flush();

    const slot = card._schedule.monday[0];
    expect(card._parseTimeToMinutes(slot.from)).toBeLessThan(
      card._parseTimeToMinutes(slot.to),
    );
    expect(slot).toEqual({ from: '07:45', to: '08:00' });
  });

  test('the bottom edge cannot be dragged above the top', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 160);
    mouse(document, 'mousemove', 0);
    mouse(document, 'mouseup', 0);
    await flush();

    expect(card._schedule.monday[0]).toEqual({ from: '06:00', to: '06:15' });
  });

  test('a click that lands on an edge without moving does not save', async () => {
    // Finding F3. A window under ~2 hours is 14px tall and its two 8px
    // edges leave a 6px band, so most clicks aimed at it land on an edge.
    // That began a resize whose immediate mouseup wrote the slot back
    // unchanged - a WebSocket round trip and a schedule read on the door -
    // and the re-render destroyed the node before the click could open the
    // dialog. The user clicked their window and nothing happened, every
    // time. This blocked touch entirely.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '07:00' }] });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.top[data-day="monday"][data-index="0"]',
    );
    hass.callWS.mockClear();

    mouse(edge, 'mousedown', 120);
    mouse(document, 'mouseup', 120);
    await flush();

    expect(hass.callWS).not.toHaveBeenCalled();
    expect(card._schedule.monday[0]).toEqual({ from: '06:00', to: '07:00' });
  });

  test('a click on an edge still opens the editor', async () => {
    // The other half of finding F3: dropping the no-op resize is only
    // useful if the click then gets through to the dialog.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '07:00' }] });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.top[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 120);
    mouse(document, 'mouseup', 120);
    edge.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    await flush();

    expect(card.shadowRoot.getElementById('edit-dialog')).not.toBeNull();
  });
});

describe('the edit dialog', () => {
  test('clicking a window opens its editor with the stored times', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });

    card.shadowRoot
      .querySelector('.time-slot[data-day="monday"][data-index="0"]')
      .dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    await flush();

    expect(card.shadowRoot.getElementById('edit-from').value).toBe('06:00');
    expect(card.shadowRoot.getElementById('edit-to').value).toBe('20:00');
  });

  test('saving writes the edited times', async () => {
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();
    hass.callWS.mockClear();

    card.shadowRoot.getElementById('edit-from').value = '07:30';
    card.shadowRoot.getElementById('edit-to').value = '21:30';
    card.shadowRoot.getElementById('dialog-save').click();
    await flush();

    expect(card._schedule.monday[0]).toEqual({ from: '07:30', to: '21:30' });
  });

  test('an all-day window can be saved', async () => {
    // Finding F1 again, from the dialog. A blanket `from < to` guard
    // rejected all-day too, and Save became a dead button with no
    // explanation. Both of the door's spellings have to go through: what is
    // typed is what is stored, untouched.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });

    card._handleSlotUpdate('monday', 0, '00:00', '00:00');
    await flush();
    expect(card._schedule.monday[0]).toEqual({ from: '00:00', to: '00:00' });

    // 23:59 is an ordinary time and is stored as one - a minute short of
    // the whole day, which is exactly what it says.
    card._handleSlotUpdate('monday', 0, '00:00', '23:59');
    await flush();
    expect(card._schedule.monday[0]).toEqual({ from: '00:00', to: '23:59' });
  });

  test('an empty time is not saved', async () => {
    // `<input type="time">` yields "" when the user clears it; writing that
    // would send a slot the backend schema refuses.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '', '20:00');
    await flush();

    expect(card._schedule.monday[0]).toEqual({ from: '06:00', to: '20:00' });
    expect(hass.callWS).not.toHaveBeenCalled();
  });

  test('deleting removes the window and saves', async () => {
    const { card, hass } = await openCard({
      monday: [{ from: '06:00', to: '08:00' }, { from: '18:00', to: '20:00' }],
    });
    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();
    hass.callWS.mockClear();

    card.shadowRoot.getElementById('dialog-delete').click();
    await flush();

    expect(card._schedule.monday).toEqual([{ from: '18:00', to: '20:00' }]);
    expect(hass.callWS).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'powerpetdoor/schedule/update' }),
    );
  });

  test('a new window offers no delete button', async () => {
    // There is nothing to delete yet - Cancel is the way out - and offering
    // both makes the two buttons mean the same thing.
    const { card } = await openCard();
    card._createDefaultSlot('monday');
    await flush();

    expect(card.shadowRoot.getElementById('dialog-delete')).toBeNull();
    expect(card.shadowRoot.getElementById('dialog-cancel')).not.toBeNull();
  });

  test('the dialog is opened as a native modal', async () => {
    // showModal(), not an `open` attribute. Only the modal form puts the
    // dialog in the top layer and activates Escape, the focus trap and
    // focus restore - which is the entire reason it is a <dialog> and not
    // the <div> overlay it used to be.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();

    const overlay = card.shadowRoot.getElementById('dialog-overlay');
    expect(overlay.tagName).toBe('DIALOG');
    expect(overlay.open).toBe(true);
  });

  test('Escape closes the dialog and clears the editing state', async () => {
    // The browser closes a modal <dialog> on Escape by itself and fires
    // `close`; without a listener the card kept `_editingSlot` set, so the
    // next render put the dialog straight back and Escape appeared to do
    // nothing at all.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();
    expect(card._editingSlot).not.toBeNull();

    // What the browser does on Escape, which is what the card must react to.
    card.shadowRoot.getElementById('dialog-overlay').close();
    await flush();

    expect(card._editingSlot).toBeNull();
    expect(card.shadowRoot.getElementById('edit-dialog')).toBeNull();
  });

  test('clicking the backdrop closes the dialog', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();

    const overlay = card.shadowRoot.getElementById('dialog-overlay');
    overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    await flush();

    expect(card.shadowRoot.getElementById('edit-dialog')).toBeNull();
  });

  test('clicking inside the dialog does not close it', async () => {
    // The backdrop handler fires on any mousedown that reaches it, so
    // without the inner stopPropagation the dialog closed the moment the
    // user touched a time field.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();

    card.shadowRoot
      .getElementById('edit-dialog')
      .dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
    await flush();

    expect(card.shadowRoot.getElementById('edit-dialog')).not.toBeNull();
  });
});

describe('the keyboard path', () => {
  test('a day column creates a default window on Enter', async () => {
    // Finding F4: dragging cannot be expressed with a key, so the keyboard
    // path creates a sensible 9-to-5 window and opens its editor. Without
    // it the card was completely unusable without a mouse.
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="wednesday"]');

    column.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
    );
    await flush();

    // Exactly one window, and no implied all-day one beside it: adding a
    // 9-to-5 window must actually restrict the sensor. The mouse path
    // produces this same result from the same starting state.
    expect(card._schedule.wednesday).toEqual([{ from: '09:00', to: '17:00' }]);
    expect(card.shadowRoot.getElementById('edit-dialog')).not.toBeNull();
  });

  test('Space works as well as Enter', async () => {
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="friday"]');

    column.dispatchEvent(
      new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }),
    );
    await flush();

    expect(card._schedule.friday).toHaveLength(1);
  });

  test('an unrelated key does nothing', async () => {
    const { card } = await openCard();
    const column = card.shadowRoot.querySelector('.day-column[data-day="friday"]');

    column.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'a', bubbles: true, cancelable: true }),
    );
    await flush();

    expect(card._schedule.friday).toBeUndefined();
  });

  test('a window opens its editor on Enter', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });

    card.shadowRoot
      .querySelector('.time-slot[data-day="monday"][data-index="0"]')
      .dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
      );
    await flush();

    expect(card.shadowRoot.getElementById('edit-dialog')).not.toBeNull();
  });

  test('the header expands on Enter', async () => {
    const hass = makeHass();
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    card.shadowRoot
      .getElementById('header')
      .dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
      );
    await flush();

    expect(card.shadowRoot.querySelectorAll('.day-column')).toHaveLength(7);
  });

  test('every interactive element is reachable by tab and announced', async () => {
    // Finding F4: no keyboard path and no ARIA anywhere. A grid of unlabelled
    // divs is invisible to a screen reader.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });

    for (const selector of ['.day-column', '.time-slot', '#header']) {
      const element = card.shadowRoot.querySelector(selector);
      expect(element.getAttribute('tabindex')).toBe('0');
      expect(element.getAttribute('role')).toBe('button');
    }

    // The grid cells have no text of their own, so they need an aria-label.
    for (const selector of ['.day-column', '.time-slot']) {
      expect(card.shadowRoot.querySelector(selector).getAttribute('aria-label'))
        .toBeTruthy();
    }

    // The header is the opposite case, and must NOT have one: on a
    // role="button", aria-label replaces the element's contents for a screen
    // reader, so a label here would silence the sensor name and the summary
    // and announce a fixed string in their place. Its own text is the label.
    const header = card.shadowRoot.getElementById('header');
    expect(header.getAttribute('aria-label')).toBeNull();
    expect(header.textContent).toContain('Inside');
    expect(header.textContent).toContain('1 time slot');
  });

  test('the focus ring is drawn outside the window, not on it', async () => {
    // A window is filled with a colour the user chooses. Drawn inside it,
    // the ring had to contrast with that colour - and the default green
    // against --primary-text-color on a dark theme is 2.8:1, under WCAG
    // 1.4.11's 3:1, so a keyboard user could not see where focus was.
    // Outside, it sits on the day column, where the pair is the theme's own
    // text-on-card contrast whatever slot colour is configured.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const css = card.shadowRoot.querySelector('style').textContent;
    const rule = css.match(/\.time-slot:focus-visible\s*\{([^}]*)\}/);

    expect(rule).not.toBeNull();
    expect(rule[1]).toMatch(/outline:\s*2px solid/);
    // Positive, i.e. outward. A negative offset is the bug.
    expect(Number(rule[1].match(/outline-offset:\s*(-?[\d.]+)px/)[1])).toBeGreaterThan(0);
  });

  test('only the window that is actually open announces itself as active', async () => {
    // Finding F-10. The active check took the day and threw it away, so on
    // a Wednesday afternoon Monday's window announced "active now" too -
    // every day's did. The visual highlight filters by day, so a
    // screen-reader user was told the opposite of what was on screen.
    jest.useFakeTimers().setSystemTime(new Date(2026, 7, 26, 12, 0, 0)); // a Wednesday
    try {
      loadCard();
      const card = document.createElement('powerpetdoor-schedule-card');
      card.setConfig({ entity: ENTITY });
      const hass = makeHass();
      hass.callWS = jest.fn().mockResolvedValue({
        entity_id: ENTITY,
        kind: 'inside',
        schedule: {
          monday: [{ from: '09:00', to: '17:00' }],
          wednesday: [{ from: '09:00', to: '17:00' }],
        },
      });
      card.hass = hass;
      document.body.appendChild(card);
      await Promise.resolve();
      await Promise.resolve();
      card._handleHeaderClick();

      const label = (day) =>
        card.shadowRoot
          .querySelector(`.time-slot[data-day="${day}"]`)
          .getAttribute('aria-label');

      // Same clock time, same window, different day - which is the whole
      // point of asserting both.
      expect(label('wednesday')).toContain('active now');
      expect(label('monday')).not.toContain('active now');
      expect(label('monday')).toContain('Monday');
    } finally {
      jest.useRealTimers();
    }
  });

  test('a window announces its day and both its times', async () => {
    // The grid shows only the start time and the end lived in `title`,
    // which never reaches a touch user and is not reliably announced.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const label = card.shadowRoot
      .querySelector('.time-slot[data-day="monday"]')
      .getAttribute('aria-label');

    expect(label).toContain('Monday');
    expect(label).toContain('6:00 AM');
    expect(label).toContain('8:00 PM');
  });
});

describe('read-only users', () => {
  test('a non-admin cannot create a window with the keyboard', async () => {
    // Finding F10: the WebSocket update command requires admin, so a
    // non-admin got a fully interactive card whose every save failed.
    //
    // Driven through the real input path rather than by calling the create
    // method directly. The gate is that _attachEventListeners returns before
    // binding any editing listener, so a non-admin's day column is neither
    // focusable nor listening - and a test that reached past that would pass
    // whether the gate existed or not.
    const { card } = await openCard({}, { user: { is_admin: false } });
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    expect(column.getAttribute('tabindex')).toBeNull();
    expect(column.getAttribute('role')).toBeNull();

    column.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
    );
    await flush();

    expect(card._schedule.monday).toBeUndefined();
  });

  test('an admin pressing Enter on a day does create a window', async () => {
    // The other side of the gate. Without this the test above passes on a
    // card where the keyboard create path is simply broken for everyone.
    const { card } = await openCard({});
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    expect(column.getAttribute('tabindex')).toBe('0');

    column.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
    );
    await flush();

    expect(card._schedule.monday).toEqual([{ from: '09:00', to: '17:00' }]);
  });

  test('a non-admin can still hear what the windows are', async () => {
    // A read-only slot is not a button - there is nothing to activate - but
    // dropping the role left a generic element, and ARIA ignores a label on
    // one of those. The window carries no text of its own either (only a
    // start time, and only when it is tall enough), so the grid was
    // announced as nothing at all to exactly the user who cannot see it.
    const { card } = await openCard(
      { monday: [{ from: '06:00', to: '20:00' }] },
      { user: { is_admin: false } },
    );
    const slot = card.shadowRoot.querySelector('.time-slot[data-day="monday"]');

    expect(slot.getAttribute('role')).toBe('img');
    expect(slot.getAttribute('tabindex')).toBeNull();
    expect(slot.getAttribute('aria-label')).toContain('Monday');
    expect(slot.getAttribute('aria-label')).toContain('6:00 AM');
    expect(slot.getAttribute('aria-label')).toContain('8:00 PM');
  });

  test('a non-admin is told the card is read-only', async () => {
    const { card } = await openCard({}, { user: { is_admin: false } });

    expect(card.shadowRoot.querySelector('.hint').textContent).toContain(
      'read-only access',
    );
  });

  test('an admin gets the editing hint instead', async () => {
    const { card } = await openCard({});

    expect(card.shadowRoot.querySelector('.hint').textContent).toContain('Drag');
  });
});

describe('the schedule summary', () => {
  test('a sensor the schedule shuts out does not claim to be active 24/7', async () => {
    // The third cause of `Inactive · Active 24/7 (no schedule set)`, which
    // rounds 1 and 3 both attacked. A table that gates only the OTHER sensor
    // makes `to_ha_format` return {} for this one - indistinguishable from
    // "no schedule" - so the commonest asymmetric setup ("inside any time,
    // outside only during the day") read that contradiction on the outside
    // card all night.
    //
    // The fix's branch RUNS in other tests, so jest branch coverage was
    // clean while its output was never read; only asserting the rendered
    // text pins it.
    const hass = makeHass({
      states: {
        [ENTITY]: { entity_id: ENTITY, state: 'off', attributes: { friendly_name: 'Outside' } },
      },
    });
    hass.callWS = jest
      .fn()
      .mockResolvedValue({ entity_id: ENTITY, kind: 'outside', schedule: {} });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    const subtitle = card.shadowRoot.querySelector('.subtitle').textContent;
    expect(subtitle).toContain('Inactive');
    expect(subtitle).not.toContain('24/7');
    expect(subtitle).toContain('No window is open');
  });

  test('a door with no schedule says it is always active', async () => {
    const { card } = await openCard({});
    expect(card.shadowRoot.querySelector('.subtitle').textContent).toContain('24/7');
  });

  test('a door with windows counts them', async () => {
    const { card } = await openCard({
      monday: [{ from: '06:00', to: '20:00' }],
      tuesday: [{ from: '06:00', to: '20:00' }, { from: '21:00', to: '22:00' }],
    });

    expect(card.shadowRoot.querySelector('.subtitle').textContent).toContain(
      '3 time slots across 2 days',
    );
  });

  test('a single window is described in the singular', async () => {
    // "1 time slots across 1 days" is the kind of thing that makes a card
    // look unfinished.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });

    expect(card.shadowRoot.querySelector('.subtitle').textContent).toContain(
      '1 time slot across 1 day',
    );
  });

  test('a door with no schedule still draws seven all-day bars', async () => {
    // The implied 24/7 state. Drawing nothing would suggest the sensor is
    // never enabled, which is the opposite of the truth.
    const { card } = await openCard({});

    expect(card.shadowRoot.querySelectorAll('.time-slot')).toHaveLength(7);
  });
});

describe('configuration', () => {
  test('a card with no entity refuses to be configured', async () => {
    loadCard();
    const card = document.createElement('powerpetdoor-schedule-card');

    expect(() => card.setConfig({})).toThrow('Please define an entity');
  });

  test('the editor is offered for the visual config UI', () => {
    const { card } = loadCard();
    expect(card.getConfigElement().tagName.toLowerCase()).toBe(
      'powerpetdoor-schedule-card-editor',
    );
  });

  test('the stub config has an entity field for the picker to fill', () => {
    const { card } = loadCard();
    expect(card.getStubConfig()).toEqual({ entity: '' });
  });

  test('a custom slot colour is applied', async () => {
    const { card } = await openCard();
    expect(card._getSlotColor()).toBe('var(--primary-color, #03a9f4)');

    card._config.slot_color = '#ff0000';
    expect(card._getSlotColor()).toBe('#ff0000');
  });
});

describe('drag listener hygiene', () => {
  test('removing the card mid-drag detaches its document listeners', async () => {
    // Finding F11. The drag listeners live on `document`, not on the card,
    // so removing it mid-drag left them attached for the life of the page -
    // pinning the card and its shadow DOM, and letting the next mouseup
    // ANYWHERE run a resize that wrote a schedule to a door the user had
    // already navigated away from.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.top[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 120);
    mouse(document, 'mousemove', 240);
    card.remove();
    hass.callWS.mockClear();

    mouse(document, 'mouseup', 240);
    await flush();

    expect(hass.callWS).not.toHaveBeenCalled();
  });

  test('a completed drag detaches its listeners too', async () => {
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.top[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 120);
    mouse(document, 'mousemove', 240);
    mouse(document, 'mouseup', 240);
    await flush();
    hass.callWS.mockClear();

    // A second, unrelated mouseup must not start anything.
    mouse(document, 'mouseup', 300);
    await flush();

    expect(hass.callWS).not.toHaveBeenCalled();
  });
});

describe('reloading', () => {
  test('the reload link asks the device again', async () => {
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    hass.callWS.mockClear();

    card.shadowRoot
      .getElementById('refresh-link')
      .dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    await flush();

    expect(hass.callWS).toHaveBeenCalledWith({
      type: 'powerpetdoor/schedule/get',
      entity_id: ENTITY,
    });
  });

  test('the reload control is a button, so Space activates it', async () => {
    // It was <a href="#" role="button">. The role tells a screen reader to
    // press Space; on an anchor Space scrolls the dashboard instead, so the
    // only recovery the card offers a user whose schedule failed to load
    // did nothing for them. A real button needs no role and gets Enter and
    // Space from the browser.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const reload = card.shadowRoot.getElementById('refresh-link');

    expect(reload.tagName).toBe('BUTTON');
    expect(reload.getAttribute('type')).toBe('button');
    expect(reload.getAttribute('role')).toBeNull();
    expect(reload.getAttribute('href')).toBeNull();
  });

  test('a state change on the entity reloads the schedule', async () => {
    // The card follows the entity, so an edit made elsewhere - the
    // set_schedule action, the phone app - shows up without a page reload.
    const { card, hass } = await openCard({});
    hass.callWS.mockClear();

    card.hass = makeHass({
      states: {
        [ENTITY]: { entity_id: ENTITY, state: 'off', attributes: {} },
      },
      callWS: hass.callWS,
    });
    await flush();

    expect(hass.callWS).toHaveBeenCalled();
  });

  test('a state change mid-edit does not discard what the user is typing', async () => {
    // Reloading under an open dialog would replace the schedule the dialog
    // is editing and the user's half-finished change would vanish.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();
    hass.callWS.mockClear();

    card.hass = makeHass({
      states: { [ENTITY]: { entity_id: ENTITY, state: 'off', attributes: {} } },
      callWS: hass.callWS,
    });
    await flush();

    expect(hass.callWS).not.toHaveBeenCalled();
  });
});

describe('the first edit on a door with no schedule (F-1)', () => {
  // A door with no schedule is on 24/7 and the grid draws seven implied
  // all-day bars. Saving is wholesale - apply_schedule replaces this
  // sensor's entries with exactly what the card sends - so what the card
  // omits is what the door switches off.

  test('restricting one day leaves the other six alone', async () => {
    // The out-of-box path: every new user's first edit did this, and it
    // silently switched their pet door's sensor off Tuesday to Sunday.
    const { card, hass } = await openCard({});
    expect(card._hasSchedule()).toBe(false);

    // 480px = 1440 minutes, so 1px = 3 minutes: 180px is 09:00, 340px is 17:00.
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');
    mouse(column, 'mousedown', 180);
    mouse(document, 'mousemove', 340);
    mouse(document, 'mouseup', 340);
    await flush();
    card.shadowRoot.getElementById('dialog-save').click();
    await flush();

    const saved = hass.callWS.mock.calls.at(-1)[0].schedule;
    expect(saved.monday).toEqual([{ from: '09:00', to: '17:00' }]);
    // Every other day must still be present and still all-day.
    for (const day of ['tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']) {
      expect(saved[day]).toEqual([{ from: '00:00', to: '00:00' }]);
    }
  });

  test('the edited day does not keep an all-day window underneath', async () => {
    // The opposite failure, and just as silent: the door ORs its entries,
    // so an all-day entry left on the edited day swallows the restriction
    // and nothing changes.
    const { card, hass } = await openCard({});

    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');
    mouse(column, 'mousedown', 180);
    mouse(document, 'mousemove', 340);
    mouse(document, 'mouseup', 340);
    await flush();
    card.shadowRoot.getElementById('dialog-save').click();
    await flush();

    const saved = hass.callWS.mock.calls.at(-1)[0].schedule;
    expect(saved.monday).toHaveLength(1);
    expect(saved.monday).not.toContainEqual({ from: '00:00', to: '00:00' });
  });

  test('the keyboard path produces exactly the same schedule', async () => {
    // Two input methods must not disagree about what the user asked for.
    const { card, hass } = await openCard({});
    card._createDefaultSlot('monday');
    await flush();
    card.shadowRoot.getElementById('dialog-save').click();
    await flush();

    const saved = hass.callWS.mock.calls.at(-1)[0].schedule;
    expect(saved.monday).toEqual([{ from: '09:00', to: '17:00' }]);
    expect(saved.tuesday).toEqual([{ from: '00:00', to: '00:00' }]);
  });

  test('cancelling leaves the door unscheduled', async () => {
    // Opening the editor materialises seven real entries so the implied
    // bar can be edited. Backing out must not keep them: the collapsed card
    // reported "7 time slots across 7 days" for a door with no schedule
    // that had received no write at all.
    const { card, hass } = await openCard({});

    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();
    card.shadowRoot.getElementById('dialog-cancel').click();
    await flush();

    expect(card._hasSchedule()).toBe(false);
    expect(hass.callWS).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'powerpetdoor/schedule/update' }),
    );
  });
});

describe('pointing the card at a different entity (F-3)', () => {
  test('the schedule and title are reloaded, not carried over', async () => {
    // Home Assistant reuses the element when only the config changes - the
    // card editor's live preview does it on every keystroke. Carrying the
    // old schedule over showed one sensor's windows under the other
    // sensor's name, welded to the new entity's on/off state.
    const inside = { monday: [{ from: '06:00', to: '20:00' }] };
    const outside = { tuesday: [{ from: '08:00', to: '18:00' }] };

    const hass = makeHass();
    hass.callWS = jest.fn().mockImplementation((msg) =>
      Promise.resolve(
        msg.entity_id.includes('outside')
          ? { entity_id: msg.entity_id, kind: 'outside', schedule: outside }
          : { entity_id: msg.entity_id, kind: 'inside', schedule: inside },
      ),
    );

    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    expect(card._kind).toBe('inside');
    expect(card._schedule).toEqual(inside);

    card.setConfig({
      type: 'custom:powerpetdoor-schedule-card',
      entity: 'binary_sensor.power_pet_door_outside_schedule',
    });
    await flush();
    await flush();

    expect(card._kind).toBe('outside');
    expect(card._schedule).toEqual(outside);
    // It actually refetched rather than guessing.
    expect(hass.callWS).toHaveBeenCalledTimes(2);
  });

  test('re-setting the SAME entity does not refetch', async () => {
    // The editor calls setConfig for unrelated option changes too (colours).
    // Refetching on every one would hammer the door through the WebSocket
    // API for no reason.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const before = hass.callWS.mock.calls.length;

    card.setConfig({ type: 'custom:powerpetdoor-schedule-card', entity: ENTITY, slot_color: 'red' });
    await flush();

    expect(hass.callWS.mock.calls.length).toBe(before);
    expect(card._config.slot_color).toBe('red');
  });
});

describe('keyboard focus survives a re-render (F-2)', () => {
  test('activating the header leaves focus on the header', async () => {
    // render() replaces the whole shadow root, so every keyboard activation
    // used to drop focus to <body>. Since the dialog is the only keyboard
    // route to editing, resizing or deleting, a user paid a full Tab
    // traversal on every single edit.
    const hass = makeHass();
    hass.callWS = jest.fn().mockResolvedValue({ entity_id: ENTITY, kind: 'inside', schedule: {} });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    const header = card.shadowRoot.getElementById('header');
    header.focus();
    expect(card.shadowRoot.activeElement).toBe(header);

    header.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await flush();

    // A NEW node - the old one was destroyed - but the same element.
    expect(card.shadowRoot.activeElement).toBe(card.shadowRoot.getElementById('header'));
    expect(card.shadowRoot.activeElement.id).toBe('header');
  });

  test('focus returns to the same slot after a re-render', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const slot = card.shadowRoot.querySelector('.time-slot[data-day="monday"][data-index="0"]');
    slot.focus();

    card.render();
    await flush();

    const restored = card.shadowRoot.activeElement;
    expect(restored).not.toBeNull();
    expect(restored.dataset.day).toBe('monday');
    expect(restored.dataset.index).toBe('0');
  });

  test('the card never steals focus it did not have', async () => {
    // Restoring unconditionally would yank focus away from whatever else on
    // the dashboard the user was using whenever a push re-rendered us.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const outside = document.createElement('input');
    document.body.appendChild(outside);
    outside.focus();

    card.render();
    await flush();

    expect(card.shadowRoot.activeElement).toBeNull();
    expect(document.activeElement).toBe(outside);
  });

  test('focus returns to a day column, which has no slot index', async () => {
    // A .day-column carries data-day but no data-index, so it exercises the
    // branch that builds a selector without one. Getting that wrong would
    // restore focus to the wrong element, or to none.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const column = card.shadowRoot.querySelector('.day-column[data-day="wednesday"]');
    column.focus();

    card.render();
    await flush();

    const restored = card.shadowRoot.activeElement;
    expect(restored).not.toBeNull();
    expect(restored.classList.contains('day-column')).toBe(true);
    expect(restored.dataset.day).toBe('wednesday');
  });

  test('an element with neither an id nor a day is simply not restored', async () => {
    // The grid contains focusable-by-script elements that identify nothing -
    // there is no selector that could find them again after the DOM is
    // replaced, so the honest behaviour is to give up rather than guess and
    // focus the wrong thing.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    const anonymous = card.shadowRoot.querySelector('.schedule-grid');
    anonymous.setAttribute('tabindex', '-1');
    anonymous.focus();
    expect(card.shadowRoot.activeElement).toBe(anonymous);

    card.render();
    await flush();

    expect(card.shadowRoot.activeElement).toBeNull();
  });
});

describe('windows that cross midnight', () => {
  // The device has no way to say "tomorrow": a wire entry is a day mask plus
  // a start and an end. So a window running into the next day is not
  // expressible, and the card is not allowed to invent one.
  //
  // What a door that HAS such an entry sends is two same-day windows -
  // `to_ha_format` splits it before the card ever sees it. That split used
  // to arrive spelled `22:00-00:00`, which the card read as wrapping and
  // drew as a stub; it is now `22:00-23:59`, an ordinary window.

  const SPLIT_OVERNIGHT = {
    monday: [
      { from: '00:00', to: '06:00' },
      { from: '22:00', to: '00:00' },
    ],
  };

  test('the two halves a door reports are drawn as two ordinary windows', async () => {
    const { card } = await openCard(SPLIT_OVERNIGHT);
    const bars = [...card.shadowRoot.querySelectorAll('.time-slot[data-day="monday"]')];

    expect(bars.map((bar) => bar.getAttribute('style'))).toEqual([
      'top: 0%; height: 25%;', // 00:00-06:00
      'top: 91.66666666666666%; height: 8.333333333333332%;', // 22:00-end of day
    ]);
  });

  test('at 2am the morning half is the one highlighted', async () => {
    // The symptom that made the spelling matter: with the evening half read
    // as wrapping, the card highlighted the 10pm bar at 2am and drew
    // nothing at the now-line.
    jest.useFakeTimers().setSystemTime(new Date(2026, 7, 24, 2, 0, 0)); // a Monday
    try {
      loadCard();
      const card = document.createElement('powerpetdoor-schedule-card');
      card.setConfig({ entity: ENTITY });
      const hass = makeHass();
      hass.callWS = jest
        .fn()
        .mockResolvedValue({ entity_id: ENTITY, kind: 'inside', schedule: SPLIT_OVERNIGHT });
      card.hass = hass;
      document.body.appendChild(card);
      await Promise.resolve();
      await Promise.resolve();
      card._handleHeaderClick();

      card._updateActiveSlotHighlight();

      const active = [...card.shadowRoot.querySelectorAll('.time-slot.active-now')];
      expect(active).toHaveLength(1);
      expect(active[0].dataset.index).toBe('0');
    } finally {
      jest.useRealTimers();
    }
  });

  test('the dialog refuses an end earlier than its start', async () => {
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '22:00', '06:00');
    await flush();

    // Not written, and not applied locally either.
    expect(hass.callWS).not.toHaveBeenCalled();
    expect(card._schedule.monday[0]).toEqual({ from: '06:00', to: '20:00' });
  });

  test('it says why, with the dialog still open and the times still in it', async () => {
    // A toast after the fact would leave the user with nothing to correct.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });

    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();
    card._handleSlotUpdate('monday', 0, '22:00', '06:00');
    await flush();

    expect(card._editingSlot).toEqual({ day: 'monday', index: 0 });
    const error = card.shadowRoot.getElementById('dialog-error');
    expect(error.getAttribute('role')).toBe('alert');
    expect(error.textContent).toContain('cannot schedule past midnight');
  });

  test('a window ending at midnight is accepted, not refused', async () => {
    // 00:00 closing a window is the day's LAST minute, so this is "22:00
    // until the end of the day" and the backend sends it as 22:00-24:00.
    // Refusing it would block the commonest half of an overnight schedule.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '22:00', '00:00');
    await flush();

    expect(card._schedule.monday[0]).toEqual({ from: '22:00', to: '00:00' });
    expect(hass.callWS).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'powerpetdoor/schedule/update' }),
    );
  });

  test('an end equal to the start is refused too', async () => {
    // The boundary, and it moved. This used to assert the opposite, calling
    // 09:00-09:00 "the door's other spelling of a whole day" - which the
    // time maths in this same suite already contradicted. Measured on
    // firmware 1.7.18, coinciding ends are an EMPTY window.
    //
    // Letting one through is the worst of the three outcomes: the door
    // accepts it, the schedule sensor goes off with no next event to bring
    // it back, and this card reads "Active 24/7 (no schedule set)" because
    // a schedule with no open windows looks exactly like no schedule. The
    // pet is shut out and nothing on screen says so.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '09:00', '09:00');
    await flush();

    expect(hass.callWS).not.toHaveBeenCalled();
    expect(card._schedule.monday[0]).toEqual({ from: '06:00', to: '20:00' });
    // ...and the dialog stays open, saying why, with the times still in it.
    expect(card._editingSlot).toEqual({ day: 'monday', index: 0 });
    expect(card.shadowRoot.getElementById('dialog-error').textContent).toContain(
      'does not cover any time',
    );
  });

  test('midnight to midnight is still a whole day', async () => {
    // The other side of that boundary: 00:00-00:00 is NOT an empty window,
    // because midnight closing a window is the end of the day. Refusing it
    // would block the commonest thing anyone writes.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });
    hass.callWS.mockClear();

    card._handleSlotUpdate('monday', 0, '00:00', '00:00');
    await flush();

    expect(card._schedule.monday[0]).toEqual({ from: '00:00', to: '00:00' });
    expect(card._slotSpanMinutes(card._schedule.monday[0])).toBe(1440);
    expect(hass.callWS).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'powerpetdoor/schedule/update' }),
    );
  });

  test('the error clears when the dialog is closed', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });

    card._handleSlotClick('monday', 0, new MouseEvent('click'));
    await flush();
    card._handleSlotUpdate('monday', 0, '22:00', '06:00');
    await flush();
    expect(card._dialogError).not.toBeNull();

    card._closeDialog();
    await flush();

    expect(card._dialogError).toBeNull();
  });
});

describe('edits that race the network', () => {
  test('cancelling during a save does not wipe the schedule', async () => {
    // Finding F-12. `_materialised` records that Cancel still has an
    // unscheduled door to restore. It used to be cleared only AFTER the
    // save round trip, so a Cancel that landed while the save was in flight
    // reset the whole table to {} -- and the card then reported "Active
    // 24/7 (no schedule set)" for a door that had just been given one.
    const { card, hass } = await openCard({});
    let releaseSave;
    hass.callWS.mockImplementation((msg) =>
      msg.type === 'powerpetdoor/schedule/update'
        ? new Promise((resolve) => {
            releaseSave = resolve;
          })
        : Promise.resolve({ entity_id: ENTITY, kind: 'inside', schedule: {} }),
    );

    // Driven through the dialog's own buttons rather than by calling
    // internals, because the bug is about WHEN the save clears the undo
    // record relative to the user's next click.
    const click = (id) =>
      card.shadowRoot
        .getElementById(id)
        .dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));

    card._createDefaultSlot('monday');
    await flush();
    click('dialog-save');
    await flush();

    expect(card._schedule.monday).toEqual([{ from: '09:00', to: '17:00' }]);

    // Now, with that save still in flight, open another window's editor and
    // back out of it.
    card._handleSlotClick('tuesday', 0, new MouseEvent('click'));
    await flush();
    click('dialog-cancel');
    await flush();

    expect(card._schedule.monday).toEqual([{ from: '09:00', to: '17:00' }]);

    releaseSave({});
    await flush();
  });

  test('a slow reply cannot overwrite a newer one', async () => {
    // Finding F-14. Two state changes start two loads and nothing promises
    // the first sent is the first back, so the loser used to win by
    // resolving last -- leaving a schedule the door no longer has on screen.
    const { card, hass } = await openCard({ monday: [{ from: '06:00', to: '20:00' }] });

    let releaseStale;
    hass.callWS
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            releaseStale = () =>
              resolve({ entity_id: ENTITY, kind: 'inside', schedule: { monday: [] } });
          }),
      )
      .mockImplementationOnce(() =>
        Promise.resolve({
          entity_id: ENTITY,
          kind: 'inside',
          schedule: { friday: [{ from: '08:00', to: '09:00' }] },
        }),
      );

    const stale = card._loadSchedule();
    const fresh = card._loadSchedule();
    await fresh;

    releaseStale();
    await stale;

    expect(card._schedule).toEqual({ friday: [{ from: '08:00', to: '09:00' }] });
  });
});

describe('creating a window at the very bottom of a day', () => {
  test('a click on the last pixel makes a quarter hour, not a whole day', async () => {
    // Finding F-13. The click rounded to 1440, both ends clamped to 23:59,
    // and start == end is the door's spelling of ALL DAY -- so asking for
    // fifteen minutes enabled the sensor around the clock, drawn as a
    // sliver at the bottom of the column.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    mouse(column, 'mousedown', 480); // the column is 480px tall
    mouse(document, 'mouseup', 480);
    await flush();

    // Ends at midnight, not 23:59: the click means "to the end of the day",
    // and 23:59 would be a minute short of it.
    const created = card._schedule.monday.find((slot) => slot.from !== '06:00');
    expect(created).toEqual({ from: '23:45', to: '00:00' });
  });

  test('the window it creates is a quarter hour, not twenty-four', async () => {
    // The consequence that made it matter, asserted directly: `from` and
    // `to` being equal is what the card and the door both read as 24 hours.
    // 15 rather than 14 because 23:59 is the end of the day, so the window
    // runs to midnight and the user gets exactly what they clicked for.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    const column = card.shadowRoot.querySelector('.day-column[data-day="monday"]');

    mouse(column, 'mousedown', 480);
    mouse(document, 'mouseup', 480);
    await flush();

    const created = card._schedule.monday.find((slot) => slot.from !== '06:00');
    expect(card._slotSpanMinutes(created)).toBe(15);
  });
});

describe('when schedules are switched off on the door', () => {
  // The door's master switch. With it off the door consults NO window and
  // both sensors are live around the clock - measured on firmware 1.7.18,
  // where this is the shipped default. The card draws the stored windows
  // either way, so without saying so it implies a restriction that is not
  // being applied, and every edit the user makes to that grid changes
  // nothing they can observe.

  const offCard = async (schedule = { monday: [{ from: '06:00', to: '20:00' }] }) => {
    const hass = makeHass();
    hass.callWS = jest.fn().mockResolvedValue({
      entity_id: ENTITY,
      kind: 'inside',
      schedule,
      timers_enabled: false,
    });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    card._handleHeaderClick();
    await flush();
    return { card, hass };
  };

  test('the card says the windows are not being applied', async () => {
    const { card } = await offCard();
    const notice = card.shadowRoot.querySelector('.notice');

    expect(notice).not.toBeNull();
    expect(notice.textContent).toContain('not being applied');
    // Announced, but as a standing condition rather than an error - the
    // user chose this setting.
    expect(notice.getAttribute('role')).toBe('status');
  });

  test('it names the switch that turns them back on', async () => {
    // A warning the user cannot act on is just noise.
    const { card } = await offCard();

    expect(card.shadowRoot.querySelector('.notice').textContent).toContain('Schedule enabled');
  });

  test('the windows are still drawn, because they are still stored', async () => {
    // The schedule is real and editable; it is simply not in force. Hiding
    // it would stop the user preparing one before switching it on.
    const { card } = await offCard();

    expect(card.shadowRoot.querySelectorAll('.time-slot[data-day="monday"]')).toHaveLength(1);
  });

  test('nothing is said when schedules ARE switched on', async () => {
    // `timers_enabled: true` explicitly. This used `openCard`, whose mock
    // OMITS the key entirely - so it silently duplicated the absent-key test
    // below and never once exercised the true branch. With that gap,
    // `result.timers_enabled !== false` could become `=== undefined` and
    // every card on a perfectly healthy door would show the orange "your
    // schedules are not being applied" banner, with the whole suite green.
    const hass = makeHass();
    hass.callWS = jest.fn().mockResolvedValue({
      entity_id: ENTITY,
      kind: 'inside',
      schedule: { monday: [{ from: '06:00', to: '20:00' }] },
      timers_enabled: true,
    });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    card._handleHeaderClick();
    await flush();

    expect(card._timersEnabled).toBe(true);
    expect(card.shadowRoot.querySelector('.notice')).toBeNull();
  });

  test('a failed reload does not turn the banner on by itself', async () => {
    // The `!== undefined` guard beside it. The attribute fallback can supply
    // a schedule but never this flag, so without the guard one transient
    // WebSocket failure would paint the false banner on a door whose
    // schedules are switched on and working.
    const { card, hass } = await offCard();
    expect(card.shadowRoot.querySelector('.notice')).not.toBeNull();

    hass.callWS = jest.fn().mockResolvedValue({
      entity_id: ENTITY,
      kind: 'inside',
      schedule: {},
      timers_enabled: true,
    });
    await card._loadSchedule();
    expect(card._timersEnabled).toBe(true);

    // ...and now a failure, which must leave that answer alone.
    hass.callWS = jest.fn().mockRejectedValue(new Error('socket died'));
    await card._loadSchedule();

    expect(card._timersEnabled).toBe(true);
    expect(card.shadowRoot.querySelector('.notice')).toBeNull();
  });

  test('a card that never loaded does not accuse the user', async () => {
    // `timers_enabled` absent (an older backend, or a failed load) must not
    // be read as "off" - that would put a warning on every card.
    const hass = makeHass();
    hass.callWS = jest.fn().mockResolvedValue({ entity_id: ENTITY, kind: 'inside', schedule: {} });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    card._handleHeaderClick();
    await flush();

    expect(card.shadowRoot.querySelector('.notice')).toBeNull();
  });
});

describe('dragging one window into another', () => {
  // The mocked column is 480px for 1440 minutes, so clientY is minutes/3:
  // 160 is 08:00, 200 is 10:00, 260 is 13:00. Written out in each test
  // rather than helpered, because the whole point of these is WHERE the
  // pointer sits relative to a neighbour.

  test('an edge dragged into a neighbour stops at its border', async () => {
    // 06:00-08:00 with 10:00-12:00 below it. Dragging the first window's
    // bottom to 11:00 puts the pointer INSIDE the second, so the edge stops
    // at 10:00 - drawing one window crossing into another says nothing
    // true, since applying it makes them a single window.
    const { card } = await openCard({
      monday: [
        { from: '06:00', to: '08:00' },
        { from: '10:00', to: '12:00' },
      ],
    });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 160);
    mouse(document, 'mousemove', 220);

    expect(card._dragCurrentMinutes).toBe(600);
    expect(card._dragMergeWith).toBe(1);
    expect(card._dragDoomed).toEqual([]);
  });

  test('releasing there merges the two into one window', async () => {
    const { card } = await openCard({
      monday: [
        { from: '06:00', to: '08:00' },
        { from: '10:00', to: '12:00' },
      ],
    });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 160);
    mouse(document, 'mousemove', 220);
    mouse(document, 'mouseup', 220);
    await flush();

    // One window spanning both, not two touching ones: the merge takes the
    // absorbed window's far edge, so the result reaches 12:00.
    expect(card._schedule.monday).toEqual([{ from: '06:00', to: '12:00' }]);
  });

  test('dragging clear past a neighbour dooms it rather than stopping', async () => {
    // Pointer at 13:00 is beyond the second window entirely, so the edge is
    // free again and the window it passed over is marked for removal.
    const { card } = await openCard({
      monday: [
        { from: '06:00', to: '08:00' },
        { from: '10:00', to: '12:00' },
      ],
    });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 160);
    mouse(document, 'mousemove', 260);

    expect(card._dragCurrentMinutes).toBe(780);
    expect(card._dragMergeWith).toBeNull();
    expect(card._dragDoomed).toEqual([1]);
  });

  test('a doomed window is drawn in the removal colour', async () => {
    // The user's only warning that releasing here destroys a window, so it
    // is asserted on the DOM rather than on the internal set alone.
    const { card } = await openCard({
      monday: [
        { from: '06:00', to: '08:00' },
        { from: '10:00', to: '12:00' },
      ],
    });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 160);
    mouse(document, 'mousemove', 260);

    const swallowed = card.shadowRoot.querySelector(
      '.time-slot[data-day="monday"][data-index="1"]',
    );
    expect(swallowed.classList.contains('doomed')).toBe(true);
  });

  test('dragging back off a doomed window clears the warning', async () => {
    // The doomed set shrinks as well as grows; a mark left behind would
    // tell the user they are about to destroy something they are not.
    const { card } = await openCard({
      monday: [
        { from: '06:00', to: '08:00' },
        { from: '10:00', to: '12:00' },
      ],
    });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 160);
    mouse(document, 'mousemove', 260);
    mouse(document, 'mousemove', 180);

    const other = card.shadowRoot.querySelector(
      '.time-slot[data-day="monday"][data-index="1"]',
    );
    expect(card._dragDoomed).toEqual([]);
    expect(other.classList.contains('doomed')).toBe(false);
  });

  test('releasing past a neighbour absorbs it', async () => {
    const { card } = await openCard({
      monday: [
        { from: '06:00', to: '08:00' },
        { from: '10:00', to: '12:00' },
      ],
    });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 160);
    mouse(document, 'mousemove', 260);
    mouse(document, 'mouseup', 260);
    await flush();

    expect(card._schedule.monday).toEqual([{ from: '06:00', to: '13:00' }]);
  });

  test('the top edge merges upward the same way', async () => {
    // The mirror image, because the two directions are separate code paths
    // and only one of them was ever exercised.
    const { card } = await openCard({
      monday: [
        { from: '06:00', to: '08:00' },
        { from: '10:00', to: '12:00' },
      ],
    });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.top[data-day="monday"][data-index="1"]',
    );

    mouse(edge, 'mousedown', 200);
    mouse(document, 'mousemove', 140);
    mouse(document, 'mouseup', 140);
    await flush();

    expect(card._schedule.monday).toEqual([{ from: '06:00', to: '12:00' }]);
  });

  test('a drag that stops short of a neighbour leaves it alone', async () => {
    // The other side of the boundary: 09:00 is below the first window and
    // above the second, so nothing merges and nothing is doomed.
    const { card } = await openCard({
      monday: [
        { from: '06:00', to: '08:00' },
        { from: '10:00', to: '12:00' },
      ],
    });
    const edge = card.shadowRoot.querySelector(
      '.slot-edge.bottom[data-day="monday"][data-index="0"]',
    );

    mouse(edge, 'mousedown', 160);
    mouse(document, 'mousemove', 180);
    mouse(document, 'mouseup', 180);
    await flush();

    expect(card._schedule.monday).toEqual([
      { from: '06:00', to: '09:00' },
      { from: '10:00', to: '12:00' },
    ]);
  });
});

describe('copying a schedule', () => {
  const OTHER = 'binary_sensor.power_pet_door_outside_schedule';

  // `counterpart` is what the backend sends so the card knows which entity
  // the other sensor's schedule lives on. Without it there is nothing to
  // copy from and the button is not offered at all.
  const openWithCounterpart = async (schedule, otherSchedule) => {
    const hass = makeHass();
    hass.callWS = jest.fn().mockImplementation((msg) => {
      if (msg.type === 'powerpetdoor/schedule/get' && msg.entity_id === OTHER) {
        return Promise.resolve({ entity_id: OTHER, kind: 'outside', schedule: otherSchedule });
      }
      if (msg.type === 'powerpetdoor/schedule/get') {
        return Promise.resolve({
          entity_id: ENTITY, kind: 'inside', schedule, counterpart: OTHER,
        });
      }
      return Promise.resolve({});
    });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    card._handleHeaderClick();
    await flush();
    return { card, hass };
  };

  test('the copy button is offered only when there is a counterpart', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });

    // openCard's mock sends no `counterpart`, which is the disabled-sibling
    // case: offering the button would produce a copy from nothing.
    expect(card.shadowRoot.getElementById('copy-from-link')).toBeNull();
  });

  test('copying from the other sensor replaces this schedule and saves', async () => {
    const { card, hass } = await openWithCounterpart(
      { monday: [{ from: '06:00', to: '08:00' }] },
      { tuesday: [{ from: '09:00', to: '17:00' }] },
    );

    card.shadowRoot.getElementById('copy-from-link').click();
    await flush();
    card.shadowRoot.getElementById('copy-from-confirm').click();
    await flush();

    expect(card._schedule).toEqual({ tuesday: [{ from: '09:00', to: '17:00' }] });
    expect(hass.callWS).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'powerpetdoor/schedule/update',
        schedule: { tuesday: [{ from: '09:00', to: '17:00' }] },
      }),
    );
  });

  test('the copy is read fresh, not taken from anything cached', async () => {
    // The other sensor may have been edited in another tab since this card
    // loaded; copying a stale view would quietly undo that.
    const { card, hass } = await openWithCounterpart({}, { friday: [{ from: '01:00', to: '02:00' }] });

    card.shadowRoot.getElementById('copy-from-link').click();
    await flush();
    card.shadowRoot.getElementById('copy-from-confirm').click();
    await flush();

    expect(hass.callWS).toHaveBeenCalledWith({
      type: 'powerpetdoor/schedule/get',
      entity_id: OTHER,
    });
  });

  test('cancelling the copy leaves the schedule untouched', async () => {
    const { card } = await openWithCounterpart(
      { monday: [{ from: '06:00', to: '08:00' }] },
      { tuesday: [{ from: '09:00', to: '17:00' }] },
    );

    card.shadowRoot.getElementById('copy-from-link').click();
    await flush();
    card.shadowRoot.getElementById('copy-from-cancel').click();
    await flush();

    expect(card._schedule).toEqual({ monday: [{ from: '06:00', to: '08:00' }] });
  });

  test('a copy that fails to read says so and changes nothing', async () => {
    const hass = makeHass();
    hass.callWS = jest.fn().mockImplementation((msg) => {
      if (msg.type === 'powerpetdoor/schedule/get' && msg.entity_id === OTHER) {
        return Promise.reject(new Error('door went away'));
      }
      return Promise.resolve({
        entity_id: ENTITY,
        kind: 'inside',
        schedule: { monday: [{ from: '06:00', to: '08:00' }] },
        counterpart: OTHER,
      });
    });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    card._handleHeaderClick();
    await flush();
    const notified = jest.fn();
    card.addEventListener('hass-notification', notified);

    card.shadowRoot.getElementById('copy-from-link').click();
    await flush();
    card.shadowRoot.getElementById('copy-from-confirm').click();
    await flush();

    expect(card._schedule).toEqual({ monday: [{ from: '06:00', to: '08:00' }] });
    expect(notified).toHaveBeenCalled();
  });
});

describe('copying one day onto others', () => {
  test('the day header is a button only when the user can edit', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });

    expect(card.shadowRoot.querySelector('.day-copy[data-day="monday"]')).not.toBeNull();
  });

  test('a non-admin gets no copy buttons at all', async () => {
    const { card } = await openCard(
      { monday: [{ from: '06:00', to: '08:00' }] },
      { user: { is_admin: false } },
    );

    expect(card.shadowRoot.querySelector('.day-copy')).toBeNull();
  });

  test('copying Monday to two days replaces both and saves once', async () => {
    const { card, hass } = await openCard({
      monday: [{ from: '06:00', to: '08:00' }],
      // Wednesday already has something, to prove copy REPLACES rather than
      // merges - "copy Monday to Wednesday" means Wednesday looks like
      // Monday, and pressing it twice must not differ from pressing it once.
      wednesday: [{ from: '20:00', to: '22:00' }],
    });
    card.shadowRoot.querySelector('.day-copy[data-day="monday"]').click();
    await flush();
    const boxes = card.shadowRoot.querySelectorAll('input[name="copy-day"]');
    boxes.forEach((box) => {
      if (box.value === 'tuesday' || box.value === 'wednesday') box.checked = true;
    });
    hass.callWS.mockClear();

    card.shadowRoot.getElementById('copy-day-confirm').click();
    await flush();

    expect(card._schedule.tuesday).toEqual([{ from: '06:00', to: '08:00' }]);
    expect(card._schedule.wednesday).toEqual([{ from: '06:00', to: '08:00' }]);
    expect(card._schedule.monday).toEqual([{ from: '06:00', to: '08:00' }]);
    expect(
      hass.callWS.mock.calls.filter(([m]) => m.type === 'powerpetdoor/schedule/update'),
    ).toHaveLength(1);
  });

  test('the copied days are independent objects, not shared references', async () => {
    // A shallow copy would make editing Tuesday silently edit Monday too.
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    card.shadowRoot.querySelector('.day-copy[data-day="monday"]').click();
    await flush();
    card.shadowRoot.querySelectorAll('input[name="copy-day"]').forEach((box) => {
      if (box.value === 'tuesday') box.checked = true;
    });
    card.shadowRoot.getElementById('copy-day-confirm').click();
    await flush();

    card._schedule.tuesday[0].from = '01:00';

    expect(card._schedule.monday[0].from).toBe('06:00');
  });

  test('confirming with no day chosen refuses instead of silently doing nothing', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    card.shadowRoot.querySelector('.day-copy[data-day="monday"]').click();
    await flush();

    card.shadowRoot.getElementById('copy-day-confirm').click();
    await flush();

    expect(card.shadowRoot.getElementById('copy-day-error')).not.toBeNull();
    expect(card._copyingDay).toBe('monday');
  });

  test('All ticks every day except the source, which stays fixed', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    card.shadowRoot.querySelector('.day-copy[data-day="monday"]').click();
    await flush();

    card.shadowRoot.getElementById('copy-day-all').click();

    const boxes = Array.from(card.shadowRoot.querySelectorAll('input[name="copy-day"]'));
    expect(boxes.filter((b) => b.checked)).toHaveLength(7);
    // The source is checked AND disabled: it is what is being copied from,
    // so offering to exclude it would be meaningless.
    expect(boxes.find((b) => b.value === 'monday').disabled).toBe(true);
  });

  test('None clears every day the user could have chosen', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    card.shadowRoot.querySelector('.day-copy[data-day="monday"]').click();
    await flush();
    card.shadowRoot.getElementById('copy-day-all').click();

    card.shadowRoot.getElementById('copy-day-none').click();

    const enabled = Array.from(
      card.shadowRoot.querySelectorAll('input[name="copy-day"]:not(:disabled)'),
    );
    expect(enabled.filter((b) => b.checked)).toHaveLength(0);
  });

  test('cancelling copies nothing', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    card.shadowRoot.querySelector('.day-copy[data-day="monday"]').click();
    await flush();
    card.shadowRoot.querySelectorAll('input[name="copy-day"]').forEach((box) => {
      if (box.value === 'tuesday') box.checked = true;
    });

    card.shadowRoot.getElementById('copy-day-cancel').click();
    await flush();

    expect(card._schedule.tuesday).toBeUndefined();
    expect(card._copyingDay).toBeNull();
  });
});

describe('Escape on the copy dialogs', () => {
  // The browser closes a modal <dialog> on Escape by itself and fires
  // `close`. Without a listener the card keeps its state set, the next
  // render puts the dialog straight back, and Escape appears to do nothing.
  const OTHER = 'binary_sensor.power_pet_door_outside_schedule';

  test('Escape closes the day picker and clears the state', async () => {
    const { card } = await openCard({ monday: [{ from: '06:00', to: '08:00' }] });
    card.shadowRoot.querySelector('.day-copy[data-day="monday"]').click();
    await flush();
    expect(card._copyingDay).toBe('monday');

    card.shadowRoot.getElementById('copy-day-overlay').close();
    await flush();

    expect(card._copyingDay).toBeNull();
    expect(card.shadowRoot.getElementById('copy-day-overlay')).toBeNull();
  });

  test('Escape closes the copy-from confirmation and copies nothing', async () => {
    const hass = makeHass();
    hass.callWS = jest.fn().mockResolvedValue({
      entity_id: ENTITY,
      kind: 'inside',
      schedule: { monday: [{ from: '06:00', to: '08:00' }] },
      counterpart: OTHER,
    });
    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    card._handleHeaderClick();
    await flush();
    card.shadowRoot.getElementById('copy-from-link').click();
    await flush();
    expect(card._confirmCopyFrom).toBe(true);

    card.shadowRoot.getElementById('copy-from-overlay').close();
    await flush();

    expect(card._confirmCopyFrom).toBe(false);
    expect(card._schedule).toEqual({ monday: [{ from: '06:00', to: '08:00' }] });
  });
});
