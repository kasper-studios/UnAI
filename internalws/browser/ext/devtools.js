// UnAI Browser Bridge — DevTools helpers (network/console).
// Лёгкий «DevTools» без CDP: перехват сетевых запросов через webRequest API
// и лог консоли страницы через content.js.

// ---------------- Network: webRequest

const NETWORK_BUFFER_LIMIT = 500;
const networkBuffer = [];

function recordRequest(details) {
  if (details.tabId < 0) return;
  networkBuffer.push({
    ts: Date.now(),
    method: details.method,
    url: details.url,
    status: details.statusCode || 0,
    type: details.type || 'other',
    tabId: details.tabId,
    error: details.error || undefined
  });
  if (networkBuffer.length > NETWORK_BUFFER_LIMIT) {
    networkBuffer.splice(0, networkBuffer.length - NETWORK_BUFFER_LIMIT);
  }
}

if (typeof chrome !== 'undefined' && chrome.webRequest) {
  chrome.webRequest.onCompleted.addListener(recordRequest, { urls: ['<all_urls>'] });
  chrome.webRequest.onErrorOccurred.addListener(recordRequest, { urls: ['<all_urls>'] });
}

function getNetworkLog(tabId, limit = 100) {
  const entries = tabId === undefined || tabId === null
    ? networkBuffer
    : networkBuffer.filter(e => e.tabId === tabId);
  return entries.slice(-limit);
}

// ---------------- Console: буфер сообщений из content.js

const CONSOLE_BUFFER_LIMIT = 200;
const consoleBuffer = [];

if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === 'console') {
      consoleBuffer.push({
        ts: Date.now(),
        tabId: msg.tabId !== undefined ? msg.tabId : null,
        level: msg.level,
        text: msg.text,
        url: msg.url
      });
      if (consoleBuffer.length > CONSOLE_BUFFER_LIMIT) {
        consoleBuffer.splice(0, consoleBuffer.length - CONSOLE_BUFFER_LIMIT);
      }
    }
  });
}

function getConsoleLog(tabId, limit = 50) {
  const entries = tabId === undefined || tabId === null
    ? consoleBuffer
    : consoleBuffer.filter(e => e.tabId === tabId);
  return entries.slice(-limit);
}

self.unaiDevtools = { getNetworkLog, getConsoleLog };