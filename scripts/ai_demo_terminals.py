#!/usr/bin/env python3
"""Three real RK3588 voice-demo terminals; never calls robot/task APIs.

ASR owns one private SenseVoice recognizer. LLM/TTS reuse loopback services.
Only the launcher/worker processes and temporary audio belong to this demo.
"""
from __future__ import annotations

import argparse
import array
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener
import uuid
import wave

ROLES = ('asr', 'llm', 'tts')
TITLES = {'asr': '01 ASR | SenseVoice 语音识别',
          'llm': '02 LLM | RK3588 NPU 本地大模型',
          'tts': '03 TTS | Matcha + Vocos 语音合成'}
KEYS = {'SHERPA_ASR_MODEL_DIR', 'SHERPA_ASR_THREADS', 'FUNASR_LANGUAGE',
        'FUNASR_USE_ITN', 'AUDIO_DEVICE', 'AUDIO_RECORD_SECONDS', 'TTS_PLAYER_CMD',
        'LLM_LOCAL_BASE_URL', 'LLM_LOCAL_MODEL', 'TTS_LOCAL_URL', 'RKLLM_PORT', 'TTS_PORT'}
OPENER = build_opener(ProxyHandler({}))


def config(root: Path) -> dict:
    cfg = {}
    path = root / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip().removeprefix('export ')
            if '=' not in line or line.startswith('#'):
                continue
            key, value = line.split('=', 1)
            if key.strip() in KEYS:
                # Read selected values only; do not execute/source the .env file.
                parts = shlex.split(value, comments=True)
                cfg[key.strip()] = ' '.join(parts)
    cfg.update({k: os.environ[k] for k in KEYS if k in os.environ})
    return cfg


def local_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme != 'http' or p.hostname not in {'127.0.0.1', 'localhost', '::1'} or p.username:
        raise ValueError('演示仅允许本机 HTTP 地址，不使用云端接口：' + url)
    return url


def urls(cfg: dict) -> tuple[str, str]:
    llm = cfg.get('LLM_LOCAL_BASE_URL', 'http://127.0.0.1:' + cfg.get('RKLLM_PORT', '8080'))
    tts = cfg.get('TTS_LOCAL_URL', 'http://127.0.0.1:' + cfg.get('TTS_PORT', '8081') + '/tts')
    return local_url(llm.rstrip('/')), local_url(tts)


def http(url: str, payload=None, timeout=65):
    local_url(url)
    raw = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(url, data=raw, headers={'Content-Type': 'application/json'})
    try:
        with OPENER.open(req, timeout=timeout) as response:
            body = response.read(16 * 1024 * 1024 + 1)
            if len(body) > 16 * 1024 * 1024:
                raise ValueError('本机服务响应过大')
            return body
    except HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read(1024).decode("utf-8", "replace")}') from exc


def get_json(url: str, payload=None, timeout=65):
    return json.loads(http(url, payload, timeout))


def write_json(path: Path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def say(session: Path, role: str, text: str):
    stamp = time.strftime('%H:%M:%S')
    # Strip terminal escape/control characters from untrusted speech/model text.
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', str(text))
    print(f'[{stamp}] {text}', flush=True)
    with (session / (role + '.log')).open('a', encoding='utf-8') as stream:
        stream.write(f'[{stamp}] {text}\n')


def stopped(session: Path):
    return (session / 'STOP').exists()


def wait_json(session: Path, path: Path):
    while not stopped(session):
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        time.sleep(.15)
    return None


def wav_info(data: bytes):
    with wave.open(io.BytesIO(data), 'rb') as w:
        rate, channels, width, frames = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        return rate, channels, width, frames, w.readframes(frames)


def load_asr(cfg: dict, session: Path):
    model_dir = Path(cfg.get('SHERPA_ASR_MODEL_DIR', '')).expanduser()
    model = model_dir / 'model.int8.onnx'
    if not model.exists():
        model = model_dir / 'model.onnx'
    tokens = model_dir / 'tokens.txt'
    if not model.is_file() or not tokens.is_file():
        raise RuntimeError(f'找不到 SenseVoice 模型：{model_dir}；检查 QHXD/.env')
    say(session, 'asr', '加载独立演示用 SenseVoice（CPU）；业务后端保持运行。')
    say(session, 'asr', '模型：' + str(model))
    t0 = time.monotonic()
    import sherpa_onnx
    model_obj = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=int(cfg.get('SHERPA_ASR_THREADS', '4')),
        language=cfg.get('FUNASR_LANGUAGE', 'zh'),
        use_itn=cfg.get('FUNASR_USE_ITN', 'true').lower() in {'1', 'true', 'yes', 'on'})
    say(session, 'asr', f'加载完成，用时 {time.monotonic()-t0:.3f} s')
    return model_obj


