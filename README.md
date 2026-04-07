# 经营分析智能体

> 上传周同比 Excel → AI 自动生成苹果风格经营分析周报 · 开箱即用桌面应用

## 下载安装

前往 [Releases](../../releases) 下载最新版本，**无需安装 Python / Node.js**：

| 平台 | 文件 |
|------|------|
| macOS Apple Silicon (M1/M2/M3/M4) | `*-arm64.dmg` |
| macOS Intel | `*-x64.dmg` |
| Windows 10/11 | `*Setup*.exe` |

## 快速开始

1. 安装应用并启动
2. 首次启动弹出配置界面 → 填入 API Key → 保存
3. 主界面上传 `产品周同比数据.xlsx`（包含目标周 + 前两周，共 3 个 Sheet）
4. 填写目标周数 → 点击「生成经营分析报告」
5. 约 30~60 秒后，下载 HTML 报告（浏览器打开，Ctrl+P 可另存为 PDF）

## 数据格式

Excel 文件每张 Sheet 对应一周数据，Sheet 名如 `W11`、`W12`、`W13`。  
建议上传目标周 + 前两周共 3 张 Sheet，以生成趋势对比。

## 报告结构

| 模块 | 内容 |
|------|------|
| MODULE 01 | 整体大盘（KPI + 三周趋势图 + 缺口柱状图） |
| MODULE 02 | 渠道诊断（8大渠道 + 强势/问题洞察） |
| MODULE 03 | 季节结构（五季节 + 甜甜圈 + 折线图） |
| MODULE 04 | 新老品分析 |
| MODULE 05 | 行动计划（P1~P4 优先级卡片） |

## 开发

```bash
# 克隆
git clone <repo-url>
cd weekly-report-app

# Python 依赖（首次）
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r src/requirements.txt

# Node 依赖
cd electron-app && npm install && cd ..

# 开发模式启动（先启动 Streamlit，再启动 Electron）
# 终端 1:
ANTHROPIC_API_KEY=sk-xxx python3 -m streamlit run src/app.py --server.port 18570

# 终端 2:
cd electron-app && npm start
```

## 架构

```
weekly-report-app/
├── src/
│   ├── app.py            # Streamlit 应用（UI + AI 调用）
│   └── requirements.txt  # Python 依赖
├── electron-app/
│   ├── src/
│   │   ├── main.js       # Electron 主进程（启动 Streamlit + 窗口管理）
│   │   ├── preload.js    # IPC bridge
│   │   └── renderer/
│   │       └── settings.html  # 可视化配置界面（API Key / Base URL / 模型）
│   ├── assets/           # 图标资源
│   ├── build.yml         # electron-builder 配置
│   └── package.json
└── .github/workflows/
    └── build-release.yml # 自动打包 macOS DMG + Windows EXE
```

## macOS 签名提示

未签名 App 会被 Gatekeeper 拦截，在终端执行：

```bash
xattr -cr "/Applications/经营分析智能体.app"
```

## License

MIT
