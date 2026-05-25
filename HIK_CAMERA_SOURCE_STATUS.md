# Hik Camera Source Status

## 目标

在保留原 USB / UVC 摄像头入口的前提下，为 RKNN YOLO26 连续检测服务预留并接入 Hikrobot/MVS SDK 采集入口。

## 已完成的软件改动

- `experiments/rknn_yolo/hik_camera_source.py`：新增 Hikrobot MVS SDK 相机源，负责枚举 Hik USB/GigE 设备、打开设备、StartGrabbing、按帧转换为 RGB numpy array。
- `experiments/rknn_yolo/camera_detect_service.py`：新增 `--camera-backend auto|usb|hik`、`--hik-index`、`--hik-serial`、`--hik-timeout-ms`，并在采集层支持 USB 与 Hik 切换。
- `experiments/rknn_yolo/camera_config.json`：默认仍为 `camera_backend=usb`，保留旧 USB 摄像头入口。
- `experiments/rknn_yolo/camera_config_hik.example.json`：Hik 示例配置默认不绑定 serial，打开第 1 台枚举到的 Hik 相机；当前实测设备 serial 为 `DA3860587`。
- `README.md`、`experiments/rknn_yolo/README.md`：补充 USB/Hik 切换方式、启动命令和当前硬件状态。

## 当前硬件测试结果

- MVS SDK 已安装在 `/opt/MVS`。
- 当前 Hik 设备被 USB 层识别为 `2bdf:0001 Hikrobot MV-CS020-10UC`。
- 当前 MVS SDK 标签为 `USB MV-CS020-10UC DA3860587`。
- 已验证 MVS SDK 可枚举、create handle、open、start grabbing，并成功读取 RGB 帧，帧尺寸为 `(1240, 1624, 3)`。
- 已验证 `camera_config_hik.example.json` dry-run 可使用 Hik 帧完成 RKNN YOLO 推理，生成 `outputs/latest_hik_detection.jpg` 和 JSONL。
- 已验证非 dry-run 提交到后端成功返回 `accepted=true`、`state_updated=true`。

## 验证命令

```bash
cd /home/robomaster/QHXD
python3 -m py_compile experiments/rknn_yolo/hik_camera_source.py experiments/rknn_yolo/camera_detect_service.py
```

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config_hik.example.json --dry-run --max-frames 2 --read-fail-limit 2
```

当前 dry-run 输出包含：

```text
Hik camera opened via MVS SDK: USB MV-CS020-10UC DA3860587
frame=1 ... backend=HikCameraSource ...
Saved detection visualization: outputs/latest_hik_detection.jpg
{"detection_status": {"enabled": true, ...}}
```

## 后续人工验收

- [x] 物理重插 Hik 相机，确认系统可枚举 Hik USB3 Vision 设备。
- [x] 本轮测试中 Hik 相机已可被 MVS SDK 打开并读取帧；如后续复现 USB error，再优先检查线缆/供电/USB3 口。
- [x] 运行 Hik dry-run 能打开 MVS SDK 相机并获取至少 1 帧。
- [x] 使用 `camera_config_hik.example.json` 生成 `outputs/latest_hik_detection.jpg`。
- [ ] 切回 `camera_config.json` 后 USB 摄像头入口仍可运行。

## 2026-05-25 实时画面更新修复记录

### 现象

Dashboard 的 YOLO 实时画面没有持续更新。排查后发现有两个问题叠加：

1. Hik 服务保存的是 `outputs/latest_hik_detection.jpg`，但后端 `/api/perception/latest_frame` 默认只读取 USB 入口的 `outputs/latest_camera_detection.jpg`，导致前端可能一直拿到旧图。
2. Hik SDK 在多次打开/停止后出现 USB3 Vision transport 不稳定：Linux `lsusb` 仍能看到 `2bdf:0001 Hikrobot MV-CS020-10UC`，但 MVS SDK 会出现 `enum found no device` 或 `GetImageBuffer ret=0x80000007`，导致 YOLO 服务不能继续产出新图。

### 已修复的软件侧问题

- 后端 `/api/perception/latest_frame` 默认会在 `latest_camera_detection.jpg` 与 `latest_hik_detection.jpg` 中选择 mtime 最新的文件。
- 后端 latest frame 响应增加 `Cache-Control: no-store, no-cache, must-revalidate`，并返回 `X-Latest-Frame-Path`、`X-Latest-Frame-Age` 便于确认前端实际拿到哪张图。
- 后端默认 `PERCEPTION_LATEST_FRAME_MAX_AGE_SECONDS=10`，图片超过 10 秒未更新会返回 `latest_frame_stale`，避免前端把旧图片误认为实时流。
- Hik 配置新增 `camera_retry_interval=3.0`，相机不可用或连续读帧失败时会尝试重连。
- `scripts/start_yolo_camera.sh` 改为通过 `scripts/run_yolo_camera_service.sh` 启动 worker；worker 异常退出时会按 `YOLO_RESTART_DELAY` 自动重启，`stop_all.sh` 仍可停止服务。

### 当前硬件侧状态

- `usbreset 008/002` 可让 MVS SDK 从 `enum found no device` 恢复到能打开设备。
- reset 后当前仍出现连续 `GetImageBuffer ret=0x80000007`，说明相机/USB3 transport 层仍未稳定产出帧。
- 软件现在不会再把旧图显示成实时画面；但要恢复真正实时图像，仍需要 Hik SDK 能稳定返回帧。优先检查 USB3 口、线缆、供电，或物理重新插拔相机后观察 `logs/yolo_camera.log`。

### 验证命令

```bash
curl --noproxy '*' -i 'http://127.0.0.1:8000/api/perception/latest_frame?t=check'
```

正常实时更新时应返回 200，且响应头类似：

```text
X-Latest-Frame-Path: /home/robomaster/QHXD/experiments/rknn_yolo/outputs/latest_hik_detection.jpg
X-Latest-Frame-Age: 0.xxx
```

如果相机服务没有产出新图，会返回：

```text
HTTP/1.1 404 Not Found
{"success":false,"error":"latest_frame_stale",...}
```
