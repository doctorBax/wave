"""Arrow-key terminal interface, implemented using Python's standard library."""
from __future__ import annotations

import curses
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .core import CONFIG_FILE, DISCORD, load_config

SERVICE = 'wave-dpi.service'
MODES = ('discord', 'custom', 'all')
STRATEGIES = ('record-sni', 'record-mid', 'passthrough')
ITEMS = ('start', 'stop', 'restart', 'mode', 'strategy', 'hosts', 'logs', 'quit')
LABELS = ('▶  Запустить', '■  Остановить', '↻  Перезапустить', '◈  Режим обхода',
          '◇  TLS-стратегия', '✎  Свои домены', '≡  Журнал сервиса', '×  Выход')


def command(*args):
    try:
        process = subprocess.run(args, capture_output=True, text=True, timeout=25, check=False)
        return process.returncode, (process.stdout or process.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as err:
        return 1, str(err)


def service_status():
    code, _ = command('systemctl', 'is-active', '--quiet', SERVICE)
    return code == 0


def save_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='.wave-', suffix='.json', dir=CONFIG_FILE.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(cfg, out, indent=2, ensure_ascii=False)
            out.write('\n')
        os.chmod(filename, 0o644)
        os.replace(filename, CONFIG_FILE)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def valid_domain(value):
    try:
        name = value.strip().rstrip('.').encode('idna').decode('ascii').lower()
    except (UnicodeError, ValueError):
        return None
    if len(name) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+', name):
        return None
    return name


def action(name, value=None):
    if os.geteuid() != 0:
        return 'Нужен root. Запусти: sudo wave-dpi'
    if name in ('start', 'stop', 'restart'):
        status, output = command('systemctl', name, SERVICE)
        return 'Готово' if status == 0 else (output[-190:] or 'Команда завершилась с ошибкой')
    cfg = load_config()
    if name == 'mode':
        cfg['mode'] = MODES[(MODES.index(cfg['mode']) + 1) % len(MODES)]
    elif name == 'strategy':
        cfg['strategy'] = STRATEGIES[(STRATEGIES.index(cfg['strategy']) + 1) % len(STRATEGIES)]
    elif name == 'add-host':
        domain = valid_domain(value or '')
        if not domain:
            return 'Некорректное имя домена'
        cfg['hosts'] = sorted(set(cfg['hosts'] + [domain]))
        cfg['mode'] = 'custom'
    elif name == 'delete-host':
        if value not in cfg['hosts']:
            return 'Домен не найден'
        cfg['hosts'].remove(value)
    else:
        return 'Неизвестная команда'
    save_config(cfg)
    if service_status():
        status, output = command('systemctl', 'restart', SERVICE)
        if status:
            return 'Настройки сохранены, но перезапуск не удался: ' + output[-110:]
    return 'Настройки сохранены'


def put(screen, y, x, message, color=0, maxlen=None):
    h, w = screen.getmaxyx()
    if y < 0 or y >= h or x < 0 or x >= w:
        return
    try:
        text = str(message)[:maxlen or max(0, w - x - 1)]
        screen.addstr(y, x, text, curses.color_pair(color))
    except curses.error:
        pass


def center(screen, y, text, color=0):
    _, width = screen.getmaxyx()
    put(screen, y, max(0, (width - len(text)) // 2), text, color)


def prompt(screen, title):
    height, width = screen.getmaxyx()
    screen.move(height - 3, 0)
    screen.clrtoeol()
    put(screen, height - 3, 2, title)
    screen.move(height - 2, 0)
    screen.clrtoeol()
    curses.echo()
    curses.curs_set(1)
    try:
        screen.move(height - 2, 2)
        return screen.getstr(height - 2, 2, min(200, width - 4)).decode('utf-8', 'replace').strip()
    finally:
        curses.noecho()
        curses.curs_set(0)


def domain_menu(screen):
    notice = 'A = добавить   D = удалить   ESC = назад'
    selected = 0
    while True:
        screen.erase()
        cfg = load_config()
        names = cfg['hosts']
        center(screen, 2, 'WAVE / ДОМЕНЫ', 1)
        center(screen, 4, notice, 3)
        for i, name in enumerate(names[:max(1, screen.getmaxyx()[0] - 9)]):
            center(screen, 6 + i, ('> ' if i == selected else '  ') + name, 2 if i == selected else 0)
        if not names:
            center(screen, 7, 'Список пуст. Нажми A, чтобы добавить домен.', 3)
        screen.refresh()
        key = screen.getch()
        if key in (27, ord('q'), ord('Q')):
            return ''
        if key in (curses.KEY_UP, ord('k')):
            selected = max(0, selected - 1)
        if key in (curses.KEY_DOWN, ord('j')):
            selected = min(max(0, len(names) - 1), selected + 1)
        if key in (ord('a'), ord('A')):
            value = prompt(screen, 'Имя домена (например discord.com):')
            return action('add-host', value) if value else ''
        if key in (ord('d'), ord('D')) and names:
            return action('delete-host', names[selected])


def logs_screen(screen):
    _, result = command('journalctl', '-u', SERVICE, '-n', '150', '--no-pager', '--output=short-iso')
    lines = result.splitlines() or ['Журнал пуст']
    offset = max(0, len(lines) - (screen.getmaxyx()[0] - 6))
    while True:
        screen.erase()
        center(screen, 1, 'WAVE / JOURNAL', 1)
        max_visible = max(1, screen.getmaxyx()[0] - 6)
        for i, row in enumerate(lines[offset:offset + max_visible]):
            put(screen, 3 + i, 2, row, 0, screen.getmaxyx()[1] - 4)
        center(screen, screen.getmaxyx()[0] - 2, '↑↓ листать · ESC назад', 3)
        screen.refresh()
        key = screen.getch()
        if key in (27, ord('q'), ord('Q'), 10):
            return
        if key in (curses.KEY_UP, ord('k')):
            offset = max(0, offset - 1)
        if key in (curses.KEY_DOWN, ord('j')):
            offset = min(max(0, len(lines) - max_visible), offset + 1)


def tui(screen):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    for i, fg in enumerate((curses.COLOR_CYAN, curses.COLOR_MAGENTA, curses.COLOR_WHITE,
                            curses.COLOR_GREEN, curses.COLOR_RED), 1):
        curses.init_pair(i, fg, -1)
    screen.keypad(True)
    selected, message = 0, ''
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 19 or width < 47:
            center(screen, height // 2, 'Расширь окно терминала (47x19).', 5)
            screen.refresh()
            if screen.getch() in (27, ord('q')):
                return
            continue
        cfg = load_config()
        running = service_status()
        center(screen, 1, 'W A V E    D P I', 1)
        center(screen, 2, 'Linux · local TLS bypass · IPv4', 3)
        center(screen, 4, '●  ACTIVE' if running else '○  STOPPED', 4 if running else 5)
        center(screen, 5, f"Режим: {cfg['mode']}    Стратегия: {cfg['strategy']}", 0)
        pad = max(2, (width - 42) // 2)
        put(screen, 7, pad, '╭' + '─' * 40 + '╮', 1)
        for i, label in enumerate(LABELS):
            suffix = ''
            if ITEMS[i] == 'mode':
                suffix = '  ' + cfg['mode']
            elif ITEMS[i] == 'strategy':
                suffix = '  ' + cfg['strategy']
            text = label + suffix
            put(screen, 8 + i, pad, '│', 1)
            put(screen, 8 + i, pad + 2, ('› ' if selected == i else '  ') + text,
                2 if selected == i else 0, 36)
            put(screen, 8 + i, pad + 41, '│', 1)
        put(screen, 16, pad, '╰' + '─' * 40 + '╯', 1)
        center(screen, height - 3, message[:max(0, width - 4)] or '↑↓ выбор  ·  Enter действие  ·  Q выход', 3)
        center(screen, height - 2, 'Только TCP/443 · UDP/голос Discord не обрабатывается', 3)
        screen.refresh()
        key = screen.getch()
        if key in (curses.KEY_UP, ord('k')):
            selected = (selected - 1) % len(ITEMS)
        elif key in (curses.KEY_DOWN, ord('j')):
            selected = (selected + 1) % len(ITEMS)
        elif key in (ord('q'), ord('Q'), 27):
            return
        elif key in (10, 13, curses.KEY_ENTER):
            choice = ITEMS[selected]
            if choice == 'quit':
                return
            if choice == 'logs':
                logs_screen(screen)
            elif choice == 'hosts':
                message = domain_menu(screen)
            else:
                message = action(choice)


def main(args):
    if not args:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print('Интерактивный интерфейс: sudo wave-dpi (в терминале)')
            return
        curses.wrapper(tui)
        return
    command_name = args[0].lower()
    if command_name in ('--help', '-h', 'help'):
        print('wave-dpi [status|start|stop|restart|logs|mode MODE|strategy NAME|add-host DOMAIN|delete-host DOMAIN]')
        return
    if command_name == 'status':
        cfg = load_config()
        print(f"Wave DPI: {'active' if service_status() else 'stopped'}\nMode: {cfg['mode']}\nStrategy: {cfg['strategy']}\nHosts: {', '.join(cfg['hosts']) or '(none)'}")
        return
    if command_name == 'logs':
        os.execvp('journalctl', ['journalctl', '-u', SERVICE, '-n', '50', '--no-pager'])
    if command_name in ('start', 'stop', 'restart'):
        print(action(command_name))
        return
    if command_name in ('mode', 'strategy') and len(args) == 2:
        choices = MODES if command_name == 'mode' else STRATEGIES
        if args[1] not in choices:
            sys.exit(f'Allowed: {", ".join(choices)}')
        if os.geteuid() != 0:
            sys.exit('Требуется root: sudo wave-dpi ...')
        cfg = load_config()
        cfg[command_name] = args[1]
        save_config(cfg)
        if service_status():
            code, out = command('systemctl', 'restart', SERVICE)
            if code:
                sys.exit(out)
        print('Готово')
        return
    if command_name in ('add-host', 'delete-host') and len(args) == 2:
        print(action(command_name, args[1]))
        return
    sys.exit('Неизвестная команда. wave-dpi --help')
