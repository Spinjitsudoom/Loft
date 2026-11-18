"""Runs the web app's JavaScript tests (tests/js) with Node, when Node is installed."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node isn't installed")
def test_web_app_helpers():
    here = Path(__file__).parent / "js"
    r = subprocess.run(["node", "--test", *sorted(str(p) for p in here.glob("*.test.mjs"))],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
