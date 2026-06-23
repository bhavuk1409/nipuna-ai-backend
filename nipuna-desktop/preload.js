const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('nipuna', {
  getState: () => ipcRenderer.invoke('get-state'),
  startAuth: () => ipcRenderer.invoke('start-auth'),
  disconnect: () => ipcRenderer.invoke('disconnect'),
  log: (msg) => ipcRenderer.send('renderer-log', msg),
  onState: (cb) => {
    const handler = (_event, s) => cb(s);
    ipcRenderer.on('state', handler);
    // Return cleanup function
    return () => ipcRenderer.removeListener('state', handler);
  },
});