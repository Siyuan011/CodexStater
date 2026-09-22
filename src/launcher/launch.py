"""Linux/macOS launcher shared by all Bash entry points."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'monitor'))
from settings import ROOT, DEFAULT_CONFIG, load, resolve, codex_root
from scheduler import Scheduler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['Run','launch','stop','export','Install','Status','Pause','Resume','Remove'])
    parser.add_argument('--config', '-Config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--codex-root', '-CodexRoot')
    parser.add_argument('--codex-exe', help='Codex CLI executable path or command name')
    parser.add_argument('--no-browser', '-NoBrowser', action='store_true')
    parser.add_argument('--check', '-Check', action='store_true')
    parser.add_argument('--non-interactive', '-NonInteractive', action='store_true', help='Accepted for compatibility; no folder dialogs are used')
    args = parser.parse_args()
    if sys.platform not in ('linux', 'darwin'):
        parser.error('Use run.cmd on Windows; Bash supports Linux/macOS only.')
    config_path = resolve(args.config)
    config = (json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists()
              else json.loads((ROOT/'config/config.example.json').read_text(encoding='utf-8-sig')))
    if args.codex_root:
        config['codex_root'] = str(resolve(args.codex_root))
    data_root = codex_root(config)
    if args.action in ('Run','Install','launch','export') and not data_root.is_dir():
        raise ValueError(f'Codex directory does not exist: {data_root}; set --codex-root or codex_root in config.')
    command = args.codex_exe or config.get('codex_exe') or 'codex'
    executable = shutil.which(command) or (str(resolve(command)) if resolve(command).is_file() else None)
    if args.action in ('Run','Install') and not executable:
        raise ValueError('Codex CLI not found. Set --codex-exe or codex_exe in config.')
    if args.check:
        print(json.dumps(dict(platform=sys.platform, python=sys.executable, config=str(config_path),
                              codex_root=str(data_root), codex_exe=executable), indent=2))
        return 0
    if args.action in ('Run','Install'):
        config.update(codex_root=str(data_root), codex_exe=executable)
    if not config_path.exists() or args.codex_root or args.action in ('Run','Install'):
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if args.action in ('Run','Install','Status','Pause','Resume','Remove'):
        scheduler = Scheduler(ROOT, config_path, config)
        if args.action in ('Run','Install'):
            scheduler.install()
            scheduler.start()
            print('Monitor enabled; immediate sample requested.')
        else:
            getattr(scheduler, {'Status':'status','Pause':'pause','Resume':'resume','Remove':'remove'}[args.action])()
        if args.action != 'Run':
            return 0
    action = 'launch' if args.action == 'Run' else args.action
    argv = [sys.executable, str(ROOT/'src/dashboard/app.py'), action, '--config', str(config_path)]
    if args.no_browser and action == 'launch':
        argv.append('--no-browser')
    subprocess.run(argv, check=True)
    if action == 'export' and not args.no_browser:
        webbrowser.open((resolve(config.get('export_dir','exports'))/'最新用量报告.html').as_uri())
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Stater: {error}', file=sys.stderr)
        raise SystemExit(1)
