#!/usr/bin/env bash
# Development environment setup for ha-powerpetdoor.
#
# Idempotent: safe to re-run after pulling a change to
# .pre-commit-config.yaml, pyproject.toml or tests/frontend/package.json.
#
# This repo has two toolchains. The Python one covers the integration; the
# npm one covers www/powerpetdoor-schedule-card.js, which is browser
# JavaScript with no build step - npm is only ever used to install the test
# and lint tooling, never to bundle or package the card.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "Step 1: Installing the integration and its dev dependencies..."
echo "--------------------------------------------------------------"
if command -v uv &> /dev/null; then
    uv sync --all-extras
    RUN="uv run"
else
    echo "uv not found (https://docs.astral.sh/uv/); falling back to pip."
    echo "Note: the dev dependency group pins pytest-homeassistant-custom-component"
    echo "      by interpreter, so pip needs a venv on a supported Python."
    pip install -e . --group dev
    RUN=""
fi

echo
echo "Step 2: Installing the frontend test toolchain..."
echo "-------------------------------------------------"
# The card itself needs nothing installed to run - a browser loads it as-is.
# These are jest/eslint only, so a contributor who is only touching Python
# can skip this and everything except the two card hooks still works.
if command -v npm &> /dev/null; then
    npm install --no-audit --no-fund
    echo "Installed: jest (jsdom) and eslint for www/powerpetdoor-schedule-card.js"
else
    echo "Warning: npm not found; the card's lint and test hooks will not run."
    echo "  The Python side is unaffected. Install Node (>=22) to enable them."
fi

echo
echo "Step 3: Installing git hooks..."
echo "-------------------------------"
# Hooks are the only part of this that a fresh clone does NOT get for free:
# .pre-commit-config.yaml is checked in, but nothing runs it until these two
# commands have been run once in the working copy.
if $RUN pre-commit --version &> /dev/null; then
    $RUN pre-commit install
    $RUN pre-commit install --hook-type pre-push
    echo "Installed: pre-commit (lint, format, types, fast tests, card lint/tests)"
    echo "           pre-push   (full suite + 100% coverage, deps, HA matrix)"
else
    echo "Warning: pre-commit not available."
    echo "  With uv:  uv sync --all-extras   (it is in the dev group)"
    echo "  With pip: pip install pre-commit"
fi

echo
echo "Step 4: Checking dependency freshness..."
echo "----------------------------------------"
$RUN python scripts/check_dependencies.py || true

echo
echo "Done. Useful commands:"
echo "  uv run pytest                               Run the Python suite"
echo "  uv run pytest --cov                         ...with the 100% coverage gate"
echo "  uv run ruff check custom_components tests   Lint"
echo "  uv run mypy custom_components               Type-check"
echo "  npm test                                    Card tests (jsdom)"
echo "  npm run lint                                Card lint"
echo "  uv run python scripts/check_translations.py --untranslated"
echo "  uv run python scripts/ha_matrix.py --quick  Which (python, HA) pairs work"
echo "  pre-commit run --all-files                  Run every hook over the tree"
echo
echo "Optional: 'direnv allow' activates .venv automatically on cd (.envrc)."
