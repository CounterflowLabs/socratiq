"""Helpers for integrating the official Codex CLI/app-server."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_DEVICE_URL_RE = re.compile(r"https://auth\.openai\.com/codex/device")
_DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4,5}-[A-Z0-9]{4,6}\b")
_CHATGPT_LOGIN_RE = re.compile(r"logged in using chatgpt", re.IGNORECASE)
_APIKEY_LOGIN_RE = re.compile(r"logged in using api", re.IGNORECASE)


def get_codex_home() -> str:
    """Return the configured Codex home directory."""
    return os.environ.get("CODEX_HOME", "/codex-home")


def get_codex_env() -> dict[str, str]:
    """Build a clean environment for Codex CLI subprocesses."""
    env = os.environ.copy()
    env["CODEX_HOME"] = get_codex_home()
    env.setdefault("TERM", "dumb")
    env.setdefault("NO_COLOR", "1")
    return env


def get_codex_bin() -> str | None:
    """Resolve the Codex CLI binary path."""
    explicit = os.environ.get("CODEX_BIN")
    if explicit:
        return explicit
    return shutil.which("codex")


def require_codex_bin() -> str:
    """Resolve the Codex CLI binary path or raise."""
    codex_bin = get_codex_bin()
    if codex_bin:
        return codex_bin
    raise RuntimeError(
        "Codex CLI is not installed in the backend container. "
        "Rebuild Docker so the official Codex binary is present."
    )


def get_codex_app_server_command() -> list[str]:
    """Return the app-server command argv."""
    return [require_codex_bin(), "app-server"]


def _clean_cli_output(text: str) -> str:
    cleaned = _ANSI_RE.sub("", text).replace("\r", "")
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip()


async def get_codex_login_status() -> dict[str, Any]:
    """Return whether Codex CLI is available and logged in."""
    codex_bin = get_codex_bin()
    if not codex_bin:
        return {
            "available": False,
            "logged_in": False,
            "auth_mode": None,
            "message": "backend 容器内未安装 Codex CLI",
        }

    proc = await asyncio.create_subprocess_exec(
        codex_bin,
        "login",
        "status",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=get_codex_env(),
    )
    stdout, _ = await proc.communicate()
    output = _clean_cli_output(stdout.decode("utf-8", errors="replace"))

    auth_mode: Literal["chatgpt", "apikey"] | None = None
    if _CHATGPT_LOGIN_RE.search(output):
        auth_mode = "chatgpt"
    elif _APIKEY_LOGIN_RE.search(output):
        auth_mode = "apikey"

    return {
        "available": True,
        "logged_in": auth_mode is not None,
        "auth_mode": auth_mode,
        "message": output or "无法读取 Codex 登录状态",
    }


async def list_codex_models() -> list[dict[str, str]]:
    """List available Codex models via the official app-server."""
    try:
        from codex_app_server_sdk import CodexClient
    except ImportError as exc:
        raise RuntimeError(
            "Python package codex-app-server-sdk is not installed."
        ) from exc

    async with CodexClient.connect_stdio(
        command=get_codex_app_server_command(),
        env=get_codex_env(),
        request_timeout=30.0,
        inactivity_timeout=30.0,
    ) as client:
        await client.initialize()
        payload = await client.list_models(include_hidden=False)

    data = payload.get("data", []) if isinstance(payload, dict) else []
    models: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("model") or "").strip()
        if not model_id:
            continue
        display_name = str(item.get("displayName") or item.get("model") or model_id).strip()
        description = str(item.get("description") or "").strip()
        models.append(
            {
                "id": model_id,
                "display_name": display_name,
                "description": description,
            }
        )

    models.sort(key=lambda model: (model["id"] != "gpt-5-codex", model["display_name"]))
    return models


@dataclass(slots=True)
class CodexLoginSession:
    """In-memory device-auth login session."""

    id: str
    process: asyncio.subprocess.Process
    status: Literal["pending", "waiting_for_user", "completed", "failed"] = "pending"
    verification_url: str | None = None
    user_code: str | None = None
    message: str | None = None
    logged_in: bool = False
    output_lines: list[str] = field(default_factory=list)
    monitor_task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "status": self.status,
            "verification_url": self.verification_url,
            "user_code": self.user_code,
            "message": self.message,
            "logged_in": self.logged_in,
        }


class CodexLoginManager:
    """Track one or more device-auth flows in-process."""

    def __init__(self) -> None:
        self._sessions: dict[str, CodexLoginSession] = {}
        self._lock = asyncio.Lock()

    def get(self, session_id: str) -> CodexLoginSession | None:
        return self._sessions.get(session_id)

    async def start(self) -> dict[str, Any]:
        """Start or reuse a device-auth session."""
        status = await get_codex_login_status()
        if status["logged_in"]:
            return {
                "session_id": None,
                "status": "completed",
                "verification_url": None,
                "user_code": None,
                "message": status["message"],
                "logged_in": True,
            }

        async with self._lock:
            for session in self._sessions.values():
                if (
                    session.status in {"pending", "waiting_for_user"}
                    and session.process.returncode is None
                ):
                    return session.snapshot()

            proc = await asyncio.create_subprocess_exec(
                require_codex_bin(),
                "login",
                "--device-auth",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=get_codex_env(),
            )
            session = CodexLoginSession(id=str(uuid.uuid4()), process=proc)
            session.monitor_task = asyncio.create_task(self._monitor(session))
            self._sessions[session.id] = session

        await self._wait_until_ready(session)
        return session.snapshot()

    async def _wait_until_ready(self, session: CodexLoginSession) -> None:
        for _ in range(40):
            if session.verification_url or session.user_code or session.status in {
                "completed",
                "failed",
            }:
                return
            await asyncio.sleep(0.25)

    async def _monitor(self, session: CodexLoginSession) -> None:
        stream = session.process.stdout
        if stream is None:
            session.status = "failed"
            session.message = "无法读取 Codex 登录输出。"
            return

        while True:
            line = await stream.readline()
            if not line:
                break

            cleaned = _clean_cli_output(line.decode("utf-8", errors="replace"))
            if not cleaned:
                continue
            session.output_lines.append(cleaned)

            if session.verification_url is None:
                url_match = _DEVICE_URL_RE.search(cleaned)
                if url_match:
                    session.verification_url = url_match.group(0)

            if session.user_code is None:
                code_match = _DEVICE_CODE_RE.search(cleaned)
                if code_match:
                    session.user_code = code_match.group(0)

            if session.verification_url and session.user_code:
                session.status = "waiting_for_user"
                session.message = "请在浏览器完成 ChatGPT 登录。"

        return_code = await session.process.wait()
        status = await get_codex_login_status()

        if return_code == 0 and status["logged_in"]:
            session.status = "completed"
            session.logged_in = True
            session.message = "ChatGPT 登录成功。"
            return

        if session.status != "completed":
            session.status = "failed"
            session.logged_in = False
            session.message = (
                status["message"]
                or (session.output_lines[-1] if session.output_lines else None)
                or "Codex 登录失败。"
            )


codex_login_manager = CodexLoginManager()
