const { app, BrowserWindow, shell, ipcMain } = require('electron');
const path = require('path');
const http = require('http');
const https = require('https');
const { spawn } = require('child_process');
const WebSocket = require('ws');

let mainWindow = null;

const IS_PROD = app.isPackaged;

const state = {
  authUrl: IS_PROD ? 'https://www.nipunaai.in/desktop-auth' : 'http://localhost:8080/desktop-auth',
  apiWsUrl: IS_PROD ? 'wss://api.nipunaai.in/api/v1/ws/agents' : 'ws://localhost:8000/api/v1/ws/agents',
  mcpUrl: 'http://localhost:9000',   // Tally XML port
  mcpServerPort: 3000,               // Our MCP HTTP server port
  status: 'idle',                    // idle | authenticating | connecting | connected | error
  connected: false,
  tallyReachable: false,
  mcpRunning: false,
  lastError: null,
};

let callbackServer = null;      // Local HTTP server for OAuth callback
let agentWs = null;             // WebSocket to backend
let mcpProcess = null;          // Child process for MCP server
let clerkJwt = null;            // Stored Clerk JWT
let mcpInternalSecret = null;   // Shared secret for /internal/call (captured from MCP stdout)
let tallyCheckInterval = null;
let mcpReadyCheckInterval = null;

// ─── Renderer Sync ────────────────────────────────────────────────────────────

function updateRenderer() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('state', { ...state });
  }
}

function setState(patch) {
  Object.assign(state, patch);
  updateRenderer();
}

// ─── Window ───────────────────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 480,
    height: 640,
    title: 'Nipuna Desktop',
    resizable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer/index.html'));
  mainWindow.on('closed', () => { mainWindow = null; });
}

// ─── OAuth Callback Server (port 41731) ───────────────────────────────────────

function startCallbackServer() {
  return new Promise((resolve) => {
    if (callbackServer) {
      resolve();
      return;
    }

    callbackServer = http.createServer(async (req, res) => {
      const url = new URL(req.url, 'http://localhost:41731');
      if (url.pathname !== '/callback') {
        res.writeHead(404);
        res.end();
        return;
      }

      const opaqueToken = url.searchParams.get('token');
      if (!opaqueToken) {
        res.writeHead(400);
        res.end('Missing token');
        return;
      }

      // Respond immediately with a nice page
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(`<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Nipuna Desktop — Connected</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Geist:wght@400;500;600;700&display=swap');
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: #f7f7f4;
      color: #0f0f10;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
      padding: 20px;
    }
    .card {
      text-align: center;
      background: #ffffff;
      border: 1px solid rgba(0, 0, 0, 0.06);
      border-radius: 12px;
      padding: 40px;
      width: 100%;
      max-width: 360px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02), 0 20px 48px -20px rgba(0,0,0,0.06);
    }
    .check-icon {
      width: 48px;
      height: 48px;
      background: #f0fdf4;
      border: 1px solid #d1fae5;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #047857;
      margin: 0 auto 20px;
    }
    .check-icon svg {
      width: 20px;
      height: 20px;
    }
    h1 {
      font-family: 'Geist', sans-serif;
      font-size: 20px;
      font-weight: 600;
      margin-bottom: 8px;
      letter-spacing: -0.03em;
    }
    p {
      color: #6b6b70;
      font-size: 13px;
      line-height: 1.5;
    }
    @media (prefers-color-scheme: dark) {
      body {
        background: #0c0c0e;
        color: #f3f3f7;
      }
      .card {
        background: #141416;
        border-color: rgba(255, 255, 255, 0.06);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15), 0 20px 48px -20px rgba(0,0,0,0.4);
      }
      .check-icon {
        background: rgba(16, 185, 129, 0.12);
        border-color: rgba(16, 185, 129, 0.2);
        color: #34d399;
      }
      p {
        color: #8e8e93;
      }
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="check-icon">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"></polyline>
      </svg>
    </div>
    <h1>You're connected!</h1>
    <p>You can close this tab and return to the Nipuna Desktop app.</p>
  </div>
</body>
</html>`);

      // Exchange the opaque token for the real Clerk JWT
      try {
        setState({ status: 'connecting', lastError: null });
        const jwt = await exchangeToken(opaqueToken);
        clerkJwt = jwt;
        await connectAgentWebSocket(jwt);
      } catch (err) {
        setState({ status: 'error', lastError: err.message });
      }
    });

    callbackServer.on('error', (err) => {
      console.error('Callback server error:', err);
    });

    callbackServer.listen(41731, '127.0.0.1', () => {
      console.log('OAuth callback server listening on http://127.0.0.1:41731');
      resolve();
    });
  });
}

