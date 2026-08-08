"""Unit tests for workspace auth/session model (ADR-0004).

Проверяет state-зависимое поведение login-тулзы через `enabled_if`:
тулза появляется/скрывается из `methods` при смене сессии — без реального
браузера и реальных сервисов-аутеров.
"""
import pytest
from typing import Any, Dict, Optional
from unai.sdk import Workspace, tool


class AuthWorkspace(Workspace):
    """Минимальный воркспейс с одноразовой login-тулзой (state-зависимая)."""

    def __init__(self, runtime_id: str = "auth-test", bus: Optional[Any] = None, **kw):
        super().__init__(runtime_id, bus, **kw)
        # state: none | valid | invalid  — в проде в ~/.unai/data/<id>/session.json
        self._session_state: str = "none"

    # ---- session lifecycle -------------------------------------------------
    def _save_session(self, data: Dict[str, Any]) -> None:
        self._session_state = "valid"

    def reset_session(self) -> None:
        """Юзерный reset → state none, login доступен (ADR-0004)."""
        self._session_state = "none"

    def invalidate_session(self) -> None:
        """Фактическая невалидность (401/expired) → login доступен."""
        self._session_state = "invalid"

    def session_valid(self) -> bool:
        return self._session_state == "valid"

    # ---- tools -------------------------------------------------------------
    @tool(
        "auth.login",
        description="Log in (shown ONLY when session is none/invalid).",
        enabled_if=lambda ws: not ws.session_valid(),
    )
    async def login(self, username: str, password: str) -> str:
        if self.session_valid():
            raise RuntimeError("Already logged in — reset-session first.")
        if username and password:
            self._save_session({"username": username})
            return f"Logged in as {username}"
        raise RuntimeError("Login failed: empty credentials")

    @tool("auth.whoami", description="Who is logged in (only if session valid).")
    async def whoami(self) -> str:
        if not self.session_valid():
            raise RuntimeError("Not logged in")
        return "user@example.com"


@pytest.mark.asyncio
async def test_login_visible_when_session_none():
    ws = AuthWorkspace()
    assert "auth.login" in ws.methods
    assert "auth.whoami" in ws.methods


@pytest.mark.asyncio
async def test_login_disappears_after_successful_login():
    ws = AuthWorkspace()
    assert "auth.login" in ws.methods
    await ws.tools["login"].invoke({"username": "dirom", "password": "ok"})
    # после успешного логина session valid → login скрывается
    assert "auth.login" not in ws.methods
    assert "auth.whoami" in ws.methods
    # manifest methods тоже отражают state
    assert "auth.login" not in ws.manifest.methods


@pytest.mark.asyncio
async def test_reset_session_brings_login_back():
    ws = AuthWorkspace()
    await ws.tools["login"].invoke({"username": "dirom", "password": "ok"})
    assert "auth.login" not in ws.methods
    ws.reset_session()
    assert "auth.login" in ws.methods
    assert "auth.whoami" in ws.methods


@pytest.mark.asyncio
async def test_invalidate_session_brings_login_back():
    ws = AuthWorkspace()
    await ws.tools["login"].invoke({"username": "dirom", "password": "ok"})
    assert "auth.login" not in ws.methods
    ws.invalidate_session()
    assert "auth.login" in ws.methods


@pytest.mark.asyncio
async def test_login_fails_when_already_logged_in():
    ws = AuthWorkspace()
    await ws.tools["login"].invoke({"username": "dirom", "password": "ok"})
    assert "auth.login" not in ws.methods
    # После успешного логина login скрыта из tools — direct call на login возбуждает
    # RuntimeError на уровне воркспейса, а не в MCP-стеке.
    with pytest.raises(RuntimeError, match="Already logged in"):
        await ws.login(username="x", password="y")
