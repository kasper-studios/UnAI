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
