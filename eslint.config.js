/**
 * ESLint flat config for the Power Pet Door Lovelace card.
 *
 * The card runs in a browser as a classic script - no modules, no bundler,
 * no Node. So `sourceType` is 'script' and the globals are browser globals
 * only. Configuring it as a module would let `import` past the linter and
 * straight into a runtime SyntaxError in the user's dashboard.
 *
 * This file lives at the REPO ROOT, not next to the toolchain in
 * tests/frontend/. ESLint 9's flat config silently ignores any file outside
 * its config's base path, so a config under tests/frontend/ linted exactly
 * nothing while still exiting 0 - the worst possible failure mode for a
 * lint gate. The npm script cd's to the root and invokes the binary from
 * tests/frontend/node_modules.
 */
const js = require('@eslint/js');
const globals = require('globals');

module.exports = [
  {
    // Never lint installed dependencies or coverage output.
    ignores: ['**/node_modules/**', '**/coverage/**'],
  },
  {
    files: ['**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: {
        ...globals.browser,
      },
    },
    rules: {
      ...js.configs.recommended.rules,

      // The card renders device-supplied schedule data. Assigning it into
      // innerHTML is the one XSS vector this file has, and the threat model
      // in .claude/CLAUDE.md calls it out by name. Warn loudly; the existing
      // template rendering uses innerHTML for static markup, so this cannot
      // be an error until that is refactored.
      'no-implied-eval': 'error',
      'no-eval': 'error',

      // A custom element that throws in a lifecycle callback leaves the
      // dashboard with a blank card and no message.
      'no-undef': 'error',
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],

      // Browser-script hygiene.
      'no-var': 'error',
      'prefer-const': 'error',
      eqeqeq: ['error', 'smart'],
      'no-console': ['warn', { allow: ['info', 'warn', 'error'] }],
    },
  },
];
