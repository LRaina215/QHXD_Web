# PHASE4E：YOLO 识别图像 JPEG Bytes 内存缓存与前端刷新

## 1. 阶段定位

本阶段用于在已完成 RK3588 本地 YOLO26 / RKNN 摄像头连续检测服务的基础上，进一步完成 **识别图像的前端可视化**。

当前阶段不采用文件落盘方案，不将画框后的识别图像保存为 `latest_camera_detection.jpg` 后再由前端读取，而是采用：

```text
YOLO 服务
  -> 画框后的图像
  -> JPEG bytes
  -> POST 到 RK3588 后端
  -> 后端内存缓存最新 JPEG
  -> 前端 Dashboard 定时 GET 最新图片
```

本阶段目标是让 Dashboard 能看到 RK3588 本地 YOLO 识别后的最新画面，同时避免引入 MJPEG、WebRTC、RTSP 等复杂视频流方案。

---

## 2. 阶段目标

完成一套低负载、低复杂度的 YOLO 识别图像展示链路：

```text
RK3588 Camera Detect Service
        ↓
RKNN YOLO26 推理
        ↓
绘制检测框 annotated_frame
        ↓
JPEG 编码为 bytes
        ↓
POST /api/internal/perception/latest_frame
        ↓
FastAPI 内存缓存 latest_frame_bytes
        ↓
GET /api/perception/latest_frame
        ↓
Dashboard <img> 定时刷新
```

核心效果：

- 不写入磁盘图片文件；
- 只缓存最新一帧 JPEG；
- 前端能看到最新识别画面；
- 后端可报告图片更新时间、大小、在线/超时状态；
- 不影响已有 YOLO detection_status、mission bridge、语音入口和系统状态流。

---

## 3. 本阶段不做的内容

本阶段明确不做：

- 不做 MJPEG；
- 不做 WebRTC；
- 不做 RTSP；
- 不做视频录制；
- 不做多路摄像头；
- 不做 YOLO 结果直接控制底盘；
- 不做 YOLO 结果直接接入 Nav2 costmap；
- 不重新训练 YOLO；
- 不重新转换 RKNN；
- 不改 NUC mission bridge；
- 不改 RT-Thread 控制链路；
- 不大规模重构 Dashboard。

---

## 4. 推荐参数

第一版建议使用低频识别图像刷新，保证稳定与低负载：

```text
YOLO 推理频率：1 FPS
前端图片刷新：1 秒一次
图片尺寸：优先使用当前推理输出尺寸，建议 640×640 或 640×480
JPEG quality：70~80
后端缓存策略：只缓存最新一帧
图片超时阈值：3~5 秒
```

---

## 5. 任务清单

## Task 1：后端新增 latest frame 内存缓存服务

### 目标

在 RK3588 后端中增加一个内存级的最新识别图像缓存服务，用于保存 YOLO 服务提交的最新 JPEG bytes。

### 需要做什么

新增或扩展后端服务模块，例如：

```text
backend/app/services/perception_frame_store.py
```

内部维护：

```python
latest_frame_bytes: bytes | None
latest_frame_updated_at: datetime | None
latest_frame_content_type: str = "image/jpeg"
latest_frame_source: str | None
latest_frame_size_bytes: int
```

### 功能要求

1. 支持写入最新 JPEG bytes；
2. 支持读取最新 JPEG bytes；
3. 支持查询 frame status；
4. 支持判断 frame 是否超时；
5. 不保存历史帧；
6. 不写入磁盘；
7. 后端启动时允许没有任何图片。

### 验收标准

- 后端启动不依赖任何图片文件；
- 未提交图片时，frame store 状态为 unavailable；
- 提交一张 JPEG 后，frame store 能返回 bytes、时间戳和大小；
- 多次提交后，只保留最新一帧；
- 不影响已有 `/api/state/latest` 和 detection_status 逻辑。

---

## Task 2：后端新增 JPEG bytes 上传接口

### 目标

让 YOLO 摄像头检测服务能够把画框后的 JPEG bytes 直接提交给 RK3588 后端。

### 需要新增接口

```http
POST /api/internal/perception/latest_frame
Content-Type: image/jpeg
```

### 请求说明

请求体直接为 JPEG bytes。

可选 Header：

```text
X-Frame-Source: rk3588-rknn-yolo26
X-Frame-Id: camera_front
```

如果不做 Header，也可以先在后端使用默认值。

### 返回示例

