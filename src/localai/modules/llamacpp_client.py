from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


@dataclass
class LlamaCppConfig:
    base_url: str = "http://127.0.0.1:8080/v1"
    model: str = "local-model"
    autostart: bool = False
    server_path: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    extra_dll_dirs: tuple[str, ...] = ()
    n_gpu_layers: int = 999
    ctx_size: int = 8192
    reasoning: str = "off"
    reasoning_budget: int = 0
    startup_timeout_seconds: int = 120

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LlamaCppConfig":
        data = config.get("llamacpp", {}) if config else {}
        return cls(
            base_url=str(data.get("base_url") or cls.base_url),
            model=str(data.get("model") or cls.model),
            autostart=_to_bool(data.get("autostart", cls.autostart)),
            server_path=str(data.get("server_path") or ""),
            model_path=str(data.get("model_path") or ""),
            mmproj_path=str(data.get("mmproj_path") or ""),
            extra_dll_dirs=_split_paths(data.get("extra_dll_dirs", ())),
            n_gpu_layers=int(data.get("n_gpu_layers") or cls.n_gpu_layers),
            ctx_size=int(data.get("ctx_size") or cls.ctx_size),
            reasoning=str(data.get("reasoning") or cls.reasoning),
            reasoning_budget=int(data.get("reasoning_budget") or cls.reasoning_budget),
            startup_timeout_seconds=int(
                data.get("startup_timeout_seconds") or cls.startup_timeout_seconds
            ),
        )


class LlamaCppClient:
    """Small OpenAI-compatible client for llama.cpp server."""

    def __init__(self, config: LlamaCppConfig, log_dir: str | os.PathLike[str] = "logs") -> None:
        self.config = config
        self.log_dir = Path(log_dir)
        self._process: subprocess.Popen[bytes] | None = None

    def ensure_server(self) -> tuple[dict[str, Any], dict[str, Any]]:
        logger.info(
            "检查本地 AI 服务: base_url=%s, model=%s, autostart=%s",
            self.config.base_url,
            self.config.model,
            self.config.autostart,
        )
        if self.is_healthy():
            logger.info("本地 AI 服务已可用，无需启动。")
            return self.health(), self.models()

        if not self.config.autostart:
            logger.error("本地 AI 服务不可用，且 LLAMACPP_AUTOSTART=false。")
            raise RuntimeError(
                "llama.cpp service is not available and LLAMACPP_AUTOSTART is false. "
                "Start llama-server first or enable autostart in common.env."
            )

        logger.info("本地 AI 服务不可用，开始自动启动 llama.cpp 服务。")
        self.start_server()
        deadline = time.time() + self.config.startup_timeout_seconds
        next_log_at = time.time()
        while time.time() < deadline:
            if self.is_healthy():
                logger.info("本地 AI 服务启动成功。")
                return self.health(), self.models()
            now = time.time()
            if now >= next_log_at:
                remaining = int(deadline - now)
                logger.info("等待本地 AI 服务就绪，剩余约 %s 秒。", max(0, remaining))
                next_log_at = now + 10
            time.sleep(2)

        logger.error("等待本地 AI 服务启动超时，超时时间 %s 秒。", self.config.startup_timeout_seconds)
        raise RuntimeError("Timed out waiting for llama.cpp service to become healthy.")

    def start_server(self) -> None:
        server_path = Path(self.config.server_path)
        model_path = Path(self.config.model_path)
        logger.info("准备启动 llama.cpp: server_path=%s", server_path)
        logger.info("准备启动 llama.cpp: model_path=%s", model_path)
        if self.config.mmproj_path:
            logger.info("准备启动 llama.cpp: mmproj_path=%s", self.config.mmproj_path)
        if not server_path.exists():
            logger.error("LLAMACPP_SERVER_PATH 不存在: %s", server_path)
            raise FileNotFoundError(f"LLAMACPP_SERVER_PATH does not exist: {server_path}")
        if not model_path.exists():
            logger.error("LLAMACPP_MODEL_PATH 不存在: %s", model_path)
            raise FileNotFoundError(f"LLAMACPP_MODEL_PATH does not exist: {model_path}")

        parsed = urlparse(self.config.base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8080

        command = [
            str(server_path),
            "-m",
            str(model_path),
            "--alias",
            self.config.model,
            "-c",
            str(self.config.ctx_size),
            "-ngl",
            str(self.config.n_gpu_layers),
            "--reasoning",
            self.config.reasoning,
            "--reasoning-budget",
            str(self.config.reasoning_budget),
            "--host",
            host,
            "--port",
            str(port),
        ]
        if self.config.mmproj_path:
            command.extend(["--mmproj", self.config.mmproj_path])

        self.log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = self.log_dir / "llama_server.out.log"
        stderr_path = self.log_dir / "llama_server.err.log"
        logger.info("llama.cpp stdout 日志: %s", stdout_path)
        logger.info("llama.cpp stderr 日志: %s", stderr_path)
        env = os.environ.copy()
        path_parts = [str(server_path.parent)]
        path_parts.extend(_expand_dll_dirs(self.config.extra_dll_dirs))
        path_parts.append(env.get("PATH", ""))
        env["PATH"] = os.pathsep.join(path_parts)

        self._process = subprocess.Popen(
            command,
            stdout=stdout_path.open("ab"),
            stderr=stderr_path.open("ab"),
            cwd=str(server_path.parent),
            env=env,
        )
        logger.info("llama.cpp 进程已启动: pid=%s, host=%s, port=%s", self._process.pid, host, port)

    def shutdown_server(self) -> None:
        if not self._process:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=10)
        finally:
            self._process = None

    def assert_model_available(self, models_response: dict[str, Any]) -> None:
        data = models_response.get("data", [])
        model_ids = {str(item.get("id")) for item in data if isinstance(item, dict)}
        if model_ids and self.config.model not in model_ids:
            raise RuntimeError(
                f"Configured model '{self.config.model}' is not in llama.cpp models: "
                f"{', '.join(sorted(model_ids))}"
            )

    def chat(self, messages: list[dict[str, Any]], max_tokens: int = 1024, temperature: float = 0) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        response = self.post_json(f"{self.config.base_url.rstrip('/')}/chat/completions", payload)
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError(f"No choices returned from llama.cpp: {response}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if content is None:
            raise RuntimeError(f"No message.content returned from llama.cpp: {response}")
        return str(content)

    def is_healthy(self) -> bool:
        try:
            self.health()
            return True
        except Exception:
            return False

    def health(self) -> dict[str, Any]:
        return self.get_json(self._server_url("/health"))

    def models(self) -> dict[str, Any]:
        return self.get_json(f"{self.config.base_url.rstrip('/')}/models")

    def get_json(self, url: str) -> dict[str, Any]:
        request = Request(url, method="GET")
        return _read_json(request)

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return _read_json(request)

    def _server_url(self, path: str) -> str:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        return f"{base_url}{path}"


def _read_json(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"HTTP request failed: {request.full_url}") from exc


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_paths(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    raw = str(value).strip()
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(os.pathsep) if item.strip())


def _expand_dll_dirs(paths: tuple[str, ...]) -> list[str]:
    expanded: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            expanded.append(str(path))
            continue
        expanded.append(str(path))
        expanded.extend(str(child) for child in path.iterdir() if child.is_dir())
    return expanded
