"""
CLI → Daemon communication over Unix Domain Socket.

Uses SYNC httpx (NOT async) because Typer is synchronous.
httpx.Client supports UDS via HTTPTransport(uds=...).
"""

import logging
from pathlib import Path
from typing import Any

import httpx

from ghost.constants import DAEMON_BASE_URL, DEFAULT_SOCKET_POINTER

logger = logging.getLogger(__name__)


class GhostClient:
    """Synchronous HTTP client that talks to the Ghost daemon over UDS."""

    def __init__(self, socket_path: Path, ghost_home: Path | None = None) -> None:
        self.socket_path = self._resolve_socket(socket_path, ghost_home)
        self._base_url = DAEMON_BASE_URL

    def _resolve_socket(self, default_path: Path, ghost_home: Path | None) -> Path:
        """
        Resolve the actual socket path.

        Edge Case 1: If the socket path was too long, the daemon writes a pointer
        file at ~/.ghost/socket_path. Check there first.
        """
        if ghost_home:
            pointer = ghost_home / DEFAULT_SOCKET_POINTER
            if pointer.exists():
                actual = Path(pointer.read_text().strip())
                if actual.exists():
                    return actual
        return default_path

    def _client(self) -> httpx.Client:
        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        return httpx.Client(transport=transport, base_url=self._base_url)

    def is_daemon_running(self) -> bool:
        """Check if the daemon is alive."""
        try:
            with self._client() as c:
                r = c.get("/api/health", timeout=2.0)
                return r.status_code == 200
        except (httpx.ConnectError, FileNotFoundError, ConnectionRefusedError):
            return False

    def get_health(self) -> dict[str, Any]:
        """Get full health status."""
        with self._client() as c:
            r = c.get("/api/health", timeout=5.0)
            r.raise_for_status()
            return dict(r.json())

    def forge(self, intent: str, project_id: str | None = None) -> dict[str, Any]:
        """Request tool synthesis."""
        with self._client() as c:
            r = c.post(
                "/api/forge",
                json={"intent": intent, "project_id": project_id},
                timeout=120.0,  # LLM calls can be slow
            )
            r.raise_for_status()
            return dict(r.json())

    def get_cost(self, detail: bool = False) -> dict[str, Any] | None:
        """Get API cost statement."""
        # For simplicity in this endpoint:
        with self._client() as c:
            r = c.get("/api/health", timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                return data.get("session_cost", None)
        return None

    def get_audit_logs(self, topic: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Get audit logs."""
        params: dict[str, Any] = {"limit": limit}
        if topic:
            params["topic"] = topic
        with self._client() as c:
            r = c.get("/api/logs", params=params, timeout=5.0)
            r.raise_for_status()
            return list(r.json())

    def set_log_level(self, level: str) -> None:
        """Change daemon log level."""
        with self._client() as c:
            r = c.post("/api/config/log-level", json={"level": level}, timeout=5.0)
            r.raise_for_status()

    def shutdown(self) -> None:
        """Initiate daemon shutdown."""
        try:
            with self._client() as c:
                c.post("/api/shutdown", timeout=2.0)
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass  # Expected if it shuts down quickly
