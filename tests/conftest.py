import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    """Isolate tests from the process-wide locmem cache."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
