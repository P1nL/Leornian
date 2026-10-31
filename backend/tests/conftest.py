import os
from urllib.parse import urlparse

import pytest

from leornian.bootstrap.services import GoalWorkflow
from leornian.platform.database import Database
from leornian.platform.migrate import migrate


@pytest.fixture(scope="session")
def database():
    url = os.environ.get("LEORNIAN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set LEORNIAN_TEST_DATABASE_URL to the isolated Leornian test database")
    if urlparse(url).path != "/leornian_test":
        pytest.fail("Integration tests only accept the leornian_test database")
    migrate(url)
    return Database(url)


@pytest.fixture
def workflow(database):
    return GoalWorkflow(database)


@pytest.fixture
def session(workflow):
    return workflow.create_session("Test learner")
