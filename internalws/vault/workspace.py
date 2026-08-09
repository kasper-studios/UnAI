from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import pyotp
from cryptography.fernet import Fernet
from unai.sdk import Workspace, tool
from unai.common.protocol import SettingsSchema, SettingItem

SETTINGS_SCHEMA = SettingsSchema(
    title="Vault & 2FA Authenticator Settings",
    description="Encrypted local key-value vault and TOTP 2FA code generator",
    items={
        "auto_lock": SettingItem(
            type="choice",
            title="Vault Storage Auto-Lock",
            description="Auto lock or keep unlocked during runtime session",
            choices=["Session (Keep unlocked in memory)", "Always Re-decrypt"],
            default="Session (Keep unlocked in memory)",
        ),
    },
)

class VaultWorkspace(Workspace):
    """
    Встроенный воркспейс хранилища секретов, учётных данных и 2FA генератора.
    Хранит пароли, API-ключи и TOTP-секреты в зашифрованном виде (AES-256 Fernet).
    """

    def __init__(self, runtime_id: str, bus: Optional[Any] = None, **kwargs: Any):
        super().__init__(runtime_id, bus, **kwargs)
        self._unai_home = Path.home() / ".unai"
        self._vault_dir = self._unai_home / "data" / "vault"
        self._key_file = self._unai_home / "vault.key"
        self._vault_file = self._vault_dir / "vault.json"
        self._fernet = None

    def _get_fernet(self) -> Fernet:
        if self._fernet is None:
            self._unai_home.mkdir(parents=True, exist_ok=True)
            if not self._key_file.exists():
                key = Fernet.generate_key()
                self._key_file.write_bytes(key)
                try:
                    os.chmod(self._key_file, 0o600)
                except Exception:
                    pass
            else:
                key = self._key_file.read_bytes().strip()
            self._fernet = Fernet(key)
        return self._fernet

    def _load_data(self) -> Dict[str, Any]:
        if not self._vault_file.exists():
            return {"secrets": {}, "credentials": {}}
        try:
            fernet = self._get_fernet()
            encrypted_data = self._vault_file.read_bytes()
            if not encrypted_data:
                return {"secrets": {}, "credentials": {}}
            decrypted_data = fernet.decrypt(encrypted_data)
            return json.loads(decrypted_data.decode("utf-8"))
        except Exception:
            return {"secrets": {}, "credentials": {}}

    def _save_data(self, data: Dict[str, Any]) -> None:
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        fernet = self._get_fernet()
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        encrypted_data = fernet.encrypt(json_bytes)
        self._vault_file.write_bytes(encrypted_data)
        try:
            os.chmod(self._vault_file, 0o600)
        except Exception:
            pass

    def metadata(self) -> Dict[str, Any]:
        return {
            "name": "Vault & 2FA Authenticator",
            "kind": "built-in",
            "description": "Зашифрованное хранилище паролей, API-ключей и генератор 2FA кодов",
        }

    def features(self) -> Dict[str, bool]:
        return {
            "notifications": False,
            "settings": True,
            "persistent": True,
            "background": False,
        }

    # ====================================================================
    # Generic Secrets & API Keys
    # ====================================================================

    @tool(
        "vault.secret.get",
        description="Get a raw secret, API key, or token by name (e.g. 'openai_api_key', 'stripe_key')",
        arguments={
            "name": {"type": "string", "description": "Secret key name"}
        }
    )
    async def secret_get(self, name: str) -> Optional[str]:
        data = self._load_data()
        return data.get("secrets", {}).get(name)

    @tool(
        "vault.secret.set",
        description="Save or update a raw secret, API key, or token by name",
        arguments={
            "name": {"type": "string", "description": "Secret key name"},
            "value": {"type": "string", "description": "Secret value"}
        }
    )
    async def secret_set(self, name: str, value: str) -> str:
        data = self._load_data()
        if "secrets" not in data:
            data["secrets"] = {}
        data["secrets"][name] = value
        self._save_data(data)
        return f"Successfully saved secret '{name}' to vault"

    # ====================================================================
    # Login Credentials & TOTP
    # ====================================================================

    @tool(
        "vault.credentials.get",
        description="Get login credentials (username, password, and optional TOTP secret) for a service",
        arguments={
            "service": {"type": "string", "description": "Service name (e.g. 'google', 'github')"}
        }
    )
    async def credentials_get(self, service: str) -> Optional[Dict[str, Any]]:
        data = self._load_data()
        creds = data.get("credentials", {}).get(service)
        if not creds:
            # Fallback to secrets if stored as name
            sec = data.get("secrets", {}).get(service)
            if sec:
                return {"value": sec}
            return None
        return creds

    @tool(
        "vault.credentials.set",
        description="Save or update login credentials and optional TOTP 2FA secret for a service",
        arguments={
            "service": {"type": "string", "description": "Service name (e.g. 'google', 'github')"},
            "username": {"type": "string", "description": "Username / Email / Login", "default": ""},
            "password": {"type": "string", "description": "Password", "default": ""},
            "totp": {"type": "string", "description": "TOTP 2FA Secret Key (base32)", "default": ""}
        }
    )
    async def credentials_set(self, service: str, username: str = "", password: str = "", totp: str = "") -> str:
        data = self._load_data()
        if "credentials" not in data:
            data["credentials"] = {}
        data["credentials"][service] = {
            "username": username,
            "password": password,
            "totp": totp.strip().replace(" ", "").upper()
        }
        self._save_data(data)
        return f"Successfully saved credentials for service '{service}' to vault"

    @tool(
        "vault.totp.code",
        description="Generate current 6-digit TOTP 2FA code for a service",
        arguments={
            "service": {"type": "string", "description": "Service name or secret key name"}
        }
    )
    async def totp_code(self, service: str) -> str:
        data = self._load_data()
        totp_secret = None
        
        creds = data.get("credentials", {}).get(service)
        if creds and isinstance(creds, dict):
            totp_secret = creds.get("totp")
        if not totp_secret:
            totp_secret = data.get("secrets", {}).get(service)
            if not totp_secret:
                totp_secret = data.get("secrets", {}).get(f"{service}_totp")

        if not totp_secret:
            raise RuntimeError(f"No TOTP 2FA secret found for service '{service}' in vault")

        cleaned_secret = totp_secret.strip().replace(" ", "").upper()
        try:
            totp_obj = pyotp.TOTP(cleaned_secret)
            return totp_obj.now()
        except Exception as e:
            raise RuntimeError(f"Failed to generate TOTP code for '{service}': {e}")

    # ====================================================================
    # Management & Listing
    # ====================================================================

    @tool(
        "vault.list",
        description="List all stored keys and services in vault (with masked values)"
    )
    async def list_vault(self) -> Dict[str, Any]:
        data = self._load_data()
        secrets_list = []
        for k in data.get("secrets", {}).keys():
            secrets_list.append(k)

        creds_list = []
        for s, info in data.get("credentials", {}).items():
            user = info.get("username", "")
            has_pass = bool(info.get("password"))
            has_totp = bool(info.get("totp"))
            creds_list.append({
                "service": s,
                "username": user,
                "has_password": has_pass,
                "has_totp_2fa": has_totp
            })

        return {
            "secrets": secrets_list,
            "credentials": creds_list
        }

    @tool(
        "vault.remove",
        description="Delete a key or service entry from vault",
        arguments={
            "name": {"type": "string", "description": "Key or service name to delete"}
        }
    )
    async def remove_entry(self, name: str) -> str:
        data = self._load_data()
        removed = False
        if name in data.get("secrets", {}):
            del data["secrets"][name]
            removed = True
        if name in data.get("credentials", {}):
            del data["credentials"][name]
            removed = True

        if removed:
            self._save_data(data)
            return f"Successfully removed '{name}' from vault"
        return f"Entry '{name}' not found in vault"
