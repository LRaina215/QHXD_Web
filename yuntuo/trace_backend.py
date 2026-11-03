"""ASGI entrypoint adding observers to existing business calls, with no model loading."""
from __future__ import annotations
import time

from yuntuo.processing_trace import RequestObserver, emit, observe, start, trace_id


def install():
    from app.services.asr_service import ASRService
    from app.services.audio_recorder import AudioRecorder
    from app.services.voice.llm_client import DeepSeekClient
    from app.services.voice.llm_intent_parser import LLMIntentParser
    from app.services.voice_entry import VoiceEntryService
    from app.services.smart_voice_service import SmartVoiceService
    from app.services.tts_service import TTSService
    from app.services.mission_gateway import MissionGateway
    from app.services.nav2_mission_adapter import Nav2MissionAdapter

    pending = {}

    def created(bound, result):
        # Bound lookup is bounded and process-local, like the existing confirmation registry.
        now = time.monotonic()
        for key, (_, at) in list(pending.items()):
            if now-at > 600:
                pending.pop(key, None)
        if len(pending) >= 512:
            pending.pop(next(iter(pending)))
        pending[result] = (trace_id(), now)
        return {'pending_command_id': result, 'state': 'waiting_for_explicit_confirmation'}

    def confirm(bound):
        request = bound['request']
        previous = pending.pop(request.pending_command_id, None)
        return {'request': request, 'related_trace': previous[0] if previous else None}

    observe(AudioRecorder, 'record', 'ASR', lambda b: {'record_seconds': b['duration']},
            lambda b, r: {'success': r.success, 'audio_device': r.audio_device, 'detail': r.detail, 'error': r.error})
    observe(ASRService, 'transcribe_audio_file', 'ASR', lambda b: {'backend': b['self'].backend},
            lambda b, r: {'result': r})
    for name in ('chat_json', 'chat_text'):
        observe(DeepSeekClient, name, 'LLM',
                lambda b: {'input': b.get('user_prompt'),
                           'backend': b['self'].config(b.get('force_enable')).backend,
                           'model': b['self'].config(b.get('force_enable')).model},
                lambda b, r: {'success': r.success, 'output': r.content, 'error': r.error,
                               'backend': r.backend, 'model': r.model,
                               'usage': (r.raw_response or {}).get('usage')})
    observe(LLMIntentParser, 'parse', 'LLM', lambda b: {'text': b['text'], 'use_llm': b.get('use_llm')},
            lambda b, r: {'parsed': r, 'parser': r.parser,
                           'note': '规则命中，不表示调用过大模型' if r.parser == 'rule' else '以实际子步骤为准'})
    observe(SmartVoiceService, 'handle', 'LLM', lambda b: {'request': b['request']},
            lambda b, r: {'result': r[0]})
    observe(VoiceEntryService, '_create_pending', 'TASK', after=created)
    observe(VoiceEntryService, 'confirm_pending_command', 'TASK', before=confirm,
            after=lambda b, r: {'result': r[0]})
    observe(VoiceEntryService, 'handle_text_command', 'TASK',
            lambda b: {'request': b['request']}, lambda b, r: {'result': r[0]})
    for name in ('speak_with_policy', 'speak'):
        observe(TTSService, name, 'TTS', lambda b: {'text': b['text']},
                lambda b, r: {'result': r})
    observe(TTSService, '_maybe_local_play', 'TTS', lambda b: {'audio_path': b['audio_path']},
            lambda b, r: {'note': '播放调度函数已返回，不等于扬声器已播完'})
    # Public gateway methods include preflight rejections before _dispatch.
    for name in ('go_to_waypoint', 'go_to_point', 'start_patrol', 'return_home',
                 'search_target', 'follow_target', 'pause', 'resume', 'cancel'):
        if hasattr(MissionGateway, name):
            observe(MissionGateway, name, 'TASK', lambda b: {'request': b.get('request')},
                    lambda b, r: {'result': r[0]})
    observe(Nav2MissionAdapter, 'forward', 'TASK',
            lambda b: {k: b.get(k) for k in ('command', 'source', 'payload')},
            lambda b, r: {'bridge_response': r[0], 'note': '桥接受理响应，不等于实际到达/停稳'})


start('backend')
install()
from app.main import app as business_app  # existing routes, state and middleware unchanged
app = RequestObserver(business_app)
emit('SYSTEM', 'observer.ready', service='backend', observes='existing Web/mini-program requests')
