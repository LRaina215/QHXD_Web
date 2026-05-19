# PHASE4B_DONE.md

## 阶段结论

Phase 4B voice interaction is functionally complete and ready for acceptance. The implementation now covers both uploaded wav commands and RK3588 server-side USB microphone recording, while preserving the existing `mission_gateway` behavior.

This acceptance preparation only updates documentation and this done record. It does not add new features and does not change mission behavior.

## Completed Scope

- Added and documented uploaded wav command flow: `POST /api/voice/audio_command`.
- Added and documented RK3588 server-side recording flow: `POST /api/voice/record_command`.
- Documented FunASR model path environment variables and model caching behavior.
- Documented `AUDIO_DEVICE` and related `arecord` environment variables.
- Documented `voice_records` retention/deletion behavior.
- Documented supported voice commands and waypoint aliases.
- Documented known limitations: no wake word, no streaming ASR, no browser microphone recording, no LLM/OpenClaw.
- Added a manual acceptance checklist in README.

## Key Code / Documentation References

- `README.md:256` Phase 4B voice acceptance section.
- `README.md:271` supported voice commands table.
- `README.md:286` waypoint alias documentation.
- `README.md:355` FunASR model caching behavior.
- `README.md:366` `/api/voice/audio_command` usage.
- `README.md:425` `/api/voice/record_command` usage.
- `README.md:488` `voice_records` directory behavior.
- `README.md:522` known limitations.
- `README.md:535` manual acceptance checklist.
- `backend/app/main.py:323` uploaded wav endpoint: `/api/voice/audio_command`.
- `backend/app/main.py:348` server-side recording endpoint: `/api/voice/record_command`.
- `backend/app/main.py:210` shared ASR result -> voice command -> mission gateway flow.
- `backend/app/services/audio_recorder.py:22` `arecord` based USB microphone recording.
- `backend/app/services/audio_recorder.py:103` `AUDIO_DEVICE`, sample rate, channel, format, and record directory config.
- `backend/app/services/audio_recorder.py:121` unique `voice_YYYYMMDD_HHMMSS_mmm_<uuid8>.wav` filename generation.
- `backend/app/services/asr_service.py:70` FunASR cached model detection.
- `backend/app/services/asr_service.py:73` cached model calls report `model_load_time_s=0.0`.
- `frontend/src/App.vue:567` Dashboard server-side record button handler.
- `frontend/src/App.vue:834` Dashboard “语音任务入口” card.

## Supported Commands

| Category | intent / command | Example utterances |
| --- | --- | --- |
| Go to waypoint | `go_to_waypoint` | `去二零一实验室`, `去201`, `去一号点`, `送到实验室` |
| Start patrol | `start_patrol` | `开始巡检` |
| Pause task | `pause_task` | `暂停任务` |
| Resume task | `resume_task` | `继续任务`, `恢复任务` |
| Return home | `return_home` | `返回起点`, `返航`, `回家` |
| Query status | `query_status` | `当前状态`, `现在在哪` |

Unknown commands or unresolved waypoint commands return `accepted=false` or `intent=unknown` and must not trigger mission execution.

## Waypoint Aliases

Waypoint aliases are configured in `backend/app/config/waypoints.json`.

Current aliases:

- `wp_201` / 二零一实验室: `二零一实验室`, `201实验室`, `二零一`, `201`.
- `wp_001` / 一号点: `一号点`, `1号点`, `1 号点`, `一号`, `201`, `实验室`, `送到实验室`.
- `wp_002` / 二号点: `二号点`, `2号点`, `2 号点`, `二号`, `202`.
- `home` / 起点: `起点`, `home`, `家`.

Alias matching follows the order in `waypoints.json`; if an alias appears in multiple waypoints, the first matching waypoint wins.

## Known Limitations

- No wake word.
- No streaming ASR.
- No browser microphone recording; the Dashboard button calls RK3588 backend recording.
- No multi-turn voice dialogue.
- No LLM free-form task planning.
- No OpenClaw integration.
- No direct motor control from voice.

## Manual Acceptance Checklist

- [ ] Backend starts successfully.
- [ ] `GET /api/state/latest` returns `success=true`.
- [ ] `/api/voice/audio_command` known-command mock (`VOICE_MOCK_RECOGNIZED_TEXT=去二零一实验室`) returns `go_to_waypoint`, `wp_201`, `accepted=true`.
- [ ] `/api/voice/audio_command` unknown-command mock (`VOICE_MOCK_RECOGNIZED_TEXT=打开窗户`) returns `accepted=false` or `intent=unknown` and does not trigger mission.
- [ ] `/api/voice/record_command` records from `AUDIO_DEVICE=plughw:CARD=Device,DEV=0` and returns a voice command result.
- [ ] `/api/voice/record_command` with `keep_audio=false` deletes the generated wav and returns `audio_path=null`.
- [ ] Wrong `AUDIO_DEVICE` returns `audio_record_failed` and does not trigger mission.
- [ ] Dashboard shows “语音任务入口”.
- [ ] Dashboard button disables while waiting and recovers after completion.
- [ ] Unknown voice is displayed as not accepted, not as task success.
- [ ] FunASR first request reports model load time; subsequent requests in the same process report `model_load_time_s=0.0`.

## Validation Notes

Previous Phase 4B validation confirmed:

- Unit tests passed: `Ran 21 tests ... OK`.
- Real USB microphone recording worked with `plughw:CARD=Device,DEV=0`.
- Wrong device returned `audio_record_failed`.
- FunASR cache behavior worked: first call reported model load time, second call reported `model_load_time_s=0.0`.

This acceptance-prep pass reran light regression after docs update:

- Backend temporary startup check on `127.0.0.1:8024`: passed.
- `GET /api/state/latest`: returned `success=True`, task state `idle`.
- `audio_command` known command with `VOICE_MOCK_RECOGNIZED_TEXT=去二零一实验室`: returned `go_to_waypoint`, `wp_201`, `accepted=True`, task state `running`.
- `record_command` with real USB recording and `keep_audio=false`: returned `go_to_waypoint`, `wp_201`, `accepted=True`, `audio_path=None`, `audio_retained=False`.
- `audio_command` unknown command with `VOICE_MOCK_RECOGNIZED_TEXT=打开窗户`: returned `accepted=False`, `need_confirm=True`, `task_status=None`, detail `未知文本命令，未触发机器人任务。`.
- Temporary validation servers on ports `8024` and `8025` were stopped after validation.
