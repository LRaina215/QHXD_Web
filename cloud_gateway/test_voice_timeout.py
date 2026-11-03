"""Voice processing gets a longer deadline; control forwarding remains unchanged."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import cloud_gateway as gateway


@pytest.mark.parametrize('path', ['/api/voice/smart_command', '/api/voice/smart_record_command',
                                 '/api/voice/smart_audio_command', '/api/voice/speak'])
def test_voice_deadline(path):
    assert gateway._forward_timeout(path) == gateway.VOICE_FORWARD_TIMEOUT_SECONDS


@pytest.mark.parametrize('path', ['/api/mission/pause', '/api/mission/cancel', '/api/platform/estop',
                                 '/api/voice/confirm_command', '/api/voice/tts/latest'])
def test_control_and_read_deadlines_stay_short(path):
    assert gateway._forward_timeout(path) == gateway.FORWARD_TIMEOUT_SECONDS


@pytest.mark.parametrize('kind', ['json', 'wav'])
def test_actual_forwarders_use_the_voice_budget(monkeypatch, tmp_path, kind):
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value='response')
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(gateway.httpx, 'AsyncClient', factory)
    if kind == 'json':
        result = asyncio.run(gateway._forward_json_to_rk('/api/voice/smart_record_command', {}, 'test'))
    else:
        file = tmp_path / 'test.wav'
        file.write_bytes(b'fixture')
        result = asyncio.run(gateway._forward_wav_to_rk(file, source='test', requested_by='test', keep_audio=False,
                                                      request_id='test', rk_path='/api/voice/smart_audio_command'))
    assert result == 'response'
    assert factory.call_args.kwargs['timeout'] == gateway.VOICE_FORWARD_TIMEOUT_SECONDS
