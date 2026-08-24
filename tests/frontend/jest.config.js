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
  // `branches` reads as a reduction from the previous 100 and is not one.
  // That 100% was 2 branches out of 2: only the registration code ran, so
  // the denominator was almost the whole file's worth of code that never
  // executed. The suite now runs 300 branches and covers 285 of them, and
  // every other metric is at 100%. The 15 uncovered arcs are the else side
  // of optional chaining on `this.shadowRoot`, which a constructed custom
  // element always has - reaching them would mean asserting a state the
  // browser cannot produce.
  coverageThreshold: {
    global: {
      branches: 95,
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
