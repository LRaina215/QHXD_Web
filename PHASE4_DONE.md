# PHASE4_DONE.md

## Phase 4 总结

Phase 4 已完成从“文本/语音指令入口”到“RK3588 YOLO26 视觉感知”再到“后端状态与 Dashboard 展示”的闭环接入。

本阶段没有改变底盘任务执行语义，也没有让视觉结果直接控制底盘。Phase 4 的定位是：

- 增加自然语言/语音任务入口；
- 增加 FunASR 离线语音识别接入；
- 增加 RKNN YOLO26 单图与 USB 摄像头连续检测能力；
- 将视觉检测结果以 `detection_status` 写入后端状态；
- 在 Dashboard 中展示视觉状态与最新检测画面；
- 为后续 Hik 相机、长期运行服务和更高级决策模块留下清晰扩展点。

## 参考完成记录

本文件基于以下阶段完成文档整理：

- `PAHSE4A_DONE.md`
- `PHASE4B_DONE.md`
- `PHASE4C_DONE.md`
- `PHASE4D_DONE.md`
- `PHASE4D_2_DONE.md`

注意：项目中历史文件名存在 `PAHSE4A_DONE.md` 的拼写，本文保留其原始文件名。

## Phase 4A：文本任务入口、语音 Mock 与感知状态基础

### 已完成内容

1. 完成 QHXD 项目整体复读与现状整理，确认 Phase 1/2/3 的任务、状态、桥接和 Dashboard 基础已经存在。
2. 新增文本任务入口能力，将自然语言任务解析为内部任务意图。
3. 新增 ASR mock 入口，用于在真实语音链路完成前验证任务指令闭环。
4. 新增 waypoint 解析能力，支持按别名匹配地点。
5. 新增 `detection_status` 后端数据结构和内部接收接口，为 YOLO 感知结果接入打基础。
6. Dashboard 增加视觉感知状态的最小展示区。
7. 新增 `experiments/rknn_yolo/` 实验目录，作为 RKNN YOLO26 推理链路的隔离工作区。

### 主要代码位置

- `backend/app/schemas.py`：增加语音/任务/检测相关 schema。
- `backend/app/main.py`：增加语音文本入口、ASR mock、内部感知接收接口。
- `backend/app/services/intent_parser.py`：自然语言任务意图解析。
- `backend/app/services/waypoint_resolver.py`：waypoint 与 alias 解析。
- `backend/app/services/voice_entry.py`：语音/文本任务入口服务。
- `backend/app/services/asr_service.py`：ASR mock 与后续真实 ASR 的服务边界。
- `backend/app/services/state_store.py`：保留和写入 `detection_status`。
- `backend/app/config/waypoints.json`：地点与别名配置。
- `frontend/src/App.vue`、`frontend/src/style.css`：Dashboard 感知状态展示。
- `experiments/rknn_yolo/`：RKNN YOLO 实验目录。

### 主要接口

- `POST /api/voice/text_command`
- `POST /api/voice/asr_text_mock`
- `POST /api/internal/perception/detection_status`

## Phase 4B：FunASR 语音识别与录音指令

### 已完成内容

1. 接入真实音频文件识别接口 `/api/voice/audio_command`。
2. 接入设备录音识别接口 `/api/voice/record_command`。
3. 增加 FunASR 模型路径、缓存行为和环境变量说明。
4. 增加 `AUDIO_DEVICE`、录音采样率、声道、时长等相关配置说明。
5. 明确 `voice_records` 目录行为：录音文件保存、调试用途与清理边界。
6. 文档化支持的语音指令与 waypoint aliases。
7. 处理未知语音：未知指令不会触发 mission。
8. 完成六条音频测试样本分类与重命名工作。

### 支持的核心语音指令

- “去二零一实验室”
- “暂停任务”
- “继续任务”
- “返回起点”
- “开始巡检”
- 未知命令：只返回无法识别/未知意图，不触发任务。

### 主要代码位置

- `backend/app/main.py`：`audio_command` 与 `record_command` 路由。
- `backend/app/schemas.py`：语音请求/响应 schema。
- `backend/app/services/asr_service.py`：FunASR 识别、模型路径、模型缓存。
- `backend/app/services/audio_recorder.py`：命令行录音封装。
- `backend/app/services/voice_entry.py`：ASR 文本到任务意图的统一入口。
- `backend/app/services/intent_parser.py`：命令意图解析。
- `backend/app/services/waypoint_resolver.py`：地点 alias 匹配。
- `backend/data/voice_records/`：录音输出目录。

### 主要接口

- `POST /api/voice/audio_command`
- `POST /api/voice/record_command`

### 验证结果

