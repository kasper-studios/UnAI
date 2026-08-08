# Web Workspace / Browser Bridge — выбор браузера

> Как это работает: агент использует **отдельный браузер**, а не личное
> окружение юзера. Юзер скачивает/устанавливает браузер (по умолчанию Firefox),
> логинится в свои аккаунты/почту/Google и передаёт его агенту — агент работает
> в нём. Агент не может работать в двух браузерах одновременно: ровно один
> активный мост.

## Зачем отдельный браузер

ADR-0002: браузер для агента — это **песочница** (Chrome для агента
с одноразовым аккаунтом **Диром/Hermes**). Firefox — личный браузер юзера,
но под агента тоже отдельный (профиль-песочница). Личное окружение юзера
(аккаунты, стикеры, вкладки) — НЕ трогается: агент работает в отдельном
профиле/браузере, настраивается юзером один раз. Настройку (какой именно
браузер, какие аккаунты) редактирует юзер; агент уже просто открывает и
вертит переданный браузер как хочет.

## Выбор браузера — всегда юзером

| Сценарий | Что делает агент | Что делает юзер |
|---|---|---|
| Первый запуск | Ничего не подключает | Скачивает браузер (по умолч. Firefox), заходит в аккаунты, ставит мост |
| Смена браузера | Ожидает новый мост | Переустанавливает мост в новый браузер |
| Два браузера | НЕ ПОДДЕРЖИВАЕТСЯ: один активный мост | Ставит мост только в один браузер |

## Единственный активный мост

- Ровно **один WebSocket-клиент** на сервере UnAI (`ws://127.0.0.1:8055`).
- Если мост установлен в нескольких браузерах — **последний подключившийся
  становится активным**, остальные отбрасываются.
- Активный мост = «текущий браузер» агента.

## Реализация: WebExtension (основная) + Tampermonkey (альтернатива)

Основной мост — **WebExtension** (`internalws/browser/ext/`): background service
worker держит WebSocket, content script работает со страницей. Он умеет
больше юзерскрипта:

- нативный скриншот вкладки (`chrome.tabs.captureVisibleTab`);
- `browser.tabs.list/activate/close` — управление вкладками;
- `browser.cookies.*` — куки любого домена через API;
- `browser.storage.*` — localStorage активной вкладки;
- `devtools.eval` — выполнение JS в контексте страницы;
- `devtools.network` — журнал HTTP-запросов (webRequest);
- `devtools.console` — лог консоли страницы;
- WS живёт в service worker и НЕ рвётся при переходах СТРАНИЦ (в отличие от
  Tampermonkey content script).

Tampermonkey юзерскрипт (`internalws/browser/bridge.user.js`) остаётся как
фолбэк для браузеров без WebExtension-установки (или для быстрого теста).

## Установка

- **Firefox**: `about:debugging#/runtime/this-firefox` → Load Temporary Add-on →
  выбрать `internalws/browser/ext/manifest.json`.
- **Chrome/Chromium**: `chrome://extensions` → Developer mode → Load unpacked →
  выбрать папку `internalws/browser/ext/`.
- Альтернатива: Tampermonkey → New script → вставить содержимое
  `bridge.user.js`.

## DevTools (три фичи — без CDP)

Лёгкий DevTools-доступ без полного CDP/BiDi (Chrome/Firefox совместим):

| Метод | Что делает |
|---|---|
| `devtools.eval` | Выполнить JS-выражение в контексте СТРАНИЦЫ, вернуть JSON-результат |
| `devtools.network` | Последние HTTP-запросы (URL, метод, статус, тип), буфер ~500 |
| `devtools.console` | Сообщения консоли (log/info/warn/error/debug), буфер ~200 |

Огранично: `devtools.network` видит заголовки запросов, но НЕ тела ответов
(это уровню debugger/CDP). Когда потребуется перехват тел — вариант в будущем:
`chrome.debugger` API (Chrome-only) или WebDriver BiDi (Firefox). Пока не делаем.

## Дорожная карта (в рамках MVP)

- [x] WebExtension: manifest, background (WS), content (DOM), popup.
- [x] DOM: `dom.query/click/type/wait`, `browser.storage.*`.
- [x] DevTools: `devtools.eval/network/console`.
- [x] Куки: `browser.cookies.*`.
- [ ] Авто-установка расширения (клик-мест; `unai extension install`? — TBD).
- [ ] Сессии: persist cookies/localStorage в `~/.unai/data/browser/` для
      передачи в другие воркспейсы.