/**
 * Jest setup for the Power Pet Door Lovelace card.
 *
 * Two jobs:
 *
 *  1. Provide the slice of the Home Assistant frontend the card actually
 *     touches - a `hass` object with `callWS`, `states`, `localize`, plus
 *     the browser APIs jsdom does not implement.
 *  2. Load the card. www/powerpetdoor-schedule-card.js has no exports, but it
 *     is still `require`d rather than eval'd - see loadCard() below for why
 *     that matters to coverage and to repeat loads. Either way the tests
 *     exercise the exact bytes that ship, including the
 *     `customElements.define` and `window.customCards` side effects, rather
 *     than a module-shaped adaptation of them.
 */

require('@testing-library/jest-dom');

const path = require('path');

const CARD_PATH = path.resolve(__dirname, '../../www/powerpetdoor-schedule-card.js');

// ---------------------------------------------------------------------------
// Browser APIs jsdom lacks.
//
// Each of these is here because the card calls it. Adding a mock for
// something the card does not use would be a fake test surface, so keep this
// list honest.
// ---------------------------------------------------------------------------

if (!window.matchMedia) {
  window.matchMedia = jest.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  }));
}

// The card measures columns with getBoundingClientRect to translate a
// pointer position into a time-of-day. jsdom returns all-zeroes, which would
// make every drag resolve to 00:00 and silently pass. Give elements a
// deterministic, non-degenerate box so drag maths is actually exercised.
const DEFAULT_RECT = {
  x: 0, y: 0, top: 0, left: 0, right: 100, bottom: 480, width: 100, height: 480,
};

if (!Element.prototype.getBoundingClientRect.__patched) {
  Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
    const override = this.__testRect;
    return { ...DEFAULT_RECT, ...(override || {}), toJSON() { return this; } };
  };
  Element.prototype.getBoundingClientRect.__patched = true;
}

// jsdom does not implement HTMLDialogElement's modal behaviour: showModal,
// close, the `open` property and the `close` event are all missing, though
// they have been browser baseline since 2022. The card uses a native
// <dialog> precisely to get Escape, the focus trap and focus restore for
// free, so the shim has to exist here rather than the card degrading to a
// <div> to suit the test environment.
//
// Deliberately minimal and honest about what it does NOT reproduce: there
// is no focus trap and no top layer here, so a test must not claim to have
// verified those. What it does support is open/close state and the `close`
// event, which is what the card's own logic depends on.
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.open = true;
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.show = HTMLDialogElement.prototype.showModal;
  HTMLDialogElement.prototype.close = function close(returnValue) {
    if (!this.open) return;
    this.open = false;
    this.removeAttribute('open');
    if (returnValue !== undefined) this.returnValue = returnValue;
    this.dispatchEvent(new Event('close'));
  };
}

/** Give one element a specific box, for drag/resize tests. */
global.setElementRect = (element, rect) => {
  element.__testRect = rect;
};

// ---------------------------------------------------------------------------
// Home Assistant frontend doubles
// ---------------------------------------------------------------------------

/**
 * A minimal `hass` object.
 *
 * `callWS` is a jest.fn so a test can assert the exact WebSocket command the
 * card sent - that is the contract between this card and
 * custom_components/powerpetdoor/websocket.py, and it is the thing most
 * likely to silently drift.
 */
global.makeHass = (overrides = {}) => ({
  states: {
    'binary_sensor.power_pet_door_inside_schedule': {
      entity_id: 'binary_sensor.power_pet_door_inside_schedule',
      state: 'on',
      attributes: { friendly_name: 'Power Pet Door Inside Schedule' },
    },
    ...(overrides.states || {}),
  },
  callWS: jest.fn().mockResolvedValue([]),
  callService: jest.fn().mockResolvedValue(undefined),
  localize: jest.fn((key) => key),
  language: 'en',
  themes: { darkMode: false },
  user: { is_admin: true },
  ...overrides,
});

// ---------------------------------------------------------------------------
// Loading the card
// ---------------------------------------------------------------------------

/**
 * Load the card into this realm and return its custom-element classes.
 *
 * `require`, deliberately, rather than evaluating the source with
 * `new Function`. Two reasons, both learned the hard way:
 *
 *  1. **Coverage.** Code brought in through `new Function` is invisible to
 *     the coverage collector - the whole card reported 0%, so the 60%
 *     threshold in jest.config.js was gating nothing at all. A `require`d
 *     file is a real module with a real path, which V8's coverage provider
 *     attributes to www/powerpetdoor-schedule-card.js.
 *  2. **Idempotency.** `customElements.define` throws NotSupportedError on
 *     a second registration, so re-evaluating the source made every test
 *     after the first in a file fail. `require`'s module cache means the
 *     second call returns without re-executing - which is also exactly what
 *     a browser does when the same script URL is requested twice.
 *
 * The card still has no exports; the classes are recovered from the
 * registry its own top-level `customElements.define` calls populated.
 */
let bannerOutput = [];
let cardLoaded = false;

global.loadCard = () => {
  if (!cardLoaded) {
    // The card prints its version banner as a top-level side effect, so it
    // is emitted exactly once - during whichever test happens to load the
    // card first. A per-test `jest.spyOn(console, 'info')` therefore sees
    // it only by luck of ordering. Capture it here instead, at the one
    // moment it can happen, so `cardBanner()` is deterministic for every
    // test regardless of order.
    const original = console.info;
    console.info = (...args) => { bannerOutput.push(args.join(' ')); };
    try {
      require(CARD_PATH);
    } finally {
      console.info = original;
    }
    cardLoaded = true;
  }

  return {
    card: customElements.get('powerpetdoor-schedule-card'),
    editor: customElements.get('powerpetdoor-schedule-card-editor'),
  };
};

/** Whatever the card wrote to console.info while loading. */
global.cardBanner = () => bannerOutput.join('\n');

/** Construct a configured, hass-attached card element attached to the DOM. */
global.mountCard = async (config = {}, hass = null) => {
  loadCard();
  const element = document.createElement('powerpetdoor-schedule-card');
  element.setConfig({ type: 'custom:powerpetdoor-schedule-card', ...config });
  element.hass = hass || makeHass();
  document.body.appendChild(element);
  // Let any promise the setter kicked off settle before the test asserts.
  await Promise.resolve();
  return element;
};

// Keep the test log clean. The card's own load-time banner is captured
// separately by loadCard() (see cardBanner()); this only silences anything
// a test itself triggers.
beforeEach(() => {
  jest.spyOn(console, 'info').mockImplementation(() => {});
});

afterEach(() => {
  document.body.innerHTML = '';
  jest.clearAllTimers();
});