// ─── Token Exchange ───────────────────────────────────────────────────────────

function exchangeToken(opaqueToken) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ token: opaqueToken });
    const reqLib = IS_PROD ? https : http;
    const opts = {
      hostname: IS_PROD ? 'api.nipunaai.in' : 'localhost',
      port: IS_PROD ? 443 : 8000,
      path: '/api/v1/desktop/exchange',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
      },
    };

    const req = reqLib.request(opts, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`Token exchange failed: ${res.statusCode} — ${data}`));
          return;
        }
        try {
          const json = JSON.parse(data);
          resolve(json.clerk_jwt);
        } catch {
          reject(new Error('Invalid response from token exchange'));
        }
      });
    });

    req.on('error', (err) => reject(new Error(`Cannot reach backend: ${err.message}`)));
    req.write(body);
    req.end();
  });
}

// ─── Agent WebSocket ──────────────────────────────────────────────────────────

function connectAgentWebSocket(jwt) {
  return new Promise((resolve, reject) => {
    if (agentWs) {
      agentWs.terminate();
      agentWs = null;
    }

    const wsUrl = `${state.apiWsUrl}?token=${encodeURIComponent(jwt)}`;
    console.log('Connecting agent WebSocket…');

    const ws = new WebSocket(wsUrl, {
      headers: { Authorization: `Bearer ${jwt}` },
    });

    const timeout = setTimeout(() => {
      ws.terminate();
      reject(new Error('WebSocket connection timed out'));
    }, 10000);

    ws.on('open', () => {
      clearTimeout(timeout);
      agentWs = ws;
      console.log('Agent WebSocket connected');

      // Register this desktop agent with tally capability
      const agentId = `tally-${Date.now()}`;
      ws.send(JSON.stringify({
        type: 'register',
        agent_id: agentId,
        capabilities: ['tally'],
      }));
    });

    ws.on('message', (data) => {
      try {
        const msg = JSON.parse(data.toString());
        handleAgentMessage(msg, resolve);
      } catch (err) {
        console.error('Failed to parse WS message:', err);
      }
    });

    ws.on('close', (code) => {
      console.log('Agent WebSocket closed:', code);
      agentWs = null;
      if (state.connected) {
        setState({ connected: false, status: 'idle', lastError: 'Connection closed by server' });
        // Auto-reconnect after 5 seconds if we have a JWT
        if (clerkJwt) {
          setTimeout(() => {
            if (!agentWs && clerkJwt) {
              connectAgentWebSocket(clerkJwt).catch(console.error);
            }
          }, 5000);
        }
      }
    });

    ws.on('error', (err) => {
      clearTimeout(timeout);
      console.error('Agent WebSocket error:', err.message);
      if (!state.connected) {
        reject(new Error(`WebSocket error: ${err.message}`));
      } else {
        setState({ lastError: err.message });
      }
    });
  });
}

function handleAgentMessage(msg, resolveConnect) {
  console.log('Agent message:', msg.type);

  if (msg.type === 'registered') {
    console.log('Desktop agent registered:', msg.agent_id);
    setState({ status: 'connected', connected: true, lastError: null });
    if (resolveConnect) resolveConnect();
  }

  if (msg.type === 'tool_call') {
    handleToolCall(msg);
  }

  if (msg.type === 'error') {
    console.error('Agent error:', msg.message);
    setState({ lastError: msg.message });
  }
}

