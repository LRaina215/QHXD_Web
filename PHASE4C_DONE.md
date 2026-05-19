# PHASE4C_DONE.md

## 阶段结论

Phase 4C RK3588 本地 YOLO26 / RKNN 单图推理链路已接入到项目验收路径：

```text
samples/test.jpg -> yolo26n_fp32.rknn -> YOLO 后处理 -> detection_status JSON -> 后端 state_store -> REST / Dashboard
```

本阶段没有增加视频流、摄像头循环、自动下载、模型训练、模型转换，也没有让 YOLO 结果直接控制底盘或 mission。

## 修改范围

- `experiments/rknn_yolo/infer_image.py`
  - 保留 CLI：`--model`、`--image`、`--labels`、`--conf`、`--frame-id`、`--format`。
  - 增加 640x640 预处理、RGB 输入、batch 维度。
  - OpenCV 可用时走 BGR -> RGB；当前板端无 `cv2` 时走 Pillow RGB fallback。
  - 增加 RKNN 输出 shape / dtype / min / max / mean 调试打印。
  - 捕获 RKNN native stdout，保证重定向文件是纯 JSON。
  - 支持 `(1, N, C)`、`(1, C, N)` 和常见多 head 预测矩阵。
  - 支持 `[x1, y1, x2, y2, score, class_id]` 与常见 `xywh + class scores` 输出。
  - 增加非有限值过滤、置信度过滤、bbox 缩放、NMS。
  - 支持 `--format detections` 与 `--format detection_status`。
- `experiments/rknn_yolo/detection_status_builder.py`
  - 默认 source 更新为 `rk3588-rknn-yolo26`。
  - 事件生成包括 `person_detected`、`obstacle_detected`、`possible_blockage`。
  - 同类事件做聚合，避免重复事件刷屏。
- `experiments/rknn_yolo/models/labels.txt`
  - 新增 COCO 80 类默认标签文件。实际验收前仍需确认与模型类别顺序一致。
- `experiments/rknn_yolo/README.md`
  - 补充模型、标签、样例图片、推理命令、detection_status 输出、后端提交和 Dashboard 验收说明。
- `README.md`
  - 更新 Phase 4C RKNN YOLO26 本地推理接入说明。

## 关键行号

- `experiments/rknn_yolo/infer_image.py:27` CLI 入口。
- `experiments/rknn_yolo/infer_image.py:41` stdout 重定向，避免 RKNN 日志污染 JSON。
- `experiments/rknn_yolo/infer_image.py:68` 图片读取与预处理。
- `experiments/rknn_yolo/infer_image.py:78` RKNN output debug 打印。
- `experiments/rknn_yolo/infer_image.py:81` `detection_status` 输出包装。
- `experiments/rknn_yolo/infer_image.py:115` RKNN load/init/inference。
- `experiments/rknn_yolo/infer_image.py:150` OpenCV / Pillow 预处理。
- `experiments/rknn_yolo/infer_image.py:208` 输出解析入口。
- `experiments/rknn_yolo/infer_image.py:259` prediction matrix 解码。
- `experiments/rknn_yolo/infer_image.py:357` NMS。
- `experiments/rknn_yolo/detection_status_builder.py:8` detection_status builder。
- `experiments/rknn_yolo/detection_status_builder.py:40` event builder。
- `README.md:576` Phase 4C 主说明。
- `experiments/rknn_yolo/README.md:1` 实验目录验收说明。

## 实机观察到的 RKNN 输出

当前模型与图片：

```text
model: experiments/rknn_yolo/models/yolo26n_fp32.rknn
image: experiments/rknn_yolo/samples/test.jpg
labels: experiments/rknn_yolo/models/labels.txt
```

实际输出：

```text
Number of outputs: 1
Output 0: shape=(1, 300, 6), dtype=float32
```

该输出按 `[x1, y1, x2, y2, score, class_id]` 解析。

## 验证结果

已执行：

```bash
python3 -m py_compile experiments/rknn_yolo/infer_image.py experiments/rknn_yolo/detection_status_builder.py
```

通过。

已执行模型加载验证：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 load_rknn_test.py
```

结果：`RKNN model load/init OK`。

已执行 detections 输出：

```bash
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detections \
  > outputs/detections.json
```

结果：`outputs/detections.json` 为合法 JSON。

已执行 detection_status 输出：

```bash
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detection_status \
  > outputs/detection_status.json
```

结果：`outputs/detection_status.json` 为合法 JSON，本次样例输出：

```text
source=rk3588-rknn-yolo26
model_name=yolo26n_fp32.rknn
objects=185
events=1
```

已执行后端接入验证：

```bash
cd /home/robomaster/QHXD/backend
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8027
```

后端在无 RKNN 依赖的 FastAPI 进程中正常启动。

提交 detection_status：

```bash
curl -X POST http://127.0.0.1:8027/api/internal/perception/detection_status \
  -H "Content-Type: application/json" \
  -d @/home/robomaster/QHXD/experiments/rknn_yolo/outputs/detection_status.json
```

返回 `success=true`、`accepted=true`、`state_updated=true`。

检查状态：

```bash
curl http://127.0.0.1:8027/api/state/latest
```

结果包含：

```text
detection_status.source = rk3588-rknn-yolo26
detection_status.model_name = yolo26n_fp32.rknn
objects = 185
events = 1
```

临时后端 `8027` 已停止。

## 仍需人工确认

- `models/labels.txt` 是否与 `yolo26n_fp32.rknn` 训练/导出类别顺序完全一致。
- `samples/test.jpg` 的检测框是否视觉上合理。
- 如果检测框类别明显不对，需要提供真实 labels 顺序或导出配置后再调整。
- 如果后续接摄像头，需要人工确认摄像头设备号和权限。
