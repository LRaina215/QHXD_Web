# Hik Camera Source Status

## 目标

在保留原 USB / UVC 摄像头入口的前提下，为 RKNN YOLO26 连续检测服务预留并接入 Hikrobot/MVS SDK 采集入口。

## 已完成的软件改动

- `experiments/rknn_yolo/hik_camera_source.py`：新增 Hikrobot MVS SDK 相机源，负责枚举 Hik USB/GigE 设备、打开设备、StartGrabbing、按帧转换为 RGB numpy array。
- `experiments/rknn_yolo/camera_detect_service.py`：新增 `--camera-backend auto|usb|hik`、`--hik-index`、`--hik-serial`、`--hik-timeout-ms`，并在采集层支持 USB 与 Hik 切换。
- `experiments/rknn_yolo/camera_config.json`：默认仍为 `camera_backend=usb`，保留旧 USB 摄像头入口。
- `experiments/rknn_yolo/camera_config_hik.example.json`：新增 Hik 示例配置，默认 serial 为 `DA8290708`。
- `README.md`、`experiments/rknn_yolo/README.md`：补充 USB/Hik 切换方式、启动命令和当前硬件状态。

## 当前硬件测试结果

- MVS SDK 已安装在 `/opt/MVS`。
- Hik 设备曾被 USB 层识别为 `2bdf:0001 Hikrobot MV-CS060-10UC-PRO`，序列号 `DA8290708`。
- 首次 MVS SDK 探测结果：可枚举 1 台设备、可 create handle、可 open、可 start grabbing，但 `GetImageBuffer` 返回 `0x80000007`，未成功保存图像。
- 执行 MVS USB 权限和 usbfs 内存设置后，当前内核日志持续出现 `usb 6-1: device descriptor read/8, error -110`，`lsusb -t` 暂时不稳定列出 Hik 相机。
- 当前 `camera_config_hik.example.json` dry-run 能干净输出 `camera_unavailable` JSON，不会崩溃，也不会影响 USB 入口。

## 验证命令

```bash
cd /home/robomaster/QHXD
python3 -m py_compile experiments/rknn_yolo/hik_camera_source.py experiments/rknn_yolo/camera_detect_service.py
```

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py --config camera_config_hik.example.json --dry-run --max-frames 1 --read-fail-limit 1
```

当前 dry-run 输出包含：

```text
Hik camera could not open: Hik camera enum found no device
{"detection_status": {"enabled": false, ... "event_type": "camera_unavailable"}}
```

## 后续人工验收

- [ ] 物理重插 Hik 相机，确认 `lsusb -t` 稳定出现 USB3 Vision 设备。
- [ ] 确认 `dmesg` 不再持续出现 `usb 6-1: device descriptor read/8, error -110`。
- [ ] 运行 Hik dry-run 能打开 MVS SDK 相机并获取至少 1 帧。
- [ ] 使用 `camera_config_hik.example.json` 生成 `outputs/latest_hik_detection.jpg`。
- [ ] 切回 `camera_config.json` 后 USB 摄像头入口仍可运行。
