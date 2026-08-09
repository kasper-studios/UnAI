// UnAI Browser Bridge — content script.
// Выполняется в каждой вкладке. Не держит WebSocket сам: DOM-команды
// приходят от background (который держит единственный WS с рантаймом),
// а здесь исполняются и возвращается результат.

(() => {
  'use strict';

  // Лог консоли страницы (собирается здесь, в контексте страницы)
  const consoleBuffer = [];
  const CONSOLE_LIMIT = 100;

  function captureConsole() {
    // Хук на console.* самой страницы: перехватываем в её контексте
    const script = document.createElement('script');
    script.textContent = `
      (function() {
        if (window.__unaiConsoleHooked) return;
        window.__unaiConsoleHooked = true;
        const levels = ['log', 'info', 'warn', 'error', 'debug'];
        for (const lv of levels) {
          const orig = console[lv].bind(console);
          console[lv] = function(...args) {
            let text;
            try { text = args.map(a => {
              if (typeof a === 'string') return a;
              try { return JSON.stringify(a); } catch { return String(a); }
            }).join(' '); } catch { text = String(args); }
            window.postMessage({ type: 'unai-console', level: lv, text }, '*');
            orig(...args);
          };
        }
      })();
    `;
    (document.head || document.documentElement).appendChild(script);
    script.remove();
  }

  if (document.head || document.documentElement) captureConsole();

  // Слушаем postMessage от страницы (наш встроенный хук)
  window.addEventListener('message', (event) => {
    const d = event.data;
    if (!d || d.type !== 'unai-console') return;
    consoleBuffer.push({ level: d.level, text: d.text, url: location.href });
    if (consoleBuffer.length > CONSOLE_LIMIT) consoleBuffer.shift();
    // Прокидываем в background (там копим в общий буфер)
    chrome.runtime.sendMessage({ type: 'console', level: d.level, text: d.text, url: location.href });
  });

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || typeof msg.method !== 'string') return;

    const { method, params } = msg;

    try {
      switch (method) {
        case 'dom.query':
          sendResponse({ result: domQuery(params.selector) });
          break;

        case 'dom.click':
          sendResponse({ result: domClick(params.selector) });
          break;

        case 'dom.type':
          sendResponse({ result: domType(params.selector, params.text) });
          break;

        case 'dom.wait':
          domWait(params.selector, params.timeout_ms)
            .then(result => sendResponse({ result }))
            .catch(err => sendResponse({ error: err.message }));
          return true;

        case 'browser.storage.get':
          sendResponse({ result: storageGet(params.key) });
          break;

        case 'browser.storage.set':
          sendResponse({ result: storageSet(params.key, params.value) });
          break;

        case 'browser.page.content':
          sendResponse({ result: pageContent(params.selector) });
          break;

        case 'devtools.eval':
          sendResponse({ result: evalInPage(params.expression) });
          break;

        case 'devtools.console':
          sendResponse({ result: consoleBuffer.slice(-(params.limit || 50)) });
          break;

        default:
          sendResponse({ error: `Unknown DOM method: ${method}` });
      }
    } catch (err) {
      sendResponse({ error: err.message || String(err) });
    }
    return false;
  });

  // ---- DOM helpers

  function pageContent(selector) {
    const sel = selector || 'body';
    const el = document.querySelector(sel);
    if (!el) return `(element not found for selector: ${sel})`;
    return (el.innerText || el.textContent || '').trim();
  }

  function findEl(selector) {
    const el = document.querySelector(selector);
    if (!el) throw new Error(`Element not found: ${selector}`);
    return el;
  }

  function domQuery(selector) {
    const els = document.querySelectorAll(selector);
    return Array.from(els).slice(0, 50).map(el => ({
      tag: el.tagName.toLowerCase(),
      id: el.id || undefined,
      className: typeof el.className === 'string' ? el.className : undefined,
      text: (el.innerText || '').trim().slice(0, 200),
      value: (el.value !== undefined ? String(el.value) : undefined),
      href: el.href || undefined,
      visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
    }));
  }

  function domClick(selector) {
    const el = findEl(selector);
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.click();
    return `Clicked: ${selector}`;
  }

  function domType(selector, text) {
    const el = findEl(selector);
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.focus();
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, text); // нативный setter — React/подобные фреймворки увидят изменение
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return `Typed ${text.length} chars into: ${selector}`;
  }

  function domWait(selector, timeoutMs) {
    const timeout = timeoutMs || 5000;
    const start = Date.now();
    return new Promise((resolve, reject) => {
      function check() {
        const el = document.querySelector(selector);
        if (el) { resolve(`Found: ${selector}`); return; }
        if (Date.now() - start > timeout) {
          reject(new Error(`Timeout (${timeout}ms) waiting for: ${selector}`));
          return;
        }
        setTimeout(check, 100);
      }
      check();
    });
  }

  // ---- storage (localStorage текущей страницы)

  function storageGet(key) {
    if (key === undefined || key === null) {
      const out = {};
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        out[k] = localStorage.getItem(k);
      }
      return out;
    }
    return localStorage.getItem(key);
  }

  function storageSet(key, value) {
    if (key === undefined || key === null) throw new Error('storage.set requires key');
    localStorage.setItem(key, String(value));
    return `Saved: ${key}`;
  }

  // ---- DevTools: eval в контексте СТРАНИЦЫ (с обходом CSP)

  function evalInPage(expression) {
    // 1. Прямой eval в контексте content script (не блокируется CSP страницы!)
    try {
      const fn = new Function(`return (${expression});`);
      const res = fn();
      return serializeEvalResult(res);
    } catch (e1) {
      try {
        const res = eval(expression);
        return serializeEvalResult(res);
      } catch (e2) {
        // 2. Если прямой eval не сработал — проба через инжект <script>
        return evalViaDOMScript(expression);
      }
    }
  }

  function serializeEvalResult(res) {
    if (res === undefined) return '__UNDEFINED__';
    if (typeof res === 'function') return '[Function]';
    try {
      return JSON.parse(JSON.stringify(res));
    } catch {
      return String(res);
    }
  }

  function evalViaDOMScript(expression) {
    const script = document.createElement('script');
    script.textContent = `
      (function() {
        try {
          const __res = eval(${JSON.stringify(expression)});
          const __json = JSON.stringify(__res, (_k, v) =>
            typeof v === 'undefined' ? '__UNDEFINED__' :
            typeof v === 'function' ? '[Function]' : v);
          document.documentElement.setAttribute('data-unai-eval', __json);
        } catch (e) {
          document.documentElement.setAttribute('data-unai-eval', JSON.stringify({ __error: String(e) }));
        }
      })();
    `;
    try {
      (document.head || document.documentElement).appendChild(script);
      script.remove();

      const raw = document.documentElement.getAttribute('data-unai-eval');
      document.documentElement.removeAttribute('data-unai-eval');
      if (raw === null) return { __error: 'Script injection blocked by page CSP' };
      return JSON.parse(raw);
    } catch (err) {
      return { __error: String(err) };
    }
  }
})();