# CodingPlanWidget

CodingPlanWidget 是一个 Windows 桌面悬浮工具，用于集中查看：

- Codex 的 5 小时、每周剩余额度和重置时间；
- Kimi Coding Plan 的 5 小时、每周剩余额度和重置时间；
- DeepSeek API 余额和今日消费估算；
- AICodeMirror 账户的按量付费余额（人民币，最多三位小数）；

界面紧凑卡片布局，采用品牌图标、状态标签、右对齐剩余额度、进度条和独立重置时间，支持深浅主题、数据源显示选择、后台刷新、手动刷新、窗口折叠、置顶和拖动。主窗口和任务栏组件共用中文右键菜单，设置窗口提供中文选项及保存、取消操作。可通过设置窗口配置服务参数、界面和刷新策略。任务栏环形组件可见时，关闭主窗口会隐藏，需从右键菜单选择“退出程序”才会彻底退出；环形组件不可见时，关闭窗口退出程序。不再创建重复的系统托盘图标。

运行时不显示普通任务栏按钮、数字图标或窗口缩略图。点击右上角 `—` 或右键菜单中的“隐藏主窗口”可收起主界面，后台继续刷新，任务栏环形组件保持显示。点击环形组件，或在组件右键菜单选择“显示主窗口”可恢复主界面。鼠标悬停在组件上可查看各服务的剩余量、5 小时及每周重置时间、缓存更新时间和同步状态；缺失时间显示 `--`，DeepSeek 显示余额，重置时间标为不适用。

Windows 下还会在主任务栏的系统托盘左侧直接显示同心圆额度组件，无需悬停，主窗口最小化后仍显示。组件背景透明，深浅主题均不绘制固定底色。每个服务的中心为品牌图标，中环为每周剩余额度（蓝色），最外环为 5H 剩余额度（绿色），均从十二点方向顺时针绘制。剩余额度低于 30% 时转橙色，低于 15% 时转红色；过期数据变灰，未知数据只显示底轨，0% 不绘制进度。DeepSeek 没有周/5H限额，因此显示品牌图标和空底轨，精确余额保留在主界面和提示中，不虚构百分比。

点击环形组件恢复主窗口，左右拖动可调整位置并记住偏移；任务栏自动隐藏或同屏应用全屏时，组件跟随隐藏。组件按任务栏高度及 DPI 缩放，覆盖在任务栏上，不会让系统自动为它腾出空间；如与应用按钮重叠，可拖动至空白处。目前仅支持主屏的横向任务栏，竖向任务栏或无法定位系统托盘时不显示。

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
   ├─ widget.py             PySide6 悬浮窗和共享菜单
   ├─ taskbar.py            透明任务栏环形组件和悬浮提示
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

点击窗口右上角“设置”，或从主窗口、任务栏环形组件的右键菜单进入。设置保存到项目目录的 `config.yaml`，保存后立即生效；取消不会写入文件。写入失败时显示错误并保留原配置。

- **模型 / 数据源**：每个服务具有“在界面显示”“启用数据采集”和“在任务栏显示”开关。主界面显示控制卡片和折叠摘要，任务栏显示独立控制环形图标及其悬浮提示，仅启用采集的数据源可在任务栏显示。隐藏任一处显示不会关闭后台采集。
- `ui.taskbar_providers` 保存任务栏选择（如 `[codex]`）；空列表隐藏全部任务栏图标。旧配置未设置此项时沿用主界面选择，保存设置后独立记忆。AICodeMirror 卡片及任务栏使用随程序打包的 ICO 图标。
- **服务参数**：Codex 采集模式与自定义 JSON 命令、Kimi 采集命令、DeepSeek HTTPS 余额接口与首选币种。Codex 沿用原有规则：非空自定义命令优先于 OAuth；切回 OAuth 时清空自定义命令。
- **界面与刷新**：标题、深浅主题、宽度、展开最小高度、透明度、置顶、折叠、重置时间、刷新间隔和采集超时。展开高度会随卡片及错误提示自动增大，避免裁切内容。
- **凭据**：Kimi/DeepSeek 的 Key 继续放在 `.env` 或环境变量中，不写入界面配置。配置环境变量或修改 `.env` 后重新启动程序。

刷新过程中保存设置时，当前请求先结束，再自动按新设置刷新一次。

## 启动

### AICodeMirror 登录与余额

在“设置 → 模型 / 数据源 → AICodeMirror”点击“登录 / 重新登录 AICodeMirror”，
在独立窗口的官方网页中亲自登录，然后点击“保存并关闭”。登录成功会勾选显示和采集，
保存设置后自动刷新。也可以单独打开首次登录窗口：

```powershell
.\.venv\Scripts\python.exe main.py aicodemirror-browser --browser-mode login
```

程序使用 PySide6 自带的 Qt WebEngine，无需安装浏览器驱动或扩展。每次查询创建独立的
内存浏览器，恢复本站 Cookie，通过网站现有 `/api/auth/session` 处理会话，再只读查询
`/api/wallet`。仅使用 `data.bonusBalance`（整数厘，1000 厘 = 1 元）作为按量余额；
不会把订阅余额、API Key 限额合并进去，也不会调用模型或产生模型用量。
卡片、折叠摘要、任务栏提示和 `status` 均支持该数据源，无周/5H 百分比。

登录窗口不保存密码。浏览器缓存和页面存储仅存在内存中，只有本站安全 Cookie 使用
Windows 当前用户的 DPAPI 加密后写入 `data/aicodemirror.session.dpapi`，临时文件也只含密文。
会话不能直接复制给另一 Windows 用户使用；同一 Windows 用户下运行的其他程序仍可能解密，
因此请把整个 `data/` 当作私有数据，不要分享。登录窗口不会保存 Google/GitHub Cookie，
第三方登录是否允许嵌入浏览器由对应平台决定；遇到限制可使用官网的账号密码登录。
不关闭 Chromium 安全沙箱，不绕过安全验证。登录、刷新和清除会话之间有进程锁，避免互相覆盖。

2026-10-26 在真实账户上验证了：持久认证 Cookie、全新进程恢复后成功读取余额，以及
访问会话端点后认证 Cookie 和到期时间更新。网站当时返回约 30 天的滚动到期时间。
这说明当时有效会话可以续期，不保证以后永不过期；长时间不运行、退出官网、撤销会话、
修改密码或网站策略变化，都可能要求重新登录。`sessionInfo` 只记录恢复/续期验证结果和到期
时间，不保存 Cookie 值。缺少登录时会提示登录；网站安全验证与网络失败不会直接视为会话失效。

刷新失败保留上次余额并标记过期，卡片同时显示真正的上次成功时间。浏览器查询超时独立设置，
默认 45 秒；自动刷新沿用全局刷新间隔。点击“退出并清除本地登录”会删除本机加密会话及该服务的
余额缓存，立即生效；这不会撤销网站端会话，如需撤销请到官网操作。

```yaml
aicodemirror:
  enabled: true
  browser_timeout_seconds: 45
```

添加 `aicodemirror` 到 `ui.visible_providers` 控制卡片显示。会话文件不存在时不会发起查询。

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

# 启动悬浮窗和任务栏环形组件
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
