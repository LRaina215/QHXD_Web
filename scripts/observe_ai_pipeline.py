#!/usr/bin/env python3
"""Display real backend/bridge events only: no recording, model calls or commands."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

GROUPS = {'asr': ('ASR', '01 SenseVoice | 语音识别'), 'llm': ('LLM', '02 Qwen3 | 语言理解'),
          'task': ('TASK', '03 任务下发与 FPGA 反馈'), 'tts': ('TTS', '04 Matcha + Vocos | 语音合成'),
          'yolo': ('YOLO', '05 YOLO26 | 视觉识别')}
INTRO = {'asr': '将语音转换为文字。', 'llm': '理解指令，生成回复与任务意图。',
         'task': '显示任务下发、确认与执行反馈。', 'tts': '将回复文本转换为语音。',
         'yolo': '显示目标类别、置信度、距离与位置。', 'all': '语音、视觉与任务处理日志。'}
READ_OPENER = build_opener(ProxyHandler({}))


def yolo_snapshot(state, health, now=None):
    """Project existing API fields, keeping freshness distinct from inference timing."""
    now = now or datetime.now(timezone.utc)
    detection = state.get('detection_status') or {}
    perception = health.get('perception') or {}
    stamp = detection.get('timestamp')
    age = None
    if stamp:
        try:
            dt = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if dt.tzinfo is not None:
                age = (now-dt).total_seconds()
        except (TypeError, ValueError):
            pass
    fresh = (age is not None and -.5 <= age <= 2 and health.get('latest_frame_fresh') is True
             and detection.get('enabled') is True)
    status = ('disabled' if detection.get('enabled') is False else
              'not_reported' if not detection else 'ok' if fresh else 'stale')
    objects = []
    if fresh:
        for obj in detection.get('objects', [])[:32]:
            objects.append({key: obj.get(key) for key in (
                'class_name','confidence','bbox_xyxy','color','track_id','distance_m',
                'position_body_m','current_frame','recently_seen')})
    return {'status': status, 'model': detection.get('model_name') or perception.get('model'),
            'source': detection.get('source'), 'frame_timestamp': stamp,
            'detection_age_s': round(age, 3) if age is not None else None,
            'detect_fps': perception.get('detect_fps'), 'target_task': perception.get('target_task'),
            'fresh': fresh, 'object_count': len(objects), 'objects': objects,
            'last_reported_object_count': len(detection.get('objects', [])),
            'single_frame_npu_ms': None,
            'note': '距离无有效深度时为null；单帧NPU耗时未上报；结果年龄不是推理耗时。'
                    if fresh else '当前无新鲜识别结果，不把旧目标显示成当前目标。'}


def backend_base(root):
    port = os.environ.get('BACKEND_PORT', '')
    if not port and (root/'.env').exists():
        for line in (root/'.env').read_text(encoding='utf-8').splitlines():
            if line.strip().startswith('BACKEND_PORT='):
                port = line.split('=',1)[1].strip().strip('"\'')
    value = int(port or '8000')
    if not 1 <= value <= 65535:
        raise ValueError('BACKEND_PORT 不在有效范围内')
    return f'http://127.0.0.1:{value}'


def read_yolo(root):
    base = backend_base(root)
    def get(path):
        with READ_OPENER.open(base+path, timeout=1.5) as response:
            return json.loads(response.read(2*1024*1024))['data']
    return yolo_snapshot(get('/api/state/latest'), get('/api/perception/video_health'))


def show_yolo(root):
    try:
        data = read_yolo(root)
        display({'at': datetime.now().astimezone().isoformat(timespec='seconds'),
                 'trace':'vision-continuous', 'component':'existing-perception',
                 'event':'YOLO26.detected' if data['fresh'] else 'YOLO26.'+data['status'], 'data':data})
    except Exception as exc:
        display({'at':datetime.now().astimezone().isoformat(timespec='seconds'),
                 'component':'existing-perception','event':'YOLO26.unavailable',
                 'data':{'error':str(exc),'fresh':False}})


def clean(value):
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', str(value))


def display_fields(value):
    """Keep processing data/errors; omit explanatory notes from the presentation."""
    if isinstance(value, dict):
        return {key: display_fields(item) for key, item in value.items() if key != 'note'}
    if isinstance(value, list):
        return [display_fields(item) for item in value]
    return value


def display(item):
    if str(item.get('event', '')).startswith('YOLO26.') and 'model' in item.get('data', {}):
        data = item['data']
        fps = data.get('detect_fps')
        age = data.get('detection_age_s')
        stamp = str(item.get('at', '')).split('T')[-1].split('+')[0]
        state = {'ok':'识别中','stale':'结果过期','disabled':'已关闭','not_reported':'等待画面'}.get(data.get('status'), data.get('status'))
        print(f'\n[{stamp}] {data.get("model") or "YOLO26"} | {state} | {fps if fps is not None else "--"} FPS'
              f' | 目标 {data.get("object_count", 0)} | 更新 {age if age is not None else "--"} s', flush=True)
        for obj in data.get('objects', []):
            confidence = obj.get('confidence')
            conf = f'{confidence:.1%}' if isinstance(confidence, (int,float)) else '--'
            distance = obj.get('distance_m')
            dist = f'{distance:.3f} m' if isinstance(distance, (int,float)) else '--'
            recent = ' | 最近目标' if obj.get('current_frame') is False else ''
            print(clean(f'  #{obj.get("track_id")} {obj.get("class_name")} | 置信度 {conf}'
                        f' | 距离 {dist} | 颜色 {obj.get("color") or "--"}{recent}'), flush=True)
            print(clean(f'    坐标 {obj.get("position_body_m") or "--"} | 框 {obj.get("bbox_xyxy") or "--"}'), flush=True)
        return
    print('\n' + clean(item.get('at', '')) + '  [' + clean(item.get('trace') or 'system') + ']  '
          + clean(item.get('component', '')) + ' / ' + clean(item.get('event', '')), flush=True)
    if item.get('dropped_before_this_event'):
        print('日志繁忙，丢弃事件数：' + str(item['dropped_before_this_event']), flush=True)
    for key, value in display_fields(item.get('data', {})).items():
        if value is None:
            continue
        text = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value)
        print('  ' + clean(key) + ': ' + clean(text), flush=True)


def follow(root, group, history):
    stage, title = GROUPS[group] if group != 'all' else ('ALL', '云拓 AI 处理流程')
    print(title + '\n' + INTRO[group], flush=True)
    handles = {}
    paths = [] if group == 'yolo' else [root/'logs'/f'processing_{name}.jsonl' for name in ('backend', 'bridge')]
    last_hint = next_yolo = 0
    try:
        while True:
            if group in ('yolo', 'all') and time.monotonic() >= next_yolo:
                show_yolo(root)
                next_yolo = time.monotonic()+1
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
            if paths and not handles and time.monotonic()-last_hint > 15:
                print('等待处理日志……', flush=True)
                last_hint = time.monotonic()
            time.sleep(.2)
    except KeyboardInterrupt:
        pass
    finally:
        for f, _ in handles.values():
            f.close()


def workarea():
    """Use the desktop's work area, excluding its panel."""
    try:
        text = subprocess.run(['xprop','-root','_NET_WORKAREA','_NET_CURRENT_DESKTOP'],
                              capture_output=True,text=True,timeout=2).stdout
        current = re.search(r'_NET_CURRENT_DESKTOP[^=]*=\s*(\d+)', text)
        area = re.search(r'_NET_WORKAREA[^=]*=([^\n]+)', text)
        if area:
            values = [int(x) for x in re.findall(r'-?\d+', area.group(1))]
            offset = int(current.group(1))*4 if current else 0
            if len(values) >= offset+4:
                return tuple(values[offset:offset+4])
    except (OSError,subprocess.TimeoutExpired):
        pass
    from ai_demo_terminals import window_geometries
    _, second, third = window_geometries()
    return 0,0,int(second.split('+')[1])*2,int(third.rsplit('+',1)[1])*2


