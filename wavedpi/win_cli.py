"""Windows user-local controller and arrow-key TUI; no third-party packages."""
from __future__ import annotations

import ctypes
import json
import msvcrt
import os
import re
import socket
import subprocess
import sys
import time
import winreg
from pathlib import Path

from .core import DEFAULTS, load_config
from .win_proxy import PROXY_HOST, PROXY_PORT, serve_windows

HOME = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'WaveDPI'
CONFIG = HOME / 'config.json'
STATE = HOME / 'proxy-backup.json'
PIDFILE = HOME / 'daemon.pid'
LOGFILE = HOME / 'wave-dpi.log'
RUNKEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
INETKEY = r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
PROXY_KEYS = ('ProxyEnable', 'ProxyServer', 'ProxyOverride')
STARTUP_NAME = 'WaveDPI'
OPTIONS = ('start', 'stop', 'restart', 'mode', 'strategy', 'hosts', 'startup', 'logs', 'quit')
MODES = ('discord', 'custom', 'all')
STRATEGIES = ('record-sni', 'record-mid', 'passthrough')


def config():
    HOME.mkdir(parents=True, exist_ok=True)
    return load_config(CONFIG)


def save_config(data):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(tmp, CONFIG)


def get_registry_value(key, name):
    try:
        return winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None


def proxy_is_ours() -> bool:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INETKEY) as key:
        return (get_registry_value(key, 'ProxyEnable') or [0])[0] == 1 and \
            str((get_registry_value(key, 'ProxyServer') or [''])[0]) == f'{PROXY_HOST}:{PROXY_PORT}'


def refresh_internet_settings():
    # Notify WinINet clients that proxy settings changed.
    wininet = ctypes.windll.wininet
    wininet.InternetSetOptionW(None, 39, None, 0)  # SETTINGS_CHANGED
    wininet.InternetSetOptionW(None, 37, None, 0)  # REFRESH


def enable_proxy():
    HOME.mkdir(parents=True, exist_ok=True)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, INETKEY) as key:
        if STATE.exists():
            # A previously interrupted session can retain its backup.
            if not proxy_is_ours():
                raise RuntimeError('Есть сохранённые настройки другого прокси. Сначала: wave-dpi stop')
        else:
            if (get_registry_value(key, 'ProxyEnable') or [0])[0] and not proxy_is_ours():
                raise RuntimeError('Уже включён другой системный прокси. Отключи его перед запуском Wave DPI.')
            backup = {name: get_registry_value(key, name) for name in PROXY_KEYS}
            STATE.write_text(json.dumps(backup), encoding='utf-8')
        winreg.SetValueEx(key, 'ProxyEnable', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, 'ProxyServer', 0, winreg.REG_SZ, f'{PROXY_HOST}:{PROXY_PORT}')
        winreg.SetValueEx(key, 'ProxyOverride', 0, winreg.REG_SZ, '<local>')
    refresh_internet_settings()


def restore_proxy():
    if not STATE.exists():
        return
    # Do not overwrite proxy settings if the user manually changed them.
    if not proxy_is_ours():
        return
    backup = json.loads(STATE.read_text(encoding='utf-8'))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, INETKEY) as key:
        for name, old in backup.items():
            if old is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, old[1], old[0])
    STATE.unlink(missing_ok=True)
    refresh_internet_settings()


def daemon_alive() -> bool:
    """Verify the actual Wave DPI listener, not just an occupied TCP port."""
    try:
        with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=.5) as client:
            client.settimeout(.5)
            client.sendall(b'GET /__wave_dpi_health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            data = bytearray()
            while len(data) < 1024:
                chunk = client.recv(1024 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            return b'WaveDPI/1\n' in data and data.startswith(b'HTTP/1.1 200 OK')
    except OSError:
        return False


def command_start():
    if daemon_alive():
        if not proxy_is_ours():
            enable_proxy()
        return 'Уже запущен'
    HOME.mkdir(parents=True, exist_ok=True)
    try:
        with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=.25):
            return 'Порт прокси занят другой программой. Отключи её или измени настройки.'
    except OSError:
        pass
    launch = Path(__file__).resolve().parents[1] / 'launch.py'
    # Use pythonw.exe to avoid a console window.
    binary = Path(sys.executable)
    silent = binary.with_name('pythonw.exe')
    executable = str(silent if silent.exists() else binary)
    with LOGFILE.open('ab') as log:
        p = subprocess.Popen([executable, str(launch), 'run-daemon'],
            cwd=str(HOME), stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    PIDFILE.write_text(str(p.pid), encoding='ascii')
    for _ in range(50):
        if daemon_alive():
            try:
                enable_proxy()
            except Exception:
                command_stop()
                raise
            return 'Запущено'
        if p.poll() is not None:
            break
        time.sleep(.1)
    return 'Не удалось запустить: смотри wave-dpi logs'


def command_stop():
    # Restore first, before terminating the proxy.
    restore_proxy()
    if PIDFILE.exists():
        try:
            pid = int(PIDFILE.read_text(encoding='ascii'))
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                           capture_output=True, timeout=10)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass
        PIDFILE.unlink(missing_ok=True)
    return 'Остановлено'


def autostart_enabled():
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUNKEY) as key:
        return get_registry_value(key, STARTUP_NAME) is not None


def set_autostart(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUNKEY) as key:
        if enabled:
            launch = Path(__file__).resolve().parents[1] / 'launch.py'
            binary = Path(sys.executable)
            silent = binary.with_name('pythonw.exe')
            exe = silent if silent.exists() else binary
            cmd = f'"{exe}" "{launch}" auto-start'
            winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_NAME)
            except FileNotFoundError:
                pass


