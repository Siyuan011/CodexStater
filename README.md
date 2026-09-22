# Codex Stater

本机 Codex 用量面板及每小时后台采样。Python 3.9+，仅标准库，不发起模型对话。

## 一键运行

Windows 双击根目录 `run.cmd`：自动安装或恢复每小时巡检，立即触发一次后台采样，然后打开用量面板。重复运行复用相同配置的计划任务，不重置其下次时间，也不重复启动面板。采样异步完成，页面随后显示新数据。若之前暂停了巡检，运行此入口会恢复巡检。

Linux/macOS 执行 `bash run.sh`，自动安装用户级定时任务并打开面板。`bash run.sh --check` 只检查路径，`bash run.sh --no-browser` 不打开浏览器。Bash 不支持 Windows/Git Bash；Windows 继续使用 CMD。Linux 需要 systemd 用户服务，macOS 需要图形登录会话。

根目录保留 `run.cmd` 和 `run.sh` 两种入口；分功能入口放在 `scripts_cmd/`、`scripts_bash/`，名称全部为英文。脚本从任意工作目录启动均可。

## 分功能入口（Windows）

- `scripts_cmd/open-dashboard.cmd`：自动寻找 Python 和 .codex，创建配置并打开面板。
- `scripts_cmd/stop-dashboard.cmd`：关闭面板服务。
- `scripts_cmd/export-report.cmd`：将可交互 HTML 保存到 exports 并打开。
- `scripts_cmd/install-monitor.cmd`：安装当前用户的计划任务，默认每小时采样一次。
- `scripts_cmd/monitor-status.cmd`：显示最近结果、下次时间和采样状态。
- `scripts_cmd/pause-monitor.cmd` / `scripts_cmd/resume-monitor.cmd`：控制定时采样。
- `scripts_cmd/uninstall-monitor.cmd`：移除计划任务，保留数据。

首次可直接双击入口，无需输入命令。电脑需要已安装 Python 3.9+（可复用 Codex 的 Python）。正常后台采样没有窗口；入口出错会显示信息并停留。

## 目录

`src/dashboard` 面板与网页；`src/statistics` 日志解析和统计；`src/monitor` 额度采样及计划任务；`src/launcher` 启动器；`src/settings.py` 共用配置。

`config` 配置；`data` 历史记录及账号标注；`logs` 运行状态；`cache` 增量数据库；`exports` 导出报告；`docs` 使用说明；`tests` 测试。

面板支持 24 小时、7 天、自定义日期，逐小时分对话明细，模型与推理强度筛选，以及账号时段标注。

Bash 分功能脚本与 CMD 一一对应，例如 `bash scripts_bash/monitor-status.sh`。Linux 使用 systemd timer，macOS 使用 launchd LaunchAgent。**Linux/macOS 仅完成代码及静态检查，未进行实机运行或调度验证。** 详见 [Bash 使用说明](docs/BASH.md)。

详见 [使用说明](docs/使用说明.md) 和 [后台巡检说明](docs/本地后台巡检说明.md)。

## 开发验证

```shell
python -m unittest discover -s tests -v
node tests/test_logic.cjs
```

Node.js 仅测试需要。个人配置、采样历史、日志、缓存、导出文件不提交 Git。分享前勿强制加入这些数据。
