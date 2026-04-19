"""Helpers for LLM provider endpoint URLs."""

from pathlib import Path
from urllib.parse import urlparse, urlunparse


def normalize_container_localhost_url(base_url: str | None) -> str | None:
    """Map localhost endpoints to the host machine when running in Docker.

    In Docker, `localhost` and `127.0.0.1` point at the backend container, not
    the user's machine. The compose file exposes `host.docker.internal`, so
    local OpenAI-compatible endpoints such as Ollama or a local API server work
    when users enter a familiar localhost URL in the setup form.
    """
    if not base_url or not Path("/.dockerenv").exists():
        return base_url

    parsed = urlparse(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return base_url

    netloc = "host.docker.internal"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"

    return urlunparse(parsed._replace(netloc=netloc))
