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

        case 'dom.press':
          sendResponse({ result: domPress(params.key, params.selector) });
          break;

        case 'dom.send_keys':
          sendResponse({ result: domSendKeys(params.selector, params.text) });
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
    try {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch {}
    
    // Dispatch full pointer & mouse event sequence for React / Discord custom components
    const opts = { bubbles: true, cancelable: true, view: window };
    try { el.dispatchEvent(new PointerEvent('pointerdown', opts)); } catch {}
    try { el.dispatchEvent(new MouseEvent('mousedown', opts)); } catch {}
    try { el.focus(); } catch {}
    try { el.dispatchEvent(new PointerEvent('pointerup', opts)); } catch {}
    try { el.dispatchEvent(new MouseEvent('mouseup', opts)); } catch {}
    try { el.click(); } catch {}

    return `Clicked: ${selector}`;
  }

  function domType(selector, text) {
    const el = findEl(selector);
    try {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch {}
    try { el.focus(); } catch {}

    if (el.tagName && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
      const proto = el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, 'value');
      if (desc && desc.set) {
        desc.set.call(el, text);
      } else {
        el.value = text;
      }
    } else if (el.isContentEditable) {
      el.innerText = text;
    } else {
      el.value = text;
    }

    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return `Typed ${text.length} chars into: ${selector}`;
  }

  function parseKeySpec(keySpec) {
    if (!keySpec) throw new Error('Key specification required (e.g. "Enter", "Escape", "Control+a")');
    const parts = String(keySpec).split('+').map(s => s.trim());
    let key = parts[parts.length - 1];

    const ctrlKey = parts.some(p => /^ctrl(ol)?$/i.test(p));
    const shiftKey = parts.some(p => /^shift$/i.test(p));
    const altKey = parts.some(p => /^alt$/i.test(p));
    const metaKey = parts.some(p => /^(meta|cmd|command|win)$/i.test(p));

    const keyMap = {
      'esc': 'Escape',
      'escape': 'Escape',
      'enter': 'Enter',
      'return': 'Enter',
      'tab': 'Tab',
      'space': ' ',
      'backspace': 'Backspace',
      'delete': 'Delete',
      'up': 'ArrowUp',
      'down': 'ArrowDown',
      'left': 'ArrowLeft',
      'right': 'ArrowRight',
      'arrowup': 'ArrowUp',
      'arrowdown': 'ArrowDown',
      'arrowleft': 'ArrowLeft',
      'arrowright': 'ArrowRight',
    };

    const lowerKey = key.toLowerCase();
    if (keyMap[lowerKey]) {
      key = keyMap[lowerKey];
    } else if (key.length === 1) {
      key = shiftKey ? key.toUpperCase() : key;
    }

    let code = key;
    let keyCode = 0;
    if (key === 'Enter') { code = 'Enter'; keyCode = 13; }
    else if (key === 'Escape') { code = 'Escape'; keyCode = 27; }
    else if (key === 'Tab') { code = 'Tab'; keyCode = 9; }
    else if (key === 'Backspace') { code = 'Backspace'; keyCode = 8; }
    else if (key === 'Delete') { code = 'Delete'; keyCode = 46; }
    else if (key === ' ') { code = 'Space'; keyCode = 32; }
    else if (key === 'ArrowUp') { code = 'ArrowUp'; keyCode = 38; }
    else if (key === 'ArrowDown') { code = 'ArrowDown'; keyCode = 40; }
    else if (key === 'ArrowLeft') { code = 'ArrowLeft'; keyCode = 37; }
    else if (key === 'ArrowRight') { code = 'ArrowRight'; keyCode = 39; }
    else if (key.length === 1) {
      const charCode = key.toUpperCase().charCodeAt(0);
      keyCode = charCode;
      if (charCode >= 65 && charCode <= 90) {
        code = 'Key' + key.toUpperCase();
      } else if (charCode >= 48 && charCode <= 57) {
        code = 'Digit' + key;
      }
    }

    return { key, code, keyCode, ctrlKey, shiftKey, altKey, metaKey };
  }

  function simulateKeyPress(target, keySpec) {
    const k = parseKeySpec(keySpec);
    const opts = {
      key: k.key,
      code: k.code,
      keyCode: k.keyCode,
      which: k.keyCode,
      ctrlKey: k.ctrlKey,
      shiftKey: k.shiftKey,
      altKey: k.altKey,
      metaKey: k.metaKey,
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window
    };

    const downEv = new KeyboardEvent('keydown', opts);
    const pressEv = new KeyboardEvent('keypress', opts);
    const upEv = new KeyboardEvent('keyup', opts);

    const cancelled = !target.dispatchEvent(downEv);
    if (k.key.length === 1 || k.key === 'Enter') {
      target.dispatchEvent(pressEv);
    }

    if (!cancelled) {
      if (k.key === 'Enter') {
        if (target.form) {
          try {
            if (typeof target.form.requestSubmit === 'function') {
              target.form.requestSubmit();
            } else {
              target.form.submit();
            }
          } catch {}
        }
      } else if (k.key === 'Backspace') {
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
          const start = target.selectionStart;
          const end = target.selectionEnd;
          if (start !== null && end !== null && (start > 0 || start !== end)) {
            const val = target.value;
            const proto = target instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            const newPos = start === end ? start - 1 : start;
            const newVal = val.slice(0, newPos) + val.slice(end);
            if (desc && desc.set) { desc.set.call(target, newVal); } else { target.value = newVal; }
            target.setSelectionRange(newPos, newPos);
            target.dispatchEvent(new Event('input', { bubbles: true }));
            target.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
      } else if (k.key.length === 1 && !k.ctrlKey && !k.metaKey && !k.altKey) {
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
          const start = target.selectionStart;
          const end = target.selectionEnd;
          if (start !== null && end !== null) {
            const val = target.value;
            const proto = target instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            const newVal = val.slice(0, start) + k.key + val.slice(end);
            if (desc && desc.set) { desc.set.call(target, newVal); } else { target.value = newVal; }
            target.setSelectionRange(start + 1, start + 1);
            target.dispatchEvent(new Event('input', { bubbles: true }));
            target.dispatchEvent(new Event('change', { bubbles: true }));
          }
        } else if (target.isContentEditable) {
          try {
            document.execCommand('insertText', false, k.key);
          } catch {}
        }
      }
    }

    target.dispatchEvent(upEv);
    return `Pressed ${keySpec}`;
  }

  function domPress(keySpec, selector) {
    let target = document.activeElement || document.body;
    if (selector) {
      target = findEl(selector);
      try { target.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch {}
      try { target.focus(); } catch {}
    }
    simulateKeyPress(target, keySpec);
    return `Pressed '${keySpec}' on ${selector || target.tagName.toLowerCase()}`;
  }

  function domSendKeys(selector, text) {
    let target = document.activeElement || document.body;
    if (selector) {
      target = findEl(selector);
      try { target.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch {}
      try { target.focus(); } catch {}
    }
    for (const char of text) {
      simulateKeyPress(target, char);
    }
    return `Sent ${text.length} keys into ${selector || target.tagName.toLowerCase()}`;
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