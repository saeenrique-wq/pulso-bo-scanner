const SCANNER = 'http://localhost:8082/api/set_ssid';

async function extractAndSend() {
  try {
    const cookie = await chrome.cookies.get({ url: 'https://trade.exnova.com', name: 'ssid' });
    if (!cookie?.value || cookie.value.length < 20) {
      chrome.action.setBadgeText({ text: '!' });
      chrome.action.setBadgeBackgroundColor({ color: '#ff2d55' });
      chrome.storage.local.set({ status: 'no_ssid' });
      return;
    }
    const resp = await fetch(SCANNER, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ssid: cookie.value })
    });
    const data = await resp.json();
    if (resp.ok) {
      chrome.action.setBadgeText({ text: 'ON' });
      chrome.action.setBadgeBackgroundColor({ color: '#00ff87' });
      chrome.storage.local.set({ status: 'connected', ssid: cookie.value.slice(0,8)+'...' });
    } else {
      chrome.action.setBadgeText({ text: 'ERR' });
      chrome.action.setBadgeBackgroundColor({ color: '#ff9f00' });
      chrome.storage.local.set({ status: 'error', error: data.error });
    }
  } catch (e) {
    chrome.action.setBadgeText({ text: '?' });
    chrome.action.setBadgeBackgroundColor({ color: '#888' });
    chrome.storage.local.set({ status: 'scanner_off' });
  }
}

// Auto-conectar cuando el usuario está en Exnova
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url?.includes('trade.exnova.com')) {
    setTimeout(extractAndSend, 2500);
  }
});

// Auto-conectar al arrancar el browser si Exnova ya está abierta
chrome.runtime.onStartup.addListener(async () => {
  const tabs = await chrome.tabs.query({ url: '*://trade.exnova.com/*' });
  if (tabs.length > 0) extractAndSend();
});

// Re-conectar cada 30 min para mantener la sesión activa
setInterval(extractAndSend, 30 * 60 * 1000);

// Mensaje manual desde el popup
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === 'connect') extractAndSend();
});