```json
{
  "success": true,
  "data": {
    "accepted": true,
    "size_bytes": 184532,
    "content_type": "image/jpeg",
    "source": "rk3588-rknn-yolo26",
    "state_updated": true
  }
}
```

### 功能要求

1. 仅接受 `image/jpeg`；
2. 空 body 返回错误；
3. 非 JPEG content-type 返回错误；
4. 写入 frame store；
5. 返回结构化结果；
6. 该接口只用于内部服务，不暴露复杂权限逻辑。

### 验收标准

使用 curl 提交测试 JPEG：

```bash
curl -X POST http://127.0.0.1:8000/api/internal/perception/latest_frame \
  -H "Content-Type: image/jpeg" \
  --data-binary @samples/test_annotated.jpg
```

应满足：

- 返回 `success=true`；
- 返回 `accepted=true`；
- 返回 `size_bytes > 0`；
- 后端不报错；
- 再次提交另一张图片后，最新图片被替换。

---

## Task 3：后端新增 latest frame 读取接口

### 目标

让 Dashboard 能够通过普通 HTTP GET 获取最新识别图像。

### 需要新增接口

```http
GET /api/perception/latest_frame
```

### 返回行为

有图片时：

```text
HTTP 200
Content-Type: image/jpeg
Body: latest_frame_bytes
```

无图片时：

```text
HTTP 404
返回结构化错误或纯文本提示
```

图片超时时：

```text
HTTP 503 或仍返回最后一帧，但 frame_status 标记 stale
```

建议第一版：

- `GET /api/perception/latest_frame`：只要有图就返回最后一帧；
- 是否超时由 `GET /api/perception/frame_status` 告诉前端。

### 验收标准

提交 JPEG 后执行：

```bash
curl http://127.0.0.1:8000/api/perception/latest_frame \
  --output /tmp/latest_frame.jpg
```

应满足：

- `/tmp/latest_frame.jpg` 是可打开的 JPEG 图片；
- 浏览器访问该接口能显示图片；
- 未提交图片时，接口有明确错误，不导致后端崩溃。

---

## Task 4：后端新增 frame status 接口

### 目标

让前端判断识别图像是否在线、是否超时、最后更新时间和图片大小。

### 需要新增接口

```http
GET /api/perception/frame_status
```

### 返回示例

```json
{
  "success": true,
  "data": {
    "available": true,
    "stale": false,
    "updated_at": "2026-05-19T13:20:00Z",
    "age_ms": 820,
    "size_bytes": 184532,
    "content_type": "image/jpeg",
    "source": "rk3588-rknn-yolo26"
  }
}
```

### 功能要求

1. 未收到图片时：`available=false`；
2. 收到图片后：`available=true`；
3. 超过阈值后：`stale=true`；
4. 返回 `age_ms`；
5. 返回 `size_bytes`；
6. 不影响现有 `detection_status`。

### 验收标准

- 后端刚启动时：`available=false`；
- 提交 JPEG 后：`available=true`；
- 等待超过超时阈值后：`stale=true`；
- `age_ms` 随时间递增。

---

## Task 5：YOLO 摄像头服务支持 JPEG bytes 提交

### 目标

让现有 RK3588 YOLO 摄像头连续检测服务在每次生成画框图后，不再必须保存到文件，而是可以直接将 JPEG bytes POST 到后端。

### 需要修改的模块

通常位于：

```text
experiments/rknn_yolo/camera_detect_service.py
```

或当前项目中的等价摄像头检测服务文件。

### 功能要求

新增参数：

```text
--submit-frame
--frame-url http://127.0.0.1:8000/api/internal/perception/latest_frame
--jpeg-quality 75
```

服务流程：

```text
摄像头采帧
  -> YOLO 推理
  -> 绘制检测框
  -> cv2.imencode('.jpg', annotated_frame, quality)
  -> POST JPEG bytes 到 frame-url
```

### 要求

1. 不要求保存图片到磁盘；
2. 可保留 `--save-latest` 作为调试选项，但默认不启用；
3. POST 失败不能导致服务崩溃；
4. POST 失败时打印 warning；
5. 与 detection_status 提交逻辑互不影响；
6. 支持低频 1 FPS 提交。

### 验收标准

运行示例：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 1 \
  --submit \
  --submit-frame \
  --backend-url http://127.0.0.1:8000 \
  --jpeg-quality 75
