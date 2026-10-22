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

测试：`python -m pytest yuntuo/tests`（38 项，含 bridge + 模拟器闭环、大模型 / 语音合成服务）；`cd backend && python -m pytest`（48 项）。

## 6. 上 RK3588（2026-10-23 已切换完成）

板上 `/home/robomaster/QHXD` 已切到 `yuntuo-fpga`，旧 Nav2 / C 板 / Point-LIO 栈已停用，开机自启的服务：

| 服务 | 作用 | 端口 |
|---|---|---|
| `qhxd-backend` | 后端 + 网页静态文件 | 0.0.0.0:8000 |
| `qhxd-boot` | 开机初始化音频、切实车模式 | — |
| `yuntuo-fpga-bridge` | 任务层 ↔ FPGA（`.env` 的 `YUNTUO_FPGA_LINK`） | 127.0.0.1:9101 |
| `yuntuo-mock-fpga` | FPGA 未烧录期间扮演 FPGA 导航 + 控制遥测 | UDP 127.0.0.1:9000 → :9104 |
| `yuntuo-perception` | Astra Pro Plus + RKNN YOLO + 三维 / 颜色 / 跟踪 | UDP → :9102 |
| `yuntuo-llm` | 离线大模型（rknn-llm，NPU） | 127.0.0.1:8080 |
| `yuntuo-tts` | 离线语音合成（sherpa-onnx，CPU） | 127.0.0.1:8081 |

重装或换机的步骤：

1. 代码：`git fetch && git checkout yuntuo-fpga`，`pip install --user -r backend/requirements.txt sherpa-onnx==1.13.8`；
   相机：`./scripts/install_orbbec_openni2.sh`（Ubuntu 自带的 `libopenni2` 不认 Orbbec 设备 VID 2bc5，不要用它）；
   大模型运行库：`./scripts/install_rkllm_runtime.sh [librkllmrt.so]`（装到 `/opt/rkllm/1.3.1/`，不动 `/usr/lib` 里已有的旧版）。
2. 模型（都不进仓库，放 `~/models`）：见第 7 节表格。
3. `.env`：以 `.env.example` 为模板重写，密钥 / 音频设备 / 天气照搬旧 `.env`；点位指向 `backend/app/config/yuntuo/`。
   FPGA 未烧录时 `YUNTUO_FPGA_LINK=udp:127.0.0.1:9000`、`YUNTUO_FPGA_IS_MOCK=true`、`YUNTUO_CONTROL_TELEMETRY=udp:127.0.0.1:9104`。
4. `./scripts/install_yuntuo_services.sh --mock-fpga --with-llm --with-tts`（无终端时 `SUDO="sudo -A"` + `SUDO_ASKPASS`）。
   接真 FPGA 后改 `.env` 的链路，再不带 `--mock-fpga` 跑一遍，脚本会停掉模拟器。
5. 回滚到旧栈：`git checkout master`，恢复 `~/backups/qhxd_pre_yuntuo_*/env.master` 为 `.env`、恢复其中的 `qhxd-*.service`，
   `systemctl disable --now yuntuo-*`、`systemctl enable --now qhxd-nav-mission`，重启。
6. 现场无网络：RK3588 开热点，手机 / 电脑访问 `http://<RK3588 热点 IP>:8000`；语音识别、大模型、语音合成全部在板上。

## 7. 离线语音（RK3588 本机，已部署）

一句话的流程：麦克风 / 网页 / 小程序录音 → SenseVoice 识别 → 规则解析（常用说法直接命中）→ 复杂说法交给板载 Qwen2.5-1.5B →
白名单 + 置信度 + 运动类必须确认 → 回复文字 → 板载语音合成 → 喇叭播放。全程不联网。

| 环节 | 实现 | 模型（`~/models`） | 板上实测 |
|---|---|---|---|
| 识别 | `ASR_BACKEND=sherpa`，sherpa-onnx 版 SenseVoice int8 | `asr/sherpa-onnx-sense-voice-zh-2024-07-17`（hf-mirror csukuangfj/…） | 加载 3 s，一句 0.15–0.2 s |
| 大模型 | `yuntuo-llm`：自写 ctypes 绑定 `librkllmrt.so` 1.3.1 + OpenAI 兼容子集；`LLM_BACKEND=local` | `llm/qwen2.5-1.5b-instruct-w8a8/Qwen2.5-1.5B-Instruct.rkllm`（ModelScope RKNNAI，toolkit 1.2.4，上下文 1024） | 加载 6 s，内存 1.7 GB；意图 JSON 约 2–4 s |
| 合成 | `yuntuo-tts`：sherpa-onnx 常驻服务；`TTS_BACKEND=local` + `TTS_LOCAL_URL` | `tts/matcha-icefall-zh-en` + `tts/vocoders/vocos-16khz-univ.onnx` | 加载 3.4 s，一句 0.5–0.7 s（RTF≈0.16），中英混读 |

