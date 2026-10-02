import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("YGG_DATA_DIR", str(ROOT / "data"))
os.environ.setdefault("YGG_ETC_DIR", str(ROOT / "tests" / "no-etc"))
os.environ["NO_COLOR"] = "1"

from yggdrasil.common import Runner  # noqa: E402


class FakeRunner(Runner):
    """Runner qui n'exécute rien : réponses préparées pour `query`, journal des `run`."""

    def __init__(self, responses=None, **kwargs):
        super().__init__(**kwargs)
        self.responses = responses or {}
        self.calls = []

    def query(self, cmd, *, root=False, timeout=30):
        key = " ".join(cmd)
        self.calls.append(("query", key))
        for prefix, response in self.responses.items():
            if key.startswith(prefix):
                return response
        return (1, "")

    def run(self, cmd, *, root=False, check=True, capture=False, input=None, env=None, cwd=None):
        self.calls.append(("run", " ".join(cmd), root, input))
        return subprocess.CompletedProcess(list(cmd), 0, "", "")

    def write_file(self, path, content, *, root=False, mode="644"):
        self.calls.append(("write", str(path), content))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Les tests n'écrivent jamais dans ton vrai dossier personnel (profil, puits, cache…)."""
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var.lower()))


@pytest.fixture
def fake_runner():
    return FakeRunner


@pytest.fixture
def root_dir():
    return ROOT