def readline(session: Path):
    print('\n回车录音 | t 文字（跳过ASR） | f /路径/音频.wav | q 退出 > ', end='', flush=True)
    while not stopped(session):
        ready, _, _ = select.select([sys.stdin], [], [], .2)
        if ready:
            line = sys.stdin.readline()
            return None if not line else line.strip()
    return None


def asr_worker(cfg: dict, session: Path):
    recognizer = load_asr(cfg, session)
    duration = min(10, max(1, int(cfg.get('AUDIO_RECORD_SECONDS', '3'))))
    while not stopped(session):
        line = readline(session)
        if line is None or line.lower() in {'q', 'quit', 'exit'}:
            return
        request_id = uuid.uuid4().hex[:10]
        try:
            if line.startswith('t '):
                text = line[2:].strip()
                say(session, 'asr', '文字输入，未调用语音识别：' + text)
            else:
                audio = session / 'recording.wav'
                if line.startswith('f '):
                    audio = Path(line[2:].strip()).expanduser()
                elif line:
                    say(session, 'asr', '请输入回车、t 文字、f 音频路径 或 q。')
                    continue
                else:
                    device = cfg.get('AUDIO_DEVICE', 'plughw:CARD=Device,DEV=0')
                    say(session, 'asr', f'开始录音 {duration} s，麦克风：{device}；请讲话。')
                    subprocess.run(['arecord', '-q', '-D', device, '-r', '16000', '-c', '1',
                                    '-f', 'S16_LE', '-d', str(duration), str(audio)], check=True, timeout=duration+6)
                rate, channels, width, frames, raw = wav_info(audio.read_bytes())
                if channels != 1 or width != 2 or not 0 < frames / rate <= 10:
                    raise ValueError('需要 16-bit PCM 单声道 WAV，时长大于0且不超过10秒')
                samples = array.array('h', raw)
                if sys.byteorder != 'little':
                    samples.byteswap()
                stream = recognizer.create_stream()
                stream.accept_waveform(rate, [x / 32768.0 for x in samples])
                say(session, 'asr', f'识别中：{rate} Hz / {frames/rate:.2f} s')
                t0 = time.monotonic()
                recognizer.decode_stream(stream)
                text = re.sub(r'<\|[^|]*\|>', '', stream.result.text).strip()
                say(session, 'asr', f'识别耗时 {time.monotonic()-t0:.3f} s；结果：{text or "（空）"}')
            if not text:
                continue
            write_json(session / 'llm_in.json', {'id': request_id, 'text': text})
            say(session, 'asr', '已交给 LLM 窗口；等待语音回复播放结束。')
            result = wait_json(session, session / ('done_' + request_id + '.json'))
            if result:
                say(session, 'asr', '本轮完成。' if result['ok'] else '本轮失败：' + result['error'])
        except Exception as exc:
            say(session, 'asr', '错误：' + str(exc))


