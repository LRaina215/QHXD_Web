"""Observer contracts: unchanged calls, separate concurrent IDs, queue != transport success."""
import asyncio
import sys
from pathlib import Path
import pytest

from yuntuo import processing_trace as tr


def test_observation_does_not_repeat_or_replace_business_result(monkeypatch):
    events = []
    monkeypatch.setattr(tr, 'emit', lambda *args, **kw: events.append((args, kw)))
    result = object()
    class Business:
        calls = 0
        def run(self, value):
            self.calls += 1
            return result
    def failed_log(*args):
        raise OSError('no log directory')
    tr.observe(Business, 'run', 'TEST', failed_log, failed_log)
    b = Business()
    assert b.run(123) is result
    assert b.calls == 1


def test_original_business_exception_is_preserved(monkeypatch):
    monkeypatch.setattr(tr, 'emit', lambda *args, **kw: None)
    failure = ValueError('original failure')
    class Business:
        def run(self):
            raise failure
    tr.observe(Business, 'run', 'TEST')
    with pytest.raises(ValueError) as seen:
        Business().run()
    assert seen.value is failure


def test_concurrent_asgi_requests_propagate_context_into_worker_threads(monkeypatch):
    events = []
    monkeypatch.setattr(tr, 'emit', lambda stage, event, **kw: events.append((tr.trace_id(), stage, event, kw)))
    async def app(scope, receive, send):
        await asyncio.to_thread(tr.emit, 'ASR', 'real.worker', marker=scope['path'])
        await asyncio.sleep(.001)
        await send({'type':'http.response.start','status':202,'headers':[]})
        await send({'type':'http.response.body','body':b'original'})
    observed = tr.RequestObserver(app)
    async def run():
        async def one(path):
            sent = []
            async def send(message):
                sent.append(message)
            await observed({'type':'http','method':'POST','path':path}, None, send)
            return sent
        return await asyncio.gather(one('/api/voice/a'), one('/api/voice/b'))
    responses = asyncio.run(run())
    assert all(r[-1]['body'] == b'original' and r[0]['status'] == 202 for r in responses)
    workers = [x for x in events if x[2] == 'real.worker']
    assert len(workers) == 2 and workers[0][0] != workers[1][0]
    assert all(len([x for x in events if x[0] == w[0]]) == 3 for w in workers)
    assert tr.trace_id() == ''


def test_bridge_queue_and_transport_failure_are_distinct(monkeypatch):
    from yuntuo.trace_bridge import install
    from yuntuo.bridge.core import FpgaBridge, PendingRequest
    from yuntuo.bridge.config import BridgeConfig
    from yuntuo.bridge.poster import ListPoster
    from yuntuo.fpga_link.nv_proto import encode_goal
    install()
    events = []
    def capture(stage, event, **kw):
        kw.setdefault('trace', tr.trace_id())
        events.append((event, kw))
    monkeypatch.setattr(tr, 'emit', capture)
    bridge = FpgaBridge(BridgeConfig(), poster=ListPoster())
    class Link:
        failure = False
        sent = []
        def send(self, data):
            if self.failure:
                raise OSError('transport down')
            self.sent.append(data)
    bridge.link = Link()
    goal = encode_goal(123, -456)
    with tr.context() as root:
        request = PendingRequest('mission', {'command':'unsupported'})
        bridge._send(goal)
    assert [x[0] for x in events] == ['nv.queued']
    assert bridge.outbox.popleft() is goal
    bridge._transmit(goal)
    assert events[-1][0] == 'nv.transport.sent' and events[-1][1]['trace'] == root
    assert bridge.link.sent == [goal]
    # Request crosses the HTTP -> tick thread boundary with the same ID.
    bridge._handle_request(request, bridge.clock())
    request_events = [x for x in events if x[0] == 'bridge.request']
    assert request_events[-1][1]['trace'] == root
    with tr.context(root):
        bridge._send(goal)
    bridge.link.failure = True
    with pytest.raises(OSError, match='transport down'):
        bridge._transmit(bridge.outbox.popleft())
    assert events[-1][0] == 'nv.send.failed'
    assert sum(e[0] == 'nv.transport.sent' for e in events) == 1


def test_backend_hooks_observe_one_real_call_without_loading_models(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'backend'))
    from app.services.asr_service import ASRService, ASRResult
    import yuntuo.trace_backend as backend
    result = ASRResult('真实识别结果', '真实识别结果', 'sherpa', True, asr_time_s=.12)
    calls = []
    monkeypatch.setattr(ASRService, 'transcribe_audio_file', lambda self,audio_path: (calls.append(audio_path),result)[1])
    # Install after substituting only the expensive inference in this contract test.
    backend.install()
    events = []
    monkeypatch.setattr(tr, 'emit', lambda stage,event,**kw: events.append((stage,event,kw)))
    with tr.context():
        returned = ASRService().transcribe_audio_file('only-once.wav')
    assert returned is result and calls == ['only-once.wav']
    assert events[-1][0] == 'ASR' and events[-1][2]['result'] is result


@pytest.mark.parametrize('parser,backend,expected', [('llm','local','local'),('builtin','local','builtin')])
def test_visible_reply_source_matches_actual_parser(monkeypatch, tmp_path, parser, backend, expected):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'backend'))
    from app.schemas import SmartCommandRequest
    from app.services.intent_parser import ParsedIntent
    from app.services.smart_voice_service import SmartVoiceService, llm_intent_parser
    monkeypatch.setattr(llm_intent_parser, 'parse', lambda *args,**kw: ParsedIntent(
        intent='open_chat', detail='实际回复', parser=parser, llm_backend=backend))
    result, _ = SmartVoiceService(tmp_path/'voice.jsonl').handle(
        SmartCommandRequest(text='只问答', generate_tts=False))
    assert result.data_source == expected
