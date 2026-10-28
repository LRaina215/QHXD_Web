# 云拓 · RK3588 边缘任务引擎与 Web 控制台

本仓库是云拓轮腿机器人的 RK3588 与 Web 端工程，包含车载视觉、语音识别、语言理解、语音合成、任务编排、网页控制台及云端接入服务。

RK3588 将用户指令与相机观测转换为任务和视觉目标，通过 FPGA 桥接服务下发。FPGA 负责雷达感知、定位、路径规划、避障及轮腿运动控制；执行状态与遥测返回后端，供 Web 和微信小程序共同使用。

[项目总览](https://github.com/LRaina215/Yuntuo/tree/main) · [总体架构](https://github.com/LRaina215/SOC_FPGA_NAV/blob/main/docs/system_architecture.md) · [部署说明](docs/YUNTUO.md)

## 功能

- **边缘视觉**：YOLO26n 在 NPU 上检测目标，结合 Astra RGB-D 深度、颜色筛选与跟踪输出三维目标。
- **本地语音与语言理解**：SenseVoice 识别车载语音，Qwen3-1.7B 在 NPU 上解析意图，Matcha / Vocos 合成回复。
- **任务编排**：管理定点、返航、巡检、找物与跟随，将任务转换为 NV 报文，跟踪目标、停止和完成状态。
- **Web 控制台**：展示地图、机器人位姿、任务、视频、视觉目标、姿态、轮速及事件，提供任务操作与文字 / 语音交互。
- **地图管理**：上传 NVMP 地图、查看独立预览、跟踪 FPGA 接收进度与加载结果。
- **视频与公网访问**：MPP 硬件编码、MediaMTX 视频分发、HTTPS / WebSocket 网关，支持 WebRTC 与小程序 HLS。

## 数据流

```text
Web / 小程序 / 语音 → FastAPI 后端 → fpga_bridge → FPGA 导航 → 轮腿控制
                         ↑              ↑             │           │
Astra RGB-D → YOLO / 颜色 / 深度 / 跟踪 ──┘             │           │
                         └────── 任务状态、位姿与控制遥测 ──────────┘
```

模型服务在 RK3588 本地运行。常用指令由规则处理，复杂表达由语言模型解析；运动类语音意图经参数检查和用户确认后进入任务系统。桥接统一管理 FPGA 链路。

## 目录

| 路径 | 内容 |
|---|---|
| `backend/` | FastAPI、WebSocket、SQLite、任务预检、语音接口与平台状态 |
| `yuntuo/fpga_link/` | NV 协议、串口 / UDP、控制遥测与先验地图包 |
| `yuntuo/bridge/` | 任务状态机、目标筛选、反馈核验和 FPGA 通信 |
| `yuntuo/perception/` | RGB-D 感知与目标跟踪 |
| `yuntuo/llm/` · `yuntuo/tts/` | RKLLM 语言服务与本地语音合成 |
| `frontend/` | Vue 3、TypeScript、Vite 控制台 |
| `cloud_gateway/` · `streaming/` | 公网 API 网关与 MediaMTX 视频服务 |
| `scripts/` · `systemd/` | 启停脚本、服务单元与设备规则 |

## 本地联调

后端、模拟链路与前端分别运行：

```bash
cd backend
pip install -r requirements.txt pyserial
python -m uvicorn app.main:app --port 8000
```

```bash
./scripts/start_yuntuo_sim.sh
```

```bash
cd frontend
npm ci
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`，在模拟链路中操作找物、跟随、定点、巡检和停止功能。模拟环境的启动与收尾见[部署说明](docs/YUNTUO.md)。

## RK3588 部署

根据 `.env.example` 配置串口、相机、航点、模型及音频设备，安装后端和车载服务：

```bash
cp .env.example .env
./scripts/install_backend_service.sh
./scripts/install_rkllm_runtime.sh
./scripts/install_yuntuo_services.sh --mock-fpga --with-llm --with-tts
./scripts/status_public_robot.sh
```

上述命令使用模拟 FPGA 进行初始服务联调。双串口接线、真实链路配置、模型路径及服务管理见 [docs/YUNTUO.md](docs/YUNTUO.md)。公网接入见[网关说明](cloud_gateway/README.md)，视频配置见[视频服务](streaming/README.md)。

## 开发与测试

```bash
python -m pytest yuntuo/tests
cd backend && python -m pytest
cd ../frontend && npm run build
```

协议与任务回归位于 `yuntuo/tests/`，后端测试位于 `backend/`。真实设备测试和部署记录见[系统联调记录](docs/REAL_FPGA_INTEGRATION_20261027.md)；地图功能见[地图上传说明](docs/MAP_UPLOAD_20261027.md)。

项目基于 QHXD 车载中台演进，原 Nav2 / C 板工程保留在仓库历史与 `master` 分支。
