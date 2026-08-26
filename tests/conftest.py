# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""The one fixture that exists only because this ships outside core.

Everything else is either core-shaped and lives in
`tests/components/powerpetdoor/conftest.py`, or belongs to a suite core
would not take and lives with that suite.

This file is deliberately the whole difference: submitting upstream deletes
it, because a core integration is not a custom one and has nothing to
enable.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Load custom_components/ in every test.

    Home Assistant refuses to load custom integrations in tests unless this
    fixture is requested; autouse so no test can forget and then fail with a
    confusing "integration not found".
    """
    yield
