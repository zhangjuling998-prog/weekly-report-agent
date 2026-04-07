'use strict'

delete process.env.ELECTRON_RUN_AS_NODE

const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron')
const path = require('path')
const fs = require('fs')
const net = require('net')
const { spawn } = require('child_process')
const os = require('os')

// ── 日志 ──────────────────────────────────────────────────────────────────────
const logFile = path.join(os.homedir(), '.weekly-report', 'app.log')
fs.mkdirSync(path.dirname(logFile), { recursive: true })

function log(...args) {
  const line = `[${new Date().toISOString()}] ${args.join(' ')}`
  console.log(line)
  try { fs.appendFileSync(logFile, line + '\n') } catch {}
}

// ── 打包检测 ──────────────────────────────────────────────────────────────────
function isPkg() { return app.isPackaged }

// ── 获取 Python 路径 ──────────────────────────────────────────────────────────
function getPythonBin() {
  if (isPkg()) {
    const winBin  = path.join(process.resourcesPath, 'python', 'python.exe')
    const unixBin = path.join(process.resourcesPath, 'python', 'bin', 'python3')
    const bundled = process.platform === 'win32' ? winBin : unixBin
    if (fs.existsSync(bundled)) {
      log(`[python] using bundled: ${bundled}`)
      return bundled
    }
    log('[python] bundled not found, falling back to system')
  }
  // dev 模式：优先用项目 venv
  const venvPy = path.join(__dirname, '..', '..', 'venv', 'bin', 'python3')
  if (fs.existsSync(venvPy)) return venvPy

  const candidates = process.platform === 'win32'
    ? ['python', 'python3']
    : ['/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3', 'python3']
  for (const p of candidates) {
    if (p.startsWith('/') && !fs.existsSync(p)) continue
    return p
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

// ── 获取 Streamlit 脚本路径 ───────────────────────────────────────────────────
function getAppScript() {
  if (isPkg()) {
    return path.join(process.resourcesPath, 'app', 'app.py')
  }
  return path.join(__dirname, '..', '..', 'src', 'app.py')
}

// ── 读取配置（API Key 等） ────────────────────────────────────────────────────
const configDir  = path.join(os.homedir(), '.weekly-report')
const configPath = path.join(configDir, 'config.json')

function loadConfig() {
  try {
    if (fs.existsSync(configPath)) {
      return JSON.parse(fs.readFileSync(configPath, 'utf-8'))
    }
  } catch (e) {
    log('[config] read error:', e.message)
  }
  return {}
}

function saveConfig(data) {
  fs.mkdirSync(configDir, { recursive: true })
  const current = loadConfig()
  const merged  = { ...current, ...data }
  fs.writeFileSync(configPath, JSON.stringify(merged, null, 2), 'utf-8')
  log('[config] saved')
}

// ── 找空闲端口 ────────────────────────────────────────────────────────────────
function findFreePort(preferred = 18570) {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.listen(preferred, '127.0.0.1', () => {
      const port = server.address().port
      server.close(() => resolve(port))
    })
    server.on('error', () => {
      const s2 = net.createServer()
      s2.listen(0, '127.0.0.1', () => {
        const p = s2.address().port
        s2.close(() => resolve(p))
      })
    })
  })
}

// ── 等待端口就绪 ──────────────────────────────────────────────────────────────
function waitForPort(port, retries = 40, delay = 800) {
  return new Promise((resolve, reject) => {
    let tried = 0
    const attempt = () => {
      const sock = net.createConnection({ host: '127.0.0.1', port }, () => {
        sock.destroy()
        resolve()
      })
      sock.on('error', () => {
        if (++tried >= retries) return reject(new Error(`port ${port} not ready`))
        setTimeout(attempt, delay)
      })
    }
    attempt()
  })
}

// ── 全局状态 ──────────────────────────────────────────────────────────────────
let mainWindow     = null
let splashWindow   = null
let streamlitProc  = null
let streamlitPort  = null
let streamlitReady = false

// ── 启动 Streamlit ────────────────────────────────────────────────────────────
async function startStreamlit() {
  const port   = await findFreePort(18570)
  streamlitPort = port
  const python = getPythonBin()
  const script = getAppScript()
  const cfg    = loadConfig()

  log(`[streamlit] python=${python}`)
  log(`[streamlit] script=${script}`)
  log(`[streamlit] port=${port}`)

  const env = {
    ...process.env,
    ANTHROPIC_API_KEY:   cfg.apiKey    || '',
    OPENROUTER_BASE_URL: cfg.baseUrl   || 'https://semir.onerouter.com/api',
    WEEKLY_REPORT_MODEL: cfg.model     || 'claude-sonnet-4-6',
    STREAMLIT_SERVER_PORT:       String(port),
    STREAMLIT_SERVER_HEADLESS:   'true',
    STREAMLIT_SERVER_ENABLE_CORS: 'false',
    STREAMLIT_BROWSER_GATHER_USAGE_STATS: 'false',
    STREAMLIT_THEME_BASE:        'light',
  }

  // Windows 需要设置 Python 搜索路径
  if (isPkg() && process.platform === 'win32') {
    const pyDir = path.join(process.resourcesPath, 'python')
    env.PATH = `${pyDir};${pyDir}\\Scripts;${process.env.PATH || ''}`
    env.PYTHONHOME = pyDir
    env.PYTHONPATH = path.join(process.resourcesPath, 'app')
  } else if (isPkg()) {
    const pyDir = path.join(process.resourcesPath, 'python')
    env.PATH    = `${pyDir}/bin:${process.env.PATH || ''}`
    env.PYTHONHOME = pyDir
    env.PYTHONPATH = path.join(process.resourcesPath, 'app')
  }

  streamlitProc = spawn(python, [
    '-m', 'streamlit', 'run', script,
    '--server.port', String(port),
    '--server.headless', 'true',
    '--server.enableCORS', 'false',
    '--browser.gatherUsageStats', 'false',
    '--theme.base', 'light',
  ], { env, stdio: ['ignore', 'pipe', 'pipe'] })

  streamlitProc.stdout.on('data', d => log('[st]', d.toString().trim()))
  streamlitProc.stderr.on('data', d => log('[st:err]', d.toString().trim()))
  streamlitProc.on('close', code => {
    log(`[streamlit] exited with code ${code}`)
    streamlitReady = false
  })

  // 等待就绪
  await waitForPort(port, 60, 700)
  streamlitReady = true
  log(`[streamlit] ready on port ${port}`)
}

