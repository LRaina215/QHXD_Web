# DO_PHASE4C.md

## Phase 4C：RK3588 本地 YOLO26 / RKNN 推理接入与验收

## 1. 阶段背景

当前阶段已经完成以下前置工作：

- YOLO26 模型已完成训练或预训练模型已准备完成；
- 已得到 RK3588 可加载的 `.rknn` 模型文件；
- `.rknn` 模型已经放入 RK3588 项目的模型目录；
- RK3588 端已安装 `rknn-toolkit-lite2`；
- RK3588 端 `librknnrt.so` 已更新到可加载当前 `.rknn` 模型的版本；
- 最小 `load_rknn_test.py` 已验证模型可以 `load_rknn` 并 `init_runtime`。

Phase 4C 的目标不是训练模型，也不是做图传，而是把已经放入 RK3588 的 `.rknn` 模型真正接入项目，实现：

```text
图片输入 -> RKNN 推理 -> YOLO26 后处理 -> detection_status -> state_store -> REST / WebSocket / Dashboard
```

本阶段仍然保持弱耦合原则：YOLO 只产生检测结果、事件和告警，不直接控制底盘，不直接修改导航，不直接触发急停。

---

## 2. Codex 能否完成本阶段？

### 2.1 可以交给 Codex 完成的部分

以下内容可以交给 Codex：

1. 修改 `infer_image.py` 的输入预处理逻辑；
2. 增加 RKNN 输出 shape 调试打印；
3. 根据实际 RKNN 输出 shape 实现 YOLO26 后处理；
4. 实现 NMS、置信度过滤、类别映射；
5. 输出普通 detections JSON；
6. 输出 Phase 4A/4C 统一格式的 `detection_status`；
7. 将 `detection_status` 接入 RK3588 后端 `state_store`；
8. 通过 REST / WebSocket 暴露 `detection_status`；
9. 在 Dashboard 增加视觉检测卡片；
10. 增加最小测试、README 和运行说明。

### 2.2 仍然需要人工操作的部分

以下内容仍然需要人工完成或确认：

1. 确认 `.rknn` 模型文件已经放在正确目录；
2. 确认 `labels.txt` 与模型类别顺序一致；
3. 准备至少 1 张测试图片，建议包含人、箱子、椅子等可检测目标；
4. 在 RK3588 真机上运行推理脚本；
5. 将首次 RKNN 输出 shape 发给 Codex / 开发者用于确认后处理逻辑；
6. 人工查看输出检测结果是否明显合理；
7. 如果后处理结果为空或框明显错误，需要人工提供输出 shape 和样例输出，再让 Codex 调整；
8. 若涉及摄像头输入，需要人工确认摄像头设备号和权限。

注意：Codex 可以写代码，但它不能替代你判断模型输出是否“视觉上合理”。最终仍需要你在 RK3588 真机上跑图确认。

---

## 3. 本阶段不做的内容

Phase 4C 不做以下任务：

- 不训练 YOLO；
- 不做 `.pt -> .onnx -> .rknn` 转换；
- 不自动下载模型；
- 不做实时视频流 / WebRTC / RTSP；
- 不做摄像头长时间巡检循环；
- 不做 YOLO 结果直接控制底盘；
- 不把 YOLO 结果直接接入 Nav2 costmap；
- 不做复杂多目标跟踪；
- 不做行为识别；
- 不做多页面复杂前端重构。

---

## 4. 目录约定

建议 RK3588 侧保持如下结构：

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

其中：

- `models/*.rknn`：RK3588 NPU 推理模型；
- `models/labels.txt`：类别文件，必须与训练/导出模型的类别顺序一致；
- `samples/test.jpg`：测试图片；
- `outputs/`：保存检测结果、JSON 或可选的可视化图片。

---

## 5. 总体任务清单

### T4C-1：修正 `infer_image.py` 输入预处理

目标：保证输入符合 YOLO26 RKNN 模型要求。

最低要求：

- 读取图片；
- BGR 转 RGB；
- resize 到 `640x640`；
- 增加 batch 维度；
- 输入格式与 RKNN 模型实际要求一致；
- 保留清晰报错信息。

验收标准：

- 脚本能加载 `.rknn` 模型；
- 脚本能读取测试图片；
- 脚本能完成一次 `rknn.inference()`；
- 终端能打印每个输出 tensor 的 shape、dtype、min、max、mean。

---

### T4C-2：确认 RKNN 输出 shape

目标：获得 YOLO26 RKNN 模型的真实输出格式。

人工操作：

```bash
cd ~/QHXD/experiments/rknn_yolo

python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25
```

验收标准：

- 终端输出类似：

```text
===== RKNN output debug =====
Number of outputs: ...
Output 0: shape=..., dtype=..., min=..., max=..., mean=...
...
=============================
```

- 如果输出 shape 无法匹配后处理，必须记录并反馈。

---

### T4C-3：实现 YOLO26 后处理

目标：根据实际输出 shape，将原始 tensor 转换成检测框。

最低要求：

