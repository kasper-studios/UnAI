// ==UserScript==
// @name         UnAI Browser Bridge
// @namespace    http://tampermonkey.net/
// @version      1.0.0
// @description  Tampermonkey bridge for UnAI runtime (WebSocket ws://127.0.0.1:8055)
// @match        *://*/*
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    const WS_URL = 'ws://127.0.0.1:8055';
    let socket = null;
    let reconnectInterval = 3000;

    function getBrowserName() {
        const ua = navigator.userAgent;
        if (ua.includes('Firefox')) return 'Firefox';
        if (ua.includes('Chrome')) return 'Chrome';
        if (ua.includes('Safari')) return 'Safari';
        return 'Unknown Browser';
    }

    function sendStatus() {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
                type: 'status',
                status: {
                    browser: getBrowserName(),
                    title: document.title,
                    url: window.location.href,
                    version: '1.0.0'
                }
            }));
        }
    }

    function connect() {
        try {
            socket = new WebSocket(WS_URL);
        } catch (e) {
            setTimeout(connect, reconnectInterval);
            return;
        }

        socket.onopen = () => {
            console.log('[UnAI Bridge] Connected to runtime at', WS_URL);
            sendStatus();
        };

        socket.onmessage = async (event) => {
            let msg;
            try {
                msg = JSON.parse(event.data);
            } catch (e) {
                return;
            }

            const { id, method, params } = msg;
            if (!id) return;

            try {
                let result = null;
                switch (method) {
                    case 'browser.navigate':
                        window.location.href = params.url;
                        result = `Navigated to ${params.url}`;
                        break;

                    case 'browser.screenshot':
                        result = await takeScreenshot();
                        break;

                    case 'dom.query': {
                        const els = document.querySelectorAll(params.selector);
                        result = Array.from(els).map(el => ({
                            tag: el.tagName.toLowerCase(),
                            text: el.innerText ? el.innerText.slice(0, 200) : '',
                            html: el.outerHTML.slice(0, 500),
                            rect: el.getBoundingClientRect()
                        }));
                        break;
                    }

                    case 'dom.click': {
                        const el = document.querySelector(params.selector);
                        if (!el) throw new Error(`Element not found: ${params.selector}`);
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        el.click();
                        result = `Clicked element: ${params.selector}`;
                        break;
                    }

                    case 'dom.type': {
                        const el = document.querySelector(params.selector);
                        if (!el) throw new Error(`Element not found: ${params.selector}`);
                        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        el.focus();
                        el.value = params.text;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        result = `Typed into element: ${params.selector}`;
                        break;
                    }

                    case 'dom.press': {
                        let el = params.selector ? document.querySelector(params.selector) : (document.activeElement || document.body);
                        if (params.selector && !el) throw new Error(`Element not found: ${params.selector}`);
                        if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        if (el && el.focus) el.focus();
                        simulateKeyPress(el, params.key);
                        result = `Pressed key: ${params.key}`;
                        break;
                    }

                    case 'dom.send_keys': {
                        let el = params.selector ? document.querySelector(params.selector) : (document.activeElement || document.body);
                        if (params.selector && !el) throw new Error(`Element not found: ${params.selector}`);
                        if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        if (el && el.focus) el.focus();
                        for (const char of params.text) {
                            simulateKeyPress(el, char);
                        }
                        result = `Sent keys into element: ${params.selector}`;
                        break;
                    }

                    case 'dom.wait': {
                        const selector = params.selector;
                        const timeout = params.timeout_ms || 5000;
                        const start = Date.now();
                        result = await new Promise((resolve, reject) => {
                            function check() {
                                const el = document.querySelector(selector);
                                if (el) {
                                    resolve(`Element ${selector} found`);
                                } else if (Date.now() - start > timeout) {
                                    reject(new Error(`Timeout waiting for selector: ${selector}`));
                                } else {
                                    setTimeout(check, 100);
                                }
                            }
                            check();
                        });
                        break;
                    }

                    default:
                        throw new Error(`Unknown method: ${method}`);
                }

                socket.send(JSON.stringify({ id, result }));
            } catch (err) {
                socket.send(JSON.stringify({ id, error: err.message || String(err) }));
            }
        };

        socket.onclose = () => {
            setTimeout(connect, reconnectInterval);
        };

        socket.onerror = () => {
            socket.close();
        };
    }

    async function takeScreenshot() {
        if (!window.html2canvas) {
            await new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
                script.onload = resolve;
                script.onerror = reject;
                document.head.appendChild(script);
            });
        }
        const canvas = await window.html2canvas(document.body, { useCORS: true, logging: false });
        const dataUrl = canvas.toDataURL('image/png');
        return dataUrl.split(',')[1];
    }

    function parseKeySpec(keySpec) {
        if (!keySpec) throw new Error('Key specification required');
        const parts = String(keySpec).split('+').map(s => s.trim());
        let key = parts[parts.length - 1];

        const ctrlKey = parts.some(p => /^ctrl(ol)?$/i.test(p));
        const shiftKey = parts.some(p => /^shift$/i.test(p));
        const altKey = parts.some(p => /^alt$/i.test(p));
        const metaKey = parts.some(p => /^(meta|cmd|command|win)$/i.test(p));

        const keyMap = {
            'esc': 'Escape', 'escape': 'Escape', 'enter': 'Enter', 'return': 'Enter',
            'tab': 'Tab', 'space': ' ', 'backspace': 'Backspace', 'delete': 'Delete',
            'up': 'ArrowUp', 'down': 'ArrowDown', 'left': 'ArrowLeft', 'right': 'ArrowRight',
            'arrowup': 'ArrowUp', 'arrowdown': 'ArrowDown', 'arrowleft': 'ArrowLeft', 'arrowright': 'ArrowRight'
        };

        const lowerKey = key.toLowerCase();
        if (keyMap[lowerKey]) { key = keyMap[lowerKey]; }
        else if (key.length === 1) { key = shiftKey ? key.toUpperCase() : key; }

        let code = key; let keyCode = 0;
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
            if (charCode >= 65 && charCode <= 90) code = 'Key' + key.toUpperCase();
            else if (charCode >= 48 && charCode <= 57) code = 'Digit' + key;
        }

        return { key, code, keyCode, ctrlKey, shiftKey, altKey, metaKey };
    }

    function simulateKeyPress(target, keySpec) {
        const k = parseKeySpec(keySpec);
        const opts = { key: k.key, code: k.code, keyCode: k.keyCode, which: k.keyCode, ctrlKey: k.ctrlKey, shiftKey: k.shiftKey, altKey: k.altKey, metaKey: k.metaKey, bubbles: true, cancelable: true, composed: true, view: window };
        const downEv = new KeyboardEvent('keydown', opts);
        const pressEv = new KeyboardEvent('keypress', opts);
        const upEv = new KeyboardEvent('keyup', opts);

        const cancelled = !target.dispatchEvent(downEv);
        if (k.key.length === 1 || k.key === 'Enter') target.dispatchEvent(pressEv);

        if (!cancelled) {
            if (k.key === 'Enter') {
                if (target.form) { try { target.form.requestSubmit ? target.form.requestSubmit() : target.form.submit(); } catch {} }
            } else if (k.key === 'Backspace') {
                if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
                    const start = target.selectionStart; const end = target.selectionEnd;
                    if (start !== null && end !== null && (start > 0 || start !== end)) {
                        const val = target.value;
                        const newPos = start === end ? start - 1 : start;
                        target.value = val.slice(0, newPos) + val.slice(end);
                        target.setSelectionRange(newPos, newPos);
                        target.dispatchEvent(new Event('input', { bubbles: true }));
                        target.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            } else if (k.key.length === 1 && !k.ctrlKey && !k.metaKey && !k.altKey) {
                if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
                    const start = target.selectionStart; const end = target.selectionEnd;
                    if (start !== null && end !== null) {
                        const val = target.value;
                        target.value = val.slice(0, start) + k.key + val.slice(end);
                        target.setSelectionRange(start + 1, start + 1);
                        target.dispatchEvent(new Event('input', { bubbles: true }));
                        target.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                } else if (target.isContentEditable) {
                    try { document.execCommand('insertText', false, k.key); } catch {}
                }
            }
        }
        target.dispatchEvent(upEv);
    }

    window.addEventListener('load', sendStatus);
    let lastUrl = location.href;
    new MutationObserver(() => {
        if (location.href !== lastUrl) {
            lastUrl = location.href;
            sendStatus();
        }
    }).observe(document, { subtree: true, childList: true });

    connect();
})();
