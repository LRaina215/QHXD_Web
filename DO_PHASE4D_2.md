# DO_PHASE4D_2.md

## 阶段名称

**Phase 4D_2：RK3588 YOLO 识别图像流与 Dashboard 可视化收口**

## 阶段定位

本阶段承接 Phase 4D 已完成的 RK3588 YOLO 摄像头连续检测服务，进一步完成“识别结果可视化展示”能力。

当前选择采用 **方案 A：识别图像流**，即不做完整实时视频流，不做 WebRTC / RTSP / MJPEG，而是让 RK3588 YOLO 服务周期性保存一张带检测框的最新识别图片，由后端提供图片访问接口，Dashboard 定时刷新显示。

本阶段目标是让系统具备以下演示链路：

```text
RK3588 摄像头连续检测
    ↓
保存最新画框图 latest_camera_detection.jpg
    ↓
FastAPI 提供图片接口
    ↓
Dashboard 显示最新识别画面
    ↓
Dashboard 同时显示 detection_status / objects / events
```

---

## 一、本阶段明确不做

本阶段不做以下内容：

- 不做 WebRTC；
- 不做 RTSP；
- 不做 MJPEG 连续视频流；
- 不做复杂图传服务；
- 不重新训练 YOLO；
- 不重新转换 RKNN；
- 不做 INT8 量化；
- 不接入 Nav2 costmap；
- 不让 YOLO 结果直接控制底盘；
- 不重构 Dashboard 整体 UI；
- 不做 5 分钟稳定性验收。

本阶段只做：

```text
最新识别图像保存 + 后端图片接口 + Dashboard 图片显示 + 基础配置固化
```

---

## 二、任务清单

## Task 1：确认 YOLO 服务持续保存最新识别图片

### 任务目标

确认或补齐 `camera_detect_service.py` 在连续检测过程中可以持续保存最新画框图。

建议输出路径：

```text
experiments/rknn_yolo/outputs/latest_camera_detection.jpg
```

### 具体要求

1. YOLO 摄像头检测服务每次完成一帧检测后，应保存一张带检测框的图片；
2. 保存路径应可配置，默认使用：

```text
outputs/latest_camera_detection.jpg
```

3. 图片应包含：
   - 检测框；
   - 类别名；
   - 置信度；
4. 如果当前帧没有检测目标，也应保存当前画面，或至少保留上一张有效画面；
5. 不允许因为图片保存失败导致 YOLO 主检测服务崩溃；
6. 图片保存失败时应输出明确日志。

### 验收标准

运行 YOLO 摄像头检测服务后，执行：

```bash
ls -lh /home/robomaster/QHXD/experiments/rknn_yolo/outputs/latest_camera_detection.jpg
```

应能看到图片文件存在。

连续观察数秒：

```bash
watch -n 1 'ls -lh /home/robomaster/QHXD/experiments/rknn_yolo/outputs/latest_camera_detection.jpg'
```

应能看到文件修改时间随检测服务运行而更新。

---

## Task 2：后端提供最新识别图片接口

### 任务目标

在 RK3588 FastAPI 后端中新增一个图片读取接口，用于向前端提供最新识别画面。

推荐接口：

```http
GET /api/perception/latest_frame
```

返回类型：

```text
image/jpeg
```

### 具体要求

1. 后端从以下默认路径读取图片：

```text
/home/robomaster/QHXD/experiments/rknn_yolo/outputs/latest_camera_detection.jpg
```

2. 图片路径应集中配置，不要在多个文件中硬编码；
3. 如果图片存在，返回 JPEG 文件；
4. 如果图片不存在，返回明确错误，例如：

```json
{
  "success": false,
  "error": "latest_frame_not_found"
}
```

5. 图片接口不能影响现有接口：
   - `/api/state/latest`
   - `/ws/state`
   - `/api/internal/perception/detection_status`
   - mission 相关接口
6. 不做视频流，只返回当前最新 JPEG。

### 验收标准

启动后端后执行：

```bash
curl -I http://127.0.0.1:8000/api/perception/latest_frame
```

当图片存在时，应看到类似：

```text
HTTP/1.1 200 OK
content-type: image/jpeg
```

也可以保存测试：

```bash
curl http://127.0.0.1:8000/api/perception/latest_frame \
  --output /tmp/latest_frame.jpg
```

然后确认：

```bash
file /tmp/latest_frame.jpg
```

应显示为 JPEG 图片。

---

## Task 3：Dashboard 显示最新识别图片

### 任务目标

在 Dashboard 的视觉检测区域增加“最新识别画面”显示。

### 具体要求

1. 在现有 YOLO / 视觉检测卡片中增加图片区域；
2. 图片来源：

