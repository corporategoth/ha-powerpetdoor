# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Namespace package so `custom_components.powerpetdoor` is importable in tests.

Home Assistant loads custom integrations by path at runtime and never imports
this package, but pytest does - `tests/` imports
`custom_components.powerpetdoor.const` directly. Without this file that is an
ImportError.
"""
