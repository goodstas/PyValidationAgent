from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from secureyourcode.config import load_settings

APP_ROOT = Path(__file__).resolve().parents[1]
DEMO = APP_ROOT / "demo" / "DemoShop"
ANALYZER = APP_ROOT / "roslyn/SecureYourCode.PerformanceAnalyzer/bin/Release/netstandard2.0/SecureYourCode.PerformanceAnalyzer.dll"

needs_dotnet = pytest.mark.skipif(shutil.which("dotnet") is None or not ANALYZER.is_file(), reason="dotnet SDK or built analyzer DLL unavailable")


@pytest.fixture
def tmp_outside(tmp_path_factory) -> Path:
    """Temp dir guaranteed outside the application repository (STATE_DIR / copies of the fixture)."""
    d = Path(tempfile.mkdtemp(prefix="syc-test-"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def demo_copy(tmp_outside: Path) -> Path:
    dest = tmp_outside / "DemoShop"
    shutil.copytree(DEMO, dest, ignore=shutil.ignore_patterns("bin", "obj"))
    return dest


@pytest.fixture
def settings_factory(tmp_outside: Path):
    def make(**overrides: str):
        env = {
            "STATE_DIR": str(tmp_outside / "state"),
            "REPO_ROOT": str(DEMO),
            "GEMINI_MODEL": "fake-model-for-tests",
            "GOOGLE_CLOUD_PROJECT": "test-project",
            "GOOGLE_CLOUD_LOCATION": "global",
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
            "SCAN_TIMEOUT_SECONDS": "300",
            "MAX_REVIEW_CANDIDATES": "16",
            "PATH": os.environ.get("PATH", ""),
        }
        env.update(overrides)
        return load_settings(env_file=tmp_outside / "no.env", environ=env)

    return make