- 支持常见 YOLO 输出格式：
  - `(1, N, C)`；
  - `(1, C, N)`；
  - 多输出 head；
- 支持 `xywh -> xyxy`；
- 支持 objectness / class score 组合；
- 支持 confidence threshold；
- 支持 NMS；
- 支持 labels 映射；
- 输出统一 objects 列表。

输出示例：

```json
{
  "timestamp": "2026-05-19T00:00:00Z",
  "objects": [
    {
      "class_name": "person",
      "confidence": 0.86,
      "bbox_xyxy": [120.0, 80.0, 260.0, 360.0]
    }
  ]
}
```

验收标准：

- 对含有明显目标的测试图片，能够输出非空 `objects`；
- 置信度低于阈值的检测会被过滤；
- 多个重叠框会被 NMS 合并；
- 类别名称来自 `labels.txt`；
- 没有检测结果时输出空数组，而不是报错。

---

### T4C-4：生成 `detection_status`

目标：将 detections 封装成项目统一的感知状态。

输出格式：

```json
{
  "detection_status": {
    "enabled": true,
    "source": "rk3588-rknn-yolo26",
    "model_name": "yolo26n_fp32.rknn",
    "frame_id": "camera_front",
    "timestamp": "2026-05-19T00:00:00Z",
    "objects": [],
    "events": []
  }
}
```

事件规则第一版：

| 检测类别 | 事件 |
|---|---|
| person | `person_detected` |
| chair / backpack / suitcase / box 等 | `obstacle_detected` |
| 连续多次障碍存在 | `possible_blockage` |

验收标准：

- `--format detections` 能输出普通 detections；
- `--format detection_status` 能输出统一状态；
- 检测到 person 时生成 `person_detected`；
- 无目标时 `objects=[]`，`events=[]`。

---

### T4C-5：接入 RK3588 后端 `state_store`

目标：让本地 YOLO 结果进入中台状态。

最低要求：

- 后端状态模型支持可选 `detection_status`；
- 增加本地感知服务接口；
- 支持提交最新 `detection_status`；
- 更新 `state_store`；
- 通过 `GET /api/state/latest` 可查看；
- 通过 `WS /ws/state` 可推送。

可以先提供一个内部调试接口，例如：

```http
POST /api/internal/perception/detection_status
```

验收标准：

- 后端不依赖 RKNN runtime 也能正常启动；
- 手工提交 sample detection_status 后，`GET /api/state/latest` 能看到该字段；
- WebSocket 能推送 detection_status 更新；
- mock / real 模式不被破坏。

---

### T4C-6：Dashboard 显示视觉检测状态

目标：在现有 Dashboard 中增加一个小型视觉检测卡片。

显示内容：

- YOLO 状态：enabled / offline；
- source；
- model_name；
- 最近检测目标；
- 最近检测事件；
- 最近更新时间。

验收标准：

- Dashboard 能显示 detection_status；
- WebSocket 更新后页面自动刷新；
- 无检测结果时显示“暂无目标”；
- 不显示视频流；
- 不重构整体 UI。

---

## 6. 给 Codex 的分轮 Prompt

## Round C1：修正推理输入与输出 shape 调试

```text
Read AGENTS.md and current Phase 4A/4C docs.

Task:
Fix RK3588 RKNN YOLO image inference preprocessing and add output shape debugging.

Scope:
Only modify experiments/rknn_yolo/infer_image.py and directly related helper files if needed.
Do not integrate with backend or Dashboard in this round.

Requirements:
1. Ensure input image is read correctly.
2. Convert BGR to RGB.
3. Resize input image to 640x640.
4. Add batch dimension.
5. Feed data into RKNNLite inference in a format compatible with the exported model.
6. Print debug info for each output tensor:
   - index
   - shape
   - dtype
   - min
   - max
   - mean
7. Keep existing CLI arguments:
   - --model
   - --image
   - --labels
   - --conf
   - --frame-id
   - --format
8. Do not implement final YOLO postprocess yet unless output shape is already known.

Validation:
- python3 infer_image.py --model models/yolo26n_fp32.rknn --image samples/test.jpg --labels models/labels.txt --conf 0.25 runs inference successfully.
- Terminal prints Number of outputs and each output shape.
- Missing model/image/labels still produce clear errors.

Only modify files required for this task.
```

---

## Round C2：实现 YOLO26 输出后处理

```text
Continue in the same thread.

Task:
Implement YOLO26 postprocessing for RKNN output.

Prerequisite:
Use the actual output shapes observed from Round C1.

Requirements:
1. Parse RKNN outputs into detection boxes.
2. Support common YOLO output layouts:
   - (1, N, C)
   - (1, C, N)
   - multi-output heads if present
3. Convert boxes to bbox_xyxy.
4. Apply confidence threshold.
5. Apply class score filtering.
6. Apply NMS.
7. Map class ids to labels.txt.
8. Return objects list with:
   - class_name
   - confidence
   - bbox_xyxy
9. Empty detections must return objects=[] without error.
10. Keep output JSON stable.

Validation:
- Running infer_image.py on samples/test.jpg produces valid JSON.
- At least one obvious target can be detected if the test image contains known classes.
- No detections case is handled cleanly.

Only modify experiments/rknn_yolo/ files.
```

