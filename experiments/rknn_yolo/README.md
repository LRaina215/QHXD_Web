# RKNN YOLO26 Experiment

本目录是 Phase 4C 的 RK3588 本地 YOLO26 / RKNN 单图推理验收入口。它只负责：

```text
图片输入 -> RKNN 推理 -> YOLO 后处理 -> detections / detection_status JSON
```

YOLO 结果只进入 `detection_status`，不会直接控制底盘、导航、急停或 mission。

## 目录约定

```text
experiments/rknn_yolo/
├── infer_image.py
├── detection_status_builder.py
├── load_rknn_test.py
├── models/
│   ├── README.md
│   ├── yolo26n_fp32.rknn
│   └── labels.txt
├── samples/
│   └── test.jpg
└── outputs/
```

- `models/yolo26n_fp32.rknn`：当前 RK3588 验收模型。
- `models/labels.txt`：类别文件，必须与模型导出时的类别顺序一致。
- `samples/test.jpg`：单图推理测试图片。
- `outputs/`：保存 `detections*.json`、`detection_status*.json`、画框图等验收输出。

## 当前已验证配置

```text
模型：yolo26n_fp32.rknn
输入尺寸：640x640
输入格式：RGB
输入 layout：NHWC
输入 dtype：float32
输入范围：0.0 ~ 1.0
输出 shape：(1, 300, 6)
推荐输出 layout：xyxy_score_class
```

关键点：`infer_image.py` 的 OpenCV 分支与 Pillow fallback 分支都必须使用 `float32 / 255.0` 输入，不要再默认使用 `uint8 0~255`。当前推荐输出解析模式为：

```text
--output-layout xyxy_score_class
```

它对应：

```text
[x1, y1, x2, y2, score, class_id]
```

`--output-layout auto` 仍保留用于诊断，但验收命令建议手动指定 `xyxy_score_class`。

## 1. 模型加载最小验证

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 load_rknn_test.py
```

通过标准：输出 `RKNN model load/init OK`。

## 2. 推荐验收命令

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
  --draw-output outputs/test_fixed_preprocess.jpg \
  > outputs/detection_status_fixed_preprocess.json
```

正常结果：

- 命令无报错；
- `outputs/detection_status_fixed_preprocess.json` 是合法 JSON；
- `outputs/test_fixed_preprocess.jpg` 成功生成；
- 画框不再满屏乱飞；
- 不再出现大量随机高置信度错误框。

如果需要 plain detections JSON：

```bash
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detections \
  --output-layout xyxy_score_class \
  --max-det 20 \
  --draw-output outputs/test_fixed_preprocess.jpg \
  > outputs/detections_fixed_preprocess.json
```

## 3. 调试输入与原始输出

脚本默认会把 RKNN output shape / dtype / min / max / mean 打到 stderr，stdout 只输出 JSON，因此可以安全重定向到文件。

需要排查输入预处理或 6 列输出语义时使用：

```bash
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detections \
  --output-layout xyxy_score_class \
  --max-det 20 \
  --debug-raw
```

`--debug-raw` 会在 stderr 打印：

```text
input_tensor shape=(1, 640, 640, 3)
input_tensor dtype=float32
input_tensor min=...
input_tensor max=...
Output 0: shape=(1, 300, 6), dtype=float32
first 20 raw rows
per-column min/max/mean
```

期望输入范围为 `min>=0.0`、`max<=1.0`。

## 4. labels.txt 来源

`labels.txt` 必须与导出 ONNX / RKNN 的模型类别顺序一致。COCO 80 类 `labels.txt` 只适用于 COCO 预训练模型；自训练模型不能直接沿用 COCO `labels.txt`。

如果使用官方预训练 `yolo26n.pt`，从 Ultralytics 模型导出：

```bash
python - <<'PY'
from ultralytics import YOLO

model = YOLO("yolo26n.pt")
names = model.names

with open("labels.txt", "w", encoding="utf-8") as f:
    for i in range(len(names)):
        f.write(str(names[i]) + "\n")

print(names)
print("saved labels.txt")
PY
```

