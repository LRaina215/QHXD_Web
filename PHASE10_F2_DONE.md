# Phase 10 F2 完成记录：语音、视觉、视频与智能交互完善

更新时间：2026-07-08

## 本轮目标

在不重写 FunASR、DeepSeek、TTS、YOLO、Hik 相机、WebRTC 和导航本体的前提下，补齐 Phase 10 F2 的统一查询回答、视觉事件持久化、TTS 播报策略和视频健康可观测性。

## 已完成内容

### 1. 统一智能助手查询编排

- `backend/app/schemas.py:33`：新增 `query_navigation_status`、`query_front_status`、`query_obstacle_status`、`query_navigation_safety` 等查询意图。
- `backend/app/services/intent_parser.py:78`：本地规则解析新增“当前导航怎么样”“前方安全吗”“前面有什么”“障碍物”等语义。
- `backend/app/services/voice/llm_schema.py:21`：LLM schema 白名单加入新的查询意图。
- `backend/app/services/voice/llm_prompt.py:20`：LLM prompt 明确前方/安全/障碍物问题应走查询意图，不生成导航任务。
- `backend/app/services/voice_entry.py:37`：查询类意图进入统一 smart assistant 查询路径。
- `backend/app/services/data_service.py:47`：统一分发导航、视觉、前方安全、天气等查询数据源。
- `backend/app/services/robot_status_provider.py:47`：新增导航状态回答。
- `backend/app/services/robot_status_provider.py:90`：新增前方状态回答，组合当前检测、最近视觉事件和导航状态。

### 2. 视觉事件业务化与持久化

- `backend/app/schemas.py:224`：新增 `VisualEventRecord`、`VisualEventsResponse`。
- `backend/app/services/persistence.py:81`：新增 `visual_events` SQLite 表和索引。
- `backend/app/services/persistence.py:107`：新增 `upsert_visual_event`，按时间窗口去重并更新持续时间、最高置信度和计数。
- `backend/app/services/persistence.py:208`：新增视觉事件列表查询，默认保留最近 500 条。
- `backend/app/services/visual_event_service.py:14`：新增视觉事件服务，从 `DetectionStatus` 生成 `person_detected`、`obstacle_detected`、`camera_offline`、`camera_recovered`。
- `backend/app/main.py:1053`：`/api/internal/perception/detection_status` 入库时同步生成视觉事件。
- `backend/app/main.py:670`：新增 `GET /api/perception/events`。

### 3. TTS 播报策略与去重

- `backend/app/services/tts_service.py:71`：新增 `speak_with_policy`，支持事件去重、普通播报冷却和 critical 优先级。
- `backend/app/services/smart_voice_service.py:121`：智能助手 TTS 改用策略化播报。
- `backend/app/main.py:105`：任务事件播报改为带 `event_key` 的去重策略。
- `backend/app/main.py:1029`：任务事件 `event_key` 使用 `task_id:event_type:waypoint_id`，避免同一到达/完成事件重复播报。

### 4. 视频健康可观测性

- `backend/app/schemas.py:247`：新增 `VideoHealthStatus`、`VideoHealthResponse`。
- `backend/app/main.py:351`：新增视频健康状态汇总，包含最后帧年龄、检测状态、YOLO 相机进程、最近视觉事件等。
- `backend/app/main.py:330`：推流 URL 对 `pass`、`token`、`secret` 等参数脱敏，避免公网接口泄漏密钥。
- `backend/app/main.py:679`：新增 `GET /api/perception/video_health`。
- 云服务器 `/opt/lingxun-cloud-gateway/cloud_gateway.py`：公网代理白名单从单独图片接口扩展到 `/api/perception/`，使 `/api/perception/events` 和 `/api/perception/video_health` 可公网访问。

### 5. README 更新

- `README.md:281`：新增查询类语义示例。
- `README.md:390`：新增 TTS 去重和冷却配置。
- `README.md:448`：新增视觉事件和视频健康接口说明。
- `README.md:634`：后端 API 列表加入 `/api/perception/events` 和 `/api/perception/video_health`。
- `README.md:757`：新增 Phase 10 F2 手动验收命令。

## 已验证

### RK3588 本地验证

```bash
cd /home/robomaster/QHXD/backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests/test_phase10_f2.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

结果：

```text
3 passed
35 passed
```

### 接口验收

- `GET /api/perception/events?limit=3`：返回最近视觉事件。
- `GET /api/perception/video_health`：返回 `status=ok`，最后帧新鲜，YOLO 相机服务运行中，推流 URL 未暴露 `pass`。
- `POST /api/voice/smart_command`，文本“前方安全吗”：返回 `intent=query_navigation_safety`，`mission_candidate=null`，回答引用当前视觉目标和最近视觉事件。
- `POST /api/voice/smart_command`，文本“当前导航怎么样”：返回 `intent=query_navigation_status`，`mission_candidate=null`。
- `POST /api/voice/smart_command`，文本“天气怎么样，适合出门吗”：返回实时 Open-Meteo 天气、温湿度、降雨概率、紫外线和出行建议，不出现“不是传感器读取的数据”。
- `POST /api/voice/smart_command`，文本“你使用的模型是什么”：返回 DeepSeek V4 Flash 信息，`mission_candidate=null`。

### 公网验证

- `https://lingxunrobot.cn/api/perception/events?limit=2`：可访问。
- `https://lingxunrobot.cn/api/perception/video_health`：可访问，推流 URL 已脱敏。
- 带 `PUBLIC_API_TOKEN` 调用 `https://lingxunrobot.cn/api/voice/smart_command`，文本“前方安全吗”：返回 `query_navigation_safety`，不生成 mission。

## 仍需人工实机验收

- 文本、浏览器麦克风、车载麦克风三种入口的现场 TTS 行为是否完全一致。
- 实际巡检到达点后的视觉摘要播报是否符合演示节奏。
- Hik 相机真实短断开/恢复后，Web 播放器是否无需刷新即可恢复。
- 小程序端暂按计划后置，本轮未改小程序。

## 安全边界

- 未修改导航本体、Nav2、Point-LIO、C 板通信协议或 odom 积分逻辑。
- 未提高 YOLO 推理频率，视觉事件不逐帧入库。
- 查询类语义只返回文本/事件，不直接控制底盘。
- 天气数据来自 Open-Meteo 结构化结果和缓存，不让 LLM 编造天气。
