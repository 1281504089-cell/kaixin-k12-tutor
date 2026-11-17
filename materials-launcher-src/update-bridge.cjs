const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('kaixinDesktop', {
  checkForUpdates: () => ipcRenderer.invoke('desktop:check-release'),
  getUpdateStatus: () => ipcRenderer.invoke('desktop:get-release-status'),
  onUpdateStatus: callback => {
    const handler = (_event, status) => callback(status);
    ipcRenderer.on('desktop:release-status', handler);
    return () => ipcRenderer.removeListener('desktop:release-status', handler);
  },
});