// ─── Tool Call Proxy (backend → local MCP server) ────────────────────────────

async function handleToolCall(msg) {
  const { call_id, action, params } = msg;
  console.log('Tool call received:', action, call_id);

  if (!agentWs || agentWs.readyState !== WebSocket.OPEN) {
    return;
  }

  try {
    const result = await callLocalMcp(action, params);
    agentWs.send(JSON.stringify({
      type: 'tool_result',
      call_id,
      provider: 'tally',
      action,
      result,
      error: null,
    }));
  } catch (err) {
    agentWs.send(JSON.stringify({
      type: 'tool_result',
      call_id,
      provider: 'tally',
      action,
      result: null,
      error: err.message,
    }));
  }
}

function callLocalMcp(action, params) {
  return new Promise((resolve, reject) => {
    // Use the internal unauthenticated route — only accessible from this process
    const body = JSON.stringify({ action, params: params || {} });

    const headers = {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body),
    };
    // Attach the internal secret if we have it (captured from MCP stdout at startup)
    if (mcpInternalSecret) {
      headers['x-internal-secret'] = mcpInternalSecret;
    }

    const opts = {
      hostname: 'localhost',
      port: state.mcpServerPort,
      path: '/internal/call',
      method: 'POST',
      headers,
    };

    const req = http.request(opts, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json.error) reject(new Error(json.error || 'MCP internal call error'));
          else resolve(json.result);
        } catch {
          reject(new Error('Invalid MCP response'));
        }
      });
    });

    req.on('error', (err) => reject(new Error(`MCP server unreachable: ${err.message}`)));
    req.write(body);
    req.end();
  });
}

function checkMcpServerReady() {
  return new Promise((resolve) => {
    const req = http.request(
      {
        hostname: 'localhost',
        port: state.mcpServerPort,
        path: '/health',
        method: 'GET',
      },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );

    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => {
      req.destroy();
      resolve(false);
    });
    req.end();
  });
}

function startMcpReadinessCheck() {
  if (mcpReadyCheckInterval) return;

  const doCheck = async () => {
    const ready = await checkMcpServerReady();
    if (ready) {
      clearInterval(mcpReadyCheckInterval);
      mcpReadyCheckInterval = null;
      if (!state.mcpRunning) {
        setState({ mcpRunning: true });
      }
      startTallyHealthCheck();
    }
  };

  doCheck();
  mcpReadyCheckInterval = setInterval(doCheck, 500);
}

// ─── MCP Server Child Process ─────────────────────────────────────────────────

function startMcpServer() {
  if (mcpProcess) return;

  // server.mjs is the HTTP transport version (server.mjs, not index.mjs which is stdio)
  let mcpServerDir, mcpServerScript;
  if (app.isPackaged) {
    mcpServerDir    = path.join(process.resourcesPath, 'tally-mcp-server');
    mcpServerScript = path.join(mcpServerDir, 'dist', 'server.mjs');
  } else {
    mcpServerDir    = path.join(__dirname, '..', 'nipuna-backend', '1766393040_tally_mcp_server_v6');
    mcpServerScript = path.join(mcpServerDir, 'dist', 'server.mjs');
  }

  console.log('Starting MCP server:', mcpServerScript);

  const env = {
    ...process.env,
    PORT: String(state.mcpServerPort),
    TALLY_PORT: '9000',
    MCP_DOMAIN: `http://localhost:${state.mcpServerPort}`,
    PASSWORD: 'nipuna-desktop',
  };

  // cwd must be the MCP server root so its own node_modules are found
  mcpProcess = spawn('node', [mcpServerScript], { env, cwd: mcpServerDir, stdio: 'pipe' });

  mcpProcess.stdout.on('data', (data) => {
    const lines = data.toString().split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      // Capture the internal secret emitted by the MCP server on startup
      if (trimmed.startsWith('INTERNAL_SECRET=')) {
        mcpInternalSecret = trimmed.slice('INTERNAL_SECRET='.length);
        console.log('[MCP] Internal secret captured');
      } else {
        console.log('[MCP]', trimmed);
      }
    }
  });

  mcpProcess.stderr.on('data', (data) => {
    console.error('[MCP ERR]', data.toString().trim());
  });

  mcpProcess.on('close', (code) => {
    console.log('MCP server exited with code', code);
    mcpProcess = null;
    mcpInternalSecret = null;
    setState({ mcpRunning: false });
    if (mcpReadyCheckInterval) {
      clearInterval(mcpReadyCheckInterval);
      mcpReadyCheckInterval = null;
    }
  });

  mcpProcess.on('error', (err) => {
    console.error('Failed to start MCP server:', err.message);
    setState({ mcpRunning: false, lastError: `MCP server failed to start: ${err.message}` });
    if (mcpReadyCheckInterval) {
      clearInterval(mcpReadyCheckInterval);
      mcpReadyCheckInterval = null;
    }
  });

  // Start readiness polling ONCE here — not in stdout/stderr (avoids race condition)
  startMcpReadinessCheck();
}