// ── 创建 Splash 窗口 ──────────────────────────────────────────────────────────
function createSplash() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 300,
    frame: false,
    transparent: false,
    alwaysOnTop: true,
    resizable: false,
    backgroundColor: '#F5F5F7',
    webPreferences: { contextIsolation: true },
  })
  splashWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(splashHTML())}`)
}

function splashHTML() {
  return `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: -apple-system, 'PingFang SC', sans-serif;
    background: #F5F5F7;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    height: 100vh; color: #1D1D1F;
    -webkit-app-region: drag;
  }
  .icon { font-size: 56px; margin-bottom: 16px; }
  h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
  p  { font-size: 13px; color: #6E6E73; margin-bottom: 28px; }
  .spinner {
    width: 28px; height: 28px;
    border: 3px solid #D2D2D7;
    border-top-color: #007AFF;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .label { font-size: 12px; color: #AEAEB2; margin-top: 10px; }
</style></head>
<body>
  <div class="icon">📊</div>
  <h1>经营分析智能体</h1>
  <p>正在启动，请稍候…</p>
  <div class="spinner"></div>
  <div class="label">Loading Streamlit…</div>
</body></html>`
}

// ── 创建主窗口 ────────────────────────────────────────────────────────────────
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    show: false,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#F5F5F7',
    title: '经营分析智能体',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // 允许加载 localhost
      webSecurity: false,
    },
  })

  mainWindow.loadURL(`http://127.0.0.1:${streamlitPort}`)

  mainWindow.webContents.on('did-finish-load', () => {
    if (splashWindow) {
      splashWindow.close()
      splashWindow = null
    }
    mainWindow.show()
    mainWindow.focus()
  })

  // 外部链接在系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.on('closed', () => { mainWindow = null })
}

// ── IPC Handlers ──────────────────────────────────────────────────────────────
ipcMain.handle('config:load', () => loadConfig())
ipcMain.handle('config:save', (_evt, data) => { saveConfig(data); return true })
ipcMain.handle('app:version', () => app.getVersion())
ipcMain.handle('app:restart-streamlit', async () => {
  if (streamlitProc) {
    streamlitProc.kill()
    streamlitProc = null
    streamlitReady = false
    await new Promise(r => setTimeout(r, 1000))
  }
  await startStreamlit()
  if (mainWindow) mainWindow.loadURL(`http://127.0.0.1:${streamlitPort}`)
  return true
})

// ── 设置窗口 ──────────────────────────────────────────────────────────────────
function createSettingsWindow() {
  const win = new BrowserWindow({
    width: 560,
    height: 600,
    resizable: false,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#F5F5F7',
    title: '经营分析智能体 — 设置',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  win.loadFile(path.join(__dirname, 'renderer', 'settings.html'))
  return win
}

// IPC: 打开设置窗口
ipcMain.handle('settings:open', () => {
  createSettingsWindow()
})

// ── App 启动 ──────────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  const cfg = loadConfig()

  // 没有 API Key → 先显示设置页
  if (!cfg.apiKey) {
    const settingsWin = createSettingsWindow()
    // 等待 restartStreamlit 完成后自动关闭设置页
    const originalHandler = ipcMain.listeners('app:restart-streamlit')[0]
    ipcMain.removeAllListeners('app:restart-streamlit')
    ipcMain.handle('app:restart-streamlit', async () => {
      if (streamlitProc) { streamlitProc.kill(); streamlitProc = null; streamlitReady = false }
      await startStreamlit()
      settingsWin.close()
      createMainWindow()
      return true
    })
    return
  }

  createSplash()

  try {
    await startStreamlit()
    createMainWindow()
  } catch (err) {
    log('[error] Failed to start streamlit:', err.message)
    if (splashWindow) splashWindow.close()
    dialog.showErrorBox('启动失败', `Streamlit 启动失败：\n${err.message}\n\n请查看日志：${logFile}`)
    app.quit()
    return
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow()
  })
})

app.on('window-all-closed', () => {
  if (streamlitProc) {
    streamlitProc.kill()
    streamlitProc = null
  }
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (streamlitProc) {
    streamlitProc.kill()
    streamlitProc = null
  }
})