- 后端可启动。
- `audio_command` 可识别测试音频。
- `record_command` 可通过 USB 麦克风录音后识别。
- 错误录音设备会返回 `audio_record_failed`，不会误触发任务。
- 未知语音不会触发 mission。
- FunASR 模型缓存行为已验证并写入文档。
- 相关单元测试通过，记录中为 21 个测试通过。

### 已知限制

- 没有 wake word。
- 没有 streaming ASR。
- 没有浏览器麦克风录音。
- 没有接入 LLM/OpenClaw。

## Phase 4C：RKNN YOLO26 单图推理与 detection_status 接入

### 已完成内容

1. 完成 RK3588 上 `yolo26n_fp32.rknn` 单图加载和推理。
2. 修复关键预处理问题：输入必须是 `RGB + NHWC + float32 / 255.0 + 640x640`。
3. 增加安全解析与调试能力：`--debug-raw`、`--output-layout`、`--max-det`。
4. 支持多种 6 列输出布局：`auto`、`xyxy_score_class`、`xyxy_class_score`、`class_score_xyxy`。
5. 确认当前 YOLO26 RKNN 推荐输出布局为 `xyxy_score_class`。
6. 生成 `detections` 与 `detection_status` 两种 JSON 格式。
7. 支持绘制检测框到输出图片。
8. 验证后端可接收 `detection_status` 并写入 `state_store`。
9. 更新 RKNN YOLO README，说明 labels 来源、推荐命令和调试方法。

### 关键修正

此前推理可以运行，但检测框明显异常，出现大量高置信度误检。定位后确认主要原因是输入预处理与模型期望不匹配：原代码使用 `uint8 0~255` 输入。

已统一改为：

```python
input_tensor = np.expand_dims(resized.astype(np.float32) / 255.0, axis=0)
```

当前已验证输入：

- RGB
- NHWC
- float32
- 0.0 到 1.0
- 640x640

当前已验证输出：

- output shape = `(1, 300, 6)`
- output layout = `xyxy_score_class`
- row format = `[x1, y1, x2, y2, score, class_id]`

### 主要代码位置

- `experiments/rknn_yolo/infer_image.py`：单图推理、预处理、输出解析、NMS、绘图、CLI。
- `experiments/rknn_yolo/detection_status_builder.py`：YOLO 检测结果转后端 `detection_status`。
- `experiments/rknn_yolo/README.md`：模型、labels、推荐命令、调试说明。
- `experiments/rknn_yolo/models/yolo26n_fp32.rknn`：RKNN 模型。
- `experiments/rknn_yolo/models/labels.txt`：类别标签。
- `experiments/rknn_yolo/samples/test.jpg`：单图测试图片。
- `experiments/rknn_yolo/outputs/`：验收输出目录。

### 推荐单图验收命令

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

### 生成的验收文件

- `experiments/rknn_yolo/outputs/debug_raw_fixed_preprocess.json`
- `experiments/rknn_yolo/outputs/detections_fixed_preprocess.json`
- `experiments/rknn_yolo/outputs/detection_status_fixed_preprocess.json`
- `experiments/rknn_yolo/outputs/test_fixed_preprocess.jpg`

### 验证结果

- `infer_image.py` 语法检查通过。
- `--debug-raw` 可输出输入 tensor 与原始输出统计。
- JSON 输出合法。
- 绘制图片成功生成，检测框较修复前明显正常。
- 后端测试端口接收 `detection_status` 返回 `success=true`、`accepted=true`、`state_updated=true`。
- `/api/state/latest` 中可看到 `detection_status.source = rk3588-rknn-yolo26`。

### 注意事项

- `labels.txt` 必须与导出 ONNX/RKNN 的模型类别顺序一致。
- COCO 80 类 labels 只适用于 COCO 预训练模型。
- 自训练模型不能直接沿用 COCO labels。
- labels 错误通常影响类别名，不应导致框位置整体错乱。

## Phase 4D：USB 摄像头连续 YOLO 检测服务

### 已完成内容

1. 将单图推理能力封装为可复用的 `RknnYoloRunner`。
2. 新增 USB 摄像头连续检测服务。
3. 支持从 USB 摄像头按 FPS 抽帧推理。
4. 支持 dry-run 模式，只输出 JSONL，不提交后端。
5. 支持 submit 模式，将每帧检测结果提交到后端 `detection_status` 接口。
6. 支持保存最新带框图片。
7. 支持事件节流，避免同类事件过度刷屏。
8. 优先使用 OpenCV `VideoCapture` 抓帧，并保留 ffmpeg fallback 作为无 `cv2` 或 OpenCV 打不开相机时的备用路径。
9. 为后续 Hik 相机接入保留 camera service 边界。

### 主要代码位置

- `experiments/rknn_yolo/infer_image.py`：`RknnYoloRunner`。
- `experiments/rknn_yolo/camera_detect_service.py`：摄像头连续检测服务。
- `experiments/rknn_yolo/camera_config.example.json`：示例配置。
- `experiments/rknn_yolo/outputs/latest_camera_detection.jpg`：最新带框图片默认输出。