def layout_rectangles(area):
    x,y,width,height = area
    half = width//2
    row = max(80, int(height*.2))
    return {'asr':(x,y,half,row), 'llm':(x+half,y,width-half,row),
            'task':(x,y+row,half,row), 'tts':(x+half,y+row,width-half,row),
            'yolo':(x,y+2*row,width,height-2*row)}


def observer_windows(root):
    if not shutil.which('wmctrl'):
        return {}
    result = subprocess.run(['wmctrl','-lp'],capture_output=True,text=True,timeout=2)
    windows = {}
    script = os.fsencode(root/'scripts/observe_ai_pipeline.py')
    for line in result.stdout.splitlines():
        fields = line.split(None,4)
        if len(fields)<3:
            continue
        try:
            argv = Path('/proc/'+fields[2]+'/cmdline').read_bytes().split(b'\0')
            if script not in argv or b'--console' not in argv:
                continue
            role = argv[argv.index(b'--console')+1].decode()
            if role in GROUPS:
                windows[role] = fields[0]
        except (OSError,ValueError,IndexError):
            pass
    return windows


def window_bounds(wid):
    frame = subprocess.run(['xprop','-id',wid,'_NET_FRAME_EXTENTS'],capture_output=True,text=True,timeout=2).stdout
    match = re.search(r'=\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)', frame)
    left,right,top,bottom = map(int,match.groups()) if match else (0,0,0,0)
    text = subprocess.run(['xwininfo','-id',wid],capture_output=True,text=True,timeout=2).stdout
    def number(label):
        return int(re.search(label+r':\s*(-?\d+)',text).group(1))
    outer = (number('Absolute upper-left X')-left,number('Absolute upper-left Y')-top,
             number('Width')+left+right,number('Height')+top+bottom)
    return outer,(left,right,top,bottom)


