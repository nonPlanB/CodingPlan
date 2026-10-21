# CodingPlanWidget

CodingPlanWidget 是一个 Windows 桌面悬浮工具，用于集中查看：

- Codex 的 5 小时、每周剩余额度和重置时间；
- Kimi Coding Plan 的 5 小时、每周剩余额度和重置时间；
- DeepSeek API 余额和今日消费估算；

界面采用额度卡片和进度条，支持深浅主题、数据源显示选择、后台刷新、手动刷新、窗口折叠、置顶、拖动和系统托盘。可通过设置窗口配置服务参数、界面和刷新策略。系统托盘可用时，关闭窗口会隐藏到托盘，需从托盘菜单选择 `Exit` 才会彻底退出；托盘不可用时，关闭窗口退出程序。

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
   ├─ widget.py             PySide6 悬浮窗和托盘
   └─ settings.py           界面与数据源设置窗口
```

运行后按需创建以下文件；DeepSeek 每日快照在该服务首次成功刷新后生成：

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
- 使用 Kimi 或 DeepSeek 时，需要对应 API Key；

## 安装

在项目根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

无需激活虚拟环境，后续直接使用 `.venv` 中的 Python 即可。

## 配置

数据源是否启用、显示哪些卡片，以当前 `config.yaml` 为准。可在“设置 → 模型 / 数据源”中分别调整显示和采集开关。仅使用 Codex OAuth 时无需创建 `.env`。使用 Kimi 或 DeepSeek 时，可复制环境变量模板，也可以直接使用系统环境变量：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```env
KIMI_API_KEY=your_kimi_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
```

只填写实际使用的服务。Kimi 也支持 `KIMI_CODING_API_KEY`，与 `KIMI_API_KEY` 任意一个存在即可。修改凭据后重新启动程序。不要提交或分享 `.env`。

Codex 不需要写入 `.env`，它使用本机 Codex CLI 的 ChatGPT OAuth 登录状态：

```powershell
codex login
```

不使用的 Provider 可在设置中取消“启用数据采集”，或在 `config.yaml` 中关闭：

```yaml
kimi:
  enabled: false

deepseek:
  enabled: false
```

常用配置示例（实际值以当前 `config.yaml` 为准；设置窗口会保存到此文件）：

```yaml
app:
  refresh_interval_seconds: 180

ui:
  title: "Coding Energy"
  theme: "dark"
  visible_providers: [codex, kimi, deepseek]
  always_on_top: true
  opacity: 0.92
  width: 360
  expanded_height: 360
  show_reset_times: true

provider:
  timeout_seconds: 15
```

DeepSeek 的 `preferred_currency` 为空时使用接口返回的第一个币种，也可以填写 `CNY` 或 `USD`。设置窗口中，宽度范围为 320–640 px，展开最小高度为 240–900 px，透明度为 0.4–1.0，刷新间隔为 30–86400 秒，采集超时为 1–120 秒。

## 界面与设置

点击窗口右上角“设置”，或从右键菜单、托盘菜单进入。设置保存到项目目录的 `config.yaml`，保存后立即生效；取消不会写入文件。写入失败时显示错误并保留原配置。

- **模型 / 数据源**：Codex、Kimi、DeepSeek 各自具有“在界面显示”和“启用数据采集”开关。前者控制卡片、折叠摘要和额度表情，后者控制采集；隐藏卡片并不会关闭后台采集。这里配置的是服务额度来源，不是对话模型名称。
- **服务参数**：Codex 采集模式与自定义 JSON 命令、Kimi 采集命令、DeepSeek HTTPS 余额接口与首选币种。Codex 沿用原有规则：非空自定义命令优先于 OAuth；切回 OAuth 时清空自定义命令。
- **界面与刷新**：标题、深浅主题、宽度、展开最小高度、透明度、置顶、折叠、重置时间、刷新间隔和采集超时。展开高度会随卡片及错误提示自动增大，避免裁切内容。
- **凭据**：Kimi/DeepSeek 的 Key 继续放在 `.env` 或环境变量中，不写入界面配置。配置环境变量或修改 `.env` 后重新启动程序。

刷新过程中保存设置时，当前请求先结束，再自动按新设置刷新一次。

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
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "main.py", "widget" -WorkingDirectory $PWD.Path -WindowStyle Hidden
```

