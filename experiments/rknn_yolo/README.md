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
- `models/labels.txt`：类别文件，必须与模型导出时的类别顺序一致；当前提交的是 COCO 80 类默认标签，请按真实模型确认。
- `samples/test.jpg`：单图推理测试图片。
- `outputs/`：保存 `detections.json`、`detection_status.json` 等临时输出。

## 1. 模型加载最小验证

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 load_rknn_test.py
```

通过标准：输出 `RKNN model load/init OK`。

## 2. 单图推理并输出 detections

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detections \
  > outputs/detections.json
```

脚本会在终端 stderr 打印 RKNN 输出调试信息，例如：

```text
===== RKNN output debug =====
Number of outputs: 1
Output 0: shape=(1, 300, 6), dtype=float32, min=..., max=..., mean=...
=============================
```

`stdout` 只输出 JSON，因此可以安全重定向到文件。

## 3. 输出 detection_status

```bash
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --frame-id camera_front \
  --format detection_status \
  > outputs/detection_status.json
```

输出格式：

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

## 4. 提交到后端 state_store

后端不依赖 RKNN runtime 启动。先启动后端：

```bash
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

提交 detection_status：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
curl -X POST http://127.0.0.1:8000/api/internal/perception/detection_status \
  -H "Content-Type: application/json" \
  -d @outputs/detection_status.json
```

检查最新状态：

```bash
curl http://127.0.0.1:8000/api/state/latest
```

通过标准：返回 JSON 中包含 `data.detection_status`，且 Dashboard 的“视觉检测状态”卡片同步显示 source、model、最近目标、最近事件和更新时间。

## 5. 已知输出格式

当前 `models/yolo26n_fp32.rknn` 在 `samples/test.jpg` 上已观察到输出：

```text
Output 0: shape=(1, 300, 6), dtype=float32
```

脚本按 `[x1, y1, x2, y2, score, class_id]` 解析该输出，同时兼容常见 YOLO 输出布局：

- `(1, N, C)`
- `(1, C, N)`
- 典型多 head 输出中的 channel-first / channel-last 预测矩阵

## 6. 手工验收清单

- [ ] `.rknn` 模型位于 `models/yolo26n_fp32.rknn`。
- [ ] `labels.txt` 与模型类别顺序一致。
- [ ] `samples/test.jpg` 是可读取图片。
- [ ] `infer_image.py --format detections` 能输出合法 JSON。
- [ ] `infer_image.py --format detection_status` 能输出合法 JSON。
- [ ] 终端能看到 RKNN output debug shape。
- [ ] 有明显目标的图片能输出非空 `objects`。
- [ ] 无检测时输出 `objects=[]`，不报错。
- [ ] POST 到 `/api/internal/perception/detection_status` 后，`GET /api/state/latest` 能看到 `detection_status`。
- [ ] Dashboard 能显示视觉检测状态，不显示视频流，不影响 mission UI。

## 7. 限制

- 不训练模型。
- 不转换 `.pt/.onnx/.rknn`。
- 不下载模型。
- 不做视频流 / 摄像头循环。
- 不把 YOLO 结果直接接入导航、急停或电机控制。
