# DeepSeek 用量监控 — AGENTS.md

## 项目概述

一个 Windows 本地桌面小工具，用 tkinter 实时查看 DeepSeek API 的消费与用量数据（余额、今日/近 30 天消费、请求数、Tokens、缓存命中率）。仅两个 Python 源码文件，**纯标准库、零第三方依赖**，无构建系统、无打包流程、无测试框架。

## 运行环境

- Windows（使用了 `ctypes.windll`、Windows Mutex、Chrome 的 Windows 路径，不可跨平台运行）
- Python 3.8+（仅用标准库：tkinter、urllib、json、threading、ctypes 等）

## 构建与运行命令

```bash
pythonw ds_gui.py          # 启动 GUI（推荐，无控制台窗口）
python ds_gui.py           # 调试时可带控制台输出
python ds_api.py           # 命令行验证 API 封装（打印余额/用量，需有效 token）
```

也可直接双击 `启动用量监控.bat`（内部即 `start "" pythonw ds_gui.py`）。

无 lint、无测试、无 CI；改动后用 `python -m py_compile ds_api.py ds_gui.py` 做最基本的语法验证，再实际启动 GUI 确认。

## 代码结构

| 文件 | 说明 |
|---|---|
| `ds_api.py` (~230 行） | DeepSeek 平台内部接口封装：`get_summary`（余额/累计消费）、`get_usage`（按 API Key×模型 汇总消费/请求/Tokens/缓存）、token 读写、从 Chrome leveldb 扫描提取登录 token。`ApiError` 为统一异常类型。 |
| `ds_gui.py` (~580 行） | 全部 UI 逻辑，单类 `UsageApp`。完整模式（卡片 + ttk.Treeview 明细表格，支持表头排序）与迷你模式（无边框置顶横条，可拖动）双模式；自动刷新（10 分钟）；线程内请求网络避免阻塞 UI；Windows Mutex 保证单实例。 |
| `config.json` | 运行态 token 存储（`token`/`user_id`/`saved_at`），**在 .gitignore 中，绝不提交**。 |
| `config.example.json` | 配置模板，克隆后复制为 `config.json`。 |
| `ds_gui_config.json` | GUI 偏好（`mini_mode`、两种模式各自的窗口位置（完整模式含窗口尺寸）、`topmost`），由程序自动读写。 |
| `usage_history.json` | 「今日快照」功能生成的本地历史记录，运行时产生。 |
| `deepseek.ico` / `deepseek_mini.png` | 窗口图标 / 迷你条图标。 |
| `images/` | README 截图。 |

## 关键实现细节与约定

- **接口是网页端内部 API**（`platform.deepseek.com/api/v0/...`），非官方公开接口，随时可能变动；响应统一为 `{code, msg, data.biz_data}` 结构，`code != 0` 即抛 `ApiError`。
- **时区按 GMT+8 天对齐**：`ds_api.py` 中 `TZ = 28800`，`_day_range`/`_today_range` 返回天对齐时间戳；`_day_range(N)` 的窗口**含今天**（end = 明天零点），故明细表/近30天卡片与「今日消费」口径衔接。
- **token 自动恢复链**：`config.json` token → 失效后扫描 Chrome Local Storage leveldb 正则提取 `userToken` → 逐个用 `get_summary` 验证 → 保存首个有效的；全部失败返回空串；GUI 侧还有引导登录轮询和手动粘贴兜底。`refresh()` 先用 config token 直接请求 `get_summary`（兼作验证，省一次请求），失效才走恢复链。
- **网络请求一律放后台线程**（`refresh()`/`snapshot()` 的 `worker`），tkinter 非线程安全，**UI 更新必须经 `root.after(0, ...)` 回主线程**（见 `_apply_data`/`_on_refresh_error`）；`refresh(manual=True)` 表示手动触发（失败弹窗），自动刷新失败只置灰不打扰；`_refreshing` 标志防并发刷新；GUI 偏好改动即时落盘到 `ds_gui_config.json`。
- **代码风格**：Python 源码与注释、UI 文案全部为中文；文件头带 `# -*- coding: utf-8 -*-`；命名用小写蛇形，私有方法加 `_` 前缀；无类型注解（仅少量函数签名有简单注解）；无 docstring 规范，注释用行内中文短语。改动请保持一致。
- 完整模式拖标题栏移动不会触发 Python 事件，位置在退出时（`_on_close`）补存——修改窗口位置逻辑时注意这一约定。

## 安全注意事项

- `config.json` 含真实 DeepSeek API token，**严禁提交**（已在 .gitignore）；`ds_gui_config.json` 与 `usage_history.json` 也不含敏感信息但目前未被 ignore，注意不要误把 token 写入这两处。
- 所有数据请求直连 DeepSeek 官方接口，无第三方中转；改动时不得引入会把 token 外发的逻辑。
- 仓库中不得出现真实 token，示例配置一律用占位符。

## 维护须知

- 改 `ds_api.py` 的数据结构时，同步检查 `ds_gui.py` 的 `refresh`/`_fill_table`/`_sort_key` 对字段的引用。
- 修改窗口/模式切换逻辑时，需同时验证：迷你⇄完整切换、位置记忆、置顶开关、多显示器工作区钳制（`_get_work_area`/`_snap_to_nearest_edge`）。
- 该项目无自动化测试，验证方式 = 启动 GUI 实际观察（需有效 DeepSeek 登录态）。
