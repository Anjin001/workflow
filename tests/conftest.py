from pathlib import Path

import pytest

from workflow.task import load_task

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def task():
    return load_task(ROOT / "examples" / "average.json")
