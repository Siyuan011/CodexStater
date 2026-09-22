# Codex Stater

本机 Codex 用量面板及每小时后台采样。Python 3.9+，仅标准库，不发起模型对话。

## 双击使用（Windows）

- `打开用量面板.cmd`：自动寻找 Python 和 .codex，创建配置并打开面板。
- `停止用量面板.cmd`：关闭面板服务。
- `导出用量报告.cmd`：将可交互 HTML 保存到 exports 并打开。
- `安装后台巡检.cmd`：安装当前用户的计划任务，默认每小时采样一次。
- `查看巡检状态.cmd`：显示最近结果、下次时间和采样状态。
- `暂停后台巡检.cmd` / `恢复后台巡检.cmd`：控制定时采样。
- `卸载后台巡检.cmd`：移除计划任务，保留数据。

首次可直接双击入口，无需输入命令。电脑需要已安装 Python 3.9+（可复用 Codex 的 Python）。正常后台采样没有窗口；入口出错会显示信息并停留。

## 目录

`src/dashboard` 面板与网页；`src/statistics` 日志解析和统计；`src/monitor` 额度采样及计划任务；`src/launcher` 启动器；`src/settings.py` 共用配置。

`config` 配置；`data` 历史记录及账号标注；`logs` 运行状态；`cache` 增量数据库；`exports` 导出报告；`docs` 使用说明；`tests` 测试。

面板支持 24 小时、7 天、自定义日期，逐小时分对话明细，模型与推理强度筛选，以及账号时段标注。

详见 [使用说明](docs/使用说明.md) 和 [后台巡检说明](docs/本地后台巡检说明.md)。

## 开发验证

```shell
python -m unittest discover -s tests -v
node tests/test_logic.cjs
```

Node.js 仅测试需要。个人配置、采样历史、日志、缓存、导出文件不提交 Git。分享前勿强制加入这些数据。
