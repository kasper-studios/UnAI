import asyncio
import base64
import json
from typing import Any, Dict, List, Optional
import websockets
from unai.sdk import Workspace, tool

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
                "Браузерный мост KasperBridge не подключен. Пожалуйста, убедитесь, "
                "что расширение или юзерскрипт установлены в вашем браузере, "
                "и откройте любую страницу для автоматического подключения к ws://127.0.0.1:8055"
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
            response = await asyncio.wait_for(fut, timeout=15.0)  # Таймаут 15 секунд
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result")
        finally:
            self._pending_requests.pop(req_id, None)

    @tool(
        "browser.status",
        description="Получить статус предоставленного пользователем браузера и проверить подключение KasperBridge"
    )
    async def status(self) -> Dict[str, Any]:
        await self._ensure_server_started()
        connected = self._active_websocket is not None
        if not connected:
            return {
                "connected": False,
                "info": "Браузерный мост не подключен. Агенту не передан браузер. "
                        "Пожалуйста, откройте любую страницу в браузере с активным KasperBridge "
                        "для автоматического подключения к ws://127.0.0.1:8055"
            }
        return {
            "connected": True,
            "browser": self._active_tab_info.get("browser", "unknown"),
            "active_tab": {
                "title": self._active_tab_info.get("title", "Unknown Page"),
                "url": self._active_tab_info.get("url", "unknown")
            },
            "bridge_version": self._active_tab_info.get("version", "1.0.0"),
            "info": "Браузер успешно предоставлен пользователем. Соединение активно."
        }

    @tool(
        "browser.open",
        description="Открыть указанный URL в браузере. Если мост еще не подключен, инструмент попытается открыть системный браузер по умолчанию.",
        arguments={
            "url": {"type": "string", "description": "URL для открытия", "default": "about:blank"}
        }
    )
    async def open_browser(self, url: str = "about:blank") -> str:
        await self._ensure_server_started()
        if self._active_websocket:
            await self._send_request("browser.navigate", {"url": url})
            return f"В активном браузере успешно открыта ссылка: {url}"
        else:
            import webbrowser
            try:
                webbrowser.open(url)
                return (
                    f"Мост не был активен. Попытались открыть системный браузер на {url}. "
                    "Пожалуйста, убедитесь, что в этом браузере установлено расширение/юзерскрипт KasperBridge, "
                    "чтобы оно автоматически подключилось к UnAI."
                )
            except Exception as e:
                return (
                    f"Не удалось автоматически запустить системный браузер: {e}. "
                    "Пожалуйста, запустите ваш любимый браузер вручную и убедитесь, что расширение KasperBridge активно."
                )

    @tool(
        "browser.navigate",
        description="Изменить ссылку (перейти по URL) на текущей активной вкладке",
        arguments={
            "url": {"type": "string", "description": "Новый URL для перехода"}
        }
    )
    async def navigate(self, url: str) -> str:
        await self._send_request("browser.navigate", {"url": url})
        return f"Успешно перешли на {url}"

    @tool(
        "browser.screenshot",
        description="Сделать нативный скриншот видимой области страницы через расширение"
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
            return f"Скриншот успешно сохранен: MEDIA:{filepath.absolute()}"
        except Exception as e:
            return f"Скриншот получен в base64, но произошла ошибка при сохранении на диск: {e}"

    @tool(
        "browser.dom.query",
        description="Найти элементы на странице по CSS-селектору",
        arguments={
            "selector": {"type": "string", "description": "CSS-селектор элемента"}
        }
    )
    async def dom_query(self, selector: str) -> List[Dict[str, Any]]:
        result = await self._send_request("dom.query", {"selector": selector})
        return result

    @tool(
        "browser.dom.click",
        description="Кликнуть по элементу на странице",
        arguments={
            "selector": {"type": "string", "description": "CSS-селектор элемента для клика"}
        }
    )
    async def dom_click(self, selector: str) -> str:
        await self._send_request("dom.click", {"selector": selector})
        return f"Клик по элементу '{selector}' успешно выполнен."

    @tool(
        "browser.dom.type",
        description="Ввести текст в текстовое поле",
        arguments={
            "selector": {"type": "string", "description": "CSS-селектор поля ввода"},
            "text": {"type": "string", "description": "Текст для ввода"}
        }
    )
    async def dom_type(self, selector: str, text: str) -> str:
        await self._send_request("dom.type", {"selector": selector, "text": text})
        return f"Текст успешно введен в поле '{selector}'."

    @tool(
        "browser.dom.wait",
        description="Ожидать появления элемента на странице",
        arguments={
            "selector": {"type": "string", "description": "CSS-селектор элемента"},
            "timeout_ms": {"type": "integer", "description": "Таймаут ожидания в миллисекундах", "default": 5000}
        }
    )
    async def dom_wait(self, selector: str, timeout_ms: int = 5000) -> str:
        await self._send_request("dom.wait", {"selector": selector, "timeout_ms": timeout_ms})
        return f"Элемент '{selector}' успешно появился на странице."
