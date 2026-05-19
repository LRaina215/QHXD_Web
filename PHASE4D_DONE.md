# PHASE4D_DONE.md

## 阶段结论

Phase 4D 已在 Phase 4C 单图推理基础上新增 RK3588 YOLO26 摄像头连续检测服务入口：

```text
USB 摄像头 / 本地摄像头
  -> camera_detect_service.py
  -> RknnYoloRunner
  -> detection_status
  -> /api/internal/perception/detection_status
  -> state_store / WebSocket / Dashboard
```

本阶段没有训练模型、转换 RKNN、修改 RKNN runtime、接视频流、修改 mission bridge / NUC bridge / RT-Thread，也没有让 YOLO 结果控制底盘。

## 修改文件列表

- `experiments/rknn_yolo/infer_image.py`
  - 新增 `RknnYoloRunner`，用于模型 load/init/release 与单帧推理复用。
  - 新增数组帧预处理函数，继续沿用 Phase 4C 已验证配置：RGB、640x640、NHWC、float32 / 255.0、batch 维度。
  - 新增 `draw_detections_on_array()`，供摄像头服务保存最近一帧画框图。
  - 保留原 `infer_image.py` CLI 行为。
- `experiments/rknn_yolo/camera_detect_service.py`
  - 新增连续检测服务。
  - 支持 `--camera`、`--fps`、`--dry-run`、`--submit`、`--backend-url`、`--save-latest`、`--max-det`、`--output-layout`。
  - 优先使用 OpenCV `VideoCapture`；当前 Python 未安装 `cv2` 时 fallback 到系统 `ffmpeg` 读取 `/dev/videoN`。
  - 支持事件节流、异常状态、后端提交失败不崩溃、Ctrl+C 释放资源。
- `experiments/rknn_yolo/camera_config.example.json`
  - 新增 USB 摄像头连续检测配置示例，并记录后续 Hik 相机 adapter 伏笔。
- `experiments/rknn_yolo/README.md`
  - 新增 Phase 4D 摄像头服务 dry-run、submit、排障、Dashboard 和无视频流说明。
- `README.md`
  - 新增 Phase 4D 项目总入口命令。

## 摄像头服务启动方式

### dry-run

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 1 \
  --frame-id camera_front \
  --dry-run \
  --save-latest outputs/latest_camera_detection.jpg
```

### submit

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 1 \
  --frame-id camera_front \
  --backend-url http://127.0.0.1:8000 \
  --submit \
  --save-latest outputs/latest_camera_detection.jpg
```

## 当前 FPS / 模型 / 摄像头

- 当前推荐 FPS：`1`，默认参数为 `2`。
- 当前模型：`models/yolo26n_fp32.rknn`。
- 当前 labels：`models/labels.txt`。
- 当前推荐 layout：`xyxy_score_class`。
- 当前摄像头编号：按任务预期为 `0`，对应 `/dev/video0`。

## 实机验证结果

### 单图回归

已执行：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detection_status \
  --output-layout xyxy_score_class \
  --max-det 20 \
  --draw-output outputs/test_phase4d_regression.jpg \
  > outputs/detection_status_phase4d_regression.json
```

结果：

```text
JSON 合法
outputs/test_phase4d_regression.jpg 已生成
objects = 6
events = person_detected, obstacle_detected
```

### 摄像头设备检查

已执行：

```bash
ls /dev/video*
lsusb
python3 -c 'import cv2'
```

当前观察：

```text
/dev/video0
/dev/video1
/dev/video-dec0
/dev/video-enc0
Bus 007 Device 005: ID 32e6:9221 WebCamera WebCamera
```

当前 Python 环境仍未安装 `cv2`，摄像头服务已使用 ffmpeg fallback 从 `/dev/video0` 成功采帧、推理、保存画框并提交后端。

### dry-run 验证

已执行：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 1 \
  --frame-id camera_front \
  --dry-run \
  --save-latest outputs/latest_camera_detection.jpg \
  --max-frames 3 \
  > outputs/camera_dry_run.jsonl
```

结果：

