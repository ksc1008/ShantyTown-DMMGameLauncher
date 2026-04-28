"""Test-time defaults.

Forces the i18n translator to Korean so existing tests that assert
specific Korean labels (``"설정 필요"``, ``"실행"``, …) keep passing
regardless of the host machine's actual locale. Tests that need to
verify English behavior should call ``init_translator("en")``
themselves.
"""

from __future__ import annotations

import pytest

from shantytown.core.i18n import KO, init_translator


@pytest.fixture(autouse=True)
def _force_ko_locale() -> None:
    init_translator(KO)
