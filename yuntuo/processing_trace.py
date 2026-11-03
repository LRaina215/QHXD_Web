"""Bounded, best-effort observation of the real request path, never a command source."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import functools
import inspect
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import re
import threading
import time
from uuid import uuid4

CURRENT = ContextVar('yuntuo_processing_trace', default='')
_queue = queue.Queue(maxsize=1024)
_lock = threading.Lock()
_thread = None
_lost = 0
_component = 'backend'


def trace_id():
    return CURRENT.get()


def new_id(value=''):
    return value if re.fullmatch(r'[a-f0-9]{12,32}', value or '') else uuid4().hex[:16]


@contextmanager
def context(value=''):
    token = CURRENT.set(new_id(value))
    try:
        yield CURRENT.get()
    finally:
        CURRENT.reset(token)


def headers():
    return {'X-Yuntuo-Trace': trace_id()} if trace_id() else {}


def plain(value, depth=0):
    if depth > 5:
        return '[depth limit]'
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    elif is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(k): plain(v, depth+1) for k, v in list(value.items())[:40]
                if not any(s in str(k).lower() for s in ('api_key', 'password', 'authorization', 'secret'))}
    if isinstance(value, (tuple, list)):
        return [plain(x, depth+1) for x in value[:32]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', str(value))[:6000]


def _writer(component, directory):
    global _lost
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ('processing_' + component + '.jsonl')
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        handler = RotatingFileHandler(path, maxBytes=4*1024*1024, backupCount=2, encoding='utf-8')
        while True:
            item = _queue.get()
            if _lost:
                item['dropped_before_this_event'] = _lost
                _lost = 0
            handler.emit(logging.LogRecord('processing', logging.INFO, '', 0,
                                          json.dumps(item, ensure_ascii=False), (), None))
            _queue.task_done()
    except Exception:
        # The observer must never take down or wait on the control/business path.
        while True:
            _queue.get()
            _queue.task_done()


def start(component='backend'):
    global _thread, _component
    if _thread is not None:
        return
    with _lock:
        if _thread is None:
            _component = component
            directory = Path(os.environ.get('YUNTUO_PROCESS_TRACE_DIR', Path(__file__).resolve().parents[1] / 'logs'))
            _thread = threading.Thread(target=_writer, args=(component, directory), daemon=True, name='processing-log')
            _thread.start()


def emit(stage, event, *, trace=None, **data):
    global _lost
    if os.environ.get('YUNTUO_PROCESS_TRACE', '1').lower() in {'0', 'false', 'off'}:
        return
    try:
        start(_component)
        _queue.put_nowait({'at': datetime.now(timezone.utc).astimezone().isoformat(timespec='milliseconds'),
                          'component': _component, 'trace': trace if trace is not None else trace_id(),
                          'stage': stage, 'event': event, 'data': plain(data)})
    except queue.Full:
        _lost += 1
    except Exception:
        pass


def safe(function, *args):
    try:
        return function(*args) or {}
    except Exception:
        return {}


def observe(cls, name, stage, before=None, after=None):
    """Preserve return object, exceptions and call count; observe only."""
    original = getattr(cls, name)
    if getattr(original, '_processing_observer', False):
        return
    signature = inspect.signature(original)

    @functools.wraps(original)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs).arguments
        t0 = time.monotonic()
        emit(stage, name + '.begin', **safe(before, bound))
        try:
            result = original(*args, **kwargs)
        except Exception as exc:
            emit(stage, name + '.error', error_type=type(exc).__name__, error=str(exc),
                 duration_ms=round((time.monotonic()-t0)*1000, 2))
            raise
        emit(stage, name + '.end', duration_ms=round((time.monotonic()-t0)*1000, 2),
             **safe(after, bound, result))
        return result
    wrapped._processing_observer = True
    setattr(cls, name, wrapped)


class RequestObserver:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope.get('type') != 'http' or scope.get('method') != 'POST' or path.startswith('/api/internal/'):
            return await self.app(scope, receive, send)
        with context() as request_id:
            emit('REQUEST', 'http.begin', method='POST', path=path)
            t0 = time.monotonic()
            async def observed_send(message):
                if message['type'] == 'http.response.start':
                    emit('REQUEST', 'http.response', status=message['status'],
                         duration_ms=round((time.monotonic()-t0)*1000, 2))
                await send(message)
            try:
                return await self.app(scope, receive, observed_send)
            except Exception as exc:
                emit('REQUEST', 'http.error', error_type=type(exc).__name__, error=str(exc))
                raise
