# CodingPlanWidget

CodingPlanWidget 是一个 Windows 桌面悬浮工具，用于集中查看：

- Codex 的 5 小时、每周剩余额度和重置时间；
- Kimi Coding Plan 的 5 小时、每周剩余额度和重置时间；
- DeepSeek API 余额和今日消费估算。

程序支持后台刷新、手动刷新、窗口折叠、置顶、拖动和系统托盘。关闭窗口只会隐藏到托盘，需从托盘菜单选择 `Exit` 才会彻底退出。

## 工程结构

```text
CodingPlan/
├─ main.py                  命令行和源码启动入口
├─ app_launcher.py          PyInstaller 图形界面入口
├─ config.yaml              刷新、界面和 Provider 配置
├─ .env.example             API Key 模板
├─ requirements.txt         Python 依赖
├─ CodingPlanWidget.spec    Windows EXE 打包配置
├─ assets/
│  └─ coding_plan.ico       应用图标
├─ core/                    配置、采集、缓存、脱敏和状态处理
├─ providers/               Codex、Kimi、DeepSeek 数据源
└─ ui/
   └─ widget.py             PySide6 悬浮窗和托盘
```

运行后会自动创建：

```text
data/
├─ usage.json               最新额度缓存
├─ deepseek_daily.json      DeepSeek 当日余额快照
└─ ui_state.json            窗口位置、折叠和置顶状态
```

## 环境要求

- Windows 10/11；
- Python 3.10 或更高版本；
- 使用 Codex 时，需要已安装并登录 Codex CLI；
- 使用 Kimi 或 DeepSeek 时，需要对应 API Key。

## 安装

在项目根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

无需激活虚拟环境，后续直接使用 `.venv` 中的 Python 即可。

## 配置

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```env
KIMI_API_KEY=your_kimi_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
```

只填写实际使用的服务。不要提交或分享 `.env`。

Codex 不需要写入 `.env`，它使用本机 Codex CLI 的 ChatGPT OAuth 登录状态：

```powershell
codex login
```

不使用的 Provider 可以在 `config.yaml` 中关闭：

```yaml
kimi:
  enabled: false

deepseek:
  enabled: false
```

常用配置：

```yaml
app:
  refresh_interval_seconds: 180

ui:
  always_on_top: true
  opacity: 0.92
  width: 280
  expanded_height: 300
  show_reset_times: true

provider:
  timeout_seconds: 15
```

DeepSeek 的 `preferred_currency` 为空时使用接口返回的第一个币种，也可以填写 `CNY` 或 `USD`。

## 启动

首次运行建议先检查环境并刷新一次：

```powershell
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py refresh
.\.venv\Scripts\python.exe main.py status
```

启动桌面悬浮窗：

```powershell
.\.venv\Scripts\python.exe main.py widget
```

不显示命令行窗口的静默启动方式：

```powershell
Start-Process .\.venv\Scripts\pythonw.exe -ArgumentList "main.py", "widget" -WorkingDirectory $PWD
```

如需桌面快捷方式，可在 Windows 的“新建快捷方式”中设置：

```text
目标："<项目目录>\.venv\Scripts\pythonw.exe" "<项目目录>\main.py" widget
起始位置：<项目目录>
```

## 命令说明

```powershell
# 检查 Python、依赖、API Key、Codex 登录和目录权限
.\.venv\Scripts\python.exe main.py doctor

# 在线采集所有已启用 Provider，并更新 data/usage.json
.\.venv\Scripts\python.exe main.py refresh

# 只读取本地缓存，不访问网络
.\.venv\Scripts\python.exe main.py status

# 启动悬浮窗和系统托盘
.\.venv\Scripts\python.exe main.py widget
```

## 调试与排错

调试时使用 `python.exe` 启动，不要使用 `pythonw.exe`，这样可以在终端中看到错误：

```powershell
.\.venv\Scripts\python.exe main.py widget
```

推荐排查顺序：

1. 运行 `doctor`，检查依赖、Key 和登录状态。
2. 运行 `refresh`，查看具体 Provider 的错误。
3. 运行 `status`，确认缓存是否成功写入。
4. 最后启动 `widget`。

常见状态：

- `unsupported`：Provider 未配置、未登录或被禁用；
- `offline`：网络、代理、SSL 或超时问题；
- `error`：接口返回或数据解析失败；
- `stale`：本次刷新失败，界面保留了上一次成功值。

重置本地状态：

```powershell
# 重置窗口位置和折叠状态
Remove-Item .\data\ui_state.json -ErrorAction SilentlyContinue

# 重置 DeepSeek 今日消费估算
Remove-Item .\data\deepseek_daily.json -ErrorAction SilentlyContinue

# 清空额度缓存
Remove-Item .\data\usage.json -ErrorAction SilentlyContinue
```

## 打包 Windows EXE

安装 PyInstaller：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
```

执行打包：

```powershell
.\.venv\Scripts\python.exe -m PyInstaller CodingPlanWidget.spec
Copy-Item config.yaml dist\CodingPlanWidget\config.yaml
Copy-Item .env.example dist\CodingPlanWidget\.env.example
```

生成的程序位于：

```text
dist\CodingPlanWidget\CodingPlanWidget.exe
```

发布或移动整个 `dist\CodingPlanWidget` 目录，不要只复制 EXE。首次使用时，在该目录中把 `.env.example` 复制为 `.env` 并填写自己的 Key。

## 安全说明

- `.env`、`data/` 和 Codex `auth.json` 不应提交或分享；
- 程序不会在缓存中保存 API Key 或 Codex Token；
- 错误信息和缓存写入前会进行敏感信息脱敏；
- DeepSeek 今日消费是根据余额变化计算的本地估算，充值、退款或赠送余额可能影响准确性。
