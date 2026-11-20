const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('kaixinUpdate', {
  cancel: () => ipcRenderer.invoke('desktop:cancel-release'),
  onStatus: listener => ipcRenderer.on('desktop:release-status', (_event, status) => listener(status)),
});