如果使用自训练模型 `best.pt`，从 `best.pt` 导出：

```bash
python - <<'PY'
from ultralytics import YOLO

model = YOLO("runs/detect/train/weights/best.pt")
names = model.names

with open("labels.txt", "w", encoding="utf-8") as f:
    for i in range(len(names)):
        f.write(str(names[i]) + "\n")

print(names)
print("saved labels.txt from best.pt")
PY
```

labels 错误通常会导致类别名错位，例如把 `person` 显示成其他类别；它通常只影响类别名，不应导致框位置整体错乱。框位置整体错乱时优先检查输入预处理、坐标布局、letterbox/resize 方式和输出 layout。

## 5. 输出 detection_status

推荐命令会生成：

```json
{
  "detection_status": {
    "enabled": true,
    "source": "rk3588-rknn-yolo26",
    "model_name": "yolo26n_fp32.rknn",
    "frame_id": "camera_front",
    "timestamp": "...",
    "objects": [],
    "events": []
  }
}
```

事件规则：

- `person` -> `person_detected`
- `chair` / `backpack` / `suitcase` / `box` / `bottle` / `traffic cone` / `obstacle` -> `obstacle_detected`
- 如果调用方后续提供连续阻塞帧计数，`blockage_frames >= 3` 时可生成 `possible_blockage`

## 6. 提交到后端 state_store

后端不依赖 RKNN runtime 启动。先启动后端：

```bash
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8027
```

提交 detection_status：

```bash
curl -X POST http://127.0.0.1:8027/api/internal/perception/detection_status \
  -H "Content-Type: application/json" \
  -d @/home/robomaster/QHXD/experiments/rknn_yolo/outputs/detection_status_fixed_preprocess.json
```

检查最新状态：

```bash
curl http://127.0.0.1:8027/api/state/latest
```

通过标准：返回 `success=true`、`accepted=true`、`state_updated=true`，`/api/state/latest` 包含 `data.detection_status`。Dashboard 的“视觉检测状态”卡片应同步显示 source、model、最近目标、最近事件和更新时间。

## 7. 手工验收清单

- [ ] `.rknn` 模型位于 `models/yolo26n_fp32.rknn`。
- [ ] `labels.txt` 来自同一个 `yolo26n.pt` / `best.pt`，与 RKNN 模型类别顺序一致。
- [ ] `samples/test.jpg` 是可读取图片。
- [ ] `infer_image.py --format detections --output-layout xyxy_score_class --max-det 20` 能输出合法 JSON。
- [ ] `infer_image.py --format detection_status --output-layout xyxy_score_class --max-det 20` 能输出合法 JSON。
- [ ] `--debug-raw` 能看到 `input_tensor shape=(1, 640, 640, 3)`、`dtype=float32`、输入范围 `0.0~1.0`。
- [ ] `outputs/test_fixed_preprocess.jpg` 中目标框视觉合理，框不再满屏乱飞。
- [ ] objects 数量受 `--max-det 20` 控制。
- [ ] 无检测时输出 `objects=[]`，不报错。
- [ ] POST 到 `/api/internal/perception/detection_status` 后，`GET /api/state/latest` 能看到 `detection_status`。
- [ ] Dashboard 能显示视觉检测状态，不显示视频流，不影响 mission UI。

## 8. 限制

- 不训练模型。
- 不转换 `.pt/.onnx/.rknn`。
- 不下载模型。
- 不做视频流 / 摄像头循环。
- 不把 YOLO 结果直接接入导航、急停或电机控制。
- 不修改 RKNN runtime、backend state_store、Dashboard 或 mission bridge。

## 9. Phase 4D 摄像头连续检测服务

Phase 4D 在单图推理基础上新增：

```text
USB 摄像头 -> 连续采帧 -> RKNN YOLO26 -> detection_status -> 后端 state_store -> Dashboard
```