---

## Round C3：完善 detection_status 输出

```text
Continue in the same thread.

Task:
Finalize detection_status output for RK3588 local YOLO.

Requirements:
1. Ensure --format detections outputs plain detections JSON.
2. Ensure --format detection_status wraps detections into detection_status.
3. detection_status must include:
   - enabled
   - source = rk3588-rknn-yolo26
   - model_name
   - frame_id
   - timestamp
   - objects
   - events
4. Generate simple events:
   - person_detected
   - obstacle_detected
   - possible_blockage if supported by current helper state
5. Add or update README with command examples.

Validation:
- --format detections works.
- --format detection_status works.
- person class generates person_detected event.
- Empty result produces empty objects/events.

Only modify experiment files and minimal README docs.
```

---

## Round C4：接入后端 state_store

```text
Read AGENTS.md and current RK3588 backend docs.

Task:
Integrate local YOLO detection_status into the RK3588 backend state flow.

Scope:
Do not require RKNN runtime for backend startup.
Do not run actual YOLO inside FastAPI process in this round.
Only allow detection_status to be submitted and stored.

Requirements:
1. Extend state schemas to include optional detection_status if not already present.
2. Add a service for latest local perception status.
3. Add internal endpoint:
   POST /api/internal/perception/detection_status
4. Store latest detection_status in state_store.
5. Expose detection_status through:
   - GET /api/state/latest
   - WS /ws/state
6. Preserve existing mock/real mode behavior.
7. Do not modify mission bridge behavior.

Validation:
- backend starts without RKNN runtime.
- POST sample detection_status succeeds.
- GET /api/state/latest includes detection_status.
- WebSocket pushes detection_status update.

Only modify backend files required for this task.
```

---

## Round C5：Dashboard 显示检测状态

```text
Continue in the same thread.

Task:
Display detection_status on the Dashboard.

Requirements:
1. Add a small visual detection card.
2. Show:
   - enabled/offline
   - source
   - model_name
   - latest objects
   - latest events
   - timestamp
3. Keep UI consistent with current Dashboard.
4. Do not add video streaming.
5. Do not redesign the whole UI.

Validation:
- frontend starts.
- Dashboard shows sample detection_status from backend.
- WebSocket updates refresh the card.
- Existing mission/status UI still works.

Only modify frontend files required for this task.
```

---

## Round C6：阶段收尾与验收文档

```text
Continue in the same thread.

Task:
Prepare Phase 4C YOLO inference integration for acceptance.

Requirements:
1. Update experiments/rknn_yolo/README.md with:
   - model placement
   - labels placement
   - sample image placement
   - how to run infer_image.py
   - how to output detection_status
2. Add backend verification commands:
   - POST detection_status
   - GET latest state
3. Add Dashboard verification notes.
4. Do not add new features.

Validation:
- README commands are executable.
- Acceptance checklist is clear.
- No unrelated refactors.

Only modify docs/README files if code is already complete.
```

---

## 7. 总体验收标准

Phase 4C 通过需同时满足：

1. RK3588 能加载 `.rknn` 模型并完成一次图片推理；
2. `infer_image.py` 能输出 RKNN 输出 shape；
3. 后处理能生成 `objects`；
4. 支持 `--format detection_status`；
5. 后端可接收并存储 `detection_status`；
6. `GET /api/state/latest` 能看到 `detection_status`；
7. WebSocket 能推送 `detection_status`；
8. Dashboard 能显示检测状态和事件；
9. 没有视频流也不影响验收；
10. YOLO 结果不直接控制底盘。

---

## 8. 人工最终验收步骤

### 8.1 模型推理验收

```bash
cd ~/QHXD/experiments/rknn_yolo

python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detection_status
```

通过标准：

- 命令成功运行；
- 输出 JSON；
- JSON 中存在 `detection_status`；
- 如果图片中有可识别目标，`objects` 非空。

### 8.2 后端状态接入验收

将 detection_status 提交给后端：

```bash
curl -X POST http://127.0.0.1:8000/api/internal/perception/detection_status \
  -H "Content-Type: application/json" \
  -d @outputs/detection_status.json
```

检查最新状态：

```bash
curl http://127.0.0.1:8000/api/state/latest
```

通过标准：

- 返回 JSON 中包含 `detection_status`。

### 8.3 Dashboard 验收

打开前端页面，检查：

- 是否显示视觉检测卡片；
- 是否显示模型名称；
- 是否显示最近目标；
- 是否显示事件；
- WebSocket 更新是否能刷新页面。

---

## 9. 后续阶段预留

Phase 4C 完成后，后续可以继续扩展：

1. 摄像头实时输入；
2. 周期性 YOLO 推理服务；
3. 保存检测截图；
4. 视觉告警入库；
5. 与巡检任务关联；
6. 自定义模型 INT8 量化版本部署；
7. 进一步优化 RK3588 NPU 推理性能。

这些不属于本阶段验收范围。