### USB 摄像头情况

已识别到 USB 摄像头设备：

- `/dev/video0`
- `/dev/video1`
- `/dev/video-dec0`
- `/dev/video-enc0`
- `Bus 007 Device 005: ID 32e6:9221 WebCamera WebCamera`

当前 Python 环境已验证 `cv2` 可用，实际 dry-run 使用 `OpenCvCameraSource` 从 USB 摄像头完成抓帧；ffmpeg fallback 仍保留为备用路径。

### 推荐运行命令

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo

python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 1 \
  --frame-id camera_front \
  --save-latest outputs/latest_camera_detection.jpg \
  --output-layout xyxy_score_class \
  --max-det 20 \
  --submit \
  --backend-url http://127.0.0.1:8000
```

### 验证结果

- dry-run 连续输出 3 行 JSON，`enabled=true`，检测对象数量正常。
- submit 模式可向后端提交，HTTP 200。
- `/api/state/latest` 中可看到检测对象与事件。
- 1 分钟运行验证完成：40 帧，约 64.11 秒，41 次提交包含结束时的 `service_stopped` 状态。
- 最新带框图片成功生成。
- OpenCV 采集路径补充验证完成：`python3` 使用 NumPy 1.21.5 与 OpenCV 4.5.4，服务启动日志显示 `backend=OpenCvCameraSource`，3 帧 dry-run 生成 `outputs/camera_cv2_dry_run.jsonl` 与 `outputs/latest_camera_detection_cv2.jpg`。

### 已知限制

- OpenCV `cv2` 已安装并验证可用，服务优先使用 OpenCV；ffmpeg fallback 仍保留。
- 尚未做 5 分钟以上长稳测试。
- 尚未做 systemd 服务化。
- 尚未接入 Hik SDK。
- 当前是抽帧检测，不是视频流服务。

## Phase 4D_2：最新检测画面后端接口与 Dashboard 展示

### 已完成内容

1. 后端新增最新检测画面读取接口。
2. Dashboard 在视觉检测卡片中增加最新检测画面展示区域。
3. Dashboard 每 2 秒刷新一次最新图片。
4. 当图片不存在或接口不可用时显示占位状态，不影响已有状态展示。
5. 摄像头检测服务支持 `--config` 配置文件启动。
6. 新增实际配置文件 `camera_config.json`。
7. 验证最新图片接口、缺图错误路径和前端构建。

### 主要代码位置

- `backend/app/main.py`：新增 `GET/HEAD /api/perception/latest_frame`。
- `backend/app/services/state_store.py`：保持原有状态写入语义。
- `frontend/src/App.vue`：Dashboard 最新检测图片展示。
- `frontend/src/style.css`：视觉图片区域样式。
- `experiments/rknn_yolo/camera_detect_service.py`：支持 `--config`。
- `experiments/rknn_yolo/camera_config.json`：当前 USB 相机配置。

### 最新画面接口

- `GET /api/perception/latest_frame`
- `HEAD /api/perception/latest_frame`

默认读取：

```text
/home/robomaster/QHXD/experiments/rknn_yolo/outputs/latest_camera_detection.jpg
```

可通过环境变量覆盖：

```text
PERCEPTION_LATEST_FRAME_PATH
```

接口行为：

- 图片存在：返回 `image/jpeg`，并带 `Cache-Control: no-store`。
- 图片不存在：返回 404 JSON，错误码为 `latest_frame_not_found`。

### 当前 camera_config.json

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

配置优先级：

```text
CLI 参数 > config 文件 > 默认值
```

### 验证结果

- 使用配置文件启动摄像头服务，`--max-frames 3` 正常生成最新图片并提交后端。
- `GET/HEAD /api/perception/latest_frame` 返回 200、`image/jpeg`、`no-store`。
- 下载的图片为 JPEG，分辨率记录为 1920x1080。
- 缺图路径返回 404 JSON，错误码正确。
- `frontend` 执行 `npm run build` 通过。

## 当前后端与前端运行方法

### 后端

```bash
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

如果当前 shell 激活的是不包含 `uvicorn` 的虚拟环境，需要切换到项目可用 Python 环境，或在该环境中安装后端依赖。

### 前端

```bash
cd /home/robomaster/QHXD/frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

### 摄像头 YOLO 服务

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config.json
```

### 查询后端状态

```bash
curl http://127.0.0.1:8000/api/state/latest
```

### 查看最新检测图片接口

```bash
curl -I http://127.0.0.1:8000/api/perception/latest_frame
curl http://127.0.0.1:8000/api/perception/latest_frame --output /tmp/latest_camera_detection.jpg
```

## Phase 4 交付接口总览

### 语音/任务入口

