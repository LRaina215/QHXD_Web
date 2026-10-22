# RKNN Models

将外部训练并转换好的 `.rknn` 模型放在本目录。不要提交 `.pt`、`.onnx`、`.rknn` 等大模型文件。

建议命名：

- `yolov8n_rk3588_int8.rknn`
- `yolo11n_rk3588_int8.rknn`
- `custom_delivery_yolo_rk3588.rknn`

推荐流程：`best.pt -> best.onnx -> best.rknn -> experiments/rknn_yolo/models/custom_delivery_yolo_rk3588.rknn`。

## YOLO26n INT8（云拓感知节点在用）

- 生成：`tools/convert_yolo26_int8.py`（在 RK3588 上，用独立 venv；官方 `yolo26n.pt` + Astra 实拍 60 张 + coco128 前 64 张校准）。
- 位置：RK3588 的 `~/models/yolo/yolo26n_int8.rknn` + 同名 `.json`（不进仓库）；`.env` 里
  `YUNTUO_RKNN_MODEL=/home/robomaster/models/yolo/yolo26n_int8.rknn`、`YUNTUO_DETECT_CONF=0.40`。
  去掉这两行就回到本目录的 `yolo26n_fp32.rknn`。
- 输入：`.json` 里 `input=uint8_rgb` 时 `infer_image.py` 直接喂 uint8（/255 已在模型里）；没有 `.json` 时按 fp32 模型喂 float。
- 输出：两路 boxes `[1,4,8400]`（cx,cy,w,h）+ scores `[1,80,8400]`，`infer_image.py` 按形状自动识别，取最大类后做 NMS。

2026-10-23 板上实测（coco128 128 张；"6 类"指 person / bottle / cup / sports ball / chair / backpack）：

| 模型 | mAP@0.5 | 6 类召回 / 精度 | 单帧（预处理 + 推理 + 后处理） |
|---|---|---|---|
| yolo26n_fp32.rknn，阈值 0.35 | 0.508 | 0.414 / 0.902 | 约 88–104 ms |
| yolo26n_int8.rknn，阈值 0.35 | 0.451 | 0.423 / 0.802 | 约 35–55 ms |
| yolo26n_int8.rknn，阈值 0.40 | — | 0.389 / 0.836 | 同上 |
| yolo26n_int8.rknn，阈值 0.45 | — | 0.361 / 0.883 | 同上 |

同样解码下 fp32 ONNX（CPU）mAP 0.519、6 类 0.423 / 0.893，所以精度下降来自量化，不是检测头差异。
试过 kl_divergence（0.450）、检测头留 fp16（0.443）、注意力层留 fp16（0.184，混合精度出错），都不比 normal 好。
评测：`python3 tools/eval_coco128.py <模型...> --conf 0.40`（先停 yuntuo-perception）。
