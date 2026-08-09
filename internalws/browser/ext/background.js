// UnAI Browser Bridge — background service worker.
// Держит единственное WebSocket-соединение с рантаймом UnAI (ws://127.0.0.1:8055),
// маршрутизирует команды на активную вкладку (content script) и обратно.

// devtools.js грузится как часть service worker (importScripts — работает
// и в Chrome MV3, и в Firefox MV3).
importScripts('devtools.js');

const WS_URL = 'ws://127.0.0.1:8055';

let ws = null;
let wsConnected = false;
let reconnectDelay = 2000;
let reconnectTimer = null;
let pending = new Map(); // reqId -> {resolve, reject}
let reqCounter = 0;
let lastReceivedPingAt = 0;

// ---------------------------------------------------------------- WebSocket

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    wsConnected = true;
    reconnectDelay = 2000;
    console.log('[UnAI Bridge] connected to', WS_URL);
    sendStatusNow();
  };

  ws.onmessage = async (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }

    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error)); else p.resolve(msg.result);
      return;
    }
    if (msg.method) {
      try {
        const result = await dispatch(msg.method, msg.params || {}, msg.id);
        if (msg.id) ws.send(JSON.stringify({ id: msg.id, result }));
      } catch (err) {
        if (msg.id) ws.send(JSON.stringify({ id: msg.id, error: err.message || String(err) }));
      }
    }
  };

  ws.onclose = () => {
    wsConnected = false;
    ws = null;
    scheduleReconnect();
  };
  ws.onerror = () => { try { ws.close(); } catch {} };
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 1.2, 5000);
}

function isConnected() { return wsConnected; }

// ---------------------------------------------------------------- keepalive & auto-connect

// 15s interval while service worker is active
setInterval(() => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    connect();
  } else {
    try { ws.send(JSON.stringify({ type: 'ping' })); } catch {}
  }
}, 15000);

// Chrome Alarm every 0.35 min (~21s) to prevent MV3 Service Worker 30s idle termination
chrome.alarms.create('unai-ping', { periodInMinutes: 0.35 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'unai-ping') {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      connect();
    } else {
      try {
        ws.send(JSON.stringify({ type: 'ping' }));
        sendStatusNow();
      } catch {
        connect();
      }
    }
  }
});

// Auto reconnect on user tab/window interactions
chrome.tabs.onActivated.addListener(() => { connect(); sendStatusNow(); });
chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (changeInfo.status === 'complete') { connect(); sendStatusNow(); }
});
chrome.windows.onFocusChanged.addListener(() => { connect(); sendStatusNow(); });

connect();
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);

// ---------------------------------------------------------------- dispatch

async function dispatch(method, params, reqId) {
  switch (method) {
    // ---- вкладки (только WebExtension)
    case 'browser.tabs.list':
      return listTabs();
    case 'browser.tabs.activate':
      return activateTab(params.id || params.index);
    case 'browser.tabs.close':
      return closeTab(params.id);

    // ---- навигация / статус
    case 'browser.navigate':
      return navigate(params.url);
    case 'browser.status':
      return getStatus();

    // ---- скриншот (native, через API браузера)
    case 'browser.screenshot':
      return screenshot();

    // ---- куки (только WebExtension)
    case 'browser.cookies.list':
      return cookiesList(params);
    case 'browser.cookies.get':
      return cookiesGet(params);
    case 'browser.cookies.set':
      return cookiesSet(params);
    case 'browser.cookies.remove':
      return cookiesRemove(params);

    // ---- DOM (через content script активной вкладки)
    case 'dom.query':
    case 'dom.click':
    case 'dom.type':
    case 'dom.press':
    case 'dom.send_keys':
    case 'dom.wait':
    case 'browser.storage.get':
    case 'browser.storage.set':
    case 'devtools.console':
      return sendToActiveTab(method, params);

    case 'devtools.eval':
      return devtoolsEval(params.expression);
    case 'browser.page.content':
      return pageContent(params.selector);

    // ---- DevTools: network — буфер в самом background
    case 'devtools.network': {
      const tab = await getActiveTab();
      return self.unaiDevtools ? self.unaiDevtools.getNetworkLog(tab.id, params.limit || 100) : [];
    }

    default:
      throw new Error(`Unknown method: ${method}`);
  }
}

// ---------------------------------------------------------------- tabs

async function getActiveTab() {
  let [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) {
    [tab] = await chrome.tabs.query({ active: true });
  }
  if (!tab) {
    const tabs = await chrome.tabs.query({});
    tab = tabs[0];
  }
  if (!tab) throw new Error('No active tab found in browser');
  return tab;
}

async function listTabs() {
  const tabs = await chrome.tabs.query({});
  return tabs.map(t => ({
    id: t.id,
    index: t.index,
    title: t.title || '',
    url: t.url || '',
    active: t.active,
    pinned: t.pinned,
    windowId: t.windowId
  }));
}