当前脚本：

```text
experiments/rknn_yolo/camera_detect_service.py
experiments/rknn_yolo/camera_config.example.json
```

现阶段默认配置仍使用 USB / UVC 摄像头，且默认设备名为 `/dev/qhxd-usb-camera`。该名字由 `scripts/setup_usb_camera_alias.sh` 通过 udev 绑定到当前 USB 摄像头的 capture 节点，避免系统枚举成 `/dev/video1`、`/dev/video2` 时脚本仍死查找 `/dev/video0`。脚本优先使用 OpenCV `VideoCapture`；如果当前 Python 没有 `cv2`，或 OpenCV 无法打开相机，会尝试用系统 `ffmpeg` 抓帧。当前 RK3588 环境已验证 OpenCV 采集路径可用。

已预留并接入 Hikrobot/MVS SDK 采集入口，可通过配置切换到 Hik 相机；切换只发生在相机采集层，`RKNN YOLO26 -> detection_status -> 后端 state_store -> Dashboard` 的数据合约不变。USB 入口仍保留，且 `camera_config.json` 默认通过 `/dev/qhxd-usb-camera` 使用 USB。

### 查看摄像头设备

```bash
ls /dev/video*
lsusb
```

正常 USB 摄像头通常会出现 `/dev/video0`、`/dev/video1` 等节点。如果只看到 `/dev/video-dec0`、`/dev/video-enc0`，那是 Rockchip 编解码节点，不是普通 USB 摄像头采集节点。当前项目推荐使用稳定别名：

```bash
cd /home/robomaster/QHXD
./scripts/setup_usb_camera_alias.sh
ls -l /dev/qhxd-usb-camera
```

当前已绑定结果应类似：

```text
/dev/qhxd-usb-camera -> video1
```

`camera_config.json` 默认使用 `/dev/qhxd-usb-camera`，因此即使系统没有 `/dev/video0`，也不会再因固定查找 video0 导致打不开相机。

### USB / Hik 采集入口切换

`camera_detect_service.py` 支持三种采集后端：

```text
camera_backend = usb   # 强制使用原 USB / UVC 摄像头入口
camera_backend = hik   # 强制使用 Hikrobot MVS SDK 入口
camera_backend = auto  # 先尝试 USB，USB 不可用时再尝试 Hik
```

默认配置文件仍保留 USB：

```text
experiments/rknn_yolo/camera_config.json
```

Hik 示例配置：

```text
experiments/rknn_yolo/camera_config_hik.example.json
```

Hik 入口依赖海康 MVS SDK，当前 RK3588 已发现 SDK 路径：

```text
/opt/MVS
/opt/MVS/Samples/aarch64/Python/MvImport
/opt/MVS/lib/aarch64/libMvCameraControl.so
```

使用 Hik 相机 dry-run：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py \
  --config camera_config_hik.example.json \
  --dry-run \
  --max-frames 1 \
  --read-fail-limit 1
```

或者通过 Hik 快捷启动脚本：

```bash
cd /home/robomaster/QHXD
./scripts/start_yolo_hik_camera.sh
```

如需临时指定另一份 Hik 配置，可覆盖：

```bash
HIK_YOLO_CONFIG=/path/to/camera_config_hik.json ./scripts/start_yolo_hik_camera.sh
```

当前这台 Hik USB3 Vision 相机曾被系统识别为 `2bdf:0001 Hikrobot MV-CS060-10UC-PRO`，序列号 `DA8290708`。首次 MVS 探测可以枚举、打开并 start grabbing，但抓帧返回 `0x80000007`。执行 MVS USB 权限和 usbfs 内存设置后，当前内核日志出现反复的 `usb 6-1: device descriptor read/8, error -110`，`lsusb -t` 暂时不再稳定列出该相机。因此软件入口已接入，但 Hik 出图最终验收还需要先让相机在 USB3 总线/MVS SDK 中稳定枚举。

### dry-run 模式

只打印 `detection_status`，不提交后端：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera /dev/qhxd-usb-camera \
  --conf 0.25 \
  --fps 1 \
  --frame-id camera_front \
  --dry-run \
  --save-latest outputs/latest_camera_detection.jpg
```

