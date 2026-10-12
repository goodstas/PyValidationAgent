"""Configuration: process environment > .env > application defaults."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

APP_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER_TOKEN = "REPLACE_WITH_LONG_RANDOM_TOKEN"
MIN_TOKEN_LENGTH = 32

DEFAULTS: dict[str, str] = {
    "GOOGLE_CLOUD_LOCATION": "global",
    "GOOGLE_GENAI_USE_VERTEXAI": "true",
    "REPO_ROOT": "./demo/DemoShop",
    "STATE_DIR": "~/.secureyourcode-state",
    "SCAN_TIMEOUT_SECONDS": "300",
    "MAX_REVIEW_CANDIDATES": "16",
    "ALLOW_UNAUTHENTICATED_LOOPBACK": "false",
}


class ConfigError(RuntimeError):
    """Invalid or missing configuration; the message is safe to print (never contains secrets)."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    state_dir: Path
    google_cloud_project: str | None
    google_cloud_location: str
    gemini_model: str | None
    use_vertexai: bool
    scan_timeout_seconds: int
    max_review_candidates: int
    service_token: str | None = field(repr=False)
    allow_unauthenticated_loopback: bool
    analyzer_dll: Path
    app_root: Path = APP_ROOT

    def require_model(self) -> None:
        """Live model calls need an explicit model, project and Vertex mode; fail clearly otherwise."""
        if not self.gemini_model:
            raise ConfigError("GEMINI_MODEL is not configured (it is mandatory; no default model is assumed).")
        if not self.google_cloud_project or self.google_cloud_project == "YOUR_PROJECT_ID":
            raise ConfigError("GOOGLE_CLOUD_PROJECT is not configured.")
        if not self.use_vertexai:
            raise ConfigError("GOOGLE_GENAI_USE_VERTEXAI must be true: only Vertex AI is supported.")


def _resolve_path(raw: str, base: Path) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def load_settings(env_file: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    environ = dict(os.environ if environ is None else environ)
    env_file = env_file if env_file is not None else APP_ROOT / ".env"
    file_values = {k: v for k, v in dotenv_values(env_file).items() if v is not None} if env_file.is_file() else {}

    def get(key: str) -> str | None:
        if key in environ and environ[key] != "":
            return environ[key]
        if key in file_values and file_values[key] != "":
            return file_values[key]
        return DEFAULTS.get(key)

    repo_root = _resolve_path(get("REPO_ROOT") or "", APP_ROOT)
    state_dir = _resolve_path(get("STATE_DIR") or "", APP_ROOT)
    analyzer = get("ANALYZER_DLL") or str(
        APP_ROOT / "roslyn/SecureYourCode.PerformanceAnalyzer/bin/Release/netstandard2.0/SecureYourCode.PerformanceAnalyzer.dll"
    )

    try:
        timeout = int(get("SCAN_TIMEOUT_SECONDS") or "300")
        max_candidates = int(get("MAX_REVIEW_CANDIDATES") or "16")
    except ValueError as exc:
        raise ConfigError(f"Invalid integer setting: {exc}") from exc

    return Settings(
        repo_root=repo_root,
        state_dir=state_dir,
        google_cloud_project=get("GOOGLE_CLOUD_PROJECT"),
        google_cloud_location=get("GOOGLE_CLOUD_LOCATION") or "global",
        gemini_model=get("GEMINI_MODEL"),
        use_vertexai=_truthy(get("GOOGLE_GENAI_USE_VERTEXAI")),
        scan_timeout_seconds=timeout,
        max_review_candidates=max_candidates,
        service_token=get("SERVICE_TOKEN"),
        allow_unauthenticated_loopback=_truthy(get("ALLOW_UNAUTHENTICATED_LOOPBACK")),
        analyzer_dll=_resolve_path(analyzer, APP_ROOT),
    )


def validate_state_dir(settings: Settings, repo_root: Path | None = None) -> None:
    """STATE_DIR must be absolute and outside both the application repo and the analyzed repo."""
    repo_root = (repo_root or settings.repo_root).resolve()
    state = settings.state_dir
    for label, root in (("application repository", settings.app_root), ("analyzed repository", repo_root)):
        if _is_within(state, root) or _is_within(root, state):
            raise ConfigError(f"STATE_DIR ({state}) must not overlap the {label} ({root}).")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_server_auth(settings: Settings, host: str) -> None:
    """Refuse unsafe server startup: placeholder/short tokens, or no token without explicit loopback opt-in."""
    token = settings.service_token
    if token:
        if token == PLACEHOLDER_TOKEN:
            raise ConfigError("SERVICE_TOKEN is still the placeholder value; generate a random token of 32+ characters.")
        if len(token) < MIN_TOKEN_LENGTH:
            raise ConfigError(f"SERVICE_TOKEN must be at least {MIN_TOKEN_LENGTH} characters.")
        return
    if not is_loopback(host):
        raise ConfigError("Refusing to bind a non-loopback address without SERVICE_TOKEN.")
    if not settings.allow_unauthenticated_loopback:
        raise ConfigError(
            "No SERVICE_TOKEN configured. Set SERVICE_TOKEN, or ALLOW_UNAUTHENTICATED_LOOPBACK=true for loopback-only development."
        )
