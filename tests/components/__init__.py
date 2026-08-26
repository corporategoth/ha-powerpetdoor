# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Mirrors Home Assistant core's `tests/components/` layout.

Everything below this directory is written the way core writes tests, so
that submitting this integration upstream is a move rather than a rewrite.
The suites that core would not take - the Lovelace card, the hypothesis
fuzzers, the simulator-backed integration tests - live beside it under
`tests/` instead.
"""