def llm_worker(cfg: dict, session: Path):
    base, _ = urls(cfg)
    endpoint = base + ('/chat/completions' if base.endswith('/v1') else '/v1/chat/completions')
    last = None
    say(session, 'llm', '调用现有本机 RKLLM 服务，不重新加载大模型：' + endpoint)
    say(session, 'llm', '等待 ASR 输入；当前接口整段返回，不模拟逐字生成。')
    while not stopped(session):
        item = wait_json(session, session / 'llm_in.json')
        if item is None:
            return
        if item['id'] == last:
            time.sleep(.15)
            continue
        last = item['id']
        try:
            say(session, 'llm', '收到输入：' + item['text'])
            say(session, 'llm', '正在进行本地推理……')
            t0 = time.monotonic()
            result = get_json(endpoint, {'model': cfg.get('LLM_LOCAL_MODEL', 'qwen3-1.7b'),
                'messages': [
                    {'role': 'system', 'content': '你是云拓轮腿机器人的本地语音助手。用简洁中文回答，尽量不超过80字。本次仅演示问答，没有车辆控制权限，不要声称已执行任何动作。'},
                    {'role': 'user', 'content': item['text']}], 'max_tokens': 160, 'temperature': .3})
            elapsed = time.monotonic() - t0
            answer = result['choices'][0]['message']['content'].strip()
            if not answer:
                raise RuntimeError('模型回复为空')
            say(session, 'llm', '模型：' + str(result.get('model', '未返回')))
            say(session, 'llm', '回复：\n' + answer)
            usage = result.get('usage', {})
            say(session, 'llm', f'请求耗时 {elapsed:.3f} s（含排队/预填充）；输入token={usage.get("prompt_tokens", "未知")}，输出token={usage.get("completion_tokens", "未知")}')
            write_json(session / 'tts_in.json', {'id': last, 'text': answer})
        except Exception as exc:
            say(session, 'llm', '错误：' + str(exc))
            write_json(session / ('done_' + last + '.json'), {'ok': False, 'error': str(exc)})


def tts_worker(cfg: dict, session: Path):
    _, endpoint = urls(cfg)
    last = None
    say(session, 'tts', '复用现有本机语音合成服务：' + endpoint)
    say(session, 'tts', '等待 LLM 回复；合成后通过 RK 声卡实际播放。')
    while not stopped(session):
        item = wait_json(session, session / 'tts_in.json')
        if item is None:
            return
        if item['id'] == last:
            time.sleep(.15)
            continue
        last = item['id']
        try:
            say(session, 'tts', '待合成文本：' + item['text'])
            t0 = time.monotonic()
            audio = http(endpoint, {'text': item['text'], 'speed': 1.0})
            elapsed = time.monotonic() - t0
            rate, channels, width, frames, _ = wav_info(audio)
            seconds = frames / rate
            if not seconds:
                raise RuntimeError('合成的音频为空')
            output = session / 'reply.wav'
            output.write_bytes(audio)
            say(session, 'tts', f'音频 {seconds:.2f} s / {rate} Hz / {channels}声道；请求耗时 {elapsed:.3f} s（可能命中服务缓存）')
            say(session, 'tts', f'请求实时率 {elapsed/seconds:.3f}（请求耗时/音频时长，非纯模型计时）')
            player = shlex.split(cfg.get('TTS_PLAYER_CMD', 'aplay'))
            if not player:
                raise RuntimeError('TTS_PLAYER_CMD 为空')
            say(session, 'tts', '正在播放……')
            subprocess.run(player + [str(output)], check=True, timeout=seconds+15)
            say(session, 'tts', '播放完成。')
            write_json(session / ('done_' + last + '.json'), {'ok': True})
        except Exception as exc:
            say(session, 'tts', '错误：' + str(exc))
            write_json(session / ('done_' + last + '.json'), {'ok': False, 'error': str(exc)})


def worker(args, cfg):
    session = Path(args.session)
    def stop(_sig=None, _frame=None):
        (session / 'STOP').touch()
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    write_json(session / (args.role + '.ready'), {'pid': os.getpid()})
    try:
        print('\033[1;36m' + TITLES[args.role] + '\033[0m', flush=True)
        say(session, args.role, '真实本机处理演示；不调用车辆命令接口。关闭任一窗口退出本次演示。')
        {'asr': asr_worker, 'llm': llm_worker, 'tts': tts_worker}[args.role](cfg, session)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        say(session, args.role, '启动失败：' + str(exc))
        say(session, args.role, '修正后重新启动脚本。按回车关闭。')
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
    finally:
        (session / 'STOP').touch()
        (session / (args.role + '.done')).touch()


