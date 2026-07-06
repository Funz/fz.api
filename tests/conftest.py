"""Test fixtures.

Mirrors fz's own convention: run every test in a fresh temporary working
directory and restore the cwd afterwards, so subprocess jobs and fz's
relative-path behavior never pollute the repository.
"""

import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _isolated_cwd():
    prev = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="fzapi-test-") as tmp:
        os.chdir(tmp)
        try:
            yield tmp
        finally:
            os.chdir(prev)
