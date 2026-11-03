"""Bridge entrypoint: observe existing queue, transport sends and FPGA feedback."""
from __future__ import annotations
from collections import OrderedDict
import functools
import struct
import time

from yuntuo import processing_trace as tr


def packet(data):
    if len(data) < 4 or data[:3] != b'NV\x01':
        return None
    kind = data[3]
    result = {'type': {0x10: 'GOAL', 0x12: 'SET_POSE', 0x20: 'TARGET', 0x30: 'MODE'}.get(kind),
              'bytes': len(data)}
    if not result['type']:
        return None
    if kind == 0x10 and len(data) >= 16:
        result.update(zip(('x_mm', 'y_mm', 'yaw_cdeg'), struct.unpack_from('<iii', data, 4)))
    elif kind == 0x30 and len(data) >= 5:
        result['mode'] = {0:'idle', 1:'goto', 2:'track', 3:'search', 4:'estop'}.get(data[4], data[4])
    elif kind == 0x20:
        result['found'] = bool(data[4]) if len(data) > 4 else None
    return result


def install():
    from yuntuo.bridge.server import Handler
    from yuntuo.bridge.core import FpgaBridge, PendingRequest
    from yuntuo.fpga_link.nv_proto import NavStatus
    if getattr(FpgaBridge, '_processing_observer', False):
        return
    FpgaBridge._processing_observer = True

    def patch(cls, name, factory):
        original = getattr(cls, name)
        setattr(cls, name, functools.wraps(original)(factory(original)))

    def http(original):
        def call(self):
            with tr.context(self.headers.get('X-Yuntuo-Trace', '')):
                tr.emit('TASK', 'bridge.http.begin', path=self.path)
                return original(self)
        return call
    patch(Handler, 'do_POST', http)

    def pending(original):
        def call(self, *args, **kw):
            original(self, *args, **kw)
            self._processing_trace = tr.trace_id()
        return call
    patch(PendingRequest, '__init__', pending)

    def origins(self):
        if not hasattr(self, '_processing_tasks'):
            self._processing_tasks = OrderedDict()
        return self._processing_tasks

    def current(self):
        task = self.runner.task
        return tr.trace_id() or (origins(self).get(task.task_id, '') if task else '')

    def handle(original):
        def call(self, req, now):
            with tr.context(getattr(req, '_processing_trace', '')) as identity:
                tr.emit('TASK', 'bridge.request', kind=req.kind, payload=req.payload)
                result = original(self, req, now)
                task = self.runner.task
                if task and result.get('data', {}).get('accepted'):
                    mapping = origins(self)
                    mapping[task.task_id] = identity
                    while len(mapping) > 64:
                        mapping.popitem(last=False)
                tr.emit('TASK', 'bridge.request.result', result=result)
                return result
        return call
    patch(FpgaBridge, '_handle_request', handle)

    def queued(original):
        def call(self, msg, urgent=False):
            result = original(self, msg, urgent)
            try:
                decoded = packet(msg)
                if decoded is not None:
                    if not hasattr(self, '_processing_packets'):
                        self._processing_packets = OrderedDict()
                    # Hold the exact bytes object until send/drop; never change the outbox.
                    metadata = {'identity': current(self), 'packet': decoded,
                                'packet_id': tr.new_id(), 'message': msg}
                    self._processing_packets[id(msg)] = metadata
                    while len(self._processing_packets) > 128:
                        self._processing_packets.popitem(last=False)
                    if decoded['type'] != 'TARGET':
                        tr.emit('TASK', 'nv.queued', trace=metadata['identity'],
                                packet=decoded, packet_id=metadata['packet_id'], note='仅进入原发送队列')
            except Exception:
                pass
            return result
        return call
    patch(FpgaBridge, '_send', queued)

    def sent(original):
        def call(self, msg):
            metadata = getattr(self, '_processing_packets', {}).pop(id(msg), None)
            t0 = time.monotonic()
            try:
                result = original(self, msg)
            except Exception as exc:
                if metadata:
                    tr.emit('TASK', 'nv.send.failed', trace=metadata['identity'],
                            packet=metadata['packet'], packet_id=metadata['packet_id'], error=str(exc))
                raise
            if metadata:
                decoded = metadata['packet']
                # Perception TARGETs can be 12Hz. Keep at most two per second in the display log.
                if decoded['type'] != 'TARGET' or t0-getattr(self, '_processing_target_at', -1e9) >= .5:
                    if decoded['type'] == 'TARGET':
                        self._processing_target_at = t0
                    tr.emit('TASK', 'nv.transport.sent', trace=metadata['identity'], packet=decoded,
                            packet_id=metadata['packet_id'], duration_ms=round((time.monotonic()-t0)*1000, 2),
                            note='原链路发送函数成功返回，不是FPGA应用层执行ACK或到达证据')
            return result
        return call
    patch(FpgaBridge, '_transmit', sent)

    def feedback(original):
        def call(self, msg, now):
            result = original(self, msg, now)
            try:
                if isinstance(msg, NavStatus) and self.status is msg and current(self):
                    key = (msg.mode, msg.state, msg.goal_x_mm, msg.goal_y_mm)
                    if key != getattr(self, '_processing_status_key', None) or now-getattr(self, '_processing_status_at', -1e9) >= 1:
                        self._processing_status_key, self._processing_status_at = key, now
                        tr.emit('TASK', 'fpga.status.observed', trace=current(self),
                                status={k: getattr(msg, k) for k in ('t_us','mode','state','goal_x_mm','goal_y_mm','vx_mmps','wz_mradps','loc_state')},
                                note='真实推进的STATUS观察；不能单独证明停稳')
            except Exception:
                pass
            return result
        return call
    patch(FpgaBridge, '_on_message', feedback)

    def event(original):
        def call(self, payload):
            result = original(self, payload)
            tr.emit('TASK', 'task.feedback', trace=current(self), feedback=payload)
            return result
        return call
    patch(FpgaBridge, '_emit', event)


def main():
    tr.start('bridge')
    install()
    tr.emit('SYSTEM', 'observer.ready', service='bridge')
    from yuntuo.bridge.server import main as business_main
    return business_main()


if __name__ == '__main__':
    raise SystemExit(main())
