# 云拓 RK3588 任务层（yuntuo-fpga 分支）

云拓-多模态复杂地形轮腿机器人：导航（雷达定位、规划、SAFE 限幅）与运动控制（RL 轮腿策略）都在 FPGA 上，
RK3588 只做任务层——视觉、语音、任务编排与 Web 中台。本分支在 QHXD_Web 基础上把 Nav2 / C 板链路换成 FPGA 链路。

```
 网页 / 语音 ──► 后端 FastAPI :8000 ──► fpga_bridge :9101 ──NV 报文──► FPGA 导航 ──► FPGA 运动控制（RL）
 (云端网关转发)    任务预检 / 状态 / WS     任务状态机            GOAL/WAYPOINTS/MODE   SAFE 限幅后的速度
                        ▲                    ▲   │ TARGET                │ STATUS 5 Hz        │ V2 遥测（只读）
 Astra Pro Plus ─► 感知节点 ─ detection ─────┘   └────────────────────────┴────────────────────┘
                  RKNN YOLO + 深度 + 颜色 + 跟踪（UDP JSON :9102）
```

硬约束：RK3588 不向底盘发速度。自主模式下的速度只能来自 FPGA 导航（控制仓库 README 里 RK3588 经 P11-39/40 发
`A5 5A 10` 速度帧的用法只作调试，本分支不实现）。

## 1. 相对 master 的变化

| 部分 | 处理 |
|---|---|
| `scripts/nav2_mission_executor.py`（Nav2 Action） | 由 `yuntuo/fpga_bridge` 替代，同一 :9101 契约，后端 `nav2_mission_adapter` 不用改 |
| Nav2 / C 板 / ROS 2 包、IMU 桥、Point-LIO / Livox / 海康启停脚本、`qhxd-nav-mission.service`、阶段过程文档 | 已从本分支删除（master 与 git 历史里仍可查）；开机脚本只做音频初始化与切实车模式 |
| 旧 YOLO 相机服务（`camera_detect_service.py`） | 由 `yuntuo/perception` 替代，代码留在 `experiments/rknn_yolo/` 供参考与 H.264 推流复用 |
| 后端状态 / WS / SQLite / 预检 / 语音确认 / LLM 安全校验 | 复用，新增目标任务、平台状态、急停与初始位姿接口 |
| RKNN YOLO 推理与后处理 | 复用（`experiments/rknn_yolo/infer_image.py`），外面套 RGB-D 感知节点 |
| 云端网关 `cloud_gateway.py` | 复用，白名单加了 `/api/platform/*`、`/api/perception/events` 等 |
| 前端 | 重写为云拓控制台（地图 / 任务 / 视觉 / 语音 / FPGA 平台 / 事件 / 分层架构），复用视频播放组件 |
| `frontend/node_modules` | 取消跟踪（`.gitignore` 早已忽略），部署时 `npm ci` |

## 2. 目录

```
yuntuo/
  fpga_link/   nv_proto.py（NV 报文）· links.py（板载串口邮箱注入 / UDP）· telemetry.py（控制 V1/V2 遥测）· nvmp.py（先验地图包）
  bridge/      config · core（链路与上送）· tasks（任务状态机）· targets（目标筛选）· inputs（感知 / 遥测输入）· server（HTTP）
  perception/  sources（Astra / 回放）· detectors（RKNN / 颜色块）· geometry（深度 -> 机身系）· color · tracker · pipeline · node
  mock_fpga.py  按固件语义模拟 FPGA 导航 + 虚拟相机 + 控制遥测；mock_camera.py 合成画面
  tests/       协议、链路、遥测、感知、bridge + 模拟器闭环（仿真时钟，确定性）
backend/app/config/yuntuo/   场地点位与巡检路线（起点 + A 台阶 / B 斜坡 / C 碎石，坐标待实测场地后修改）
scripts/  run_fpga_bridge.sh · run_yuntuo_perception.sh · install_yuntuo_services.sh · start_yuntuo_sim.sh · udev/99-yuntuo.rules
systemd/  yuntuo-fpga-bridge.service · yuntuo-perception.service
```

## 3. 任务如何落到 FPGA

