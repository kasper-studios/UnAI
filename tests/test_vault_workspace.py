import asyncio
import pytest
from internalws.vault.workspace import VaultWorkspace

@pytest.fixture
def vault_ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = VaultWorkspace(runtime_id="vault")
    return ws

@pytest.mark.asyncio
async def test_secret_set_and_get(vault_ws):
    msg = await vault_ws.secret_set("openai_api_key", "sk-test-12345")
    assert "Successfully saved" in msg

    value = await vault_ws.secret_get("openai_api_key")
    assert value == "sk-test-12345"

@pytest.mark.asyncio
async def test_credentials_set_get_totp(vault_ws):
    msg = await vault_ws.credentials_set(
        service="google",
        username="user@gmail.com",
        password="secretpassword",
        totp="JBSWY3DPEHPK3PXP"
    )
    assert "Successfully saved" in msg

    creds = await vault_ws.credentials_get("google")
    assert creds["username"] == "user@gmail.com"
    assert creds["password"] == "secretpassword"
    assert creds["totp"] == "JBSWY3DPEHPK3PXP"

    code = await vault_ws.totp_code("google")
    assert len(code) == 6
    assert code.isdigit()

@pytest.mark.asyncio
async def test_list_and_remove(vault_ws):
    await vault_ws.secret_set("stripe_key", "sk_test_999")
    await vault_ws.credentials_set("github", username="octocat", password="foo")

    listing = await vault_ws.list_vault()
    assert "stripe_key" in listing["secrets"]
    services = [c["service"] for c in listing["credentials"]]
    assert "github" in services

    msg = await vault_ws.remove_entry("stripe_key")
    assert "Successfully removed" in msg

    listing_after = await vault_ws.list_vault()
    assert "stripe_key" not in listing_after["secrets"]
