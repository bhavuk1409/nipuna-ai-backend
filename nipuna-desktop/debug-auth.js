const { app, BrowserWindow } = require('electron');

const url = process.argv[2] || 'http://localhost:8080/desktop-auth?redirect_uri=http://localhost:41731/callback';

app.disableHardwareAcceleration();

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    show: false,
    width: 1000,
    height: 900,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      offscreen: true,
    },
  });

  win.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    console.log('console', { level, message, line, sourceId });
  });

  win.webContents.session.webRequest.onErrorOccurred((details) => {
    if (details.url.includes('clerk') || details.url.includes('nipuna') || details.url.includes('127.0.0.1')) {
      console.log('request-error', {
        error: details.error,
        method: details.method,
        url: details.url,
      });
    }
  });

  win.webContents.session.webRequest.onCompleted((details) => {
    if (details.url.includes('clerk') || details.url.includes('nipuna') || details.url.includes('127.0.0.1')) {
      console.log('request-completed', {
        statusCode: details.statusCode,
        method: details.method,
        url: details.url,
      });
    }
  });

  await win.loadURL(url);
  await new Promise((resolve) => setTimeout(resolve, 12000));

  const result = await win.webContents.executeJavaScript(`
    (() => {
      const el = document.getElementById('clerk-sign-in');
      const status = document.getElementById('status');
      const debug = document.getElementById('debug-errors');
      const visibleControls = el ? Array.from(el.querySelectorAll('input:not([type="hidden"]), button, [role="button"]')).map((node) => {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return {
          tag: node.tagName,
          text: (node.textContent || node.getAttribute('aria-label') || node.getAttribute('name') || node.getAttribute('type') || '').trim(),
          display: style.display,
          visibility: style.visibility,
          opacity: style.opacity,
          disabled: Boolean(node.disabled),
          width: rect.width,
          height: rect.height,
        };
      }) : [];
      return {
        href: location.href,
        title: document.title,
        bodyText: document.body.innerText.slice(0, 1000),
        clerkPresent: Boolean(window.Clerk),
        clerkLoaded: Boolean(window.Clerk && window.Clerk.loaded),
        clerkUser: Boolean(window.Clerk && window.Clerk.user),
        clerkSession: Boolean(window.Clerk && window.Clerk.session),
        containerChildren: el ? el.childElementCount : null,
        containerHTML: el ? el.innerHTML.slice(0, 2000) : null,
        visibleControls,
        statusText: status ? status.innerText : null,
        debugText: debug ? debug.innerText : null,
      };
    })()
  `);

  console.log('dom-result', JSON.stringify(result, null, 2));
  await app.quit();
});
