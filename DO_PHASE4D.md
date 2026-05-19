# DO_PHASE4D.md

## 阶段名称

**Phase 4D：RK3588 YOLO 摄像头连续检测服务**

## 阶段背景

Phase 4C 已经完成 RK3588 本地 YOLO26 / RKNN 单图推理链路：

```text
samples/test.jpg
  -> yolo26n_fp32.rknn
  -> infer_image.py
  -> YOLO 后处理
  -> detection_status JSON
  -> 后端 state_store
  -> REST / Dashboard
```

其中已验证的关键配置为：

```text
模型：models/yolo26n_fp32.rknn
输入尺寸：640x640
输入格式：RGB
输入 layout：NHWC
输入 dtype：float32
输入范围：0.0 ~ 1.0
输出 shape：(1, 300, 6)
输出 layout：xyxy_score_class
```

Phase 4D 不再处理训练、模型转换、runtime 兼容、单图推理修复等问题，而是在 Phase 4C 的基础上，将单图推理升级为 **RK3588 摄像头连续检测服务**。

---

## 一、阶段目标

本阶段目标是实现：

```text
USB 摄像头 / 本地摄像头
    -> RK3588 连续采帧
    -> YOLO26 RKNN 推理
    -> detection_status
    -> 后端 state_store
    -> REST / WebSocket
    -> Dashboard 实时显示视觉检测状态
```

最终应支持：

1. RK3588 从摄像头连续采集图像；
2. 按固定频率执行 YOLO26 RKNN 推理；
3. 将检测结果封装成 `detection_status`；
4. 定期提交到后端接口 `/api/internal/perception/detection_status`；
5. Dashboard 能持续看到最新目标与视觉事件；
6. 摄像头异常、模型异常、推理异常时有明确状态反馈；
7. YOLO 服务不影响 mission bridge、语音交互和主状态中台。

---

## 二、本阶段不做什么

Phase 4D 明确不做：

- 不重新训练 YOLO；
- 不重新导出 ONNX；
- 不重新转换 RKNN；
- 不修改 `librknnrt.so` / RKNN runtime；
- 不做 INT8 量化；
- 不做视频流推送 / WebRTC / RTSP；
- 不做摄像头画面 Web 播放；
- 不让 YOLO 结果直接控制底盘；
- 不接入 Nav2 costmap；
- 不修改 NUC bridge；
- 不修改 RT-Thread 相关控制逻辑；
- 不重构 Dashboard 整体 UI。

本阶段只做 **连续检测服务 + detection_status 更新 + Dashboard 显示**。

---

## 三、推荐目录结构

建议在现有目录基础上新增：

```text
experiments/rknn_yolo/
├── infer_image.py                         # 已有：单图推理
├── detection_status_builder.py            # 已有：detection_status 封装
├── camera_detect_service.py               # 新增：摄像头连续检测服务
├── camera_config.example.json             # 新增：摄像头服务配置示例
├── models/
│   ├── yolo26n_fp32.rknn
│   └── labels.txt
├── samples/
├── outputs/
└── README.md
```

如果后续要正式服务化，可以再迁移到：

```text
backend/app/services/perception/
```

但本阶段优先放在 `experiments/rknn_yolo/` 下，降低对主后端的侵入。

---

## 四、任务清单

## Task 1：抽取可复用的单帧推理函数

### 目标

将 `infer_image.py` 中已经验证可用的预处理、RKNN 推理、输出解析逻辑抽取为可复用函数，供摄像头连续服务调用。

### 需要做什么

在不破坏 `infer_image.py` 原有 CLI 的前提下，整理以下能力：

1. 加载 RKNN 模型；
2. 初始化 runtime；
3. 对单帧图像执行预处理；
4. 执行推理；
5. 解析输出；
6. 生成 `detection_status`。

### 建议函数

可以在 `infer_image.py` 中保留，也可以抽成新文件，例如 `rknn_yolo_runner.py`：

```python
class RknnYoloRunner:
    def __init__(self, model_path, labels_path, conf=0.25, output_layout="xyxy_score_class"):
        ...

    def load(self):
        ...

    def infer_frame(self, frame_bgr_or_rgb) -> dict:
        ...

    def release(self):
        ...
```

### 关键要求

必须继续沿用 Phase 4C 已验证的预处理：

```text
RGB
resize 640x640
NHWC
float32 / 255.0
batch 维度
```

### 验收标准

执行原单图命令仍然成功：

