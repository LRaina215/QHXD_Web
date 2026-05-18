# RKNN YOLO Experiment

本目录是 Phase 4A 的独立 YOLO / RKNN / NPU 推理原型，不接入主后端启动流程。它只负责验证 `.rknn` 模型加载、单张图片推理和 `detection_status` 输出格式。

## 目录

- `models/`：放置外部训练并转换好的 `.rknn` 模型，不提交模型文件。
- `samples/`：放置本地测试图片，不提交大样本数据。
- `outputs/`：放置临时推理输出。
- `infer_image.py`：单张图片推理入口。
- `detection_status_builder.py`：将检测结果封装为 Phase 4A `detection_status`。

## 运行示例

```bash
cd experiments/rknn_yolo
python3 infer_image.py \
  --model models/custom_delivery_yolo_rk3588.rknn \
  --image samples/test.jpg \
  --labels labels.txt \
  --conf 0.25
```

输出 `detection_status`：

```bash
python3 infer_image.py \
  --model models/custom_delivery_yolo_rk3588.rknn \
  --image samples/test.jpg \
  --labels labels.txt \
  --conf 0.25 \
  --format detection_status
```

缺少模型、图片或 RKNN Runtime 时，脚本会直接给出可读错误并退出，不影响 RK3588 主中台。
