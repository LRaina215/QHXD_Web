# PHASE4C_DONE.md

## 阶段结论

Phase 4C RK3588 本地 YOLO26 / RKNN 单图推理链路已正式收口到项目验收路径：

```text
samples/test.jpg -> yolo26n_fp32.rknn -> YOLO 后处理 -> detection_status JSON -> 后端 state_store -> REST / Dashboard
```

本阶段没有增加视频流、摄像头循环、模型训练、模型转换，也没有让 YOLO 结果直接控制底盘或 mission。

## 关键修正

此前 RKNN YOLO26 单图推理可以成功运行，但检测框明显异常。经人工排查，主要原因是输入预处理不匹配：原代码将图片以 `uint8 0~255` 输入模型，导致检测结果出现大量高置信度误检。

已将 OpenCV 分支与 Pillow fallback 分支统一修改为：

```python
input_tensor = np.expand_dims(resized.astype(np.float32) / 255.0, axis=0)
```

Pillow fallback 分支先将 `PIL.Image` 转为 `np.asarray(resized)`，再执行同样的 `float32 / 255.0` 归一化。

当前已验证输入格式：

- RGB
- NHWC
- float32
- 0.0~1.0
- 640x640

当前已验证输出格式：

- output shape = `(1, 300, 6)`
- output layout = `xyxy_score_class`
- 语义 = `[x1, y1, x2, y2, score, class_id]`

## 修改范围

- `experiments/rknn_yolo/infer_image.py`
  - 保留 `--output-layout auto|xyxy_score_class|xyxy_class_score|class_score_xyxy`，当前推荐验收使用 `xyxy_score_class`。
  - 保留 `--max-det`，默认 50；验收命令使用 20 限制视觉杂乱度。
  - 保留 `--debug-raw`，输出 raw rows 与每列统计。
  - 新增 `--debug-raw` 模式下的 `input_tensor shape/dtype/min/max` 打印，输出到 stderr，不污染 JSON stdout。
  - OpenCV 分支固定 BGR -> RGB -> resize 640x640 -> float32 / 255.0 -> NHWC batch。
  - Pillow fallback 分支固定 RGB -> resize 640x640 -> float32 / 255.0 -> NHWC batch。
  - 保持 RKNN runtime、模型加载逻辑、NMS、坐标过滤和 JSON 输出行为不变。
- `experiments/rknn_yolo/README.md`
  - 写入当前已验证输入/输出配置、推荐命令、debug 命令。
  - 写入 `labels.txt` 的官方预训练模型与自训练模型导出方法。
  - 强调 labels 必须与导出 ONNX / RKNN 的模型类别顺序一致。
  - 补充后端接入与人工验收清单。
- `README.md`
  - 更新 Phase 4C 项目总入口说明和推荐命令。

未修改：backend、Dashboard、mission bridge、RKNN runtime、模型文件、RT-Thread / NUC bridge。

## 关键行号

- `experiments/rknn_yolo/infer_image.py:36` `--debug-raw` 参数。
- `experiments/rknn_yolo/infer_image.py:37` `--output-layout` 参数。
- `experiments/rknn_yolo/infer_image.py:38` `--max-det` 参数。
- `experiments/rknn_yolo/infer_image.py:73` 图片预处理入口。
- `experiments/rknn_yolo/infer_image.py:77` `--debug-raw` 下打印 input tensor 统计。
- `experiments/rknn_yolo/infer_image.py:183` OpenCV BGR -> RGB。
- `experiments/rknn_yolo/infer_image.py:184` resize 到 640x640。
- `experiments/rknn_yolo/infer_image.py:185` OpenCV 分支 `float32 / 255.0`。
- `experiments/rknn_yolo/infer_image.py:199` Pillow fallback 读取 RGB。
- `experiments/rknn_yolo/infer_image.py:204` Pillow fallback resize 到 640x640。
- `experiments/rknn_yolo/infer_image.py:206` Pillow fallback `float32 / 255.0`。
- `experiments/rknn_yolo/infer_image.py:256` input tensor debug 打印函数。
- `experiments/rknn_yolo/README.md:32` 当前已验证配置。
- `experiments/rknn_yolo/README.md:68` 推荐验收命令。
- `experiments/rknn_yolo/README.md:108` `--debug-raw` 说明。
- `experiments/rknn_yolo/README.md:140` `labels.txt` 来源说明。
- `README.md:576` Phase 4C 总入口说明。

## 推荐运行命令

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

plain detections 输出：

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

## 已重新生成的验收输出

```text
experiments/rknn_yolo/outputs/debug_raw_fixed_preprocess.json
experiments/rknn_yolo/outputs/detections_fixed_preprocess.json
experiments/rknn_yolo/outputs/detection_status_fixed_preprocess.json
experiments/rknn_yolo/outputs/test_fixed_preprocess.jpg
```

本次固定预处理后，`xyxy_score_class` + `--max-det 20` 在 `samples/test.jpg` 上输出：

```text
objects = 6
first object = person, confidence = 0.9224
```

`--debug-raw` 已确认输入：

```text
input_tensor shape=(1, 640, 640, 3)
input_tensor dtype=float32
input_tensor min=0.000000
input_tensor max=1.000000
```

raw output 前几行示例：

```text
row 0: [62.5, 159.125, 298.75, 638.5, 0.922363, 0]
row 1: [223.125, 148.875, 569, 638, 0.878418, 0]
row 2: [120.062, 334.5, 179.125, 444.75, 0.414795, 41]
```

这与当前推荐 layout `xyxy_score_class` 匹配：第 5 列是 `0~1` score，第 6 列是整数 class id。

## 验证结果

已执行语法检查：

```bash
python3 -m py_compile experiments/rknn_yolo/infer_image.py experiments/rknn_yolo/detection_status_builder.py
```

通过。

已执行 debug raw 验证：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detections \
  --output-layout xyxy_score_class \
  --max-det 20 \
  --debug-raw \
  > outputs/debug_raw_fixed_preprocess.json
```

结果：stderr 打印 input tensor 统计、raw rows 和 per-column stats；stdout JSON 合法。

已执行 fixed preprocess detections 输出：

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

结果：JSON 合法，`outputs/test_fixed_preprocess.jpg` 已生成。

已执行 fixed preprocess detection_status 输出：

```bash
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detection_status \
  --output-layout xyxy_score_class \
  --max-det 20 \
  > outputs/detection_status_fixed_preprocess.json
```

结果：JSON 合法，`detection_status.objects = 6`。

已执行后端接入验证：

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

返回：

```text
success=true
accepted=true
state_updated=true
```

检查状态：

```bash
curl http://127.0.0.1:8027/api/state/latest
```

结果包含：

```text
detection_status.source = rk3588-rknn-yolo26
detection_status.model_name = yolo26n_fp32.rknn
detection_status.objects = 6
detection_status.events = person_detected, obstacle_detected
```

临时后端 `8027` 已停止。

## 仍需人工确认

- `outputs/test_fixed_preprocess.jpg` 的最终视觉验收：人是否基本被框住，框是否不再满屏乱飞，误检是否处于可接受范围。
- `models/labels.txt` 是否确实来自导出 `yolo26n_fp32.rknn` 的同一个 `yolo26n.pt` 或 `best.pt`。
- 如果后续换成自训练模型，必须重新生成与该模型匹配的 `labels.txt`。
- 如果后续接摄像头循环，需要另开任务确认摄像头设备号、帧率、权限与性能预算。
