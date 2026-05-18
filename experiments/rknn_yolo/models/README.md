# RKNN Models

将外部训练并转换好的 `.rknn` 模型放在本目录。不要提交 `.pt`、`.onnx`、`.rknn` 等大模型文件。

建议命名：

- `yolov8n_rk3588_int8.rknn`
- `yolo11n_rk3588_int8.rknn`
- `custom_delivery_yolo_rk3588.rknn`

推荐流程：`best.pt -> best.onnx -> best.rknn -> experiments/rknn_yolo/models/custom_delivery_yolo_rk3588.rknn`。
