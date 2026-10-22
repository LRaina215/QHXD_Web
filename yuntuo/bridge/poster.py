"""向 RK3588 后端（FastAPI :8000）上送：任务事件逐条发送；导航快照、平台状态等按 key 只保留最新一条。"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict, deque
from urllib import request

log = logging.getLogger("fpga_bridge")


class BackendPoster(threading.Thread):
    def __init__(self, base_url: str, timeout_s: float = 1.0) -> None:
        super().__init__(daemon=True, name="backend-poster")
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.cond = threading.Condition()
        self.events: deque[tuple[str, dict]] = deque(maxlen=64)
        self.latest: OrderedDict[str, tuple[str, dict]] = OrderedDict()
        self.opener = request.build_opener(request.ProxyHandler({}))
        self.failures = 0
        self._last_warn = 0.0

    def post_event(self, path: str, payload: dict) -> None:
        with self.cond:
            self.events.append((path, payload))
            self.cond.notify()

    def post_latest(self, key: str, path: str, payload: dict) -> None:
        with self.cond:
            self.latest[key] = (path, payload)
            self.latest.move_to_end(key)
            self.cond.notify()

    def _next(self) -> tuple[str, dict, bool] | None:
        with self.cond:
            while not self.events and not self.latest:
                self.cond.wait(timeout=1.0)
            if self.events:
                path, payload = self.events.popleft()
                return path, payload, True
            if self.latest:
                _, (path, payload) = self.latest.popitem(last=False)
                return path, payload, False
        return None

    def run(self) -> None:
        while True:
            item = self._next()
            if item is None:
                continue
            path, payload, is_event = item
            for attempt in range(3 if is_event else 1):
                if self._send(path, payload):
                    break
                time.sleep(0.2 * (attempt + 1))

    def _send(self, path: str, payload: dict) -> bool:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(self.base_url + path, data=body, headers={"Content-Type": "application/json"},
                              method="POST")
        try:
            with self.opener.open(req, timeout=self.timeout_s) as resp:
                resp.read()
            self.failures = 0
            return True
        except Exception as exc:
            self.failures += 1
            now = time.monotonic()
            if now - self._last_warn > 10.0:
                self._last_warn = now
                log.warning("上送后端 %s 失败（累计 %d 次）：%s", path, self.failures, exc)
            return False


class ListPoster:
    """测试用：只记录"""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.latest: dict[str, tuple[str, dict]] = {}

    def post_event(self, path: str, payload: dict) -> None:
        self.events.append((path, payload))

    def post_latest(self, key: str, path: str, payload: dict) -> None:
        self.latest[key] = (path, payload)
