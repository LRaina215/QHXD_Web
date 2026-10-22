"""把官方 yolo26n.pt 转成 RK3588 INT8 RKNN（models/yolo26n_int8.rknn 就是这样生成的，可直接在 RK3588 上跑）。

准备（RK3588 上，独立 venv，不影响系统 python3）：
  python3 -m venv ~/venvs/rknn-convert
  ~/venvs/rknn-convert/bin/pip install torch==2.2.0 torchvision rknn-toolkit2==2.3.2 ultralytics "numpy<=1.26.4"
  工作目录放：yolo26n.pt（hf-mirror Ultralytics/YOLO26）、calib_astra/*.jpg（Astra 实拍）、coco128/（hf-mirror LibreYOLO/coco128）

  ~/venvs/rknn-convert/bin/python convert_yolo26_int8.py --workdir ~/models/yolo [--algorithm normal]

要点：
- 输入 RGB uint8，拉伸到 640x640（与 infer_image.py 相同，不做 letterbox）；/255 放进模型（mean 0、std 255），
  运行时直接喂 uint8。模型旁写 .json（input=uint8_rgb），infer_image.py 据此选择输入类型。
- 输出切在检测头拼接之前：boxes [1,4,8400]（输入图像素 cx,cy,w,h）与 scores [1,80,8400]（sigmoid 后），
  避免像素坐标和 0~1 置信度共用一个 int8 量化尺度；取最大类与 NMS 在 CPU 上做。
- 2026-10-23 试过 kl_divergence、自动 / 手动混合量化（检测头或注意力层留 fp16）都没有比 normal 更好。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

import cv2
import numpy as np
import onnx

SIZE = 640


def export_onnx(workdir: Path) -> Path:
    onnx_path = workdir / "yolo26n.onnx"
    if not onnx_path.exists():
        from ultralytics import YOLO

        exported = YOLO(str(workdir / "yolo26n.pt")).export(format="onnx", imgsz=SIZE, opset=19, simplify=True)
        Path(exported).replace(onnx_path)
    return onnx_path


def find_head_concat(model_path: Path) -> tuple[str, str]:
    """检测头的 Concat：输出 [1, 4+nc, 8400]，两个输入分别是框与分数。"""
    m = onnx.shape_inference.infer_shapes(onnx.load(str(model_path)))
    shapes = {vi.name: [d.dim_value for d in vi.type.tensor_type.shape.dim]
              for vi in list(m.graph.value_info) + list(m.graph.output)}
    for node in m.graph.node:
        if node.op_type != "Concat" or len(node.input) != 2:
            continue
        out, a, b = shapes.get(node.output[0]), shapes.get(node.input[0]), shapes.get(node.input[1])
        if out and a and b and len(out) == 3 and out[2] == 8400 and a[1] == 4 and b[1] == out[1] - 4:
            return node.input[0], node.input[1]
    raise SystemExit("找不到检测头 Concat，导出的网络结构变了")


def build_calibration(workdir: Path, coco_count: int) -> Path:
    calib = workdir / "calib_u8"
    calib.mkdir(exist_ok=True)
    images = sorted(glob.glob(str(workdir / "calib_astra" / "*.jpg")))
    images += sorted(glob.glob(str(workdir / "coco128" / "images" / "train2017" / "*.jpg")))[:coco_count]
    if not images:
        raise SystemExit("没有校准图：calib_astra/*.jpg 或 coco128/")
    lines = []
    for i, path in enumerate(images):
        rgb = cv2.cvtColor(cv2.resize(cv2.imread(path), (SIZE, SIZE), interpolation=cv2.INTER_LINEAR), cv2.COLOR_BGR2RGB)
        npy = calib / f"c{i:03d}.npy"
        np.save(npy, rgb.astype(np.float32).transpose(2, 0, 1)[None])   # 校准数据要 NCHW、0~255；运行时按 NHWC 喂
        lines.append(str(npy))
    dataset = workdir / "dataset_u8.txt"
    dataset.write_text("\n".join(lines) + "\n")
    return dataset


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", type=Path, default=Path.home() / "models" / "yolo")
    ap.add_argument("--algorithm", default="normal", choices=["normal", "kl_divergence", "mmse"])
    ap.add_argument("--coco-count", type=int, default=64)
    ap.add_argument("--out", type=Path, default=None, help="缺省 <workdir>/yolo26n_int8.rknn")
    args = ap.parse_args()
    from rknn.api import RKNN

    workdir = args.workdir.expanduser()
    onnx_path = export_onnx(workdir)
    box_out, score_out = find_head_concat(onnx_path)
    dataset = build_calibration(workdir, args.coco_count)
    out = args.out or workdir / "yolo26n_int8.rknn"
    rknn = RKNN(verbose=False)
    rknn.config(mean_values=[[0, 0, 0]], std_values=[[255, 255, 255]], target_platform="rk3588",
                quantized_algorithm=args.algorithm, quantized_method="channel", optimization_level=3)
    if rknn.load_onnx(model=str(onnx_path), outputs=[box_out, score_out]) != 0:
        raise SystemExit("load_onnx 失败")
    if rknn.build(do_quantization=True, dataset=str(dataset)) != 0:
        raise SystemExit("build 失败")
    if rknn.export_rknn(str(out)) != 0:
        raise SystemExit("export_rknn 失败")
    rknn.release()
    meta = {"input": "uint8_rgb", "size": SIZE, "resize": "stretch", "outputs": "boxes_cxcywh+scores",
            "source": "Ultralytics/YOLO26 yolo26n.pt", "quantized_algorithm": args.algorithm,
            "calibration": f"calib_astra + coco128 前 {args.coco_count} 张", "toolkit": "rknn-toolkit2 2.3.2"}
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已导出 {out}（{os.path.getsize(out)} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
