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