def terminal_command(executable: str, role: str, cmd: list[str], geometry: str):
    name = Path(executable).name
    if name == 'xfce4-terminal':
        return [executable, '--disable-server', '--title=' + TITLES[role], '--hide-menubar',
                '--geometry=' + geometry, '--font=Monospace 11', '--execute', *cmd]
    if name == 'gnome-terminal':
        return [executable, '--window', '--title=' + TITLES[role], '--geometry=' + geometry, '--', *cmd]
    if name == 'xterm':
        return [executable, '-T', TITLES[role], '-geometry', geometry, '-e', *cmd]
    raise ValueError('支持 xfce4-terminal、gnome-terminal 或 xterm')


def window_geometries():
    width, height = 1600, 900
    if shutil.which('xrandr'):
        try:
            p = subprocess.run(['xrandr', '--current'], capture_output=True, text=True, timeout=3)
            match = re.search(r'current\s+(\d+)\s+x\s+(\d+)', p.stdout)
            if match:
                width, height = map(int, match.groups())
        except (OSError, subprocess.TimeoutExpired):
            pass
    cols = max(34, min(110, (width // 2 - 30) // 9))
    rows = max(9, min(26, (height // 2 - 75) // 19))
    bottom_cols = max(cols, min(130, (width - 30) // 9))
    return (f'{cols}x{rows}+0+0', f'{cols}x{rows}+{width//2}+0',
            f'{bottom_cols}x{rows}+0+{height//2}')


def install_desktop(root: Path):
    script = Path(__file__).resolve()
    command = ' '.join('"' + str(x).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
                       for x in (sys.executable, script, '--root', root))
    entry = ('[Desktop Entry]\nType=Application\nName=云拓离线AI三终端\n'
             'Comment=语音识别 → 本地大模型 → 语音合成（演示问答）\n'
             f'Exec={command}\nPath={root}\nIcon=utilities-terminal\nTerminal=false\nCategories=Utility;\n')
    desktop = Path.home() / 'Desktop'
    if shutil.which('xdg-user-dir'):
        p = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            desktop = Path(p.stdout.strip())
    for directory in (desktop, Path.home() / '.local/share/applications'):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'yuntuo-ai-demo.desktop'
        path.write_text(entry, encoding='utf-8')
        path.chmod(0o755)
        print('已安装启动入口：' + str(path))


def check(root: Path, cfg):
    base, tts = urls(cfg)
    print('项目目录：', root)
    print('图形会话：', os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY') or '未登录图形桌面/当前为SSH')
    print('终端程序：', next((shutil.which(x) for x in ('xfce4-terminal', 'gnome-terminal', 'xterm') if shutil.which(x)), '未安装'))
    print('sherpa_onnx：', bool(importlib.util.find_spec('sherpa_onnx')))
    print('ASR模型：', cfg.get('SHERPA_ASR_MODEL_DIR', '未配置'))
    print('麦克风：', cfg.get('AUDIO_DEVICE', 'plughw:CARD=Device,DEV=0'))
    print('扬声器：', cfg.get('TTS_PLAYER_CMD', 'aplay'))
    for label, url in (('LLM', base.removesuffix('/v1') + '/health'), ('TTS', tts.rsplit('/', 1)[0] + '/health')):
        try:
            print(label, json.dumps(get_json(url, timeout=3), ensure_ascii=False))
        except Exception as exc:
            print(label, '不可用：', exc)


def launch(root: Path):
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        raise RuntimeError('请先登录 RK3588 图形桌面，再在该桌面运行脚本；SSH 普通终端不能直接弹出桌面窗口。')
    terminal = next((shutil.which(x) for x in ('xfce4-terminal', 'gnome-terminal', 'xterm') if shutil.which(x)), None)
    if not terminal:
        raise RuntimeError('没有找到终端模拟器：需要 xfce4-terminal、gnome-terminal 或 xterm')
    import fcntl
    runtime = Path.home() / '.cache/yuntuo-ai-demo'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'launcher.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('演示已经打开，请使用现有的三个窗口。') from None
        session = Path(tempfile.mkdtemp(prefix='session-', dir=runtime))
        print('演示记录：' + str(session), flush=True)
        geometries = window_geometries()
        old_signals = {}
        def stop_launcher(_sig=None, _frame=None):
            raise KeyboardInterrupt
        for sig in (signal.SIGTERM, signal.SIGHUP):
            old_signals[sig] = signal.signal(sig, stop_launcher)
        try:
            for role, geometry in zip(ROLES, geometries):
                cmd = [sys.executable, '-u', str(Path(__file__).resolve()), '--root', str(root),
                       '--role', role, '--session', str(session)]
                with (session / (role + '_terminal.log')).open('w') as log:
                    subprocess.Popen(terminal_command(terminal, role, cmd, geometry), stdout=log, stderr=log)
            deadline = time.monotonic() + 20
            while not all((session / (role + '.ready')).exists() for role in ROLES):
                if stopped(session) or time.monotonic() > deadline:
                    raise RuntimeError('部分终端没有打开，查看 ' + str(session) + ' 下的 *_terminal.log')
                time.sleep(.2)
            print('三个窗口已打开。在 ASR 窗口按回车开始录音；关闭任一窗口结束演示。', flush=True)
            while not stopped(session):
                # X/terminal close can terminate a worker without running finally.
                for role in ROLES:
                    pid = json.loads((session / (role + '.ready')).read_text())['pid']
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        (session / 'STOP').touch()
                time.sleep(.3)
        finally:
            (session / 'STOP').touch()
            # Interrupt only our own surviving worker command lines. Services stay up.
            for role in ROLES:
                ready = session / (role + '.ready')
                if not ready.exists() or (session / (role + '.done')).exists():
                    continue
                pid = json.loads(ready.read_text())['pid']
                try:
                    argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                    if os.fsencode(session) in argv and os.fsencode(Path(__file__).resolve()) in argv:
                        os.kill(pid, signal.SIGTERM)
                except (FileNotFoundError, ProcessLookupError):
                    pass
            # Keep tiny processing logs, remove this demo's recorded/generated audio.
            for name in ('recording.wav', 'reply.wav'):
                (session / name).unlink(missing_ok=True)
            for sig, previous in old_signals.items():
                signal.signal(sig, previous)


def main():
    ap = argparse.ArgumentParser(description='RK3588 离线语音 / LLM / TTS 三终端演示')
    ap.add_argument('--root', type=Path, default=Path(os.environ.get('QHXD_ROOT', Path(__file__).resolve().parents[1])))
    ap.add_argument('--check', action='store_true', help='只检查配置与本机服务，不录音、不推理、不弹窗')
    ap.add_argument('--install-desktop', action='store_true', help='安装桌面/应用菜单启动入口')
    ap.add_argument('--role', choices=ROLES, help=argparse.SUPPRESS)
    ap.add_argument('--session', help=argparse.SUPPRESS)
    args = ap.parse_args()
    root = args.root.expanduser().resolve()
    cfg = config(root)
    urls(cfg)  # reject remote/cloud endpoints before starting any worker
    if args.role:
        if not args.session:
            ap.error('worker requires --session')
        worker(args, cfg)
    elif args.check:
        check(root, cfg)
    elif args.install_desktop:
        install_desktop(root)
    else:
        launch(root)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print('启动失败：' + str(exc), file=sys.stderr, flush=True)
        if os.environ.get('DISPLAY') and shutil.which('zenity'):
            subprocess.run(['zenity', '--error', '--text=' + str(exc)], check=False)
        raise SystemExit(1)