```bash
cd ~/QHXD/experiments/rknn_yolo

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

必须满足：

- 命令无报错；
- JSON 合法；
- 输出图像正常；
- 检测框不回退到 Phase 4C 修复前的异常状态；
- `infer_image.py` 原有 CLI 参数仍可用。

---

## Task 2：实现摄像头连续检测脚本

### 目标

新增摄像头连续检测服务脚本：

```text
experiments/rknn_yolo/camera_detect_service.py
```

该脚本负责：

1. 打开摄像头；
2. 按设定 FPS 采帧；
3. 调用 YOLO26 RKNN 推理；
4. 生成 `detection_status`；
5. 可选择提交到后端；
6. 可选择保存最近一帧检测可视化图片。

### CLI 参数建议

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --conf 0.25 \
  --fps 2 \
  --frame-id camera_front \
  --backend-url http://127.0.0.1:8000 \
  --submit \
  --save-latest outputs/latest_camera_detection.jpg
```

### 参数要求

必须支持：

- `--model`：RKNN 模型路径；
- `--labels`：标签文件路径；
- `--camera`：摄像头设备编号，默认 0；
- `--conf`：置信度阈值，默认 0.25；
- `--fps`：推理频率，默认 2；
- `--frame-id`：默认 `camera_front`；
- `--backend-url`：后端地址，默认 `http://127.0.0.1:8000`；
- `--submit`：是否提交到后端；
- `--save-latest`：是否保存最近一帧画框结果；
- `--max-det`：最大保留框数，默认 20；
- `--dry-run`：只打印 detection_status，不提交后端。

### 验收标准

在 RK3588 上执行：

```bash
cd ~/QHXD/experiments/rknn_yolo

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

必须满足：

- 摄像头能打开；
- 程序能持续运行；
- 终端能周期性输出 detection_status 摘要；
- `outputs/latest_camera_detection.jpg` 能生成并更新；
- Ctrl+C 后程序能正常释放摄像头和 RKNN runtime。

---

## Task 3：实现后端提交功能

### 目标

让摄像头检测服务能周期性将 `detection_status` 提交到 RK3588 后端。

后端接口：

```http
POST /api/internal/perception/detection_status
```

### 需要做什么

在 `camera_detect_service.py` 中实现：

```text
detection_status
  -> HTTP POST
  -> /api/internal/perception/detection_status
```

### 要求

1. 提交失败不能导致服务崩溃；
2. 网络异常要打印清晰日志；
3. 后端异常时继续采集和推理；
4. 支持提交间隔，避免过高频率刷后端；
5. 默认提交频率不超过检测 FPS。

### 验收标准

先启动后端：

```bash
cd ~/QHXD/backend
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

再运行摄像头服务：

```bash
cd ~/QHXD/experiments/rknn_yolo

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

检查后端状态：

```bash
curl http://127.0.0.1:8000/api/state/latest
```

必须满足：

- `detection_status.source = rk3588-rknn-yolo26`；
- `detection_status.model_name = yolo26n_fp32.rknn`；
- `detection_status.objects` 随摄像头画面变化；
- `detection_status.timestamp` 周期更新；
- 后端无异常崩溃。

---

## Task 4：增加视觉事件节流

### 目标

防止连续检测时同类事件刷屏，例如 `person_detected` 每秒重复提交多次，导致 Dashboard 和 logs 过载。

### 需要做什么

在 `camera_detect_service.py` 或 `detection_status_builder.py` 中增加事件节流机制。

### 建议策略

对同类事件设置最小间隔：

```text
person_detected: 5 秒内最多触发一次
obstacle_detected: 5 秒内最多触发一次
possible_blockage: 10 秒内最多触发一次
```

但对象列表 `objects` 仍可每帧更新，节流只针对 `events`。

### 验收标准

连续运行摄像头服务 1 分钟：

- `objects` 可以持续刷新；
- `events` 不应每帧重复刷屏；
- 同类事件间隔符合配置；
- Dashboard 不出现告警爆炸。

---

## Task 5：增加摄像头离线与服务状态

### 目标

摄像头异常时，系统应输出明确状态，而不是静默退出或卡死。

### 需要做什么

处理以下异常：

- 摄像头打不开；
- 摄像头读取帧失败；
- RKNN 推理异常；
- 后端提交失败；
- 用户 Ctrl+C 退出。

### 建议状态

当摄像头打不开时输出：

```json
{
  "detection_status": {
    "enabled": false,
    "source": "rk3588-rknn-yolo26",
    "model_name": "yolo26n_fp32.rknn",
    "frame_id": "camera_front",
    "objects": [],
    "events": [
      {
        "event_type": "camera_unavailable",
        "level": "warning",
        "message": "摄像头不可用或无法打开"
      }
    ]
  }
}
```

### 验收标准

使用错误摄像头编号测试：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 99 \
  --dry-run
```