- `POST /api/voice/text_command`
- `POST /api/voice/asr_text_mock`
- `POST /api/voice/audio_command`
- `POST /api/voice/record_command`

### 感知状态

- `POST /api/internal/perception/detection_status`
- `GET /api/perception/latest_frame`
- `HEAD /api/perception/latest_frame`

### 既有状态展示

- `GET /api/state/latest`
- `/ws/state`

## Phase 4 交付文件总览

### 后端

- `backend/app/main.py`
- `backend/app/schemas.py`
- `backend/app/services/asr_service.py`
- `backend/app/services/audio_recorder.py`
- `backend/app/services/intent_parser.py`
- `backend/app/services/voice_entry.py`
- `backend/app/services/waypoint_resolver.py`
- `backend/app/services/state_store.py`
- `backend/app/config/waypoints.json`
- `backend/data/voice_records/`

### 前端

- `frontend/src/App.vue`
- `frontend/src/style.css`

### RKNN YOLO 实验链路

- `experiments/rknn_yolo/infer_image.py`
- `experiments/rknn_yolo/detection_status_builder.py`
- `experiments/rknn_yolo/camera_detect_service.py`
- `experiments/rknn_yolo/camera_config.json`
- `experiments/rknn_yolo/camera_config.example.json`
- `experiments/rknn_yolo/README.md`
- `experiments/rknn_yolo/models/yolo26n_fp32.rknn`
- `experiments/rknn_yolo/models/labels.txt`
- `experiments/rknn_yolo/outputs/`

### 阶段文档

- `PAHSE4A_DONE.md`
- `PHASE4B_DONE.md`
- `PHASE4C_DONE.md`
- `PHASE4D_DONE.md`
- `PHASE4D_2_DONE.md`
- `PHASE4_DONE.md`

## 手动验收清单

### 语音验收

- [ ] 后端启动成功。
- [ ] `/api/voice/audio_command` 可识别已知音频。
- [ ] `/api/voice/record_command` 可通过 USB 麦克风录音并识别。
- [ ] 未知语音不会触发 mission。
- [ ] FunASR 模型路径和缓存行为符合 README 说明。

### 单图 YOLO 验收

- [ ] `infer_image.py` 能加载 `models/yolo26n_fp32.rknn`。
- [ ] 输入预处理为 `RGB + NHWC + float32 / 255.0 + 640x640`。
- [ ] `--output-layout xyxy_score_class` 输出 JSON 合法。
- [ ] `outputs/test_fixed_preprocess.jpg` 检测框视觉合理。
- [ ] 不再出现大量随机高置信度误检满屏情况。

### 摄像头检测验收

- [ ] USB 摄像头可被系统识别。
- [ ] `camera_detect_service.py --config camera_config.json` 可启动。
- [ ] `outputs/latest_camera_detection.jpg` 持续更新。
- [ ] submit 模式可向后端提交 detection_status。
- [ ] 停止服务时可提交 offline/service_stopped 状态。

### 后端与 Dashboard 验收

- [ ] `/api/internal/perception/detection_status` 返回 accepted/state_updated。
- [ ] `/api/state/latest` 能看到 `detection_status`。
- [ ] `/api/perception/latest_frame` 返回 JPEG。
- [ ] 图片不存在时 `/api/perception/latest_frame` 返回 404 JSON。
- [ ] Dashboard 能显示 YOLO 状态、最近检测对象、事件和最新检测图片。
- [ ] Dashboard 不影响 mission/mode/state 原有功能。

## 已知限制与后续建议

1. 语音链路没有 wake word，仍需要主动调用接口。
2. 语音链路没有 streaming ASR。
3. Dashboard 没有浏览器麦克风录音。
4. 当前没有接入 LLM/OpenClaw。
5. YOLO 当前只做检测状态上报，不直接控制底盘。
6. 当前 USB 摄像头服务是抽帧检测，不是 MJPEG/WebRTC/RTSP 视频流。
9. 尚未 systemd 服务化。
10. 尚未接入 Hik 相机 SDK，但 `camera_detect_service.py` 已形成后续替换相机输入层的边界。
11. labels 必须与模型一致；换模型后必须重新确认 `models/labels.txt`。
12. Phase 4 未包含重新训练模型、重新导出 ONNX、重新转换 RKNN、INT8 量化或视频流推理。

## 最终结论

Phase 4 已经完成语音任务入口、离线 ASR、RKNN YOLO26 单图推理、USB 摄像头连续检测、后端感知状态接收、最新检测画面接口和 Dashboard 展示的主要闭环。

当前系统已经可以在 RK3588 上通过 USB 摄像头运行 YOLO26 检测，将结果提交到后端，并在 Dashboard 中查看检测状态与最新带框图片。后续 Phase 可以在此基础上继续做 Hik 相机适配、服务化部署、长期稳定性测试、视觉事件策略优化和更高级的任务决策接入。