```

应满足：

- YOLO 服务不中断；
- 后端能收到 detection_status；
- 后端能收到 latest_frame；
- `/api/perception/latest_frame` 能返回最新画框图；
- POST frame 失败时服务不会崩溃。

---

## Task 6：Dashboard 显示最新识别图像

### 目标

在 Dashboard 的视觉检测卡片中显示最新识别图像。

### 前端行为

使用普通 `<img>` 标签：

```text
/api/perception/latest_frame?t=Date.now()
```

每 1 秒或 2 秒刷新一次。

### 页面显示内容

视觉检测卡片建议包含：

```text
YOLO 状态：online / stale / unavailable
最近更新时间：xxx
图片大小：xxx KB
最新识别画面：[image]
```

### 功能要求

1. 前端定时刷新图片 URL，避免浏览器缓存；
2. 没有图片时显示“暂无识别画面”；
3. 图片 stale 时显示“识别画面超时”；
4. 不大改 Dashboard 样式；
5. 不影响已有 detection_status 对象列表与事件显示。

### 验收标准

- Dashboard 能显示最新识别画面；
- YOLO 服务运行时图片会更新；
- 后端无图片时页面不报错；
- 图片超时时页面有提示；
- mission / mode / state 原有功能不受影响。

---

## Task 7：配置文件支持 frame 提交参数

### 目标

将 frame 提交相关参数纳入 YOLO 服务配置文件，避免每次命令行过长。

### 配置示例

```json
{
  "model": "models/yolo26n_fp32.rknn",
  "labels": "models/labels.txt",
  "camera": 0,
  "conf": 0.25,
  "fps": 1,
  "frame_id": "camera_front",
  "backend_url": "http://127.0.0.1:8000",
  "submit_detection_status": true,
  "submit_frame": true,
  "frame_url": "http://127.0.0.1:8000/api/internal/perception/latest_frame",
  "jpeg_quality": 75,
  "max_det": 20
}
```

### 验收标准

支持：

```bash
python3 camera_detect_service.py --config camera_config.json
```

应满足：

- 配置文件能启用 detection_status 提交；
- 配置文件能启用 latest_frame 提交；
- 命令行参数可覆盖配置文件；
- README 有配置示例。

---

## Task 8：README 与阶段完成记录

### 目标

更新文档，让队友能复现 Phase 4E。

### 需要更新

```text
experiments/rknn_yolo/README.md
README.md
PHASE4E_DONE.md
```

### README 必须说明

1. 本阶段采用 JPEG bytes 内存缓存，不保存图片文件；
2. 不做 MJPEG、WebRTC、RTSP；
3. 后端接口：
   - `POST /api/internal/perception/latest_frame`
   - `GET /api/perception/latest_frame`
   - `GET /api/perception/frame_status`
4. YOLO 服务启动命令；
5. Dashboard 查看方法；
6. 常见故障：
   - 没有图片；
   - 图片 stale；
   - POST frame 失败；
   - 后端未启动。

### 验收标准

新成员按 README 能完成：

```text
启动后端
启动 YOLO 摄像头服务
打开 Dashboard
看到最新识别图像
看到检测对象和事件
```

---

## 6. Codex 分轮 Prompt

## Round 1：后端 latest frame 内存缓存与接口

```text
Read AGENTS.md and current project docs.

Task:
Implement JPEG bytes in-memory latest frame support for YOLO perception display.

Scope:
Backend only in this round.
Do not modify YOLO service, Dashboard, mission bridge, NUC bridge, or RT-Thread code.

Requirements:
1. Add a perception frame store service that caches only the latest JPEG bytes in memory.
2. Add POST /api/internal/perception/latest_frame accepting Content-Type image/jpeg.
3. Add GET /api/perception/latest_frame returning image/jpeg.
4. Add GET /api/perception/frame_status returning available/stale/updated_at/age_ms/size_bytes/source.
5. Do not save frames to disk.
6. If no frame exists, return a clear 404 or structured error.
7. Do not break existing detection_status endpoint.

Validation:
- Backend starts.
- Posting a JPEG returns success=true and accepted=true.
- GET /api/perception/latest_frame returns the same latest JPEG.
- GET /api/perception/frame_status reflects available=true after upload.
- Existing /api/state/latest still works.

Only modify files required for backend latest frame support.
```

---

## Round 2：YOLO 服务提交 JPEG bytes

```text
Continue in the same thread.

Task:
Add JPEG bytes frame submission support to the RK3588 YOLO camera detection service.

Scope:
YOLO camera service only in this round.
Do not modify backend APIs beyond what already exists.
Do not modify Dashboard.

