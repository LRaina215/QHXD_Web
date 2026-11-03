#!/usr/bin/env python3
"""Display real backend/bridge events only: no recording, model calls or commands."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

GROUPS = {'asr': ('ASR', '01 实际语音识别'), 'llm': ('LLM', '02 实际语言理解'),
          'task': ('TASK', '03 任务下发与FPGA反馈'), 'tts': ('TTS', '04 实际语音合成')}


def clean(value):
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', str(value))


def display(item):
    print('\n' + clean(item.get('at', '')) + '  [' + clean(item.get('trace') or 'system') + ']  '
          + clean(item.get('component', '')) + ' / ' + clean(item.get('event', '')), flush=True)
    if item.get('dropped_before_this_event'):
        print('日志繁忙，丢弃事件数：' + str(item['dropped_before_this_event']), flush=True)
    for key, value in item.get('data', {}).items():
        if value is None:
            continue
        text = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value)
        print('  ' + clean(key) + ': ' + clean(text), flush=True)


def follow(root, group, history):
    stage, title = GROUPS[group] if group != 'all' else ('ALL', '真实请求全流程')
    print(title + '\n只读跟随后端现有请求；请从网页或小程序发指令。\n'
          '同一编号对应同一次请求；确认请求通过 related_trace 关联原指令。\n'
          '这里显示实际结果/模型可见输出，不是内部思考。Ctrl+C关闭本窗口。', flush=True)
    if group == 'asr':
        print('文字输入/网页按钮不经过ASR；小程序微信识别在手机上完成时，这里不会冒称RK识别。', flush=True)
    handles = {}
    paths = [root/'logs'/f'processing_{name}.jsonl' for name in ('backend', 'bridge')]
    last_hint = 0
    try:
        while True:
            for path in paths:
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                state = handles.get(path)
                identity = (stat.st_dev, stat.st_ino)
                if state is None or state[1] != identity or stat.st_size < state[0].tell():
                    if state:
                        state[0].close()
                    f = path.open('r', encoding='utf-8')
                    if not state and not history:
                        f.seek(0, 2)
                    handles[path] = (f, identity)
                    state = handles[path]
                f = state[0]
                while True:
                    at = f.tell()
                    line = f.readline()
                    if not line:
                        break
                    if not line.endswith('\n'):
                        f.seek(at)
                        break
                    try:
                        item = json.loads(line)
                        if stage == 'ALL' or item.get('stage') in {stage, 'SYSTEM'}:
                            display(item)
                    except (ValueError, TypeError):
                        print('跳过一条无法解析的日志。', flush=True)
            if not handles and time.monotonic()-last_hint > 15:
                print('等待处理日志。需要以 trace_backend / trace_bridge 入口运行现有服务；'
                      '本观察器不会自行重启服务或加载模型。', flush=True)
                last_hint = time.monotonic()
            time.sleep(.2)
    except KeyboardInterrupt:
        pass
    finally:
        for f, _ in handles.values():
            f.close()


def desktop(root):
    path = Path.home()/'Desktop'
    if shutil.which('xdg-user-dir'):
        result = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            path = Path(result.stdout.strip())
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    command = ' '.join(map(quote, [sys.executable, Path(__file__).resolve(), '--root', root]))
    for directory in (path, Path.home()/'.local/share/applications'):
        directory.mkdir(parents=True, exist_ok=True)
        # Replace our earlier standalone-demo shortcut, rather than leave two ambiguous entries.
        file = directory/'yuntuo-ai-demo.desktop'
        file.write_text('[Desktop Entry]\nType=Application\nName=云拓真实处理流程\n'
                        'Comment=观察网页和小程序实际请求，不额外运行模型\n'
                        f'Exec={command}\nPath={root}\nIcon=utilities-terminal\nTerminal=false\n', encoding='utf-8')
        file.chmod(0o755)
        print('已更新启动入口：' + str(file))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path(os.environ.get('QHXD_ROOT', Path(__file__).resolve().parents[1])))
    ap.add_argument('--console', choices=[*GROUPS, 'all'], help='只在当前终端跟随某个分组（支持SSH）')
    ap.add_argument('--history', action='store_true', help='同时显示当前日志文件中已有的记录，按真实时间标记')
    ap.add_argument('--install-desktop', action='store_true')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    root = args.root.expanduser().resolve()
    if args.check:
        for name in ('backend', 'bridge'):
            path = root/'logs'/f'processing_{name}.jsonl'
            print(name, str(path), '已存在' if path.exists() else '未生成')
        return
    if args.install_desktop:
        return desktop(root)
    if args.console:
        return follow(root, args.console, args.history)
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        raise RuntimeError('请在RK图形桌面运行以弹窗；SSH中可用 --console all 查看同一条真实流程。')
    # Only import window helpers; this module does not initialize any AI model.
    from ai_demo_terminals import terminal_command, window_geometries
    terminal = next((shutil.which(x) for x in ('xfce4-terminal','gnome-terminal','xterm') if shutil.which(x)), None)
    if not terminal:
        raise RuntimeError('找不到 xfce4-terminal / gnome-terminal / xterm')
    first, second, third = window_geometries()
    size = first.split('+', 1)[0]
    lower_left = size + '+0+' + third.rsplit('+',1)[1]
    lower_right = size + '+' + second.split('+',1)[1].split('+')[0] + '+' + third.rsplit('+',1)[1]
    for group, geometry in zip(GROUPS, (first,second,lower_left,lower_right)):
        command = [sys.executable, '-u', str(Path(__file__).resolve()), '--root', str(root), '--console', group]
        if args.history:
            command.append('--history')
        # helper accepts arbitrary roles through its title dictionary
        import ai_demo_terminals
        ai_demo_terminals.TITLES[group] = GROUPS[group][1]
        with open(os.devnull, 'w') as devnull:
            subprocess.Popen(terminal_command(terminal, group, command, geometry), stdout=devnull, stderr=devnull)
    print('四个只读观察窗口已打开。现在从网页/小程序正常下发指令。')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print('启动失败：' + str(exc), file=sys.stderr)
        if os.environ.get('DISPLAY') and shutil.which('zenity'):
            subprocess.run(['zenity','--error','--text='+str(exc)], check=False)
        raise SystemExit(1)