必须满足：

- 程序不出现难以理解的 traceback；
- 输出明确摄像头不可用；
- 如果开启 `--submit`，后端能看到 detection_status offline / unavailable 状态；
- 正常退出并释放资源。

---

## Task 6：Dashboard 显示连续检测状态

### 目标

确认当前 Dashboard 能持续显示由摄像头服务提交的检测结果。

如果已有 detection_status 卡片，只需小幅增强，不要重构 UI。

### 页面至少显示

- YOLO 服务状态：enabled / offline；
- source；
- model_name；
- 最近更新时间；
- 最近检测对象；
- 最近视觉事件。

### 验收标准

运行摄像头服务后：

- Dashboard 能看到 YOLO 状态持续更新；
- 摄像头画面变化时 objects 变化；
- 事件不刷屏；
- 停止摄像头服务后，页面最终进入超时或 offline 状态；
- 原有 mission、mode、state 展示不受影响。

---

## Task 7：补充 README 与运行说明

### 目标

更新：

```text
experiments/rknn_yolo/README.md
README.md
```

说明如何从单图推理进入摄像头连续检测。

### README 必须包含

1. 摄像头服务启动命令；
2. dry-run 模式；
3. submit 模式；
4. 常见问题；
5. 如何确认摄像头设备号；
6. 如何确认后端接收成功；
7. 如何查看 Dashboard；
8. 本阶段不包含视频流展示。

### 推荐写入命令

查看摄像头：

```bash
ls /dev/video*
```

测试 dry-run：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --fps 1 \
  --dry-run
```

提交后端：

```bash
python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --fps 1 \
  --backend-url http://127.0.0.1:8000 \
  --submit
```

### 验收标准

新成员只看 README，就能完成：

- 找到摄像头设备；
- 启动连续检测；
- 查看 detection_status；
- 知道为什么没有视频流；
- 知道如何停止服务。

---

## Task 8：生成 Phase 4D 完成记录

### 目标

新增：

```text
PHASE4D_DONE.md
```

记录本阶段实际完成内容、运行命令、实机结果与遗留问题。

### 必须包含

- 阶段结论；
- 修改文件列表；
- 摄像头服务启动方式；
- dry-run 验证结果；
- submit 验证结果；
- Dashboard 验证结果；
- 当前 FPS；
- 当前模型；
- 当前摄像头编号；
- 已知问题；
- 后续可做但本阶段不做的事项。

### 验收标准

`PHASE4D_DONE.md` 应能回答：

- 当前 YOLO 是否能连续运行；
- 当前结果是否能进后端；
- 当前结果是否能上 Dashboard；
- 如何复现；
- 后续如果接视频流或摄像头服务 daemon 应从哪里继续。

---

## 五、给 Codex 的分轮 Prompt

## Round 1：抽取单帧推理能力

```text
Read AGENTS.md and current project docs.

Task:
Refactor the existing RKNN YOLO26 single-image inference code so it can be reused by a camera continuous detection service.

Scope:
Do not change model files, RKNN runtime, backend, Dashboard, mission bridge, NUC bridge, or RT-Thread code.

Requirements:
1. Preserve existing infer_image.py CLI behavior.
2. Extract reusable logic for:
   - model load/init/release
   - image/frame preprocessing
   - RKNN inference
   - output parsing
   - detection_status generation
3. Keep the verified preprocessing unchanged:
   - RGB
   - resize 640x640
   - NHWC
   - float32 / 255.0
   - batch dimension
4. Keep output layout xyxy_score_class supported.
5. Add minimal regression check documentation or comments.

Validation:
- Existing single-image command still works.
- detection_status JSON remains valid.
- draw-output image remains visually correct.
- No unrelated files are changed.

Only modify files required for this refactor.
```

---

## Round 2：实现摄像头连续检测 dry-run

```text
Continue in the same thread.

Task:
Add a RK3588 camera continuous detection service in experiments/rknn_yolo/camera_detect_service.py.

Scope:
Dry-run first. Do not submit to backend yet.

Requirements:
1. Open camera by --camera index.
2. Run RKNN YOLO inference at configurable --fps.
3. Print detection_status summary periodically.
4. Support --dry-run.
5. Support --save-latest outputs/latest_camera_detection.jpg.
6. Handle Ctrl+C and release camera/runtime cleanly.
7. Do not add video streaming.
8. Do not modify backend or Dashboard.

Validation:
- Service starts with camera 0.
- It runs continuously for at least 1 minute.
- It prints detection summaries.
- It saves latest detection image if requested.
- Ctrl+C exits cleanly.

