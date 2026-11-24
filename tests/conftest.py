from zoneinfo import ZoneInfo

import pytest

from custom_components.vitality.storage import Diary


@pytest.fixture
def diary(tmp_path):
    database = Diary(tmp_path / "vitality.sqlite")
    database.initialize()
    return database


@pytest.fixture
def zone():
    return ZoneInfo("Europe/Zurich")