```text
dry_run_json_lines = 3
enabled_values = [True, True, True]
object_counts = [4, 4, 5]
event_types = [[obstacle_detected], [], [person_detected]]
outputs/latest_camera_detection.jpg 已生成，size = 209740 bytes
```

`outputs/camera_dry_run.jsonl` 为纯 JSONL；RKNN runtime 日志已被重定向到 stderr，不污染 dry-run 输出。

错误摄像头编号也已验证：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 99 \
  --dry-run
```

结果为 `enabled=false`、`event_type=camera_unavailable`，且无 traceback。

### submit 验证

当前 8000 端口已有后端进程在运行。已执行：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 1 \
  --frame-id camera_front \
  --backend-url http://127.0.0.1:8000 \
  --submit \
  --save-latest outputs/latest_camera_detection.jpg \
  --max-frames 8
```

结果：连续 8 帧均提交成功，终端多次出现：

```text
Submitted detection_status: HTTP 200
```

服务运行中查询：

```bash
curl http://127.0.0.1:8000/api/state/latest
```

结果包含：

```text
detection_status.enabled = true
detection_status.source = rk3588-rknn-yolo26
detection_status.model_name = yolo26n_fp32.rknn
detection_status.objects = 5
detection_status.objects[0].class_name = person
detection_status.objects[0].confidence = 0.9092
```

服务按 `--max-frames` 正常结束后会提交 `service_stopped`，Dashboard/后端最终进入 offline 状态，这是预期行为。

### Dashboard 验证

当前 Dashboard 已有“视觉检测状态”卡片，字段包括：

- enabled / offline；
- source；
- model_name；
- 最近目标；
- 最近事件；
- 更新时间。

submit 验证已将真实摄像头 detection_status 写入 state_store；服务运行中 Dashboard 可通过现有 WebSocket / REST 状态流显示 `enabled=true`、最近目标、最近事件和更新时间。服务按 `--max-frames` 结束后最终状态为 `service_stopped` / offline。

## 1 分钟连续运行验收

已执行：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 1 \
  --frame-id camera_front \
  --backend-url http://127.0.0.1:8000 \
  --submit \
  --save-latest outputs/latest_camera_detection.jpg \
  --max-frames 40
```

结果：

```text
summary_lines = 40
submit_success = 41  # 40 帧 + 最终 service_stopped
first_ts = 2026-05-19T07:10:26.829678+00:00
last_ts = 2026-05-19T07:11:30.936179+00:00
duration_s = 64.11
latest_camera_detection.jpg size = 376849 bytes
final_state = service_stopped / offline
```

这证明摄像头服务可持续运行超过 1 分钟，持续生成 detection_status、保存最新画框并提交后端。

## 事件节流

连续服务对以下事件做节流：

```text
person_detected: 5 秒
obstacle_detected: 5 秒
possible_blockage: 10 秒
```

1 分钟验收中，`events=none` 出现在大多数帧；`person_detected` / `obstacle_detected` 只按间隔出现，没有每帧刷屏。`objects` 不节流，可按每次推理刷新。

## 已知问题

- 当前 Python 环境未安装 `cv2`，服务实际使用 ffmpeg fallback 采帧；功能已通过，但实时频率受 ffmpeg 单帧抓取开销影响，实测 40 帧约 64 秒。
- 当前完成了超过 1 分钟连续运行验收；5 分钟长稳仍建议人工在最终场地再跑一次。
- 停止服务后的 offline 状态依赖服务收到 Ctrl+C 或正常退出并提交 `service_stopped`；如果进程被强杀，后端不会自动得知服务停止。

## 后续可做但本阶段不做

- 安装/固化摄像头采集依赖，例如 `python3-opencv`。
- 确认 USB 摄像头在系统中出现 `/dev/video0` 或其他真实采集节点。
- 将摄像头服务 systemd 化。
- Hik 相机 SDK / adapter 接入。
- MJPEG / RTSP / WebRTC 视频流展示。
- INT8 量化、模型重训或重新转换 RKNN。
- 视觉事件与任务策略联动。
- YOLO 结果参与导航 costmap 或底盘控制。
