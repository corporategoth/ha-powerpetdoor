/**
 * Text the card did not author must never become markup.
 *
 * The card builds its whole DOM with `innerHTML` on a template literal, so
 * every interpolated value is parsed as HTML. Most of them are numbers the
 * card computed, which are safe by construction - but three are not:
 *
 *  * the error message from a rejected `callWS`, which for a save failure
 *    carries `str(err)` straight off the door (see websocket.py's
 *    `update_failed`),
 *  * the window times, which arrive from the door through the API,
 *  * an entity's `friendly_name` in the editor's dropdown.
 *
 * The door is a cheap embedded device that has been observed to send
 * malformed frames (issue #16), and the threat model in .claude/CLAUDE.md
 * names this exact rule: "The Lovelace card renders device-supplied text.
 * Never interpolate it into innerHTML."
 *
 * Each test asserts the payload did NOT become an element, and that the
 * text is still shown to the user - escaping that silently drops the
 * message would be a different bug.
 */

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const ENTITY = 'binary_sensor.power_pet_door_inside_schedule';

// A classic self-firing payload. `<img onerror>` is used rather than
// `<script>`, because innerHTML does not execute injected <script> but DOES
// run an inline error handler - so this is what actually fires in a browser.
const PAYLOAD = '<img src=x onerror="window.__pwned = true">';

describe('untrusted text never becomes markup', () => {
  beforeEach(() => {
    delete window.__pwned;
  });

  test('an error message from the door is shown as text, not parsed', async () => {
    const hass = makeHass();
    hass.callWS = jest.fn().mockRejectedValue(new Error(PAYLOAD));

    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();

    expect(card.shadowRoot.querySelector('img')).toBeNull();
    expect(window.__pwned).toBeUndefined();
    // ...and the user can still read what went wrong.
    expect(card.shadowRoot.querySelector('.error').textContent).toContain('onerror');
  });

  test('a window time from the door cannot break out of its attribute', async () => {
    // slot.from and slot.to reach a `title="..."` and an `aria-label="..."`.
    // A quote in either would close the attribute and open a new one.
    const hass = makeHass();
    hass.callWS = jest.fn().mockResolvedValue({
      entity_id: ENTITY,
      kind: 'inside',
      schedule: {
        monday: [{ from: '06:00" onmouseover="window.__pwned = true', to: '20:00' }],
      },
    });

    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    card._handleHeaderClick();
    await flush();

    const slot = card.shadowRoot.querySelector('.time-slot');
    expect(slot).not.toBeNull();
    expect(slot.getAttribute('onmouseover')).toBeNull();
  });

  test('a day key from the door cannot inject an element', async () => {
    // The grid iterates the card's own DAYS list, so a rogue key should
    // never be rendered at all. Asserted rather than assumed.
    const hass = makeHass();
    hass.callWS = jest.fn().mockResolvedValue({
      entity_id: ENTITY,
      kind: 'inside',
      schedule: { [`monday${PAYLOAD}`]: [{ from: '06:00', to: '20:00' }] },
    });

    const card = await mountCard({ entity: ENTITY }, hass);
    await flush();
    card._handleHeaderClick();
    await flush();

    expect(card.shadowRoot.querySelector('img')).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });

  test('a friendly_name in the editor dropdown is shown as text, not parsed', async () => {
    // An entity name is user-supplied and survives a rename; the editor
    // lists every `binary_sensor.*_schedule` in the system, not only ours.
    loadCard();
    const editor = document.createElement('powerpetdoor-schedule-card-editor');
    editor.setConfig({ entity: '' });
    editor.hass = makeHass({
      states: {
        'binary_sensor.evil_schedule': {
          entity_id: 'binary_sensor.evil_schedule',
          state: 'on',
          attributes: { friendly_name: PAYLOAD },
        },
      },
    });
    document.body.appendChild(editor);
    await flush();

    expect(editor.shadowRoot.querySelector('img')).toBeNull();
    expect(window.__pwned).toBeUndefined();
    const option = [...editor.shadowRoot.querySelectorAll('option')].find((element) =>
      element.value === 'binary_sensor.evil_schedule',
    );
    expect(option.textContent).toContain('onerror');
  });

  test('an entity id in the editor dropdown cannot break out of its attribute', async () => {
    // With no friendly_name the id itself is rendered, into BOTH a value
    // attribute and the option text.
    loadCard();
    const editor = document.createElement('powerpetdoor-schedule-card-editor');
    editor.setConfig({ entity: '' });
    editor.hass = makeHass({
      states: {
        'binary_sensor.a" onfocus="window.__pwned = true_schedule': {
          entity_id: 'binary_sensor.a" onfocus="window.__pwned = true_schedule',
          state: 'on',
          attributes: {},
        },
      },
    });
    document.body.appendChild(editor);
    await flush();

    const options = [...editor.shadowRoot.querySelectorAll('option')];
    expect(options.every((element) => element.getAttribute('onfocus') === null)).toBe(true);
    expect(window.__pwned).toBeUndefined();
  });

  test('a card colour from the dashboard config cannot close the style block', async () => {
    // The colours are card config rather than device data, but they are
    // interpolated into a <style> block - and `</style>` in one would end
    // the stylesheet and drop the rest of the card's markup into the DOM.
    const hass = makeHass();
    const card = await mountCard(
      { entity: ENTITY, slot_color: '</style><img src=x onerror="window.__pwned = true">' },
      hass,
    );
    await flush();

    expect(card.shadowRoot.querySelector('img')).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });
});