Only modify experiment files required for this task.
```

---

## Round 3：实现后端提交

```text
Continue in the same thread.

Task:
Add backend submission support to the RK3588 camera detection service.

Requirements:
1. Add --backend-url.
2. Add --submit.
3. POST detection_status to /api/internal/perception/detection_status.
4. Submission failure must not crash the service.
5. Log submission success/failure clearly.
6. Keep --dry-run working.

Validation:
- Backend running at 127.0.0.1:8000 accepts submitted detection_status.
- GET /api/state/latest includes updated detection_status.
- If backend is down, camera service continues running and reports submission failure.

Only modify camera detection service and minimal docs.
```

---

## Round 4：事件节流与异常状态

```text
Continue in the same thread.

Task:
Add event throttling and camera/service error status handling.

Requirements:
1. Throttle repeated events:
   - person_detected
   - obstacle_detected
   - possible_blockage
2. Objects may update every inference cycle, but events must not spam.
3. If camera cannot open, output a clear camera_unavailable detection_status.
4. If frame read fails repeatedly, output camera_read_failed or camera_offline state.
5. If RKNN inference fails, output yolo_inference_error event.
6. Do not produce raw tracebacks for common runtime errors.

Validation:
- Wrong camera index reports camera_unavailable cleanly.
- Normal camera service does not spam repeated events every frame.
- Service can continue or exit cleanly depending on error severity.

Only modify files required for event throttling and error handling.
```

---

## Round 5：Dashboard 显示与 README 收口

```text
Continue in the same thread.

Task:
Verify and polish Phase 4D Dashboard display and documentation.

Requirements:
1. Ensure Dashboard can display continuously updated detection_status.
2. If a detection card already exists, only make minimal improvements.
3. Show enabled/offline, source, model_name, last update time, objects, and events.
4. Update experiments/rknn_yolo/README.md with:
   - dry-run command
   - submit command
   - camera troubleshooting
   - no video streaming note
5. Add or update PHASE4D_DONE.md with actual verification steps.
6. Do not redesign the Dashboard.
7. Do not add video streaming.

Validation:
- Camera service submit mode updates Dashboard.
- README commands are correct.
- PHASE4D_DONE.md documents how to reproduce.

Only modify files required for display and documentation.
```

---

## 六、总体验收标准

Phase 4D 通过需要满足以下全部条件：

1. RK3588 能打开摄像头；
2. YOLO26 RKNN 连续检测服务能运行至少 5 分钟；
3. 推理频率可配置，默认 1~2 FPS；
4. detection_status 能周期性生成；
5. detection_status 能提交到后端；
6. `/api/state/latest` 能看到最新 detection_status；
7. Dashboard 能看到视觉检测状态持续更新；
8. 摄像头异常时能明确提示；
9. 事件不会每帧刷屏；
10. 不影响 mission bridge、语音交互、mock/real 状态模式；
11. 不引入视频流、不控制底盘、不修改导航。

---

## 七、人工验收步骤

## 1. 摄像头设备确认

```bash
ls /dev/video*
```

如果没有设备，先确认 USB 摄像头插入和权限。

---

## 2. dry-run 验收

```bash
cd ~/QHXD/experiments/rknn_yolo

python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --fps 1 \
  --dry-run \
  --save-latest outputs/latest_camera_detection.jpg
```

检查：

- 终端有 detection_status 摘要；
- `outputs/latest_camera_detection.jpg` 更新；
- Ctrl+C 能正常退出。

---

## 3. submit 验收

启动后端：

```bash
cd ~/QHXD/backend
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

运行服务：

```bash
cd ~/QHXD/experiments/rknn_yolo

python3 camera_detect_service.py \
  --model models/yolo26n_fp32.rknn \
  --labels models/labels.txt \
  --camera 0 \
  --fps 1 \
  --backend-url http://127.0.0.1:8000 \
  --submit \
  --save-latest outputs/latest_camera_detection.jpg
```

查询状态：

```bash
curl http://127.0.0.1:8000/api/state/latest
```

检查 detection_status 是否随时间更新。

---

## 4. Dashboard 验收

打开 Dashboard，检查：

- YOLO enabled/offline 状态；
- 最新对象；
- 最新事件；
- 更新时间；
- 停止摄像头服务后状态变化。

---

## 八、后续阶段预告

Phase 4D 完成后，后续可以考虑但不在本阶段做：

1. 摄像头服务 systemd 化；
2. 摄像头画面 MJPEG / RTSP / WebRTC 推流；
3. YOLO INT8 量化；
4. 特定场景数据集微调；
5. 视觉事件与任务策略联动；
6. 视觉检测结果参与巡检报告生成；
7. 多摄像头支持。

