# DONE_PHASE5.md

## 阶段结论

Phase 5 已完成语音与视觉能力的工程收口：统一启动脚本、YOLO 调试帧保存、检测短时保持、视觉事件策略、语音命令安全边界、Dashboard 展示和 README 交接说明均已补齐。

本阶段没有改变 mission、NUC bridge、RT-Thread 控制链路，也没有让 YOLO 结果直接控制底盘。

## Task 5.1：启动脚本与运行流程规范化

新增：

- `scripts/common.sh`
- `scripts/start_backend.sh`
- `scripts/start_frontend.sh`
- `scripts/start_yolo_camera.sh`
- `scripts/start_all.sh`
- `scripts/stop_all.sh`
- `scripts/status_all.sh`

脚本使用项目相对路径，统一 pid 目录 `.runtime/` 和日志目录 `logs/`。

验证结果：

- `bash -n scripts/*.sh` 通过；
- `start_backend.sh` 可识别当前后端 `/health` 已可用；
- `start_frontend.sh` 可识别当前前端端口已可用；
- `start_yolo_camera.sh` 可拉起摄像头服务并更新 `outputs/latest_camera_detection.jpg`；
- `stop_all.sh` 可停止脚本启动的 YOLO 服务；
- `status_all.sh` 可显示 backend/frontend/yolo 状态。

## Task 5.2：YOLO 调试帧与检测链路统计

修改：

- `experiments/rknn_yolo/infer_image.py`
- `experiments/rknn_yolo/camera_detect_service.py`

新增能力：

- `--save-debug-frames`
- `--debug-frame-dir`
- `--debug-every-n`
- 每帧 pipeline stats：`raw/conf/nms/final/top`
- debug 输入帧、输出帧、detection JSON 保存

验证命令：

```bash
cd /home/robomaster/QHXD/experiments/rknn_yolo
python3 camera_detect_service.py \
  --config camera_config.json \
  --dry-run \
  --max-frames 2 \
  --save-debug-frames \
  --debug-frame-dir outputs/debug_frames_phase5 \
  --debug-every-n 1 \
  --save-latest outputs/latest_phase5_debug.jpg \
  > outputs/phase5_debug_dry_run.jsonl
```

验证结果：

- 退出码 0；
- JSONL 2 行；
- 生成 input/output/detection JSON 各 2 组；
- 日志出现 `backend=OpenCvCameraSource`；
- 日志出现 `frame=1 raw=299 conf=0 nms=0 final=0 top=none` 等统计。

## Task 5.3：检测结果短时保持与 Dashboard 防闪烁

修改：

- `experiments/rknn_yolo/camera_detect_service.py`
- `experiments/rknn_yolo/detection_status_builder.py`
- `backend/app/schemas.py`
- `frontend/src/App.vue`

新增配置：

- `hold_seconds`
- `hold_classes`

`detection_status.objects` 新增可选字段：

- `current_frame`
- `recently_seen`
- `last_seen_at`
- `age_s`

Dashboard 现在分开展示“当前检测”和“最近检测”。短时保持只用于显示和事件稳定，不参与底盘控制。

## Task 5.4：视觉事件策略优化

修改：

- `experiments/rknn_yolo/detection_status_builder.py`
- `experiments/rknn_yolo/camera_detect_service.py`
- `frontend/src/App.vue`

保留事件类型：

- `person_detected`
- `obstacle_detected`
- `possible_blockage`

新增配置：

- `event_min_confidence`
- `event_min_area_ratio`
- `blockage_frames_required`
- `person_event_interval`
- `obstacle_event_interval`
- `blockage_event_interval`

事件现在支持低置信度过滤、小障碍框过滤、连续帧阻塞判断和同类事件节流。Dashboard 展示 event level/type/message。

## Task 5.5：语音命令安全边界与词表收口

新增：

- `backend/app/config/voice_commands.json`
- `scripts/cleanup_voice_records.sh`

修改：

- `backend/app/services/waypoint_resolver.py`
- `backend/app/services/intent_parser.py`
- `frontend/src/App.vue`

完成内容：

- 明确第一版命令词表；
- 未知命令不触发 mission；
- 目标点无法解析不触发 mission；
- 目标点存在歧义不触发 mission；
- Dashboard 显示最近文本/语音识别与执行摘要；
- 增加 `voice_records` dry-run 清理脚本。

验证结果：

```text
去二零一实验室 -> go_to_waypoint / wp_201 / need_confirm=false
去201 -> go_to_waypoint / need_confirm=true / 目标点存在歧义
打开窗户 -> intent=None / need_confirm=true / 未触发任务
暂停任务 -> pause_task / need_confirm=false
当前状态 -> query_status / need_confirm=false
```

## Task 5.6：README 与交接文档

更新：

- `README.md`
- `DONE_PHASE5.md`

README 已补充：

- 统一启动脚本；
- YOLO 调试帧保存；
- 短时保持字段；
- 视觉事件策略配置；
- 语音命令词表与安全边界；
- `voice_records` 清理；
- Phase 5 不包含内容。

## 验证汇总

已执行：

```bash
python3 -m py_compile experiments/rknn_yolo/infer_image.py experiments/rknn_yolo/detection_status_builder.py experiments/rknn_yolo/camera_detect_service.py backend/app/schemas.py backend/app/services/waypoint_resolver.py backend/app/services/intent_parser.py
bash -n scripts/*.sh
npm run build
```

结果：全部通过。

后端启动检查：

```text
Uvicorn running on http://127.0.0.1:8031
Application startup complete
```

前端构建：

```text
vue-tsc --noEmit && vite build
✓ built
```

YOLO debug dry-run：

```text
Camera detection service started: camera=0, backend=OpenCvCameraSource, fps=1.0, submit=False, dry_run=True
frame=1 raw=299 conf=0 nms=0 final=0 top=none
frame=2 raw=297 conf=0 nms=0 final=0 top=none
```

## 已知限制

- 未做长时间稳定性测试；
- 未做 systemd 服务化；
- 未接入 Hik SDK；
- 未接入 OpenClaw / LLM；
- 未做浏览器麦克风录音；
- 未做视频流；
- 未做模型训练、转换或量化；
- YOLO 结果仍只用于显示和事件状态，不控制底盘。
