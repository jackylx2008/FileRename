from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def load_runtime_config(
    config_path: str | os.PathLike[str] = "config.yaml",
    env_path: str | os.PathLike[str] = "common.env",
) -> dict[str, Any]:
    """Load common.env first, then config.yaml with ${ENV:-default} expansion."""
    load_env_file(env_path)
    config_file = Path(config_path)
    if not config_file.exists():
        return {}

    with config_file.open("r", encoding="utf-8") as file_obj:
        raw_config = yaml.safe_load(file_obj) or {}

    if not isinstance(raw_config, dict):
        raise ValueError(f"Config file must contain a mapping: {config_file}")
    return resolve_env_values(raw_config)


def load_env_file(env_path: str | os.PathLike[str], override: bool = False) -> None:
    """Load KEY=VALUE pairs from a local env file."""
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value.strip())
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def resolve_env_values(value: Any) -> Any:
    """Resolve ${ENV_VAR:-default} placeholders recursively."""
    if isinstance(value, dict):
        return {key: resolve_env_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_env_values(item) for item in value]
    if isinstance(value, str):
        return _resolve_string(value)
    return value


def _resolve_string(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        env_name = match.group(1)
        default = match.group(2)
        env_value = os.getenv(env_name)
        if env_value is not None:
            return env_value
        return default or ""

    return ENV_PATTERN.sub(replace, value)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
