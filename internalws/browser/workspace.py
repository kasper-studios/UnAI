import asyncio
import base64
import json
from typing import Any, Dict, List, Optional
from unai.sdk import Workspace, tool
from unai.common.protocol import SettingsSchema, SettingItem

SETTINGS_SCHEMA = SettingsSchema(
    title="Web Browser Sandbox Settings",
    description="Configure designated browser profile and KasperBridge settings",
    items={
        "browser_type": SettingItem(
            type="choice",
            title="Target Browser Profile",
            description="Browser designated for agent sandbox",
            choices=["Firefox", "Chrome / Chromium", "Brave", "Edge", "Custom"],
            default="Firefox",
        ),
        "bridge_type": SettingItem(
            type="choice",
            title="KasperBridge Extension Type",
            description="WebExtension (Background Service Worker) or Tampermonkey Userscript",
            choices=["WebExtension (Firefox / Chrome)", "Tampermonkey Userscript"],
            default="WebExtension (Firefox / Chrome)",
        ),
        "bridge_port": SettingItem(
            type="text",
            title="WebSocket Bridge Port",
            description="Port for KasperBridge auto-connection",
            default="8055",
        ),
    },
)

class BrowserWorkspace(Workspace):
    """
    Встроенный воркспейс браузера (Web/Browser Workspace).
    Управляет живой сессией, которую ПОЛЬЗОВАТЕЛЬ выбрал и предоставил агенту
    через KasperBridge WebExtension / Userscript, подключающийся по WebSocket.
    """

    def __init__(self, runtime_id: str, bus: Optional[Any] = None, **kwargs: Any):
        super().__init__(runtime_id, bus, **kwargs)
        self._active_websocket = None
        self._active_tab_info = {}
        self._pending_requests = {}
        self._server_task = None

        # Попытка фонового запуска при инициализации, если цикл уже запущен
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                self._server_task = loop.create_task(self._start_server())
        except RuntimeError:
            pass

    async def start(self) -> None:
        """Вызывается ядром при активации воркспейса (on-demand, перед первым вызовом)."""
        await self._ensure_server_started()

    async def stop(self) -> None:
        """Вызывается ядром при деактивации воркспейса."""
        if self._server_task:
            self._server_task.cancel()
            self._server_task = None
        if self._active_websocket:
            await self._active_websocket.close()
            self._active_websocket = None

    def metadata(self) -> Dict[str, Any]:
        return {
            "name": "Web Browser",
            "kind": "built-in",
            "description": "Встроенный воркспейс для работы с браузером, выбранным и предоставленным пользователем",
        }

    def features(self) -> Dict[str, bool]:
        return {
            "notifications": True,
            "settings": True,
            "persistent": True,
            "background": True,
        }

    async def _ensure_server_started(self) -> None:
        if not self._server_task:
            self._server_task = asyncio.create_task(self._start_server())
            await asyncio.sleep(0.1)  # Даём сокету время забиндиться

    async def _start_server(self) -> None:
        try:
            async with websockets.serve(self._handle_client, "127.0.0.1", 8055):
                await asyncio.Future()  # Держим сервер запущенным
        except Exception:
            pass

    async def _handle_client(self, websocket: Any, *args: Any, **kwargs: Any) -> None:
        self._active_websocket = websocket
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    req_id = data.get("id")
                    
                    # Если это ответ на наш запрос
                    if req_id and req_id in self._pending_requests:
                        self._pending_requests[req_id].set_result(data)
                    
                    # Если это обновление статуса (от расширения)
                    elif data.get("type") == "status":
                        self._active_tab_info = data.get("status", {})
                except Exception:
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if self._active_websocket == websocket:
                self._active_websocket = None
                self._active_tab_info = {}

    async def _send_request(self, method: str, params: dict) -> Any:
        await self._ensure_server_started()
        if not self._active_websocket:
            raise RuntimeError(
                "KasperBridge is not connected. Please make sure the browser extension "
                "or userscript is installed and open any page to auto-connect to ws://127.0.0.1:8055"
            )
        
        # Генерируем уникальный ID запроса
        req_id = f"req-{id(asyncio.current_task())}-{asyncio.get_running_loop().time()}"
        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut

        payload = {
            "id": req_id,
            "method": method,
            "params": params
        }
        try:
            await self._active_websocket.send(json.dumps(payload))
            response = await asyncio.wait_for(fut, timeout=15.0)
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result")
        finally:
            self._pending_requests.pop(req_id, None)

    # ====================================================================
    # Core browser tools
    # ====================================================================

    @tool(
        "browser.status",
        description="Get the status of the user-provided browser and check KasperBridge connection"
    )
    async def status(self) -> Dict[str, Any]:
        await self._ensure_server_started()
        connected = self._active_websocket is not None
        if not connected:
            return {
                "connected": False,
                "info": "KasperBridge is not connected. No browser provided to the agent. "
                        "Please open any page in a browser with active KasperBridge "
                        "to auto-connect to ws://127.0.0.1:8055"
            }
        return {
            "connected": True,
            "browser": self._active_tab_info.get("browser", "unknown"),
            "active_tab": {
                "title": self._active_tab_info.get("title", "Unknown Page"),
                "url": self._active_tab_info.get("url", "unknown")
            },
            "bridge_version": self._active_tab_info.get("version", "1.0.0"),
            "info": "Browser successfully provided by the user. Connection active."
        }

    @tool(
        "browser.open",
        description="Open a URL in the browser. If bridge is not connected, attempts to open the system default browser.",
        arguments={
            "url": {"type": "string", "description": "URL to open", "default": "about:blank"}
        }
    )
    async def open_browser(self, url: str = "about:blank") -> str:
        await self._ensure_server_started()
        if self._active_websocket:
            await self._send_request("browser.navigate", {"url": url})
            return f"Successfully opened URL in active browser: {url}"
        else:
            import webbrowser
            try:
                webbrowser.open(url)
                return (
                    f"Bridge was not active. Attempted to open system browser at {url}. "
                    "Please ensure the KasperBridge extension/userscript is installed "
                    "so it auto-connects to UnAI."
                )
            except Exception as e:
                return (
                    f"Failed to launch system browser: {e}. "
                    "Please start your browser manually and ensure KasperBridge is active."
                )

    @tool(
        "browser.navigate",
        description="Navigate to a URL in the current active tab",
        arguments={
            "url": {"type": "string", "description": "URL to navigate to"}
        }
    )
    async def navigate(self, url: str) -> str:
        await self._send_request("browser.navigate", {"url": url})
        return f"Successfully navigated to {url}"

    @tool(
        "browser.screenshot",
        description="Take a native screenshot of the visible page area via the browser extension"
    )
    async def screenshot(self) -> str:
        img_b64 = await self._send_request("browser.screenshot", {})
        
        import os
        from pathlib import Path
        import datetime

        data_dir = Path.home() / ".unai" / "data" / "browser" / "screenshots"
        data_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = data_dir / filename
        
        try:
            img_data = base64.b64decode(img_b64)
            filepath.write_bytes(img_data)
            return f"Screenshot saved: MEDIA:{filepath.absolute()}"
        except Exception as e:
            return f"Screenshot received as base64 but failed to save to disk: {e}"

    # ====================================================================
    # DOM tools
    # ====================================================================

    @tool(
        "browser.dom.query",
        description="Find elements on the page by CSS selector. Returns tag, text, id, className, visibility for each match (max 50).",
        arguments={
            "selector": {"type": "string", "description": "CSS selector"}
        }
    )
    async def dom_query(self, selector: str) -> List[Dict[str, Any]]:
        result = await self._send_request("dom.query", {"selector": selector})
        return result

    @tool(
        "browser.dom.click",
        description="Click an element on the page by CSS selector",
        arguments={
            "selector": {"type": "string", "description": "CSS selector of the element to click"}
        }
    )
    async def dom_click(self, selector: str) -> str:
        await self._send_request("dom.click", {"selector": selector})
        return f"Clicked element '{selector}' successfully."

    @tool(
        "browser.dom.type",
        description="Type text into an input field on the page",
        arguments={
            "selector": {"type": "string", "description": "CSS selector of the input field"},
            "text": {"type": "string", "description": "Text to type"}
        }
    )
    async def dom_type(self, selector: str, text: str) -> str:
        await self._send_request("dom.type", {"selector": selector, "text": text})
        return f"Text typed into '{selector}' successfully."

    @tool(
        "browser.dom.wait",
        description="Wait for an element to appear on the page",
        arguments={
            "selector": {"type": "string", "description": "CSS selector of the element"},
            "timeout_ms": {"type": "integer", "description": "Timeout in milliseconds", "default": 5000}
        }
    )
    async def dom_wait(self, selector: str, timeout_ms: int = 5000) -> str:
        await self._send_request("dom.wait", {"selector": selector, "timeout_ms": timeout_ms})
        return f"Element '{selector}' appeared on the page."

    # ====================================================================
    # Tabs tools (WebExtension only)
    # ====================================================================

    @tool(
        "browser.tabs.list",
        description="List all open browser tabs with their id, title, url, and active status"
    )
    async def tabs_list(self) -> List[Dict[str, Any]]:
        result = await self._send_request("browser.tabs.list", {})
        return result

    @tool(
        "browser.tabs.activate",
        description="Switch to (activate) a specific browser tab by its ID or index",
        arguments={
            "id": {"type": "integer", "description": "Tab ID or tab index to activate"}
        }
    )
    async def tabs_activate(self, id: int) -> Dict[str, Any]:
        result = await self._send_request("browser.tabs.activate", {"id": id})
        return result

    @tool(
        "browser.tabs.close",
        description="Close a browser tab by its ID",
        arguments={
            "id": {"type": "integer", "description": "Tab ID to close"}
        }
    )
    async def tabs_close(self, id: int) -> Dict[str, Any]:
        result = await self._send_request("browser.tabs.close", {"id": id})
        return result

    # ====================================================================
    # Cookies tools (WebExtension only)
    # ====================================================================

    @tool(
        "browser.cookies.list",
        description="List cookies for a given URL or domain",
        arguments={
            "url": {"type": "string", "description": "URL to get cookies for (optional)", "default": ""},
            "domain": {"type": "string", "description": "Domain to filter cookies (optional)", "default": ""}
        }
    )
    async def cookies_list(self, url: str = "", domain: str = "") -> List[Dict[str, Any]]:
        params = {}
        if url:
            params["url"] = url
        if domain:
            params["domain"] = domain
        result = await self._send_request("browser.cookies.list", params)
        return result

    @tool(
        "browser.cookies.get",
        description="Get a specific cookie by name and URL",
        arguments={
            "url": {"type": "string", "description": "URL the cookie belongs to"},
            "name": {"type": "string", "description": "Cookie name"}
        }
    )
    async def cookies_get(self, url: str, name: str) -> Any:
        result = await self._send_request("browser.cookies.get", {"url": url, "name": name})
        return result

    @tool(
        "browser.cookies.set",
        description="Set a cookie",
        arguments={
            "url": {"type": "string", "description": "URL to set the cookie for"},
            "name": {"type": "string", "description": "Cookie name"},
            "value": {"type": "string", "description": "Cookie value"},
            "domain": {"type": "string", "description": "Cookie domain (optional)", "default": ""},
            "path": {"type": "string", "description": "Cookie path", "default": "/"}
        }
    )
    async def cookies_set(self, url: str, name: str, value: str,
                          domain: str = "", path: str = "/") -> Any:
        params = {"url": url, "name": name, "value": value, "path": path}
        if domain:
            params["domain"] = domain
        result = await self._send_request("browser.cookies.set", params)
        return result

    @tool(
        "browser.cookies.remove",
        description="Remove a cookie by name and URL",
        arguments={
            "url": {"type": "string", "description": "URL the cookie belongs to"},
            "name": {"type": "string", "description": "Cookie name to remove"}
        }
    )
    async def cookies_remove(self, url: str, name: str) -> Dict[str, Any]:
        result = await self._send_request("browser.cookies.remove", {"url": url, "name": name})
        return result

    # ====================================================================
    # Storage tools (localStorage of current page)
    # ====================================================================

    @tool(
        "browser.storage.get",
        description="Get a value from localStorage of the current page. Pass empty key to get all entries.",
        arguments={
            "key": {"type": "string", "description": "localStorage key (empty = get all)", "default": ""}
        }
    )
    async def storage_get(self, key: str = "") -> Any:
        params = {"key": key if key else None}
        result = await self._send_request("browser.storage.get", params)
        return result

    @tool(
        "browser.storage.set",
        description="Set a value in localStorage of the current page",
        arguments={
            "key": {"type": "string", "description": "localStorage key"},
            "value": {"type": "string", "description": "Value to store"}
        }
    )
    async def storage_set(self, key: str, value: str) -> str:
        await self._send_request("browser.storage.set", {"key": key, "value": value})
        return f"Saved '{key}' to localStorage."

    # ====================================================================
    # DevTools tools
    # ====================================================================

    @tool(
        "browser.devtools.eval",
        description="Execute a JavaScript expression in the context of the current page and return the result",
        arguments={
            "expression": {"type": "string", "description": "JavaScript expression to evaluate"}
        }
    )
    async def devtools_eval(self, expression: str) -> Any:
        result = await self._send_request("devtools.eval", {"expression": expression})
        return result

    @tool(
        "browser.devtools.console",
        description="Get the console log of the current page (captured via KasperBridge hook)",
        arguments={
            "limit": {"type": "integer", "description": "Max number of entries to return", "default": 50}
        }
    )
    async def devtools_console(self, limit: int = 50) -> List[Dict[str, Any]]:
        result = await self._send_request("devtools.console", {"limit": limit})
        return result

    @tool(
        "browser.devtools.network",
        description="Get the network request log captured by the browser extension (recent requests with URL, method, status, type)",
        arguments={
            "limit": {"type": "integer", "description": "Max number of entries to return", "default": 100}
        }
    )
    async def devtools_network(self, limit: int = 100) -> List[Dict[str, Any]]:
        result = await self._send_request("devtools.network", {"limit": limit})
        return result

    # ====================================================================
    # Page content tool
    # ====================================================================

    @tool(
        "browser.page.content",
        description="Get the text content of the current page (extracted innerText, suitable for LLM consumption). "
                    "Optionally pass a CSS selector to get content of a specific element.",
        arguments={
            "selector": {"type": "string", "description": "CSS selector (default: 'body')", "default": "body"}
        }
    )
    async def page_content(self, selector: str = "body") -> str:
        # Use devtools.eval to extract text content from the page
        expression = f"document.querySelector({json.dumps(selector)})?.innerText || ''"
        result = await self._send_request("devtools.eval", {"expression": expression})
        if isinstance(result, dict) and "__error" in result:
            return f"Error extracting page content: {result['__error']}"
        if isinstance(result, str):
            # Truncate very long pages to avoid overwhelming the LLM context
            if len(result) > 50000:
                return result[:50000] + "\n\n[... truncated, page content exceeds 50000 chars]"
            return result
        return str(result) if result else "(empty page)"