def valid_domain(host):
    try:
        host = host.strip().strip('.').encode('idna').decode('ascii').lower()
    except (UnicodeError, ValueError):
        return None
    if len(host) > 253 or not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', host):
        return None
    return host


def perform(command, argument=None):
    try:
        if command == 'start':
            return command_start()
        if command == 'stop':
            return command_stop()
        if command == 'restart':
            command_stop()
            return command_start()
        if command == 'startup':
            set_autostart(not autostart_enabled())
            return 'Автозапуск переключён'
        cfg = config()
        if command == 'mode':
            cfg['mode'] = argument or MODES[(MODES.index(cfg['mode']) + 1) % len(MODES)]
        elif command == 'strategy':
            cfg['strategy'] = argument or STRATEGIES[(STRATEGIES.index(cfg['strategy']) + 1) % len(STRATEGIES)]
        elif command == 'add-host':
            host = valid_domain(argument or '')
            if not host:
                return 'Некорректный домен'
            cfg['hosts'] = sorted(set(cfg['hosts'] + [host]))
            cfg['mode'] = 'custom'
        elif command == 'delete-host':
            if argument not in cfg['hosts']:
                return 'Домен не найден'
            cfg['hosts'].remove(argument)
        else:
            return 'Неизвестная команда'
        if cfg['mode'] not in MODES or cfg['strategy'] not in STRATEGIES:
            return 'Недопустимый режим или стратегия'
        save_config(cfg)
        if daemon_alive():
            command_stop()
            return command_start()
        return 'Сохранено'
    except (OSError, RuntimeError, ValueError) as exc:
        return f'Ошибка: {exc}'


def term_clear():
    print('\x1b[2J\x1b[H', end='')


def read_key():
    ch = msvcrt.getwch()
    if ch in ('\x00', '\xe0'):
        code = msvcrt.getwch()
        return 'up' if code == 'H' else 'down' if code == 'P' else ''
    if ch == '\r':
        return 'enter'
    if ch == '\x1b':
        return 'esc'
    return ch.lower()


def interactive():
    os.system('')  # Enable ANSI escape rendering in the Windows console.
    index = 0
    message = ''
    while True:
        cfg = config()
        alive = daemon_alive()
        term_clear()
        print('\x1b[36m' + '╭' + '─' * 44 + '╮')
        print('│             W A V E   D P I                │')
        print('╰' + '─' * 44 + '╯\x1b[0m')
        print('\n \x1b[32m● ACTIVE\x1b[0m' if alive else '\n \x1b[31m○ STOPPED\x1b[0m')
        print(f" Режим: {cfg['mode']}  |  Стратегия: {cfg['strategy']}")
        print(' Windows / TCP HTTPS proxy / no UDP\n')
        labels = ['Запустить', 'Остановить', 'Перезапустить', 'Режим обхода',
                  'TLS-стратегия', 'Свои домены',
                  'Автозапуск: ' + ('ВКЛ' if autostart_enabled() else 'ВЫКЛ'),
                  'Журнал', 'Выход']
        for i, label in enumerate(labels):
            print((' \x1b[35m❯ ' if i == index else '   ') + label + ('\x1b[0m' if i == index else ''))
        print('\n ' + (message or '↑↓ выбрать   Enter применить   Q выход')[:110])
        key = read_key()
        if key == 'up':
            index = (index - 1) % len(OPTIONS)
        elif key == 'down':
            index = (index + 1) % len(OPTIONS)
        elif key in ('q', 'esc'):
            return
        elif key == 'enter':
            cmd = OPTIONS[index]
            if cmd == 'quit':
                return
            if cmd == 'logs':
                term_clear()
                print('WAVE DPI / LOGS\n')
                print('\n'.join(LOGFILE.read_text(encoding='utf-8', errors='replace').splitlines()[-45:]) if LOGFILE.exists() else 'Журнал пуст')
                print('\nНажми любую клавишу')
                read_key()
            elif cmd == 'hosts':
                term_clear()
                print('Домены:', ', '.join(cfg['hosts']) or '(пусто)')
                action = input('Добавить [+] или удалить [-]? ').strip()
                domain = input('Домен: ').strip()
                message = perform('add-host' if action == '+' else 'delete-host', domain)
            else:
                message = perform(cmd)


def main(args):
    if args and args[0] == 'run-daemon':
        serve_windows(config())
        return
    if args and args[0] == 'auto-start':
        if not daemon_alive():
            command_start()
        return
    if not args:
        interactive()
        return
    command = args[0].lower()
    if command == 'help' or command in ('--help', '-h'):
        print('wave-dpi [start|stop|restart|status|logs|mode MODE|strategy STRATEGY|add-host HOST|delete-host HOST|startup]')
    elif command == 'status':
        print('Wave DPI:', 'ACTIVE' if daemon_alive() else 'STOPPED')
        print('System proxy:', 'Wave DPI' if proxy_is_ours() else 'not Wave DPI')
        print('Config:', CONFIG)
    elif command == 'logs':
        print('\n'.join(LOGFILE.read_text(encoding='utf-8', errors='replace').splitlines()[-80:]) if LOGFILE.exists() else 'Журнал пуст')
    elif command in ('start', 'stop', 'restart', 'startup'):
        print(perform(command))
    elif command in ('mode', 'strategy', 'add-host', 'delete-host') and len(args) == 2:
        print(perform(command, args[1]))
    else:
        print('Неизвестная команда. wave-dpi --help')