终端 stderr 会周期性打印摘要，例如：

```text
[timestamp] enabled=True objects=2 top=person:0.91 events=person_detected
```

stdout 在 `--dry-run` 下输出完整 JSON，便于人工检查。`Ctrl+C` 会释放摄像头和 RKNN runtime。

### submit 模式

先启动后端：

```bash
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

再运行摄像头服务：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera /dev/qhxd-usb-camera \
  --conf 0.25 \
  --fps 1 \
  --frame-id camera_front \
  --backend-url http://127.0.0.1:8000 \
  --submit \
  --save-latest outputs/latest_camera_detection.jpg
```

检查后端接收：

```bash
curl http://127.0.0.1:8000/api/state/latest
```

通过标准：`detection_status.source = rk3588-rknn-yolo26`，`model_name = yolo26n_fp32.rknn`，`timestamp` 周期更新，`objects` 随画面变化。

### 事件节流

连续检测服务会节流同类视觉事件，避免 Dashboard 和日志被每帧重复事件刷屏：

```text
person_detected: 5 秒内最多触发一次
obstacle_detected: 5 秒内最多触发一次
possible_blockage: 10 秒内最多触发一次
```

节流只影响 `events`；`objects` 仍可每帧刷新。

### 摄像头异常状态

错误摄像头编号测试：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 99 \
  --dry-run
```

应输出 `enabled=false`、`event_type=camera_unavailable`，不会出现难以理解的 traceback。如果加 `--submit`，后端会收到 offline / unavailable 状态。

### Dashboard

Dashboard 现有“视觉检测状态”卡片会显示：

- enabled / offline；
- source；
- model_name；
- 最近检测对象；
- 最近视觉事件；
- 更新时间。

本阶段不提供摄像头视频流，不做 MJPEG / RTSP / WebRTC，也不会把 YOLO 结果直接控制底盘。

### 常见问题

1. 没有 `/dev/video0`
   先检查 USB 摄像头是否被内核识别：`lsusb`。如果 `ls /dev/video*` 只出现 `/dev/video-dec0` 和 `/dev/video-enc0`，当前还没有可用 UVC 摄像头采集节点；正常接入后应能看到 `/dev/video0` 或类似节点。

2. `OpenCV is not installed` 或 `OpenCV could not open camera`
   脚本会自动尝试 ffmpeg fallback。当前 RK3588 环境已验证系统包 `python3-opencv` 可用；如果再次出现 `numpy.core.multiarray failed to import`，优先检查用户目录中是否有不兼容的 pip NumPy 覆盖了系统 NumPy。

3. 后端提交失败
   检查 `--backend-url` 是否正确，确认 `curl http://127.0.0.1:8000/api/state/latest` 可访问。提交失败不会导致摄像头服务崩溃。

4. 没有视频画面
   这是本阶段预期行为。Phase 4D 只提交检测状态，不做视频流展示。

5. Hik 相机 MVS SDK 枚举不到设备
   先用 `lsusb -t` 确认 USB3 总线上能稳定看到 Hik 设备；如果内核日志出现 `device descriptor read/8, error -110`，说明相机当前在 USB 枚举层不稳定，优先检查供电、线缆、USB3 口、带宽和物理重插。MVS SDK 枚举不到设备时，服务会输出 `camera_unavailable`，不会影响 USB 摄像头入口。

## 10. Phase 4D_2 识别图像流

Phase 4D_2 采用“识别图像流”方案：YOLO 摄像头服务周期性保存一张带检测框的最新 JPEG，后端提供单张图片接口，Dashboard 定时刷新显示。它不是 WebRTC、RTSP、MJPEG，也不是完整视频流。