| 网页 / 语音任务 | fpga_bridge 下发 | 完成判据 |
|---|---|---|
| 定点 `go_to_waypoint`、返航 `return_home` | GOAL（地图系 mm，朝向发"不关心"，`YUNTUO_SEND_GOAL_YAW=true` 才发） | STATUS 的 goal 与下发一致且 state=到达、mode=空闲；1.2 s 未确认重发，3 次失败 |
| 巡检 `start_patrol` | 逐点 GOAL，点间按路线 `stop_seconds` 停留 | 每点一个 arrived 事件，最后 completed |
| 寻找目标 `search_target` | MODE 探索 + 持续 TARGET（只转发匹配类别 / 颜色的目标，≤12 Hz，时延 > 400 ms 的帧丢弃） | FPGA 转跟踪，站位点 0.25 m 内、目标距离 ≤ 1.05 m、速度≈0 持续 1 s；完成后 MODE 空闲 |
| 跟随 `follow_target` | 同上，类别 person | 不自动完成，取消或超时（缺省 300 s）结束 |
| 暂停 / 取消 | MODE 空闲（上下文保留在 bridge） | 恢复时重发当前 GOAL 或 MODE 探索 |
| 急停 | MODE 急停（优先发送）；解除 = MODE 空闲 | 控制侧锁存的急停需在控制板上复位 |

FPGA 自己负责：目标 1.5 s 未更新回到探索、站位 0.7 m、受阻重规划。bridge 只在受阻持续 `YUNTUO_BLOCKED_FAIL_SECONDS`（25 s）
或链路中断超过 10 s 时判失败。后端预检（Real 模式）：急停、离线、平台状态超过 3 s 未刷新、FPGA 急停 / 控制急停 / 控制故障都会拒绝运动任务。
寻找 / 跟随不要求先验地图；定点在有图且定位未就绪（对准中 / 丢失）时拒绝。

坐标：无先验图时 FPGA 用里程计系（原点 = 上电位置或 SET_POSE），点位按此解释——比赛时车每次从"起点"同一位置同一朝向出发；
有先验图时先下发 `.nvmp`（`YUNTUO_PRIOR_MAP` 或 `POST /api/internal/fpga/map`），再 `POST /api/platform/set_pose` 给初始位姿对准。

## 4. 接口

后端新增（网页 / 云端网关）：

| 接口 | 说明 |
|---|---|
| `POST /api/mission/search_target` | `{target_class, color?, label?, timeout_s}`，类别用 COCO 名：bottle / cup / person / sports ball / chair / backpack |
| `POST /api/mission/follow_target` | `{target_class: "person", label?, timeout_s}` |
| `POST /api/platform/estop` | `{engage: true|false}`；网关只要求 Token，不受 PUBLIC_CONTROL_ENABLED 限制 |
| `POST /api/platform/set_pose` | `{x, y, yaw, align}`（m / rad） |
| `GET /api/platform/status` | FPGA 导航 + 控制状态（也在 `/ws/state` 的 `platform_status` 字段里） |
| `POST /api/internal/platform/status` | fpga_bridge 上送，仅本机 |

fpga_bridge（仅 127.0.0.1:9101）：`POST /api/internal/mission`（原契约）、`/api/internal/fpga/estop`、`/set_pose`、`/map`，
`GET /health`、`/api/internal/fpga/status`。

感知节点 → fpga_bridge（UDP JSON，127.0.0.1:9102，每帧一条）：

```json
{"type": "detections", "source": "astra", "frame_seq": 12, "stamp_mono": 8123.40, "stamp_wall": 1761100000.1,
 "objects": [{"cls": "bottle", "color": "red", "conf": 0.88, "track_id": 3, "x": 1.52, "y": -0.21, "z": 0.05, "bbox": [400, 180, 440, 300]}]}
```

`x/y/z` 为机身系 m（x 前、y 左、z 上）；`stamp_mono` 是采图时刻的 `time.monotonic()`（同机进程共用 CLOCK_MONOTONIC），
bridge 据此算 TARGET 的 `latency_ms`，FPGA 用"到达时刻 − latency"回查历史位姿。

## 5. 不上车联调（PC 或 RK3588）

```bash
cd backend && python -m uvicorn app.main:app --port 8000           # 后端（需要 websockets，见 requirements.txt）
./scripts/start_yuntuo_sim.sh                                     # mock_fpga + fpga_bridge（停止：stop）
cd frontend && npm ci && npm run build && npx vite preview --port 4173   # 或 npm run dev
```

打开网页，右上角切到"实车"：链路显示"模拟"，地图上能看到车、点位与轨迹，视觉窗口是合成画面（SIMULATION）。
可直接试"寻找红色水瓶""跟随我""前往 B 点""巡检"、急停。虚拟场景：红瓶 (3.6, 1.3)、蓝瓶 (1.6, −1.7)、绕圈走动的人。

测试：`python -m pytest yuntuo/tests`（29 项，含 bridge + 模拟器闭环）；`cd backend && python -m pytest`（42 项）。

## 6. 上 RK3588