function stopMcpServer() {
  if (mcpProcess) {
    mcpProcess.kill();
    mcpProcess = null;
  }
  mcpInternalSecret = null;
  if (mcpReadyCheckInterval) {
    clearInterval(mcpReadyCheckInterval);
    mcpReadyCheckInterval = null;
  }
}

// ─── Tally Health Check ───────────────────────────────────────────────────────

function checkTallyReachable() {
  return new Promise((resolve) => {
    const req = http.request(
      { hostname: 'localhost', port: 9000, method: 'GET', path: '/' },
      (res) => { resolve(true); res.resume(); }
    );
    req.on('error', () => resolve(false));
    req.setTimeout(2000, () => { req.destroy(); resolve(false); });
    req.end();
  });
}

async function startTallyHealthCheck() {
  if (tallyCheckInterval) return;
  const doCheck = async () => {
    const reachable = await checkTallyReachable();
    if (reachable !== state.tallyReachable) {
      setState({ tallyReachable: reachable });
    }
  };
  await doCheck();
  tallyCheckInterval = setInterval(doCheck, 10000);
}

// ─── Auth Flow ────────────────────────────────────────────────────────────────

let authFlowInProgress = false;

async function startAuthFlow() {
  if (authFlowInProgress) return;
  authFlowInProgress = true;

  setState({ status: 'authenticating', lastError: null });
  await startCallbackServer();

  const redirectUri = encodeURIComponent('http://localhost:41731/callback');
  const url = `${state.authUrl}?redirect_uri=${redirectUri}`;
  console.log('Opening auth URL:', url);

  try {
    await shell.openExternal(url);
  } catch (err) {
    authFlowInProgress = false;
    setState({ status: 'error', lastError: 'Failed to open browser: ' + err.message });
  }
}

function disconnect() {
  if (agentWs) {
    agentWs.terminate();
    agentWs = null;
  }
  clerkJwt = null;
  authFlowInProgress = false;
  setState({ status: 'idle', connected: false, lastError: null });
}

// ─── App Lifecycle ────────────────────────────────────────────────────────────

app.on('ready', () => {
  createWindow();
  startMcpServer();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

app.on('before-quit', () => {
  stopMcpServer();
  if (callbackServer) {
    callbackServer.close();
    callbackServer = null;
  }
  if (tallyCheckInterval) {
    clearInterval(tallyCheckInterval);
    tallyCheckInterval = null;
  }
});

// ─── IPC Handlers ─────────────────────────────────────────────────────────────

ipcMain.handle('get-state', () => ({ ...state }));

ipcMain.handle('start-auth', async () => {
  await startAuthFlow();
  return { success: true };
});

ipcMain.handle('disconnect', () => {
  disconnect();
  return { success: true };
});

ipcMain.on('renderer-log', (_event, message) => {
  console.log('[renderer]', message);
});
