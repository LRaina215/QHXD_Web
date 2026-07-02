# 独立低延迟视频链路完成记录

## 完成内容

- RK3588 保持单一 Hikrobot MVS 相机所有者，避免第二进程抢占相机。
- 新增独立最新帧生产线程：相机按 10 FPS 采集/发布，YOLO 按 5 FPS 消费最新帧。
- 新增有界 H.264 发布器：队列固定为 1–2 帧，拥塞时丢旧帧，不累计延迟。
- 使用 RK3588 `mpph264enc` 硬件编码 H.264 Baseline 1280x720，约 1.2 Mbps。
- 视频通过 RTMP/Tailscale 上行到云服务器 MediaMTX。
- 公网页面使用 WebRTC/WHEP 为主路径，HLS 为自动回退，原 MJPEG latest frame 为最终兜底。
- 视频读取复用现有公网 Token 创建短期 HttpOnly 会话 Cookie；发布端使用独立凭据。
- MediaMTX、Cloud Gateway、Nginx 与 RK 发布器均具备重启/重连路径。
- 开机编排按 Hik USB VID `2bdf` 优先、稳定 USB 别名备用，不再把 RK 视频编解码节点误判为相机。
- 脚本托管进程使用 `nohup`，SSH 退出不会停止 YOLO/视频发布器。

## 主要文件

- `experiments/rknn_yolo/camera_detect_service.py`：最新帧生产、YOLO 采样与相机重连。
- `experiments/rknn_yolo/h264_stream_publisher.py`：MPP/GStreamer 有界发布器。
- `frontend/src/components/CloudVideoPlayer.vue`：WHEP、HLS、MJPEG 三级播放策略。
- `cloud_gateway/cloud_gateway.py`：视频会话与 MediaMTX 发布认证。
- `streaming/cloud/mediamtx.yml`：云端媒体服务配置。
- `streaming/cloud/nginx-video-locations.conf`：同域视频反代与会话校验。
- `streaming/cloud/lingxun-mediamtx.service`：MediaMTX systemd 服务。

## 实机验收

- Hik 相机：`MV-CS020-10UC`，MVS SDK 成功打开。
- RKNN YOLO：5 FPS 持续推理并向现有后端提交 `detection_status`，接口未改变。
- 视频输入：1624x1240 RGB；编码输出：H.264 Baseline 1280x720@10 FPS。
- 云端路径：`robot/front` 为 ready/online，入站错误帧为 0。
- WebRTC：浏览器已通过公网 `8189/UDP` 完成 ICE，MediaMTX 显示 `webRTCSession` 正在读取 H.264。
- HLS：带有效视频会话 Cookie 时 playlist 返回合法内容；未授权请求返回 401。
- 自动恢复：MediaMTX 短暂重启后 RK 发布器自动重建 RTMP 管线。
- 播放恢复：RK 发布源中断时页面降级到 HLS；源恢复后自动重建 WebRTC，HLS 会话随后清理。
- 单元测试：RK3588 上相机最新帧与发布器共 7 项测试通过；Cloud Gateway 视频认证/会话 4 项测试通过。

## 运行参数

```text
YOLO fps: 5
camera/stream fps: 10
stream queue: 2 frames
resolution: 1280x720
bitrate: 1200000 bps
primary playback: WebRTC/WHEP
fallback: HLS -> MJPEG
ICE: 8189/TCP + 8189/UDP
```

发布 URL 与密码只保存在 RK3588 根目录 `.env`，不得提交。URL 必须使用单引号包住，避免查询参数中的 `&` 被 shell 解释。

## 边界

- 视频流不直接控制底盘，也不改变 mission 行为。
- YOLO 仍读取原始最新帧；公网播放帧率与 YOLO 推理帧率相互独立。
- 当前公网流不携带音频。
- HLS 与 MJPEG 仅用于 WebRTC 不可用时回退，不是默认播放路径。