async function activateTab(idOrIndex) {
  let tab;
  if (typeof idOrIndex === 'number' && idOrIndex >= 0 && idOrIndex < 100000) {
    tab = await getTabByIndex(idOrIndex);
  } else {
    tab = await chrome.tabs.get(idOrIndex);
  }
  if (!tab) throw new Error(`Tab not found: ${idOrIndex}`);
  await chrome.tabs.update(tab.id, { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
  return { id: tab.id, index: tab.index, url: tab.url, title: tab.title };
}

async function getTabByIndex(index) {
  let tabs = await chrome.tabs.query({ lastFocusedWindow: true });
  if (!tabs || tabs.length === 0) {
    tabs = await chrome.tabs.query({});
  }
  const tab = tabs[index];
  if (!tab) throw new Error(`No tab at index ${index}`);
  return tab;
}

async function closeTab(id) {
  await chrome.tabs.remove(id);
  return { closed: id };
}

async function navigate(url) {
  const tab = await getActiveTab();
  await chrome.tabs.update(tab.id, { url });
  return { navigated: url, tabId: tab.id };
}

async function getStatus() {
  const tab = await getActiveTab();
  return {
    connected: wsConnected,
    browser: getBrowserName(),
    version: chrome.runtime.getManifest().version,
    active_tab: {
      id: tab.id,
      title: tab.title || '',
      url: tab.url || ''
    }
  };
}

function getBrowserName() {
  const ua = navigator.userAgent;
  if (ua.includes('Firefox')) return 'Firefox';
  if (ua.includes('Chrome')) return 'Chrome';
  if (ua.includes('Safari')) return 'Safari';
  return 'Unknown Browser';
}

async function screenshot() {
  const tab = await getActiveTab();
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  return dataUrl.split(',')[1];
}

// ---------------------------------------------------------------- cookies

async function cookiesList(params) {
  return await chrome.cookies.getAll({ url: params.url, domain: params.domain, name: params.name });
}

async function cookiesGet(params) {
  if (!params.url || !params.name) throw new Error('cookies.get requires url and name');
  const c = await chrome.cookies.get({ url: params.url, name: params.name });
  return c || null;
}

async function cookiesSet(params) {
  if (!params.url || !params.name || params.value === undefined)
    throw new Error('cookies.set requires url, name, value');
  const cookie = await chrome.cookies.set({
    url: params.url,
    name: params.name,
    value: String(params.value),
    domain: params.domain,
    path: params.path || '/',
    secure: !!params.secure,
    httpOnly: !!params.httpOnly,
    expirationDate: params.expirationDate,
    sameSite: params.sameSite
  });
  return cookie || null;
}

async function cookiesRemove(params) {
  if (!params.url || !params.name) throw new Error('cookies.remove requires url and name');
  await chrome.cookies.remove({ url: params.url, name: params.name });
  return { removed: params.name };
}

async function pageContent(selector) {
  const tab = await getActiveTab();
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'ISOLATED',
      func: (sel) => {
        const el = document.querySelector(sel || 'body');
        if (!el) return '(element not found)';
        return (el.innerText || el.textContent || '').trim();
      },
      args: [selector || 'body']
    });
    return res && res.result;
  } catch (err) {
    throw new Error(`page.content failed: ${err.message}`);
  }
}

async function devtoolsEval(expression) {
  const tab = await getActiveTab();
  if (!expression) throw new Error('devtools.eval requires expression');
  
  // 1. Try in MAIN world with Trusted Types policy support
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      func: (expr) => {
        try {
          let code = expr;
          if (window.trustedTypes && window.trustedTypes.createPolicy) {
            try {
              if (!window.__unaiTT) {
                window.__unaiTT = window.trustedTypes.createPolicy('unaiPolicy', {
                  createScript: (s) => s
                });
              }
              code = window.__unaiTT.createScript(expr);
            } catch (ttErr) {}
          }
          const val = (0, eval)(code);
          if (val === undefined) return '__UNDEFINED__';
          if (typeof val === 'function') return '[Function]';
          try {
            return JSON.parse(JSON.stringify(val));
          } catch {
            return String(val);
          }
        } catch (e) {
          return { __error: String(e) };
        }
      },
      args: [expression]
    });
    if (res && res.result && typeof res.result === 'object' && res.result.__error && res.result.__error.includes('Trusted Type')) {
      throw new Error(res.result.__error);
    }
    return res && res.result;
  } catch (err) {
    // 2. Fallback to ISOLATED extension world if MAIN world was blocked by Trusted Types
    try {
      const [resIso] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        world: 'ISOLATED',
        func: (expr) => {
          try {
            const val = (0, eval)(expr);
            if (val === undefined) return '__UNDEFINED__';
            if (typeof val === 'function') return '[Function]';
            try {
              return JSON.parse(JSON.stringify(val));
            } catch {
              return String(val);
            }
          } catch (e) {
            return { __error: String(e) };
          }
        },
        args: [expression]
      });
      return resIso && resIso.result;
    } catch (isoErr) {
      throw new Error(`devtools.eval failed: ${err.message}`);
    }
  }
}

// ---------------------------------------------------------------- content script bridge

async function sendToActiveTab(method, params) {
  const tab = await getActiveTab();
  let resp;
  try {
    resp = await chrome.tabs.sendMessage(tab.id, { method, params });
  } catch (e) {
    if (e.message && e.message.includes('Receiving end does not exist')) {
      try {
        await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ['content.js']
        });
        await new Promise(r => setTimeout(r, 150));
        resp = await chrome.tabs.sendMessage(tab.id, { method, params });
      } catch (injectErr) {
        throw new Error(`${method}: content script unavailable (${e.message})`);
      }
    } else {
      throw new Error(`${method}: content script unavailable (${e.message})`);
    }
  }
  if (resp && resp.error) throw new Error(resp.error);
  return resp && resp.result;
}

// ---------------------------------------------------------------- popup

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.method === 'popup.status') {
    getStatus().then(s => sendResponse({ status: s })).catch((e) => sendResponse({ status: { connected: wsConnected, error: e.message } }));
    return true; // асинхронный ответ
  }
});

// ---------------------------------------------------------------- events

async function sendStatusNow() {
  if (!wsConnected) return;
  try {
    const status = await getStatus();
    ws.send(JSON.stringify({ type: 'status', status }));
  } catch (e) { /* no active tab yet */ }
}