1. 代码：`git fetch && git checkout yuntuo-fpga`（目录仍是 `/home/robomaster/QHXD`），`pip install -r backend/requirements.txt pyserial`；
   感知另需 `numpy opencv-python openni`（RKNN Lite 已装）与 Orbbec OpenNI2 SDK（`OPENNI2_REDIST` 指向含 `libOpenNI2.so` 的目录）。
2. `.env`：以新的 `.env.example` 为模板重写（旧 `.env` 里的 Nav2 / C 板 / IMU 桥配置已无用，密钥照搬）；
   点位配置路径指向 `backend/app/config/yuntuo/`。
3. `./scripts/install_yuntuo_services.sh`：udev 规则、停用 RK3588 上已安装的 `qhxd-nav-mission`、启用 `yuntuo-fpga-bridge` 与
   `yuntuo-perception`；再重装 `systemd/qhxd-boot.service`（它不再依赖 Nav2 执行器）。
4. 前端：本机访问用 `scripts/start_frontend.sh`（vite dev，:5173）；公网仍走云端静态站 + 网关，`npm run build` 后把 `frontend/dist` 同步到云服务器
   （上线前确认，见第 8 节）。
5. 现场无网络：RK3588 开热点，手机 / 电脑连上后访问 `http://<RK3588 热点 IP>:5173`；ASR（FunASR SenseVoice）本来就是离线的，
   LLM / TTS 按下一节切到本地。

## 7. 离线大模型与 TTS（RK3588 本机）

宣讲要求优先离线，联网可能扣分。后端已支持：

- **LLM**：`LLM_BACKEND=local`、`LLM_ENABLE=true`，后端请求 `LLM_LOCAL_BASE_URL` 的 OpenAI 兼容 `/v1/chat/completions`，不需要 Key。
  RK3588 上可用 Rockchip RKLLM（NPU）跑 Qwen2.5-1.5B/3B-Instruct w8a8，外面套一个 OpenAI 兼容服务；或 llama.cpp server（CPU，GGUF Q4）。
  模型只做意图解析，输出照旧经过本地白名单 + 置信度 + 运动类必须确认三道校验；本地服务不支持 `response_format` 时设 `LLM_LOCAL_JSON_MODE=false`。
  规则解析器本身已覆盖"找红色水瓶""跟着我""去 A 点"等常用说法，LLM 只处理复杂说法；模型挂了也不影响基本任务。
- **TTS**：`TTS_BACKEND=local` + `TTS_LOCAL_CMD` 命令模板（不经 shell，`{text}`、`{out}` 替换），推荐 sherpa-onnx 的中文 VITS / MeloTTS 模型，
  或 Piper 中文模型；生成 wav 后沿用原来的本机播放（`TTS_AUTO_PLAY_LOCAL=true`、`TTS_PLAYER_CMD`）。
- 资源：导航已不在 RK3588 上跑，NPU 留给 YOLO（单核即可）+ RKLLM，CPU 留给 FunASR / TTS；上机后实测内存与延迟再定模型大小。

## 8. 上机后要核对的事项（目前都只在模拟器上验证过）

| 项 | 怎么核对 |
|---|---|
| FPGA 串口设备 | `lsusb` 看 CH9102 VID:PID 是否 1a86:55d4；`ls -l /dev/yuntuo-fpga`；`curl 127.0.0.1:9101/health` 的 `status_age_s` < 0.5 |
| 板载串口链路 | bridge 读 `SYS_ID` 校验 0x4E415630；STATUS 应约 5 Hz（网页 FPGA 平台卡右上角） |
| 控制遥测串口 | 若和 FPGA 串口同为 CH34x / CH910x，按序列号或口路径改 udev；`YUNTUO_CONTROL_TELEMETRY=serial:/dev/yuntuo-ctl@230400` |
| Astra Pro Plus | `pip install openni` 后能 `openni2.initialize()`；深度 640×480；彩色设备号；D2C 配准是否生效（不生效时按视角映射，见 `pipeline.color_bbox_to_depth`） |
| 相机内参与安装 | 用标定或 camera_info 替换 `ASTRA_COLOR_640 / ASTRA_DEPTH_640` 占位值；量 `YUNTUO_CAMERA_MOUNT`（x,y,z,pitch,yaw,roll） |
| 目标三维精度 | 红瓶放在 1.0 / 2.0 / 3.0 m，看网页距离与实测差；颜色判定在场地灯光下复查 |
| 场地点位 | 实测场地后改 `backend/app/config/yuntuo/waypoints.json`（m，起点为里程计原点） |
| 云端上线 | 同步前端与网关属于生产变更：先备份，确认后再做；不要把 Token / .env 提交进仓库 |
