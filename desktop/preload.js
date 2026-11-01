// Minimal bridge for the "Set overlay link" window. The overlay page itself does not use it.
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("coachLink", {
  get: () => ipcRenderer.invoke("link:get"),
  set: (url) => ipcRenderer.invoke("link:set", url),
});
