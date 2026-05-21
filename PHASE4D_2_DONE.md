# PHASE4D_2_DONE.md

## 阶段结论

Phase 4D_2 已完成“识别图像流”收口：不做 WebRTC / RTSP / MJPEG，而是由 RK3588 YOLO 摄像头服务持续保存最新带框 JPEG，后端提供单张图片接口，Dashboard 定时刷新显示。

```text
camera_detect_service.py
-> outputs/latest_camera_detection.jpg
-> GET /api/perception/latest_frame
-> Dashboard 视觉检测卡片
```

YOLO 结果仍只进入 `detection_status` 和最新识别图片，不控制底盘、导航或 mission。

## 修改文件

- `backend/app/main.py`
  - 新增 `DEFAULT_LATEST_FRAME_PATH` 和 `PERCEPTION_LATEST_FRAME_PATH` 环境变量覆盖。
  - 新增 `GET /api/perception/latest_frame`。
  - 新增 `HEAD /api/perception/latest_frame`，用于 `curl -I` 验收。
  - 图片存在时返回 `image/jpeg` 和 `Cache-Control: no-store`。
  - 图片不存在时返回结构化错误 `latest_frame_not_found`。
- `frontend/src/App.vue`
  - 在现有“视觉检测状态”卡片中新增最新识别图片区域。
  - 图片来源为 `/api/perception/latest_frame?t=Date.now()`。
  - 每 2 秒刷新一次，加载失败时显示“暂无识别画面”。
  - 保留原 source / model / objects / events / timestamp 显示。
- `frontend/src/style.css`
  - 新增最新识别图片容器样式。
- `experiments/rknn_yolo/camera_detect_service.py`
  - 新增 `--config` 支持。
  - 默认 `save_latest=outputs/latest_camera_detection.jpg`。
  - 保留 CLI 启动，命令行参数覆盖配置文件。
  - dry-run stdout 现在保持纯 JSONL，RKNN 原生日志进入 stderr。
- `experiments/rknn_yolo/camera_config.json`
  - 新增推荐运行配置。
- `experiments/rknn_yolo/README.md`
  - 新增 Phase 4D_2 识别图像流 runbook。
- `README.md`
  - 新增项目总入口说明。

## 配置文件

当前推荐配置：

```json
{
  "model": "models/yolo26n_fp32.rknn",
  "labels": "models/labels.txt",
  "camera": 0,
  "conf": 0.25,
  "fps": 1,
  "frame_id": "camera_front",
  "backend_url": "http://127.0.0.1:8000",
  "submit": true,
  "save_latest": "outputs/latest_camera_detection.jpg",
  "max_det": 20,
  "output_layout": "xyxy_score_class"
}
```

启动：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json
```

优先级：命令行参数 > 配置文件 > 内置默认值。

## 实机验收结果

### YOLO 服务配置启动

已执行：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json --max-frames 3
```

结果：

```text
latest_frame_updated = True
latest_frame_exists = True
latest_frame size = 304805 bytes
camera_backend_logged = True
summaries = 3
submit_success = 4  # 3 帧 + 最终 service_stopped
```

补充验证：OpenCV 采集路径已可用，服务启动日志显示：

```text
Camera detection service started: camera=0, backend=OpenCvCameraSource, fps=1.0, submit=False, dry_run=True
```

首次验收时使用过 `FfmpegCameraSource` fallback；当前 fallback 仍保留，但不再是默认实测路径。

### 后端图片接口

已从 `backend/` 目录启动临时后端：

```bash
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8028
```

已执行：

```bash
curl -I http://127.0.0.1:8028/api/perception/latest_frame
```

结果：

```text
HTTP/1.1 200 OK
Content-Type: image/jpeg
Cache-Control: no-store
Content-Length: 304805
```

已执行：

```bash
curl http://127.0.0.1:8028/api/perception/latest_frame --output /tmp/latest_frame_phase4d2.jpg
file /tmp/latest_frame_phase4d2.jpg
```

结果：

```text
JPEG image data, 1920x1080, components 3
```

### 缺图错误

已用环境变量启动临时后端：

```bash
PERCEPTION_LATEST_FRAME_PATH=/tmp/not_exists_phase4d2.jpg \
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8029
```

请求：

```bash
curl -i http://127.0.0.1:8029/api/perception/latest_frame
```

结果：

```text
HTTP/1.1 404 Not Found
Content-Type: application/json
{"success":false,"error":"latest_frame_not_found",...}
```

### Dashboard

前端已执行：

```bash
cd /home/robomaster/QHXD/frontend
npm run build
```

结果：`vue-tsc --noEmit && vite build` 通过。

Dashboard 视觉检测卡片现在会显示最新识别图片，并每 2 秒刷新一次；图片不可用时显示“暂无识别画面”。原 detection_status 的 source、model、最近目标、最近事件、更新时间仍保留。

## 当前限制

- OpenCV `cv2` 已安装并验证可用，实机已通过 `OpenCvCameraSource` 完成 USB 摄像头 dry-run；ffmpeg fallback 保留为备用路径。
- 本阶段仍不是视频流，只是单张最新 JPEG 的周期刷新。
- 本阶段不做 5 分钟长稳、不做 systemd、不接 Hik SDK；后续 Hik 相机应替换相机采集 adapter，并保持 `latest_camera_detection.jpg` 和 `detection_status` 合约不变。
