// UnAI Browser Bridge — popup: показывает состояние моста и активной вкладки.

const statusEl = document.getElementById('status');
const browserEl = document.getElementById('browser');
const titleEl = document.getElementById('tab-title');
const urlEl = document.getElementById('tab-url');

async function refresh() {
  const bg = chrome.runtime.getBackgroundPage ? await null : null;

  // Пробрасываем запрос в background через runtime.sendMessage
  chrome.runtime.sendMessage({ method: 'popup.status' }, (resp) => {
    if (chrome.runtime.lastError) {
      // service worker уснул — он проснётся сам
      statusEl.textContent = 'runtime sleeping…';
      statusEl.className = 'bad';
      return;
    }
    if (!resp) return;
    const s = resp.status;
    if (s.connected) {
      statusEl.textContent = '● connected to UnAI';
      statusEl.className = 'ok';
    } else {
      statusEl.textContent = '○ disconnected (runtime offline?)';
      statusEl.className = 'bad';
    }
    browserEl.textContent = `Browser: ${s.browser || 'unknown'} v${s.version || ''}`;
    titleEl.textContent = s.active_tab ? `Tab: ${s.active_tab.title}` : '';
    urlEl.textContent = s.active_tab ? s.active_tab.url : '';
  });
}

document.getElementById('refresh').addEventListener('click', refresh);
refresh();
