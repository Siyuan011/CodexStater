# Codex Stater

在本机查看 Codex 对话用量的动态面板。Python 3.9+，运行时仅使用标准库，不调用模型。可选的 Windows 后台采样程序通过账号接口读取剩余额度。

## 功能

- 打开页面读取最新日志；页面可见时每 60 秒增量刷新。
- 切换过去 24 小时、过去 7 天或自定义开始/结束日期与时间，按事件时间汇总；自定义单次最多 366 天。
- 每小时柱形固定每格 2.5M Token，最低 10M 四格；用量较高时图表自动增高。悬停查看前 8 个对话，点击展开完整明细。
- 支持手工标记账号切换时间，按全部账号、指定账号或未知账号筛选；同一对话跨账号使用可按事件时间拆分。
- 按模型、推理强度或对话筛选，支持排除指定统计任务与内部审批检查。
- 对话排行默认显示前 5 条，其余可展开、收起。
- 排行下方以环形图展示“模型 × 推理强度”的用量占比，并对照各项 Token；同一对话切换档位分别归属。
- 可叠加账号额度采样历史；支持安装本地每小时后台采样，无需模型巡检。
- 导出可离线交互的 HTML，保留 24 小时、7 天及已查询的自定义范围与筛选状态。

## 快速开始

Windows 双击 `打开用量面板.cmd` 即可。首次运行会自动从示例创建本机 `config.json`，查找可用的 Python 3.9+ 和当前用户的 `.codex`，然后打开动态面板。无需手动复制配置或填写电脑用户名；如果没有找到数据目录，会弹出文件夹选择窗口，选择后会记住该位置。

启动器优先使用配置中有效的 `codex_root`，其次是 `CODEX_HOME`，最后是当前用户主目录下的 `.codex`。旧电脑留下的无效路径会提示并自动尝试后续位置，不会扫描整块硬盘。Python 会从 `STATER_PYTHON`、`py`、`python`、`python3` 和 Codex 已有的运行环境中查找；若均不可用，需先安装 Python 3.9+。

双击 `导出最新HTML.cmd` 可生成并打开 `最新用量报告.html`；双击 `停止服务.cmd` 可停止面板。

macOS/Linux 或直接使用 Python 命令时，先安装 Python 3.9+，将 `config.example.json` 复制为 `config.json`，再按需填写 `codex_root`（留空使用 `CODEX_HOME` 或 `~/.codex`）：

```shell
python app.py launch
```

默认打开 `http://127.0.0.1:8766`。macOS/Linux 可使用 `python3 app.py launch`。本地服务只监听回环地址。

停止服务：`python app.py stop`。导出报告：`python app.py export --output report.html`。

路径、端口、刷新间隔、时区与额度历史目录均可配置。详细步骤、故障排查、统计口径见 [使用说明](使用说明.md)。

## 每小时后台采样（Windows）

采样由 Python 编写，Windows 任务计划每小时启动一次，完成后退出，不产生模型推理 Token。首次安装：

```powershell
./manage-local-monitor.ps1 -Action Install
```

默认寻找 Codex 附带的 Python；其他 Python 可通过 `-PythonPath` 指定，`.codex` 目录通过 `-CodexRoot` 指定。数据保存在脚本所在目录。在面板 `config.json` 中设置 `"quota_dir": "."`，重启面板后即可显示本仓库采集的额度。

首次本机采样建立基线，之后记录新增用量；面板仍可独立读取历史会话日志。安装前请停用原有 Codex 自动巡检，避免继续产生模型开销。同名 Windows 任务会被重新注册到当前目录。

完整安装、配置、迁移和排错步骤见 [本地后台巡检说明](本地后台巡检说明.md)。

## 数据边界

本机 Token 由日志计数，不能直接换算成订阅额度或费用。面板本身只读取 `quota-history.jsonl`；可选后台采样程序通过 `account/rateLimits/read` 查询额度，需要联网和有效登录态。

对话显示名称、项目目录名与计数可能出现在导出 HTML 中。仓库忽略个人 `config.json`、运行缓存、数据库、日志和根目录导出的 HTML；请勿强制提交这些个人文件。

## 开发验证

```shell
python -m unittest discover -s tests -v
node tests/test_logic.cjs
```

Node.js 仅用于前端聚合逻辑测试，正常运行无需 Node.js。服务测试使用临时数据目录和独立回环端口。

## 推送到 GitLab

在 GitLab 创建一个空仓库（不预先添加 README、License 或 .gitignore），然后在本目录运行：

```shell
git remote add origin <你的GitLab仓库地址>
git push -u origin main
git push origin v0.1.0
```

若在另一台电脑使用 Git bundle 转移：

```shell
git clone codex-stater-v0.1.0.bundle codex-stater
cd codex-stater
git remote set-url origin <你的GitLab仓库地址>
git push -u origin main
git push origin v0.1.0
```

bundle 包含 Git 历史和版本标签，不包含个人配置、缓存或用量报告。首次提交使用工具作者 `Codex <codex@localhost>`；后续提交可按公司的要求设置自己的 Git 姓名和邮箱。
