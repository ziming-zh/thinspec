import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from thinspec.core import Repo  # noqa: E402
from thinspec.install import init  # noqa: E402


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def step(self, seconds):
        self.t += seconds
        return self.t


@pytest.fixture(autouse=True)
def no_session_in_env(monkeypatch):
    """Tests may run inside an agent session; its id must not sign what they record."""
    for name in ("THINSPEC_SESSION", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path):
    """A repo with a core node and one design, 'instrument', under it."""
    init(tmp_path, claude=False)
    r = Repo(tmp_path)
    r.add_node("instrument", "Instrument", "core", "Where we hook into each step.",
               ["One unique hook point per step."])
    return r


@pytest.fixture
def clock(repo):
    c = Clock()
    repo.ledger.clock = c
    return c
