# Linux/macOS Bash 使用说明

本版本仅支持 Linux 和 macOS，Windows 使用 run.cmd。Bash 不再转调 PowerShell。

**验证状态：只做 Python/Bash 语法及静态检查，没有在 Linux/macOS 安装、运行或验证调度。以下步骤供验证人员使用，不表示已经实测通过。**

## 前提

- Python 3.9+，仅使用标准库。默认 python3，可通过 STATER_PYTHON 指定绝对路径。
- Codex CLI 可执行且已经登录；额度接口需要联网。通过 --codex-exe 或配置 codex_exe 指定，安装时固定绝对路径，并保存安装终端的 PATH 供后台使用。通过 Node 安装的 Codex 也需要后台能找到 node；切换 Node/Python 版本后重新安装任务。
- Linux 需要 systemd 和可访问的当前用户服务管理器，不支持 cron、容器中无 systemd 的环境或 root 系统级安装。
- macOS 需要当前用户已登录图形会话，使用 LaunchAgent，无需 sudo。

## 启动与配置

在项目根目录执行：

```bash
bash run.sh --check
bash run.sh
bash run.sh --no-browser
bash run.sh --codex-root '/path/to/.codex' --codex-exe '/path/to/codex'
bash run.sh --config '/path with spaces/stater.json'
```

--check 不安装、不启动、不创建配置；只检查路径，不验证调度器可用性或账号登录。其他入口也支持 --config；使用自定义配置时管理入口应带相同参数。相对路径以仓库根目录为基准。程序没有文件夹选择弹窗。旧 -Config、-CodexRoot、-NoBrowser、-Check、-NonInteractive 参数保留兼容。

run.sh 安装或恢复调度，异步触发一次采样，然后打开面板；首次记录可能稍后出现。默认每 60 分钟采样。配置 monitor_interval_minutes 为 5–1440 的整数，修改后重新执行安装入口。首次安装也触发一次采样；暂停后执行 run.sh 会恢复。每个用户只有一个固定名称的任务，安装另一份仓库/配置会替换其任务配置；无需同时运行多个实例。

## 管理

```bash
bash scripts_bash/install-monitor.sh
bash scripts_bash/monitor-status.sh
bash scripts_bash/pause-monitor.sh
bash scripts_bash/resume-monitor.sh
bash scripts_bash/uninstall-monitor.sh
bash scripts_bash/open-dashboard.sh
bash scripts_bash/stop-dashboard.sh
bash scripts_bash/export-report.sh --no-browser
```

停止面板不影响采样。卸载调度保留配置、历史和缓存。Linux 暂停仅停止 timer，已运行采样可完成；macOS 暂停会卸载 agent，可能终止正在执行的采样。迁移项目目录或解释器后重新安装任务。卸载前先保留项目副本，以便继续查看历史。

## 平台行为与排错

Linux 配置位于 ${XDG_CONFIG_HOME:-~/.config}/systemd/user/codex-stater-monitor.service 和 .timer。使用用户级 timer，每次启用约一分钟后首次定时触发，以后按配置间隔运行；run.sh 还会立即触发。休眠或离线时间不补造采样。注销后能否持续运行取决于用户服务/linger 配置，本工具不自动修改该配置。

```bash
systemctl --user status codex-stater-monitor.timer codex-stater-monitor.service
systemctl --user list-timers codex-stater-monitor.timer
journalctl --user -u codex-stater-monitor.service -n 50
```

macOS 配置位于 ~/Library/LaunchAgents/com.codexstater.monitor.plist，使用 StartInterval（秒）。需用户登录，睡眠/关机期间不会正常采样，恢复后的时机由 launchd 决定。没有承诺补齐错过的时间点。

```bash
launchctl print "gui/$(id -u)/com.codexstater.monitor"
plutil -lint "$HOME/Library/LaunchAgents/com.codexstater.monitor.plist"
```

两平台业务状态和错误位于 logs/local-monitor-status.json、logs/quota-errors.jsonl。macOS 标准输出和错误另存 logs/monitor-stdout.log、monitor-stderr.log；Linux 启动层错误见 journal。macOS 可能限制后台访问桌面/文稿，出现权限错误时建议将仓库及数据放到允许后台访问的位置，或由用户按系统提示授权。日志暂不自动轮转，可自行归档。

额度请求失败仍尝试本机日志采样，不以旧额度冒充新结果。不发起模型对话；本机 Token 不等于官方账单。

## 交给验证人员的检查项

1. 在各系统检查 Bash 语法、Python 版本、Codex 登录和自定义路径（含空格/中文）。
2. 用测试数据目录安装，检查即时采样、下一次定时触发及日志。
3. 重复运行、暂停、恢复、卸载，确认只有一个任务且数据保留。
4. 检查额度获取失败时仍采集本机用量，休眠恢复和重新登录后的行为。
5. 确认面板启动、停止、HTML 导出及重定位后重新安装可用。

```bash
for file in run.sh scripts_bash/*.sh src/launcher/*.sh; do bash -n "$file" || exit; done
python3 -m compileall -q src
```
