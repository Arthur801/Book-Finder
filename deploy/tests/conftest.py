"""Registers the integration marker for the deploy tests.

Why: the integration tests need docker and a free port 5000, so they are opt-in (BOOKFINDER_IT=1) and selected with -m.
"""


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: drives real docker containers; needs BOOKFINDER_IT=1")
