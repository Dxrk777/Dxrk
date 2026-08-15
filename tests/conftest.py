# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def temp_dir() -> Path:
    with TemporaryDirectory() as d:
        yield Path(d)
