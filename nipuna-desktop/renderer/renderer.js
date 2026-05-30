// ─── DOM refs ─────────────────────────────────────────────────────────────────
const statusBadge   = document.getElementById('status-badge');
const statusLabel   = document.getElementById('status-label');
const statusText    = document.getElementById('status-text');
const btnAuth       = document.getElementById('btn-auth');
const btnDisconnect = document.getElementById('btn-disconnect');
const errorBox      = document.getElementById('error-box');

const backendState     = document.getElementById('backend-state');
const backendIndicator = document.getElementById('backend-indicator');
const mcpState         = document.getElementById('mcp-state');
const mcpIndicator     = document.getElementById('mcp-indicator');
const tallyState       = document.getElementById('tally-state');
const tallyIndicator   = document.getElementById('tally-indicator');

// ─── State Rendering ──────────────────────────────────────────────────────────

function updateUI(s) {
  const status = s.status || 'idle';

  // Badge
  statusBadge.dataset.status = status;
  statusLabel.textContent = {
    idle:           'Idle',
    authenticating: 'Signing in…',
    connecting:     'Connecting…',
    connected:      'Connected',
    error:          'Error',
  }[status] || status;

  // Main status text
  if (status === 'connected') {
    if (!s.tallyReachable) {
      statusText.textContent = 'Connected to Nipuna, but Tally Prime was not detected. Please ensure Tally Prime is running on port 9000.';
    } else if (!s.mcpRunning) {
      statusText.textContent = 'Connected to Nipuna. Starting data bridge…';
    } else {
      statusText.textContent = 'Agent connected and active. Your Tally data is syncing with Nipuna AI.';
    }
  } else {
    statusText.textContent = {
      idle:           'Sign in with your Nipuna account to get started.',
      authenticating: 'Opening your browser to complete sign-in…',
      connecting:     'Establishing connection to Nipuna backend…',
      error:          s.lastError || 'An error occurred.',
    }[status] || '';
  }

  // Backend card
  const beConnected = s.connected;
  setCard(backendState, backendIndicator, beConnected ? 'Connected' : 'Not connected', beConnected);

  // MCP card
  setCard(mcpState, mcpIndicator, s.mcpRunning ? 'Running on :3000' : 'Starting…', s.mcpRunning);

  // Tally card
  setCard(tallyState, tallyIndicator, s.tallyReachable ? 'Detected on :9000' : 'Not detected', s.tallyReachable);

  // Buttons
  const busy = status === 'authenticating' || status === 'connecting';
  btnAuth.disabled = busy || s.connected;
  btnAuth.textContent = status === 'authenticating' ? 'Opening browser…'
                      : status === 'connecting'     ? 'Connecting…'
                      : 'Sign in with Nipuna';
  btnAuth.hidden = s.connected;

  btnDisconnect.hidden = !s.connected;

  // Error
  if (s.lastError && status === 'error') {
    errorBox.textContent = s.lastError;
    errorBox.hidden = false;
  } else {
    errorBox.hidden = true;
  }
}

function setCard(stateEl, indicatorEl, label, active) {
  stateEl.textContent = label;
  indicatorEl.dataset.active = active ? 'true' : 'false';
}

// ─── Button Handlers ──────────────────────────────────────────────────────────

btnAuth.addEventListener('click', async () => {
  try {
    await window.nipuna.startAuth();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
});

btnDisconnect.addEventListener('click', async () => {
  try {
    await window.nipuna.disconnect();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  }
});

// ─── Live State Updates ───────────────────────────────────────────────────────

window.nipuna.onState(updateUI);

// ─── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  try {
    const s = await window.nipuna.getState();
    updateUI(s);
  } catch (err) {
    errorBox.textContent = 'Failed to load state: ' + err.message;
    errorBox.hidden = false;
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}