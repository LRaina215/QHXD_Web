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
  - 支持 `--output-layout auto|xyxy_score_class|xyxy_class_score|class_score_xyxy`，避免把 6 列输出格式硬编码成单一假设。
  - 支持 `--debug-raw` 打印原始输出前 20 行和每列统计。
  - 支持 `--max-det` 限制 NMS 后保留的最大检测数，默认 50。
  - 增加非有限值过滤、置信度过滤、无效坐标过滤、bbox 缩放、NMS。
  - 支持 `--format detections` 与 `--format detection_status`。
  - 支持 `--draw-output outputs/test_detections.jpg` 生成画框图用于人工验收。
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

注意：画框图经人工检查明显不合理，不能再把该输出直接定论为某一种 6 列格式。当前脚本已加入 `--debug-raw`、`--output-layout` 和 `--max-det`，用于继续诊断真实输出语义。auto 模式会根据列范围推断 layout，但最终仍需结合可视化人工确认。

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

结果：`outputs/detection_status.json` 为合法 JSON，并已生成 `outputs/test_detections.jpg` 画框图。但人工复核发现画框十分杂乱，类别与实际不符，因此该输出只能作为诊断样例，不能作为“视觉合理”验收通过依据。

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


## 诊断更新：6 列输出 layout 待确认

新增诊断命令：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detections \
  --debug-raw \
  --max-det 20 \
  > outputs/debug_raw_detections.json
```

本次 `--debug-raw` 已验证会打印：

- output shape；
- first 20 raw rows；
- per-column min / max / mean / finite count。

当前原始输出前几列呈现如下特征：

```text
Output 0: shape=(1, 300, 6), dtype=float32
row 0: [276, 221.125, 321.5, 308.5, 0.998047, 59]
col 4: min=0.991211 max=0.998047 mean=0.996794
col 5: min=0 max=75 mean=27.296667
```

auto 模式当前推断：

```text
xyxy_score_class scores highest
```

但因为可视化仍然明显错误，下一步应继续人工确认：

- `labels.txt` 是否与模型真实类别顺序一致；
- 模型是否已经内置 NMS；
- 第 5/6 列到底是 score/class 还是其他语义；
- 坐标是否对应 resize 后 640 图、原图、letterbox 图或其他输入布局。

已验证强制 layout 命令可运行：

```bash
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detections \
  --output-layout class_score_xyxy \
  --max-det 20 \
  > outputs/detections_class_score_xyxy.json
```

结果为合法 JSON；当前样例下 `class_score_xyxy` 解析得到 0 个 objects。

已验证限制可视化杂乱度：

```bash
python3 infer_image.py \
  --model models/yolo26n_fp32.rknn \
  --image samples/test.jpg \
  --labels models/labels.txt \
  --conf 0.25 \
  --format detection_status \
  --output-layout auto \
  --max-det 20 \
  --draw-output outputs/test_detections_max20.jpg \
  > outputs/detection_status.json
```

结果为合法 JSON，画框图保存为 `outputs/test_detections_max20.jpg`，objects 被限制为 20。