def arrange(root, wait=0):
    if not shutil.which('wmctrl'):
        return {}
    deadline = time.monotonic()+wait
    while True:
        windows = observer_windows(root)
        if len(windows)==len(GROUPS) or time.monotonic()>=deadline:
            break
        time.sleep(.15)
    rectangles = layout_rectangles(workarea())
    report = {}
    for role,wid in windows.items():
        target = rectangles[role]
        subprocess.run(['wmctrl','-ir',wid,'-b','remove,maximized_vert,maximized_horz'],capture_output=True,timeout=2)
        # Terminal character-grid hints otherwise leave large unused strips.
        subprocess.run(['xprop','-id',wid,'-remove','WM_NORMAL_HINTS'],capture_output=True,timeout=2)
        actual,frame = window_bounds(wid)
        left,right,top,bottom = frame
        rx,ry = target[:2]
        for _ in range(2):
            values = f'0,{rx},{ry},{max(40,target[2]-left-right)},{max(20,target[3]-top-bottom)}'
            subprocess.run(['wmctrl','-ir',wid,'-e',values],capture_output=True,timeout=2)
            time.sleep(.08)
            actual,_ = window_bounds(wid)
            rx += target[0]-actual[0]
            ry += target[1]-actual[1]
        report[role] = {'window':wid,'target':target,'actual':actual}
    if report:
        path = root/'.runtime/processing_window_layout.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


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
        file.write_text('[Desktop Entry]\nType=Application\nName=云拓 AI 处理流程\n'
                        'Comment=语音、视觉与任务处理\n'
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
    ap.add_argument('--arrange', action='store_true', help='重新排列已打开的模块窗口')
    args = ap.parse_args()
    root = args.root.expanduser().resolve()
    if args.check:
        for name in ('backend', 'bridge'):
            path = root/'logs'/f'processing_{name}.jsonl'
            print(name, str(path), '已存在' if path.exists() else '未生成')
        try:
            data = read_yolo(root)
            print('YOLO', data['model'], data['status'], '检测帧率', data['detect_fps'])
        except Exception as exc:
            print('YOLO 不可用：', exc)
        return
    if args.install_desktop:
        return desktop(root)
    if args.console:
        return follow(root, args.console, args.history)
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        raise RuntimeError('请在RK图形桌面运行以弹窗；SSH中可用 --console all 查看同一条真实流程。')
    if args.arrange:
        arrange(root)
        print('布局已更新。')
        return
    # Only import window helpers; this module does not initialize any AI model.
    from ai_demo_terminals import terminal_command
    terminal = next((shutil.which(x) for x in ('xfce4-terminal','gnome-terminal','xterm') if shutil.which(x)), None)
    if not terminal:
        raise RuntimeError('找不到 xfce4-terminal / gnome-terminal / xterm')
    rectangles = layout_rectangles(workarea())
    existing = observer_windows(root)
    for group in GROUPS:
        if group in existing:
            continue
        x,y,width,height = rectangles[group]
        geometry = f'{max(24,(width-6)//9)}x{max(3,(height-32)//18)}+{x}+{y}'
        command = [sys.executable, '-u', str(Path(__file__).resolve()), '--root', str(root), '--console', group]
        if args.history:
            command.append('--history')
        # helper accepts arbitrary roles through its title dictionary
        import ai_demo_terminals
        ai_demo_terminals.TITLES[group] = GROUPS[group][1]
        with open(os.devnull, 'w') as devnull:
            subprocess.Popen(terminal_command(terminal, group, command, geometry), stdout=devnull, stderr=devnull)
    arrange(root,wait=5)
    print('已打开 5 个模块窗口。')


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
