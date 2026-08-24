# Copyright (c) 2025 Preston Elder
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

"""Settings for the randomized suite.

Kept out of the deterministic gate on purpose: CI's unit matrix runs
everything EXCEPT this directory and must still reach 100% coverage, so
nothing here may be the only thing exercising a line.
"""

from __future__ import annotations

from hypothesis import HealthCheck, settings

# Home Assistant fixtures are function-scoped and hypothesis re-enters the
# test body many times per fixture setup, which trips
# `function_scoped_fixture` by design. The tests here that use `hass` do not
# mutate it across examples, so the check is suppressed rather than worked
# around with module-scoped fixtures that would leak state between examples.
settings.register_profile(
    "fuzz",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
settings.load_profile("fuzz")
