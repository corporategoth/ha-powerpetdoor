/**
 * Jest configuration for the Power Pet Door Lovelace card.
 *
 * jsdom, not node: the card is a custom element that touches shadow DOM,
 * CSS custom properties, pointer events and timers. A node environment
 * would let most of it "pass" without ever constructing an element.
 */
const path = require('path');

module.exports = {
  testEnvironment: 'jsdom',

  // rootDir is the REPO ROOT, not this directory. Jest resolves
  // `collectCoverageFrom` globs relative to rootDir and will not glob
  // upward through `../..` - with rootDir set here, the pattern matched
  // nothing, the card reported 0%, and the 60% threshold below "passed"
  // while gating precisely nothing. Rooting at the repo root makes www/ an
  // ordinary child path.
  rootDir: path.resolve(__dirname, '../..'),

  setupFilesAfterEnv: ['<rootDir>/tests/frontend/setup.js'],

  testMatch: [
    '<rootDir>/tests/frontend/unit/**/*.test.js',
    '<rootDir>/tests/frontend/negative/**/*.test.js',
  ],

  collectCoverage: true,
  // Attributed to the real file in www/, not a copy: setup.js `require`s
  // that exact path, so this measures what ships.
  collectCoverageFrom: ['<rootDir>/www/**/*.js'],
  coverageDirectory: '<rootDir>/tests/frontend/coverage',
  coverageReporters: ['text', 'text-summary', 'lcov', 'json'],
  // A RATCHET, not a target. These are set to what the suite currently
  // achieves, so any drop fails the build. Never lower one to make a commit
  // pass - that converts the only frontend regression gate into decoration.
  //
  // `branches` is 444 of 445. The one arc left is the `if (!text)` fallback
  // in `t()`, which no input can reach because check_translations.py fails
  // the build on a key that is not in the table; it is declared in the
  // Acknowledged Gaps section of tests/TESTING_GAPS.md and explained at the
  // call site.
  //
  // It was 95 under jest 29, whose V8 coverage counted 300 branches and
  // reached 285. Jest 30 counts 445 and reaches 444 - the same suite
  // against the same card, measured better. Raising the floor with it is
  // the point of a ratchet: left at 95 the gate would now permit a
  // regression of twenty branches without a word.
  coverageThreshold: {
    global: {
      branches: 99.7,
      functions: 100,
      lines: 100,
      statements: 100,
    },
  },

  // No transpilation: the card is plain ES2022 that browsers run directly,
  // and adding babel here would mean testing something other than what
  // ships.
  transform: {},

  // V8's native coverage rather than babel-plugin-istanbul. Istanbul needs
  // a transform to instrument the source, and adding one would reintroduce
  // exactly the transpilation `transform: {}` exists to avoid. The V8
  // provider reads coverage straight from the engine, so the file measured
  // is the untouched file that ships.
  coverageProvider: 'v8',

  testTimeout: 10000,
  clearMocks: true,
  restoreMocks: true,
  verbose: true,

  reporters: [
    'default',
    ['jest-junit', {
      outputDirectory: '<rootDir>/tests/frontend/coverage',
      outputName: 'junit.xml',
    }],
  ],
};