```text
/api/perception/latest_frame
```

3. 前端应定时刷新图片，建议刷新间隔为：

```text
1 秒或 2 秒
```

4. 为避免浏览器缓存，应在图片 URL 后追加时间戳，例如：

```text
/api/perception/latest_frame?t=当前时间戳
```

5. 图片不存在时，页面应显示：

```text
暂无识别画面
```

或类似占位提示；

6. 不改变 Dashboard 现有整体布局；
7. 不影响已有 detection_status、objects、events 的显示。

### 验收标准

启动后端、前端和 YOLO 摄像头服务后，打开 Dashboard，应满足：

- 页面能显示最新识别图片；
- 图片中包含检测框；
- YOLO 服务运行时，图片会周期性刷新；
- YOLO 服务停止后，页面不会崩溃；
- detection_status 卡片仍能正常显示 objects / events。

---

## Task 4：YOLO 服务配置文件化

### 任务目标

为 YOLO 摄像头连续检测服务增加配置文件，避免每次手动输入过长命令。

推荐配置文件：

```text
experiments/rknn_yolo/camera_config.json
```

### 推荐配置内容

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

### 具体要求

1. `camera_detect_service.py` 支持：

```bash
python3 camera_detect_service.py --config camera_config.json
```

2. 配置文件中至少支持以下字段：
   - `model`
   - `labels`
   - `camera`
   - `conf`
   - `fps`
   - `frame_id`
   - `backend_url`
   - `submit`
   - `save_latest`
   - `max_det`
   - `output_layout`
3. 命令行参数仍可保留；
4. 如果命令行参数和配置文件冲突，应在 README 中说明优先级；
5. 配置文件缺失或字段错误时，应给出明确错误。

### 验收标准

执行：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json
```

应能正常启动 YOLO 检测服务，并持续：

- 更新 `latest_camera_detection.jpg`；
- 向后端提交 `detection_status`；
- 不要求输入冗长命令。

---

## Task 5：OpenCV 采集路径固化，保留 fallback

### 任务目标

优先使用 OpenCV `VideoCapture` 进行摄像头采集，提高连续检测稳定性；如果 OpenCV 不可用或采集失败，保留现有 fallback 机制。

### 具体要求

1. 检测服务启动时优先尝试：

```python
cv2.VideoCapture(camera_id)
```

2. 如果 OpenCV 不可用，应输出明确提示；
3. 如果 OpenCV 打开摄像头失败，应 fallback 到已有 ffmpeg 或其他采帧方式；
4. 如果所有采集方式失败，应提交或输出：

```text
camera_unavailable
```

5. 采集失败不能导致后端或主系统崩溃；
6. README 中说明推荐安装方式：

```bash
sudo apt install python3-opencv
```

### 验收标准

安装 OpenCV 后执行：

```bash
python3 -c "import cv2; print(cv2.__version__)"
```

能正常输出版本。

运行摄像头服务后日志应能看出当前使用的采集方式，例如：

```text
camera backend: opencv
```

如果 OpenCV 不可用，服务应明确提示 fallback，而不是直接 traceback 崩溃。

---

## Task 6：README 更新与运行说明固化

### 任务目标

更新文档，让队友可以按 README 独立运行识别图像流。

### 需要更新的文件

```text
experiments/rknn_yolo/README.md
README.md
```

### README 必须说明

1. 本阶段选择的是“识别图像流”，不是完整视频流；
2. 最新识别图片输出路径；
3. 后端图片接口：

```http
GET /api/perception/latest_frame
```

4. Dashboard 如何显示识别图片；
5. 推荐启动流程：
   - 启动后端；
   - 启动前端；
   - 启动 YOLO 摄像头服务；
   - 打开 Dashboard；
6. 推荐命令：

```bash
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```bash
cd /home/robomaster/QHXD/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json
```

7. 常见问题：
   - 图片不更新；
   - 后端返回 latest_frame_not_found；
   - Dashboard 显示旧图；
   - 摄像头打不开；
   - detection_status 有但图片没有。

### 验收标准

只看 README，新成员应能理解：

- 为什么当前不用实时视频流；
- 如何启动识别图像流；
- 如何查看最新识别画面；
- 出问题时优先检查哪里。

---

## 三、Codex 分轮 Prompt

## Round 1：后端 latest_frame 接口

