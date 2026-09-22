# Git Bash 使用说明

当前 Bash 脚本是 Windows 启动入口，与 CMD 版本共用 Python、配置、数据和 Windows 计划任务。无需安装第二套 Python，也不会创建另一套定时任务。适用 Git for Windows 提供的 Git Bash；WSL、Linux、macOS 暂不支持这套后台调度。

## 日常操作

在仓库目录打开 Git Bash：

```bash
bash run.sh
bash scripts_bash/monitor-status.sh
bash scripts_bash/pause-monitor.sh
bash scripts_bash/resume-monitor.sh
bash scripts_bash/export-report.sh
bash scripts_bash/stop-dashboard.sh
```

`run.sh` 安装或恢复定时任务、立即异步采样并打开面板。再次运行会恢复已暂停的巡检；如只想打开面板，使用 `scripts_bash/open-dashboard.sh`。停止面板不停止巡检。安装和卸载分别使用 `install-monitor.sh`、`uninstall-monitor.sh`，卸载保留历史。

支持与 CMD 相同的参数（PowerShell 拼写）：

```bash
bash run.sh -Check -NonInteractive
bash run.sh -NoBrowser -NonInteractive
bash run.sh -Config 'D:/Settings/stater.json' -CodexRoot 'D:/Profiles/.codex'
bash scripts_bash/export-report.sh -NoBrowser
```

路径含空格时必须加引号；支持 `C:/...` 和 `/c/...` 绝对路径。相对配置和数据目录以仓库根目录为基准。`STATER_PYTHON` 环境变量请使用 Windows 路径指向 `python.exe`。未设置时自动发现本机 Python 和 Codex 数据目录。

## 测试范围

Git Bash 可以测试 Bash 语法、参数转发、中文和空格路径、Python 检测、Windows 计划任务、面板启动和导出。它无法验证 Linux 的 cron/systemd 或 macOS 的 launchd；未来支持这些平台时须在对应系统实测。

```bash
for file in run.sh scripts_bash/*.sh src/launcher/*.sh; do bash -n "$file" || exit; done
bash run.sh -Check -NonInteractive
```

正常定时采样不依赖 Bash 窗口保持打开。需电脑开机且用户已登录。采样不调用模型；额度查询需联网和有效登录。
