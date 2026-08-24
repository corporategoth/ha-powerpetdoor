/**
 * The card registers itself correctly when a browser loads it.
 *
 * This is the harness's own smoke test as much as the card's: it proves the
 * shipped file in www/ can be evaluated in a jsdom realm and that its
 * top-level side effects (customElements.define, window.customCards) really
 * happen. Everything else in tests/frontend/ depends on that being true.
 */

describe('card registration', () => {
  test('defines both custom elements under their published tag names', () => {
    const { card, editor } = loadCard();

    // These tag names are a contract with every user's dashboard YAML
    // (`type: custom:powerpetdoor-schedule-card`). Renaming one silently
    // blanks the card for everyone who already added it, so pin them by
    // literal rather than deriving them from the class.
    expect(customElements.get('powerpetdoor-schedule-card')).toBe(card);
    expect(customElements.get('powerpetdoor-schedule-card-editor')).toBe(editor);
    expect(card.prototype).toBeInstanceOf(HTMLElement);
    expect(editor.prototype).toBeInstanceOf(HTMLElement);
  });

  test('advertises itself to the Lovelace card picker exactly once', () => {
    loadCard();

    const entries = window.customCards.filter(
      (entry) => entry.type === 'powerpetdoor-schedule-card',
    );
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      type: 'powerpetdoor-schedule-card',
      preview: true,
    });
    // A picker entry with no name renders as a blank row.
    expect(entries[0].name).toBeTruthy();
    expect(entries[0].description).toBeTruthy();
  });

  test('prints a version banner a user can read in the console', () => {
    loadCard();

    // Home Assistant caches /local/ hard, so this banner is the only way a
    // user can tell which copy of the card their browser is actually
    // running. scripts/check_card_version.py keeps it in step with the
    // header comment; this asserts it is emitted at all.
    const banner = cardBanner();
    expect(banner).toMatch(/POWERPETDOOR-SCHEDULE-CARD/);
    expect(banner).toMatch(/v\d+\.\d+\.\d+/);
  });
});