要点：

- 板载模型上下文只有 1K，`LLM_BACKEND=local` 时自动用精简提示（约 540 token，`LLM_PROMPT_STYLE` 可强制 full / compact）；
  系统提示由 rknn-llm 缓存，之后每句只需预填十几个 token。
- 任务类命令（去点位、找物、跟随、巡检、返航、暂停 / 继续）的回复按校验后的任务生成，不用模型自己写的话；只有闲聊用模型回复。
- 智能语音接口只解析一次（以前同一句话会调两次大模型），语音 / 大模型 / 合成都在线程池里跑，推理期间急停等接口照常响应（实测最大 41 ms）。
- NPU 由感知和大模型共用：没有找物 / 跟随任务时感知降到 5 fps（`YUNTUO_PERCEPTION_IDLE_FPS`）；librknnrt 会把感知线程调到 nice −19，
  感知节点启动后调回 0（`YUNTUO_PERCEPTION_NICE`）。感知全速时大模型约慢 50%，换 int8 量化的 YOLO 可进一步缓解。
- 端到端（文字进、语音出，含合成）：去点位 3.6 s、闲聊 4.7 s、拒绝危险指令 2.0 s、规则命中的查询 < 0.5 s。
- 试过但没用：vits-melo-tts-zh_en int8（RTF≈3.3，太慢）；matcha-icefall-zh-baker（只认中文，"B 点"会吞掉字母）。
- NPU 驱动是 0.9.6，rknn-llm 1.3.1 提示建议 0.9.7，实测可用。

## 8. 上机核对

2026-10-22 实机结果（RK3588 `hky`，Astra Pro Plus：彩色 UVC `2bc5:050f`、深度 `2bc5:060f`）：

| 项 | 结果 |
|---|---|
| 深度流 | Orbbec OpenNI2 驱动下 640×480@30（另有 160×120、320×240、1280×1024@7），室内有效像素约 65–70% |
| 彩色流 | `/dev/yuntuo-astra-color` → video0；MJPG 640×480 约 20 fps（YUYV 只有约 12 fps） |
| 出厂标定 | 设备属性 14 可读：彩色 fx = fy = 543.47、cx 316.36、cy 242.65；深度 fx 575.90；基线约 25 mm。感知节点自动读取 |
| 深度配准到彩色 | `IMAGE_REGISTRATION_DEPTH_TO_COLOR` 生效，深度边缘与彩色轮廓对齐良好 |
| 感知链路 | RKNN YOLO（fp32 模型）+ 颜色 + 三维 + 跟踪约 8 fps，采图到结果 p50 约 134 ms（< 400 ms 门限） |
| 端到端（模拟 FPGA） | 真相机看到人 → 跟随任务 → fpga_bridge 发 TARGET → 模拟 FPGA 进入跟踪、目标落在地图上 |
| 云端（2026-10-23） | 公网 lingxunrobot.cn 已换云拓前端，备案号与公安备案图标照常由 nginx 注入；网关加了 `/api/platform/*` 与 `/api/gateway/health`；小程序只读冒烟全过 |

仍待核对：

| 项 | 怎么核对 |
|---|---|
| FPGA 串口设备 | `lsusb` 看 CH9102 VID:PID 是否 1a86:55d4；`ls -l /dev/yuntuo-fpga`；`curl 127.0.0.1:9101/health` 的 `status_age_s` < 0.5 |
| 板载串口链路 | bridge 读 `SYS_ID` 校验 0x4E415630；STATUS 应约 5 Hz（网页 FPGA 平台卡右上角） |
| 控制遥测串口 | 若和 FPGA 串口同为 CH34x / CH910x，按序列号或口路径改 udev；`YUNTUO_CONTROL_TELEMETRY=serial:/dev/yuntuo-ctl@230400` |
| 相机安装 | 装车后量 `YUNTUO_CAMERA_MOUNT`（x,y,z,pitch,yaw,roll，机身系） |
| 目标三维精度 | 红瓶放在 1.0 / 2.0 / 3.0 m，看网页距离与实测差；颜色判定在场地灯光下复查 |
| 检测帧率 | fp32 模型约 8 fps；换 int8 量化模型可提速并给大模型让出 NPU（TARGET 链路已满足时延要求，非必须） |
| 场地点位 | 实测场地后改 `backend/app/config/yuntuo/waypoints.json`（m，起点为里程计原点） |
| 车载麦克风 | 现场对着麦克风说一句，看识别结果；音量在 `.env` 的 `AUDIO_CAPTURE_VOLUME` |
| 云端低延迟视频 | 旧栈的 RTMP 推流来自旧相机服务，云拓感知节点不推流；网页相机窗口走 latest_frame / MJPEG 正常。需要 HLS 时再给感知节点加推流 |
