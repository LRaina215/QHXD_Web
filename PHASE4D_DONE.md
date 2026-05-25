# PHASE4D_DONE.md

## 本轮目标

在原 Phase 4D 连续检测服务基础上，新增 MJPEG JPEG bytes 图像流，让 Dashboard 不再主要依赖 `latest_frame` 定时轮询显示画面，同时保留原有 detection_status、latest-frame、USB/Hik 切换与 mission 行为。

## 已完成内容

### 后端 MJPEG 流

- `backend/app/main.py:12`
  - 新增 `StreamingResponse`。
- `backend/app/main.py:118`
  - 抽出 `PERCEPTION_LATEST_FRAME_MAX_AGE_SECONDS` 读取逻辑。
- `backend/app/main.py:125`
  - 新增 `PERCEPTION_MJPEG_INTERVAL_MS`，默认 `200ms`，控制 MJPEG generator 检查 latest 图片更新的间隔。
- `backend/app/main.py:133`
  - 新增 `_read_latest_frame_bytes()`，复用 USB/Hik latest 图片自动选择逻辑，并过滤不存在、过期、空文件。
- `backend/app/main.py:150`
  - 新增 `_mjpeg_frame_generator()`，按 multipart MJPEG 格式输出 JPEG bytes，只在 latest 图片 mtime 变化时推新帧。
- `backend/app/main.py:431`
  - 新增接口：`GET /api/perception/frame_stream`。

### 前端接入 MJPEG

- `frontend/src/App.vue:240`
  - 新增前端 env 读取函数。
- `frontend/src/App.vue:257`
  - 新增 `VITE_USE_MJPEG_STREAM`，默认启用 MJPEG。
- `frontend/src/App.vue:796`
  - 页面 mounted 时优先启动 MJPEG stream；关闭或异常时保留 latest-frame 轮询路径。
- `frontend/src/App.vue:876`
  - 新增 `startLatestFrameStream()`，将 `<img>` 指向 `/api/perception/frame_stream?t=...`。
- `frontend/src/App.vue:881`
  - 保留 `startLatestFramePolling()` 作为 fallback。
- `frontend/src/App.vue:893`
  - MJPEG 加载失败时，自动回退到原 `/api/perception/latest_frame` 轮询。
- `frontend/src/App.vue:1455`
  - 原视觉卡片 `<img>` 不需要重写布局，只切换图片源。

### latest 图片写入安全性

- `experiments/rknn_yolo/infer_image.py:443`
  - 保存检测可视化图片时先写临时文件，再 `os.replace()` 原子替换 latest jpg，避免前端/后端读取到写入中的空文件或半张图。
- `experiments/rknn_yolo/infer_image.py:362`
  - OpenCV resize 导入失败后缓存 fallback 状态，避免每帧重复输出 NumPy / OpenCV ABI 错误。

### 配置与文档

- `.env`
  - 新增 `VITE_USE_MJPEG_STREAM=true`。
  - 新增 `PERCEPTION_MJPEG_INTERVAL_MS=200`。
  - 保留 `VITE_LATEST_FRAME_INTERVAL_MS=200` 作为 fallback 轮询间隔。
- `.env.example`
  - 同步新增 MJPEG 与 fallback 配置项。
- `README.md:36`
  - 将相机硬件采集帧率、YOLO 处理/上传频率、MJPEG 前端显示频率分开说明。
- `README.md:890`
  - 记录 `GET /api/perception/frame_stream` 接口与前端默认使用方式。

## 验收结果

### 语法与构建

```bash
python3 -m py_compile backend/app/main.py
python3 -m py_compile experiments/rknn_yolo/infer_image.py
cd frontend && npm run build
```

结果：均通过。

### 服务状态

```bash
./scripts/status_all.sh
```

验证时状态：

```text
backend: running
frontend: running
yolo_camera: running
backend /health: OK
```

### MJPEG 接口验证

```bash
timeout 3 curl --noproxy '*' -sS \
  -D /tmp/qhxd_mjpeg_headers.txt \
  http://127.0.0.1:8000/api/perception/frame_stream \
  -o /tmp/qhxd_mjpeg_sample.bin
```

响应头包含：

```text
HTTP/1.1 200 OK
content-type: multipart/x-mixed-replace; boundary=frame
x-frame-stream: mjpeg
cache-control: no-store, no-cache, must-revalidate
```

样本验证：

```text
has jpeg marker True
has boundary True
```

### latest 图片读取安全性验证

多次请求 `/api/perception/latest_frame` 后，未再观察到写入竞争导致的 `content-length: 0`；latest jpg 由临时文件原子替换生成。

## 当前边界

- MJPEG 流仍然基于 YOLO 服务输出的 latest 检测图，不是相机原始 30fps 视频流。
- 如果 YOLO 推理、画框、JPEG 保存、后端提交低于目标 fps，前端 MJPEG 也只能显示较低频率的新画面。
- 真正高帧率预览的更优架构仍是“原始相机预览流”和“YOLO 低频检测状态”分离。
- 本轮未修改 mission bridge、NUC bridge、RT-Thread 控制语义，也未让 YOLO 结果控制底盘。

## 视觉事件保持修复

本轮追加修复 Dashboard 视觉事件一闪而过的问题：

- `frontend/src/App.vue:2`
  - 引入 `watch`，监听 `detection_status` 更新。
- `frontend/src/App.vue:205`
  - 新增 `DetectionEventItem`，为视觉事件补充 `id/time/first_seen_at/expires_at`。
- `frontend/src/App.vue:232`
  - 新增 `detectionEventHistory` 前端缓存。
- `frontend/src/App.vue:259`
  - 新增 `VITE_DETECTION_EVENT_HOLD_MS`，默认保留 15 秒。
- `frontend/src/App.vue:260`
  - 新增 `VITE_DETECTION_EVENT_MAX_ITEMS`，默认最多保留 12 条。
- `frontend/src/App.vue:406`
  - `latestDetectionEventLabel` 改为读取缓存中的最近视觉事件，而不是只读当前帧事件。
- `frontend/src/App.vue:496`
  - 底部最近事件列表改为使用缓存视觉事件，因此 YOLO 事件不会在下一帧清空时立即消失。
- `frontend/src/App.vue:1126`
  - 新增 `rememberDetectionEvents()` / `pruneDetectionEventHistory()`，同一视觉事件再次出现时刷新保留时间并移动到最前。
- `frontend/src/style.css:680`
  - 视觉事件行增加时间列，便于判断事件发生时间。

配置项：

```env
VITE_DETECTION_EVENT_HOLD_MS=15000
VITE_DETECTION_EVENT_MAX_ITEMS=12
```

验收：`cd frontend && npm run build` 已通过。
