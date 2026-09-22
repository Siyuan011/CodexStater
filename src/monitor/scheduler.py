"""User-level schedulers. Never runs a shell or changes another user's jobs."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

NAME = 'codex-stater-monitor'
LABEL = 'com.codexstater.monitor'


def call(argv, check=True):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f'{argv[0]} failed')
    return result


def unit_quote(value):
    # systemd specifiers and ExecStart environment expansion are distinct.
    value = str(value)
    if any(c in value for c in '\n\r\x00'):
        raise ValueError('Paths and environment values cannot contain newlines or NUL')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


class Scheduler:
    def __init__(self, root, config_path, config):
        self.root = root
        self.config_path = config_path
        self.config = config
        if sys.platform not in ('linux', 'darwin'):
            raise RuntimeError('Bash launchers support Linux and macOS only; use run.cmd on Windows.')
        self.mac = sys.platform == 'darwin'
        executable = 'launchctl' if self.mac else 'systemctl'
        if not shutil.which(executable):
            raise RuntimeError(f'{executable} is required. Linux without systemd is not supported.')
        self.directory = (Path.home() / 'Library/LaunchAgents' if self.mac else
                          Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config') / 'systemd/user')
        self.target = f'gui/{os.getuid()}/{LABEL}' if self.mac else NAME + '.timer'
        self.plist = self.directory / (LABEL + '.plist')

    def ctl(self, *args, check=True):
        return call((['launchctl'] if self.mac else ['systemctl', '--user']) + list(args), check)

    def definitions(self):
        from settings import resolve
        minutes = int(self.config.get('monitor_interval_minutes', 60))
        if not 5 <= minutes <= 1440:
            raise ValueError('monitor_interval_minutes must be between 5 and 1440')
        logs = resolve(self.config.get('logs_dir', 'logs'))
        logs.mkdir(parents=True, exist_ok=True)
        argv = [sys.executable, str(self.root/'src/monitor/local_monitor.py'), '--config', str(self.config_path)]
        env = {'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), 'PYTHONUNBUFFERED': '1'}
        if self.mac:
            return {self.plist: plistlib.dumps(dict(Label=LABEL, ProgramArguments=argv,
                WorkingDirectory=str(self.root), EnvironmentVariables=env,
                StartInterval=minutes*60, RunAtLoad=False,
                StandardOutPath=str(logs/'monitor-stdout.log'),
                StandardErrorPath=str(logs/'monitor-stderr.log')))}
        service = '\n'.join(['[Unit]', 'Description=Codex Stater local sampling', '[Service]',
            'Type=oneshot', 'WorkingDirectory='+unit_quote(self.root),
            'ExecStart='+' '.join(unit_quote(x).replace('$', '$$') for x in argv),
            'Environment='+unit_quote('PATH='+env['PATH']), 'Environment=PYTHONUNBUFFERED=1',
            'TimeoutStartSec=10min', ''])
        timer = '\n'.join(['[Unit]', 'Description=Codex Stater periodic sampling', '[Timer]',
            'OnActiveSec=1min', f'OnUnitActiveSec={minutes}min', 'AccuracySec=1s',
            f'Unit={NAME}.service', '[Install]', 'WantedBy=timers.target', ''])
        return {self.directory/(NAME+'.service'): service.encode(),
                self.directory/(NAME+'.timer'): timer.encode()}

    def installed(self):
        return self.plist.exists() if self.mac else (self.directory/(NAME+'.timer')).exists()

    def loaded(self):
        return self.ctl('print', self.target, check=False).returncode == 0

    def install(self):
        definitions = self.definitions()
        changed = any(not path.exists() or path.read_bytes() != data for path, data in definitions.items())
        if self.mac and changed and self.loaded():
            self.ctl('bootout', self.target)
        self.directory.mkdir(parents=True, exist_ok=True)
        for path, data in definitions.items():
            if not path.exists() or path.read_bytes() != data:
                temporary = path.with_suffix(path.suffix+'.tmp')
                temporary.write_bytes(data)
                temporary.replace(path)
        if not self.mac:
            self.ctl('daemon-reload')
        self.resume()
        if changed and not self.mac:
            self.ctl('restart', NAME+'.timer')

    def resume(self):
        if not self.installed():
            raise RuntimeError('Monitor is not installed; run install-monitor.sh first.')
        if self.mac:
            self.ctl('enable', self.target)
            if not self.loaded():
                self.ctl('bootstrap', f'gui/{os.getuid()}', str(self.plist))
        else:
            self.ctl('enable', '--now', NAME+'.timer')

    def pause(self):
        if not self.installed():
            raise RuntimeError('Monitor is not installed.')
        if self.mac:
            self.ctl('disable', self.target)
            if self.loaded():
                self.ctl('bootout', self.target)
        else:
            self.ctl('disable', '--now', NAME+'.timer')

    def remove(self):
        if self.installed():
            self.pause()
        if self.mac:
            self.plist.unlink(missing_ok=True)
        else:
            self.ctl('stop', NAME+'.service', check=False)
            for suffix in ('.timer', '.service'):
                (self.directory/(NAME+suffix)).unlink(missing_ok=True)
            self.ctl('daemon-reload')

    def start(self):
        if self.mac:
            # No -k: never kill an in-progress sample to restart it.
            self.ctl('kickstart', self.target)
        else:
            self.ctl('start', '--no-block', NAME+'.service')

    def status(self):
        if not self.installed():
            print('Monitor is not installed.')
            return
        if self.mac:
            result = self.ctl('print', self.target, check=False)
            print(result.stdout if result.returncode == 0 else 'Monitor is not loaded (paused or login session unavailable).')
        else:
            result = self.ctl('status', '--no-pager', NAME+'.timer', NAME+'.service', check=False)
            print(result.stdout or result.stderr)
        from settings import resolve
        status = resolve(self.config.get('logs_dir', 'logs'))/'local-monitor-status.json'
        if status.exists():
            print(status.read_text(encoding='utf-8'))
