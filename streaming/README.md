# QHXD independent video path

The public video path is separate from FastAPI state and YOLO inference:

```text
Hikrobot MVS camera
  -> bounded frame publisher
  -> Rockchip MPP H.264
  -> RTMP over Tailscale
  -> cloud MediaMTX
  -> WebRTC/WHEP (primary) or LL-HLS (fallback)
```

The current `MV-CS020-10UC` is a USB MVS camera, not an IP camera with an RTSP
substream. RK3588 therefore encodes its raw RGB frames with Rockchip MPP. A
future Hik network camera can publish/copy H.264 into the same MediaMTX path
without changing the browser contract.

The Hikrobot camera remains owned by `camera_detect_service.py`. A dedicated
latest-frame producer reads the camera at `max(detection_fps, stream_fps)`.
YOLO samples the newest frame at its own rate, while a bounded publisher sends
frames to MPP. No second MVS process can steal the exclusive camera handle.
The stream queue is limited to one or two frames; old frames are dropped
instead of increasing latency or memory usage.

## Cloud files

- `cloud/mediamtx.yml`: one-path MediaMTX configuration.
- `cloud/lingxun-mediamtx.service`: hardened systemd unit.
- `cloud/nginx-video-locations.conf`: same-origin WebRTC and HLS reverse proxy.

MediaMTX delegates publisher authentication to the existing Cloud Gateway
endpoint `POST /internal/media-auth`. Browser reads are loopback-only behind
Nginx. The browser first authenticates its existing public API token at
`POST /api/video/session`; Nginx then protects `/video/*` with the resulting
short-lived, Secure, HttpOnly session cookie.

Required cloud gateway variables:

```env
MEDIA_PUBLISH_USER=robot-publisher
MEDIA_PUBLISH_PASSWORD=replace-with-a-separate-publish-secret
MEDIA_STREAM_PATH=robot/front
VIDEO_SESSION_SECRET=replace-with-a-separate-random-secret
VIDEO_SESSION_TTL_SECONDS=600
```

The RTMP publish URL format is:

```text
rtmp://100.118.160.119:1935/robot/front?user=robot-publisher&pass=SECRET
```

Keep this value in the RK root `.env` as `QHXD_VIDEO_STREAM_URL`; never commit
the credential.

## RK settings

Add these fields to the active Hik camera JSON after the cloud relay is ready:

```json
{
  "stream_enabled": true,
  "stream_url": "",
  "stream_fps": 10.0,
  "stream_width": 1280,
  "stream_height": 720,
  "stream_bitrate": 1200000,
  "stream_queue_size": 2,
  "stream_reconnect_interval": 3.0
}
```

Keep `fps` at 5 for YOLO unless inference capacity has been revalidated. The
camera producer and H.264 publisher can run at 10 FPS independently. The RTMP
URL in `.env` must be shell-quoted because its query string contains `&`.

## Network and acceptance

- Allow `8189/TCP` and `8189/UDP` in the Tencent Cloud security group.
- Keep MediaMTX WHEP/HLS listeners on loopback behind Nginx.
- Publish RTMP to the cloud Tailscale address; public port 1935 is unnecessary.
- `curl http://127.0.0.1:9997/v3/paths/list` must show `robot/front` ready with
  an H264 track.
- A connected browser must appear as `webRTCSession`. HLS is fallback only;
  MJPEG is the final compatibility fallback.