如需桌面快捷方式，可在 Windows 的“新建快捷方式”中设置：

```powershell
powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '项目位置\.venv\Scripts\python.exe' -ArgumentList 'main.py','widget' -WorkingDirectory '项目位置' -WindowStyle Hidden"
```

需要你在 Windows 桌面手动创建：

1. 桌面空白处右键 → **新建 → 快捷方式**。
2. 在“请输入对象的位置”中粘贴上面完整的命令。
3. 点击“下一步”，名称填写 `Coding Plan`，然后点击“完成”。

创建后，右键该快捷方式 → **属性**，将“起始位置”设为：

```
项目位置，例如E:\code\GitHub\CodingPlan
```

之后双击桌面的 `Coding Plan` 即可启动悬浮窗。

## 命令说明

```powershell
# 检查 Python、依赖、已启用服务的凭据或命令，以及缓存目录写入权限
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

## doctor 警告的根因与处理

在本项目当前配置（Codex 开启，Kimi/DeepSeek 关闭）下，实测触发 `[WARN]` 的是 **`doctor`**。原实现产生以下 6 条警告：

| 原警告 | 原因 | 修复后的行为 |
| --- | --- | --- |
| `.env file: missing` | 把可选配置文件当作必需文件；Codex OAuth 不依赖它 | 缺失显示 INFO，服务是否缺少凭据另行检查 |
| `KIMI_API_KEY: not set` | 无条件检查已关闭的服务 | Kimi 关闭则跳过；开启时与下一个 Key 二选一 |
| `KIMI_CODING_API_KEY: not set` | 把两个替代凭据分别当作必需项 | 任一存在即可通过 |
| `DEEPSEEK_API_KEY: not set` | 无条件检查已关闭的服务 | 仅 DeepSeek 开启时检查 |
| `DeepSeek provider: disabled` | 把用户主动禁用当作异常 | 显示 INFO，跳过该服务检查 |
| `DeepSeek daily snapshot: missing` | 把首次成功采集才生成的文件当作启动前置条件 | 显示 INFO，首次成功刷新后自动生成 |

这些是应用自己输出的诊断标记，不是 Python 的运行时 Warning。`doctor` 仍保留真正的问题提示，不通过关闭 warnings 或忽略异常来掩盖问题。它仅检查本地环境，登录文件存在不能保证凭据尚未过期或网络可达；运行 `refresh` 才会验证在线采集。

处理步骤：

1. 仅使用 Codex 时，保持其他服务禁用即可，不需要为了消除提示创建空 `.env` 或快照文件。
2. 如需 Kimi，在设置中开启采集，在 `.env` 或环境变量中设置 `KIMI_API_KEY` 或 `KIMI_CODING_API_KEY` 任意一个，并确保当前 Python 环境已安装 `kimi-code-usage`，或填写可用的自定义采集命令。
3. 如需 DeepSeek，开启采集并设置 `DEEPSEEK_API_KEY`。成功刷新后自动创建每日快照，无需手工创建。
4. 依次运行下列命令。`doctor` 负责诊断，`refresh` 联网更新缓存，`status` 仅读缓存。网络或会话故障会在后两者的 Provider 状态里显示，需根据具体错误继续排查。

```powershell
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py refresh
.\.venv\Scripts\python.exe main.py status
```

本项目安装说明使用 `.venv`。请使用 `.\.venv\Scripts\python.exe`；`..venv\Scripts\python.exe` 指向不同目录，可能报找不到命令，该路径错误与上述 `[WARN]` 无关。

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

发布或移动整个 `dist\CodingPlanWidget` 目录，不要只复制 EXE。使用 Kimi 或 DeepSeek 时，可在该目录中把 `.env.example` 复制为 `.env` 并填写自己的 Key；仅使用 Codex OAuth 时无需创建 `.env`。设置窗口将配置保存到 EXE 同目录的 `config.yaml`。

## 安全说明

- `.env`、`data/` 和 Codex `auth.json` 不应提交或分享；
- 程序不会在缓存中保存 API Key 或 Codex Token；
- 错误信息和缓存写入前会进行敏感信息脱敏；
- DeepSeek 今日消费是根据余额变化计算的本地估算，充值、退款或赠送余额可能影响准确性。
