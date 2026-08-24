/**
 * The card's time arithmetic, at the boundaries that decide behaviour.
 *
 * This is the half of the card a user never sees directly and feels
 * immediately: it converts a pointer position into a time, a time into a
 * bar on a grid, and back again. Every value below is a boundary - midnight,
 * the last minute of the day, the midnight wrap, the clamp at each end -
 * because the middle of the range is where every implementation agrees.
 *
 * The all-day and overnight cases are not hypothetical shapes. The door
 * stores "always" as 00:00-00:00 and an overnight window as end-before-start,
 * and findings F1 and F2 were both this maths getting them wrong.
 */

describe('time arithmetic', () => {
  let card;

  beforeEach(() => {
    loadCard();
    card = document.createElement('powerpetdoor-schedule-card');
  });

  describe('_parseTimeToMinutes', () => {
    test.each([
      ['00:00', 0],
      ['00:01', 1],
      ['06:00', 360],
      ['12:00', 720],
      ['23:59', 1439],
      ['06:00:00', 360],
    ])('reads %s as %i minutes', (value, expected) => {
      expect(card._parseTimeToMinutes(value)).toBe(expected);
    });

    test.each([['', 0], [null, 0], [undefined, 0]])(
      'treats %p as midnight rather than NaN',
      (value, expected) => {
        // NaN would propagate into a `top: NaN%` style and collapse the bar
        // to nothing, with no error anywhere.
        expect(card._parseTimeToMinutes(value)).toBe(expected);
      },
    );
  });

  describe('_minutesToTime', () => {
    test.each([
      [0, '00:00'],
      [1, '00:01'],
      [360, '06:00'],
      [1439, '23:59'],
    ])('renders %i minutes as %s', (value, expected) => {
      expect(card._minutesToTime(value)).toBe(expected);
    });

    test('clamps the end of the day to 23:59, never 24:00', () => {
      // "24:00" is not a time. `<input type="time">` refuses it, so the edit
      // dialog rendered blank and Save was a dead button, and the backend
      // schema rejects it outright. This clamp is what finding F1 was about.
      expect(card._minutesToTime(1440)).toBe('23:59');
      expect(card._minutesToTime(9999)).toBe('23:59');
    });

    test('clamps below midnight to 00:00', () => {
      expect(card._minutesToTime(-1)).toBe('00:00');
      expect(card._minutesToTime(-9999)).toBe('00:00');
    });

    test('always pads to HH:MM', () => {
      // The backend pattern requires two digits: "6:00" is rejected, so an
      // unpadded hour would make every save before 10am fail.
      expect(card._minutesToTime(0)).toMatch(/^\d{2}:\d{2}$/);
      expect(card._minutesToTime(65)).toBe('01:05');
    });
  });

  describe('_roundToInterval', () => {
    test.each([
      [0, 0],
      [7, 0],
      [8, 15],
      [15, 15],
      [22, 15],
      [23, 30],
    ])('snaps %i to %i', (value, expected) => {
      // Both sides of the 7/8 rounding boundary: a drag lands anywhere and
      // must snap predictably, or a window's edge jitters under the cursor.
      expect(card._roundToInterval(value)).toBe(expected);
    });

    test('a snap past the end of the day is still rendered as 23:59', () => {
      // 1439 rounds UP to 1440, which is midnight tomorrow. Composed with
      // the clamp, dragging to the very bottom of a column yields the last
      // minute of the day rather than an invalid time.
      expect(card._roundToInterval(1439)).toBe(1440);
      expect(card._minutesToTime(card._roundToInterval(1439))).toBe('23:59');
    });
  });

  describe('_slotSpanMinutes', () => {
    test('an ordinary window spans start to end', () => {
      expect(card._slotSpanMinutes({ from: '06:00', to: '20:00' })).toBe(840);
    });

    test('00:00-00:00 spans the whole day', () => {
      // Midnight is positional: closing a window it is the day's LAST
      // minute. Subtracting naively gives 0, which drew a 14px stub pinned
      // at midnight (finding F2).
      expect(card._slotSpanMinutes({ from: '00:00', to: '00:00' })).toBe(1440);
    });

    test('a same-time window at any OTHER hour spans nothing', () => {
      // Only midnight is special, and only because of its position. Measured
      // against firmware 1.7.18: 09:00-09:00 leaves the sensor disabled, so
      // it is an empty window, not a whole day.
      expect(card._slotSpanMinutes({ from: '09:00', to: '09:00' })).toBe(0);
    });

    test('a window ending before it starts spans nothing', () => {
      // 22:00 to 06:00 does not wrap. Measured: an inverted window leaves
      // the sensor disabled on the day it names AND on the day after, so it
      // is neither a same-day wrap nor a spill into tomorrow.
      expect(card._slotSpanMinutes({ from: '22:00', to: '06:00' })).toBe(0);
    });

    test('an evening window runs to the end of its day', () => {
      // The half of an overnight schedule that lives on this day, spelled
      // with midnight as the end. 23:59 is NOT the same thing - it is one
      // minute short, and honestly so.
      expect(card._slotSpanMinutes({ from: '22:00', to: '00:00' })).toBe(120);
      expect(card._slotSpanMinutes({ from: '22:00', to: '23:59' })).toBe(119);
    });

    test('a one-minute window spans one minute', () => {
      expect(card._slotSpanMinutes({ from: '06:00', to: '06:01' })).toBe(1);
    });
  });

  describe('_slotCovers', () => {
    test.each([
      [359, false],
      [360, true],
      [1199, true],
      [1200, false],
    ])('an ordinary window covers minute %i: %p', (minute, expected) => {
      // Start inclusive, end exclusive - both sides of both edges, so an
      // inverted comparison cannot pass.
      expect(card._slotCovers({ from: '06:00', to: '20:00' }, minute)).toBe(expected);
    });

    test.each([[1319], [1320], [1439], [0], [359], [360]])(
      'a window ending before it starts covers no minute, including %i',
      (minute) => {
        // It does not wrap. The card used to report this covered from 22:00
        // through 06:00, so the highlight claimed the pet had access for
        // eight hours a night that the door was refusing.
        expect(card._slotCovers({ from: '22:00', to: '06:00' }, minute)).toBe(false);
      },
    );

    test.each([
      [1319, false],
      [1320, true],
      [1439, true],
    ])('a window ending at midnight covers minute %i: %p', (minute, expected) => {
      // The last minute of the day IS inside it, because midnight closing a
      // window is the day's last minute.
      expect(card._slotCovers({ from: '22:00', to: '00:00' }, minute)).toBe(expected);
    });

    test('an end of 23:59 stops one minute short, and says so', () => {
      // The control: only midnight reaches past 23:59. The device is
      // measured to accept 24:00, so there is no reason to read a literal
      // 23:59 as anything but 23:59.
      expect(card._slotCovers({ from: '22:00', to: '23:59' }, 1438)).toBe(true);
      expect(card._slotCovers({ from: '22:00', to: '23:59' }, 1439)).toBe(false);
    });

    test.each([[0], [720], [1439]])('an all-day window covers minute %i', (minute) => {
      expect(card._slotCovers({ from: '00:00', to: '00:00' }, minute)).toBe(true);
    });
  });

  describe('_getSlotStyle', () => {
    test('an all-day window fills the column', () => {
      // Finding F2: this rendered as a 14px stub, so the out-of-box state
      // looked like a door with almost no schedule at all.
      expect(card._getSlotStyle({ from: '00:00', to: '00:00' })).toBe(
        'top: 0%; height: 100%;',
      );
    });

    test('an ordinary window starts and ends where it should', () => {
      // 06:00 is a quarter of the way down; 14 hours is 58.33% of a day.
      const style = card._getSlotStyle({ from: '06:00', to: '20:00' });
      expect(style).toMatch(/^top: 25%;/);
      expect(style).toMatch(/height: 58\.33/);
    });

    test('an evening window runs to the bottom of the column', () => {
      // The evening half of an overnight schedule. Read as a wrap it drew a
      // 14px stub at 22:00; read as "22:00 to the end of the day" it is the
      // two-hour bar it actually is.
      const style = card._getSlotStyle({ from: '22:00', to: '00:00' });
      expect(style).toMatch(/^top: 91\.66/);
      expect(style).toMatch(/height: 8\.33/);
    });

    test('a very short window still gets a clickable minimum height', () => {
      // A 1-minute window is 0.07% of a day, which is sub-pixel. The 1.5%
      // floor is what keeps it hittable at all (finding F3).
      expect(card._getSlotStyle({ from: '06:00', to: '06:01' })).toBe(
        'top: 25%; height: 1.5%;',
      );
    });
  });

  describe('midnight is the only end that reaches past 23:59', () => {
    // The device's end-of-day is 24:00, which HA's HH:MM shape cannot write,
    // so midnight stands in for it. Nothing else is special - the engine is
    // taken literally everywhere else.

    test('the last minute of an all-day window is covered', () => {
      expect(card._slotCovers({ from: '00:00', to: '00:00' }, 1439)).toBe(true);
    });

    test('an all-day window spans the whole day', () => {
      expect(card._slotSpanMinutes({ from: '00:00', to: '00:00' })).toBe(1440);
    });

    test('an ordinary end is exclusive, and gains nothing', () => {
      expect(card._slotCovers({ from: '06:00', to: '22:00' }, 1319)).toBe(true);
      expect(card._slotCovers({ from: '06:00', to: '22:00' }, 1320)).toBe(false);
    });
  });

  describe('_yToMinutes', () => {
    const rect = { top: 0, height: 480 };

    test.each([
      [0, 0],
      [240, 720],
      [479, 1437],
    ])('maps y=%i to minute %i', (y, expected) => {
      expect(card._yToMinutes(y, rect)).toBe(expected);
    });

    test('clamps a pointer above the column to midnight', () => {
      // A drag that leaves the column upward must not produce a negative
      // time, which would render as a bar above the grid.
      expect(card._yToMinutes(-100, rect)).toBe(0);
    });

    test('clamps a pointer below the column to the end of the day', () => {
      expect(card._yToMinutes(10000, rect)).toBe(1440);
      // ...and composed with the clamp, that is a valid time.
      expect(card._minutesToTime(card._yToMinutes(10000, rect))).toBe('23:59');
    });

    test('honours a column that does not start at the top of the page', () => {
      // The grid is rarely at y=0 in a real dashboard; ignoring rect.top
      // offsets every drag by the height of everything above the card.
      expect(card._yToMinutes(100, { top: 100, height: 480 })).toBe(0);
      expect(card._yToMinutes(340, { top: 100, height: 480 })).toBe(720);
    });
  });

  describe('clock formatting', () => {
    test.each([
      ['00:00', '12:00 AM'],
      ['00:30', '12:30 AM'],
      ['09:05', '9:05 AM'],
      ['12:00', '12:00 PM'],
      ['13:05', '1:05 PM'],
      ['23:59', '11:59 PM'],
    ])('formats %s as %s', (value, expected) => {
      // Midnight and noon are the two the 12-hour clock gets wrong: both
      // are hour 12, and `hours % 12` alone renders them as "0:00".
      expect(card._formatTime(value)).toBe(expected);
    });

    test.each([
      ['00:00', '12:00a'],
      ['12:00', '12:00p'],
      ['23:59', '11:59p'],
    ])('formats %s compactly as %s', (value, expected) => {
      expect(card._formatTimeShort(value)).toBe(expected);
    });

    test('renders an absent time as empty rather than as NaN', () => {
      expect(card._formatTime('')).toBe('');
      expect(card._formatTimeShort('')).toBe('');
    });
  });
});
