# DeepSeek 用量监控

一个本地桌面小工具，实时查看 DeepSeek API 的消费与用量数据。

## 功能特性

- **完整模式**：卡片式展示 30 天消费 / 余额 / 今日消费 / 今日缓存率 + 每个 API Key×模型 的明细表格（消费、请求次数、Tokens、缓存率）
- **表格排序**：点击任意列表头排序，支持升/降序切换（▲/▼），刷新后保留
- **迷你模式**：置顶小条显示今日消费 / 余额 / 缓存率 / 时间，可拖动，可吸附屏幕边缘
- **模式切换**：完整 ⇄ 迷你一键切换，两种模式位置独立记忆，互不干扰
- **窗口置顶**：可手动开关（全屏看电影/游戏时关闭）
- **自动刷新**：每 10 分钟自动更新，也可手动刷新
- **自动登录态**：token 本地保存，失效时自动从浏览器登录态恢复，开箱即用
- **单实例运行**：不会重复打开多个窗口

## 环境要求

- Windows
- Python 3.8+（仅使用标准库，无第三方依赖）

## 使用方法

```bash
pythonw ds_gui.py
```

或直接双击 `启动用量监控.bat`。

首次运行会检查登录态：如检测到缺失，会自动打开 DeepSeek 网页引导登录，之后即可免登录使用。

## 配置文件

| 文件 | 说明 |
|---|---|
| `config.json` | 运行态配置（含 API token），**已被 .gitignore 排除，不会提交** |
| `config.example.json` | 配置格式模板，克隆仓库后复制为 `config.json` 并填入 token 即可 |

```bash
copy config.example.json config.json
```

## 目录结构

```
DeepSeekTool/
├── ds_gui.py            # 界面（tkinter）
├── ds_api.py            # DeepSeek API 请求封装
├── deepseek.ico         # 窗口/任务栏图标
├── deepseek_mini.png    # 迷你条图标
├── 启动用量监控.bat      # 一键启动
├── config.json          # 运行态配置（不入库）
└── config.example.json  # 配置模板
```

## 隐私说明

- token 仅保存在本地 `config.json`，数据请求直接发往 DeepSeek 官方接口，**无任何第三方服务器中转**
- 仓库中不含任何真实 token