```text
camera_detect_service.py
-> outputs/latest_camera_detection.jpg
-> GET /api/perception/latest_frame
-> Dashboard 视觉检测卡片
```

### 最新识别图片路径

默认输出：

```text
/home/robomaster/QHXD/experiments/rknn_yolo/outputs/latest_camera_detection.jpg
```

`camera_detect_service.py` 默认 `save_latest` 也是 `outputs/latest_camera_detection.jpg`。如果图片保存失败，服务会打印明确日志，但不会让主检测循环崩溃。

### 后端图片接口

```http
GET /api/perception/latest_frame
```

图片存在时返回：

```text
content-type: image/jpeg
cache-control: no-store
```

图片不存在时返回：

```json
{
  "success": false,
  "error": "latest_frame_not_found"
}
```

默认读取路径集中在 `backend/app/main.py` 的 `DEFAULT_LATEST_FRAME_PATH`，也可以用环境变量覆盖：

```bash
PERCEPTION_LATEST_FRAME_PATH=/path/to/latest.jpg python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 配置文件启动

推荐配置文件：

```text
experiments/rknn_yolo/camera_config.json
```

启动：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json
```

配置文件支持：

```text
model, labels, camera, camera_backend, hik_index, hik_serial,
hik_timeout_ms, conf, fps, frame_id, backend_url, submit,
save_latest, max_det, dry_run, output_layout, submit_interval,
read_fail_limit, max_frames
```

优先级：命令行参数覆盖配置文件，配置文件覆盖内置默认值。例如：

```bash
python3 camera_detect_service.py --config camera_config.json --max-frames 3
```

会使用配置文件启动，但只运行 3 帧。

### 推荐启动流程

后端：

```bash
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

前端：

```bash
cd /home/robomaster/QHXD/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

YOLO 摄像头服务：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json
```

检查图片接口：

```bash
curl -I http://127.0.0.1:8000/api/perception/latest_frame
curl http://127.0.0.1:8000/api/perception/latest_frame --output /tmp/latest_frame.jpg
file /tmp/latest_frame.jpg
```

打开 Dashboard：

```text
http://RK3588_IP:5173
```

视觉检测卡片会显示最新识别图片，并每 2 秒追加时间戳刷新一次；同时保留 source、model、最近目标、最近事件和更新时间。

### OpenCV 与 fallback

推荐使用 OpenCV 采集路径。当前已验证组合：`python3` + NumPy 1.21.5 + OpenCV 4.5.4。安装命令：

```bash
sudo apt install python3-opencv
python3 -c "import cv2; print(cv2.__version__)"
```

服务启动时优先尝试 OpenCV `VideoCapture`。验证通过时日志会出现 `backend=OpenCvCameraSource`。如果 `cv2` 不可用或摄像头打开失败，会明确打印 fallback 日志，并尝试用 ffmpeg 从 `/dev/videoN` 抓帧。所有采集方式失败时输出 / 提交 `camera_unavailable`。

### 常见问题

1. 图片不更新
   检查 YOLO 服务是否仍在运行，确认 `ls -lh outputs/latest_camera_detection.jpg` 的修改时间是否变化。

2. 后端返回 `latest_frame_not_found`
   检查 `outputs/latest_camera_detection.jpg` 是否存在，或检查 `PERCEPTION_LATEST_FRAME_PATH` 是否指向正确文件。

3. Dashboard 显示旧图
   前端已使用 `/api/perception/latest_frame?t=时间戳` 避免缓存；如果仍旧，检查后端是否读到了同一个图片路径。

4. 摄像头打不开
   先看 `ls /dev/video*` 和 `lsusb`，确认有 `/dev/video0` 或类似 UVC 节点。OpenCV 不可用或打不开设备时会 fallback 到 ffmpeg。

5. 有 detection_status 但图片没有
   检查启动命令或配置中的 `save_latest`。detection_status 提交与图片保存是两条路径，图片保存失败不会中断检测服务。
