// Reuse the desktop's Chromium for the native lesson layout check.
const { app, BrowserWindow, session } = require('electron');
const { fileURLToPath } = require('node:url');
const { isAbsolute, dirname, join, basename } = require('node:path');
const target = process.argv.at(-1);
if (!target?.startsWith('file:') || !isAbsolute(fileURLToPath(target))) process.exit(2);
app.setPath('userData', join(dirname(fileURLToPath(target)), 'browser-profile'));
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const directory = dirname(fileURLToPath(target));
  session.defaultSession.webRequest.onBeforeRequest((request, done) => {
    let allowed = /^(data|blob):/.test(request.url);
    if (request.url.startsWith('file:')) {
      const file = fileURLToPath(request.url);
      allowed = dirname(file) === directory && ['host.html', 'probe.html'].includes(basename(file));
    }
    done({ cancel: !allowed });
  });
  const window = new BrowserWindow({ show: false, width: 1920, height: 1080,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, backgroundThrottling: false } });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  const timer = setTimeout(() => app.exit(1), 150000);
  try {
    await window.loadURL(target);
    while (!(await window.webContents.executeJavaScript('Boolean(document.getElementById("out")?.textContent?.trim())'))) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    process.stdout.write(await window.webContents.executeJavaScript('document.documentElement.outerHTML'));
    clearTimeout(timer);
    app.exit(0);
  } catch { clearTimeout(timer); app.exit(1); }
});
