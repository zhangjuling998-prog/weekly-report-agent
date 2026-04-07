'use strict'
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  loadConfig:       ()       => ipcRenderer.invoke('config:load'),
  saveConfig:       (data)   => ipcRenderer.invoke('config:save', data),
  getVersion:       ()       => ipcRenderer.invoke('app:version'),
  restartStreamlit: ()       => ipcRenderer.invoke('app:restart-streamlit'),
})
