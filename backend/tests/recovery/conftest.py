import pytest

from tests.recovery.harness import destroy_env, make_env


@pytest.fixture
def renv():
    env = make_env()
    try:
        yield env
    finally:
        destroy_env(env)