Requirements:
1. Add CLI options:
   - --submit-frame
   - --frame-url
   - --jpeg-quality
2. After drawing detection boxes, encode annotated_frame to JPEG bytes in memory.
3. POST the JPEG bytes to /api/internal/perception/latest_frame with Content-Type image/jpeg.
4. POST failure must not crash the YOLO service.
5. Keep detection_status submission behavior unchanged.
6. Do not require saving latest frame to disk.
7. Optional debug save can remain, but must not be required.

Validation:
- YOLO service runs with --submit-frame.
- Backend receives latest frame.
- GET /api/perception/latest_frame returns a visible JPEG.
- detection_status submission still works.

Only modify files required for YOLO service frame submission.
```

---

## Round 3：Dashboard 显示 latest frame

```text
Continue in the same thread.

Task:
Display the latest YOLO annotated frame on Dashboard.

Scope:
Frontend only unless a tiny API helper is required.
Do not redesign the Dashboard.

Requirements:
1. Add image display to the existing perception / YOLO card.
2. Use GET /api/perception/latest_frame?t=timestamp to avoid cache.
3. Poll /api/perception/frame_status every 1 or 2 seconds.
4. Show states:
   - unavailable: no image yet
   - online: latest image available and fresh
   - stale: latest image exists but is old
5. Keep existing detection_status objects/events display.
6. Do not add MJPEG, WebRTC, RTSP, or video player.

Validation:
- Dashboard shows latest frame when available.
- Image updates without manual page refresh.
- No-frame state does not crash UI.
- stale state is visible.
- Existing mission/mode/state UI still works.

Only modify frontend files required for latest frame display.
```

---

## Round 4：配置文件与 README

```text
Continue in the same thread.

Task:
Add config support and documentation for JPEG bytes latest frame flow.

Requirements:
1. Extend YOLO camera config to support:
   - submit_frame
   - frame_url
   - jpeg_quality
2. Document recommended config for 1 FPS latest-frame refresh.
3. Update experiments/rknn_yolo/README.md with:
   - backend startup
   - YOLO service startup
   - latest_frame endpoints
   - Dashboard verification
   - common failure cases
4. Add or update PHASE4E_DONE.md with the implemented flow.
5. Do not add new features beyond documentation/config support.

Validation:
- YOLO service can be started from config.
- README commands are consistent with actual CLI.
- PHASE4E_DONE.md explains what was completed and what was intentionally not done.

Only modify config/docs and minimal related code.
```

---

## 7. 总体验收标准

Phase 4E 通过条件：

1. 后端支持 JPEG bytes 内存缓存；
2. 后端提供 latest frame 上传、读取、状态查询接口；
3. YOLO 摄像头服务能提交画框后的 JPEG bytes；
4. Dashboard 能显示最新识别图像；
5. 前端能显示 online / stale / unavailable 状态；
6. 不发生磁盘图片依赖；
7. 不引入 MJPEG、WebRTC、RTSP；
8. 原有 detection_status、mission bridge、mode/state 功能不受影响。

---

## 8. 人工验收步骤

## Step 1：启动后端

```bash
cd ~/QHXD/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Step 2：启动 YOLO 摄像头服务

```bash
cd ~/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 1 \
  --submit \
  --submit-frame \
  --backend-url http://127.0.0.1:8000 \
  --frame-url http://127.0.0.1:8000/api/internal/perception/latest_frame \
  --jpeg-quality 75
```

## Step 3：检查 frame status

```bash
curl http://127.0.0.1:8000/api/perception/frame_status
```

期望：

```text
available=true
stale=false
size_bytes > 0
```

## Step 4：获取最新图片

```bash
curl http://127.0.0.1:8000/api/perception/latest_frame \
  --output /tmp/latest_yolo_frame.jpg
```

确认 `/tmp/latest_yolo_frame.jpg` 可打开。

## Step 5：打开 Dashboard

检查：

- 能看到最新识别图像；
- 图像会自动刷新；
- 能看到检测对象和事件；
- 停止 YOLO 服务后，页面进入 stale 或 unavailable 状态。

---

## 9. 后续阶段预告

Phase 4E 完成后，如果仍需要进一步增强，可以考虑：

1. MJPEG 识别流；
2. 更低延迟的视频流方案；
3. YOLO 事件节流和告警等级优化；
4. INT8 量化模型；
5. 摄像头自启动 systemd 服务；
6. YOLO 识别结果与任务状态联动。

但这些不属于本阶段范围。
