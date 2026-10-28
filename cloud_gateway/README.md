# Lingxun Cloud Gateway

Cloud Gateway runs on the cloud server and forwards public Dashboard/API traffic to the RK3588 backend. Model inference, RGB-D perception, audio and the FPGA task bridge stay on RK3588. Cloud services provide access control and media delivery; they do not run the FPGA navigation or balance loop.

**2026-10-27 architecture sync:** Web map upload/ACK progress and explicitly labelled preview are deployed. Browser HLS and mini-program signed HLS use the same MediaMTX source as WebRTC. A reachable gateway/RK does not prove FPGA availability: the 22:01 read-only snapshot was real mode with both FPGA data links offline. See [system architecture](https://github.com/LRaina215/SOC_FPGA_NAV/blob/main/docs/system_architecture.md), [map upload](../docs/MAP_UPLOAD_20261027.md), [mini-program video](MINIPROGRAM_VIDEO.md) and [hardware integration evidence](../docs/REAL_FPGA_INTEGRATION_20261027.md). No service deployment is part of this documentation update.

## Public Entrypoints

- Web frontend: `https://lingxunrobot.cn`
- Web same-origin API: `https://lingxunrobot.cn/api`
- Web same-origin WS: `wss://lingxunrobot.cn/ws/state`, `wss://lingxunrobot.cn/ws/navigation` (`/ws/imu` is a retained diagnostic route)
- External API: `https://api.lingxunrobot.cn`
- External WS: `wss://api.lingxunrobot.cn/ws/state`, `wss://api.lingxunrobot.cn/ws/navigation`

Both public entrypoints proxy to Cloud Gateway on `127.0.0.1:9000`.

## Environment

Copy `.env.example` to `/etc/lingxun-cloud-gateway.env`:

```bash
RK_BACKEND_BASE_URL=http://100.113.173.115:8000
PUBLIC_API_TOKEN=replace-with-a-secret-token
PUBLIC_CONTROL_ENABLED=false
PUBLIC_RATE_LIMIT_PER_MINUTE=60
PUBLIC_AUDIO_MAX_MB=20
PUBLIC_BROWSER_AUDIO_MAX_MB=5
PUBLIC_BROWSER_AUDIO_MAX_SECONDS=10
```

`PUBLIC_CONTROL_ENABLED` must default to `false`. Mission control is rejected unless a valid bearer token is present and this switch is set to `true`.

## Public Endpoint Policy

Allowed read endpoints:

- `GET /health`
- `GET /api/gateway/health` (same payload as `/health`; the main domain only proxies `/api/` and `/ws/`, so the mini program reads it here)
- `GET /api/state/latest`
- `GET /api/alerts`
- `GET /api/commands/logs`
- `GET /api/tasks/current`
- `GET /api/imu/latest`
- `GET /api/perception/latest_frame`
- `GET /api/perception/frame_stream`
- `WS /ws/state`
- `WS /ws/imu`

Allowed write endpoints with bearer-token auth:

- `POST /api/voice/text_command`
- `POST /api/voice/audio_command`
- `POST /api/voice/browser_audio_command`
- `POST /api/voice/confirm_command`
- `POST /api/robot/voice/onboard_record_command`
- `POST /api/mission/*`
- `POST /api/system/mode/switch`

Blocked public endpoint:

- `POST /api/voice/record_command`

`record_command` records on the server machine and is only meaningful on RK3588 local testing. Public browser voice records on the current browser device and uploads to `/api/voice/browser_audio_command`; public onboard voice uses `/api/robot/voice/onboard_record_command`, which safely forwards to RK3588 `/api/voice/record_command`.

## Voice Entrypoints

Browser microphone:

```text
Browser MediaRecorder webm/ogg/wav
-> POST /api/voice/browser_audio_command
-> Cloud Gateway ffmpeg converts to 16kHz mono wav
-> RK3588 /api/voice/audio_command
```

Onboard microphone:

```text
POST /api/robot/voice/onboard_record_command
-> RK3588 /api/voice/record_command
```

The cloud server must have `ffmpeg` installed for browser microphone upload:

```bash
ffmpeg -version
```

## Install On Cloud Server

```bash
sudo mkdir -p /opt/lingxun-cloud-gateway
sudo rsync -av ./ /opt/lingxun-cloud-gateway/
sudo chown -R ubuntu:ubuntu /opt/lingxun-cloud-gateway

cd /opt/lingxun-cloud-gateway
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

sudo cp lingxun-cloud-gateway.service /etc/systemd/system/lingxun-cloud-gateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now lingxun-cloud-gateway
```

## Logs And Checks

```bash
systemctl status lingxun-cloud-gateway
journalctl -u lingxun-cloud-gateway -f
tail -f /var/log/lingxun-cloud-gateway/operations.jsonl
curl http://127.0.0.1:9000/health
```
