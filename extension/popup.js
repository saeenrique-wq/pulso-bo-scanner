const dot = document.getElementById('dot');
const txt = document.getElementById('status-text');
const hint = document.getElementById('hint');

const STATE = {
  connected:   ['green',  '✅ OTC Activo — Scanner conectado', 'La conexión se renueva automáticamente.'],
  no_ssid:     ['red',    '⚠️ No hay sesión de Exnova', 'Abre trade.exnova.com y asegúrate de estar logueado.'],
  scanner_off: ['yellow', '⚡ Scanner no está corriendo', 'Ejecuta INICIAR.bat primero.'],
  error:       ['red',    '❌ Error al conectar', ''],
  unknown:     ['gray',   'Sin datos aún...', ''],
};

function render(s) {
  const [color, msg, h] = STATE[s] || STATE.unknown;
  dot.className = `dot ${color}`;
  txt.textContent = msg;
  hint.textContent = h;
}

chrome.storage.local.get(['status'], (r) => render(r.status || 'unknown'));

document.getElementById('btn').addEventListener('click', () => {
  txt.textContent = 'Conectando...';
  dot.className = 'dot gray';
  chrome.runtime.sendMessage({ action: 'connect' });
  setTimeout(() => chrome.storage.local.get(['status'], (r) => render(r.status || 'unknown')), 3000);
});