```text
Read AGENTS.md and current project docs.

Task:
Implement the latest YOLO detection frame API for Phase 4D_2.

Scope:
Expose the latest annotated YOLO image as a single JPEG endpoint. Do not implement video streaming, MJPEG, RTSP, or WebRTC.

Requirements:
1. Add GET /api/perception/latest_frame.
2. Read the image from experiments/rknn_yolo/outputs/latest_camera_detection.jpg by default.
3. Return image/jpeg when the file exists.
4. Return a clear structured error when the file does not exist.
5. Keep the path configurable in one place.
6. Do not modify mission bridge, NUC bridge, RT-Thread code, or YOLO model inference logic.

Validation:
- backend starts
- curl -I /api/perception/latest_frame returns image/jpeg when image exists
- missing image returns a clear error and does not crash backend

Only modify files required for this task.
```

---

## Round 2：Dashboard 显示识别图片

```text
Continue in the same thread.

Task:
Display the latest YOLO annotated frame on the Dashboard.

Requirements:
1. Add an image area to the existing perception / YOLO card.
2. Use /api/perception/latest_frame as the image source.
3. Refresh the image every 1 or 2 seconds using a cache-busting timestamp query.
4. Show a placeholder message when the image is unavailable.
5. Keep existing detection_status objects/events display.
6. Do not redesign the whole Dashboard.

Validation:
- frontend starts
- Dashboard shows the latest annotated image
- image refreshes without manual page reload
- existing state, mission, and detection_status UI still works

Only modify frontend files required for this task.
```

---

## Round 3：YOLO 服务保存最新识别图片与配置文件

```text
Continue in the same thread.

Task:
Ensure the RK3588 YOLO camera detection service saves the latest annotated frame and supports config-file startup.

Requirements:
1. Add or verify saving latest annotated frame to outputs/latest_camera_detection.jpg.
2. Add camera_config.json support.
3. Supported config fields:
   - model
   - labels
   - camera
   - conf
   - fps
   - frame_id
   - backend_url
   - submit
   - save_latest
   - max_det
   - output_layout
4. Keep command-line startup available.
5. Do not implement video streaming.
6. Do not modify backend mission/state logic.

Validation:
- python3 camera_detect_service.py --config camera_config.json starts
- latest_camera_detection.jpg is created and updated
- detection_status is still submitted to backend when submit=true

Only modify YOLO camera service and config files required for this task.
```

---

## Round 4：OpenCV 采集固化与 README 更新

```text
Continue in the same thread.

Task:
Polish Phase 4D_2 YOLO image-stream workflow.

Requirements:
1. Prefer OpenCV VideoCapture for camera capture when cv2 is available.
2. Keep existing fallback capture path if OpenCV fails.
3. Log which camera backend is being used.
4. Update experiments/rknn_yolo/README.md with:
   - latest image path
   - latest_frame API
   - Dashboard image display
   - config-file startup
   - troubleshooting
5. Update root README only if needed.
6. Do not add video streaming or systemd service in this round.

Validation:
- service logs camera backend
- README contains a complete runbook
- backend/frontend behavior remains unchanged

Only modify files required for this task.
```

---

## 四、总体验收标准

Phase 4D_2 通过需满足：

1. YOLO 摄像头服务能持续保存：

```text
outputs/latest_camera_detection.jpg
```

2. 后端提供：

```http
GET /api/perception/latest_frame
```

3. 浏览器可直接访问该接口看到最新识别图片；
4. Dashboard 能显示最新识别图片；
5. Dashboard 图片能周期性刷新；
6. `detection_status` 对象与事件仍能正常显示；
7. `camera_config.json` 可启动 YOLO 服务；
8. OpenCV 可用时优先使用 OpenCV 采集；
9. 图片不存在或摄像头失败时，系统有明确错误提示；
10. 没有引入视频流、底盘控制联动或复杂重构。

---

## 五、人工验收步骤

### Step 1：启动后端

```bash
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Step 2：启动前端

```bash
cd /home/robomaster/QHXD/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

### Step 3：启动 YOLO 摄像头服务

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json
```

### Step 4：检查最新识别图片

```bash
ls -lh /home/robomaster/QHXD/experiments/rknn_yolo/outputs/latest_camera_detection.jpg
```

### Step 5：检查后端图片接口

```bash
curl -I http://127.0.0.1:8000/api/perception/latest_frame
```

期望：

```text
content-type: image/jpeg
```

### Step 6：打开 Dashboard

浏览器访问：

```text
http://RK3588_IP:5173
```

检查：

- 是否显示最新识别图片；
- 图片是否会刷新；
- detection_status 是否同步显示；
- 任务状态、系统状态是否未被破坏。

---

## 六、完成后产出

完成后建议新增或更新：

```text
PHASE4D_2_DONE.md
```

记录：

- 新增接口；
- 最新图片路径；
- Dashboard 显示效果；
- 配置文件示例；
- 人工验收结果；
- 暂不做视频流的原因。

