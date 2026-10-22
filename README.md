# 云拓 · RK3588 任务层与控制台

「云拓-多模态复杂地形轮腿机器人」（全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道）的 RK3588 端工程。
导航（雷达定位、规划、安全限速）与运动控制（强化学习轮腿策略）都在 FPGA 上；RK3588 只做任务层：
RGB-D 视觉、离线语音、任务编排、Web 控制台与公网中继。

```
网页 / 语音 ─► 后端 FastAPI :8000 ─► fpga_bridge :9101 ──NV 报文──► FPGA 导航 ──► FPGA 运动控制（RL）
              任务预检 / 状态 / WS     任务状态机         目标点 / 模式 / 视觉目标    限幅后的速度
                     ▲                    ▲  STATUS 5 Hz、控制遥测（只读）◄───────────┘
Astra Pro Plus ─► 感知节点（RKNN 检测 + 深度 + 颜色 + 跟踪）
```

安全原则：RK3588 不向底盘发速度；运动类语音命令必须人工确认；急停优先于一切任务；公网写接口需要 Token，
运动控制还受云端 `PUBLIC_CONTROL_ENABLED` 开关限制。

## 目录

| 路径 | 内容 |
|---|---|
| `backend/` | FastAPI 后端：状态 / WebSocket / SQLite、任务预检与转发、语音（SenseVoice 识别、规则 + 大模型解析、语音合成）、平台状态 |
| `yuntuo/` | `fpga_link`（NV 报文、串口 / UDP 链路、控制遥测、先验地图包）、`bridge`（fpga_bridge）、`perception`（RGB-D 感知）、`llm`（板载 rknn-llm 大模型服务）、`tts`（板载 sherpa-onnx 语音合成服务）、`mock_fpga` 模拟器 |
| `frontend/` | Vue 3 控制台（设计规则见 `docs/skills/rk3588-dashboard-design/SKILL.md`） |
| `experiments/rknn_yolo/` | RKNN YOLO 推理与后处理（感知节点复用）、H.264 推流 |
| `cloud_gateway/` · `streaming/` | 云服务器上的公网网关与 MediaMTX 视频中继 |
| `scripts/` · `systemd/` | 启停脚本、服务单元、udev 规则 |
| `docs/YUNTUO.md` | 详细说明：任务如何落到 FPGA、接口、上机步骤与核对清单、离线 LLM / TTS |

## 不上车联调（PC 或 RK3588）

```bash
cd backend && pip install -r requirements.txt pyserial && python -m uvicorn app.main:app --port 8000
./scripts/start_yuntuo_sim.sh            # 模拟 FPGA + 虚拟相机 + fpga_bridge（停止：stop）
cd frontend && npm ci && npm run dev     # http://127.0.0.1:5173
```

网页右上角切到"实车"：链路显示"模拟"，可直接试"寻找红色水瓶""跟随我""前往 B 点""巡检"和急停。

## 上 RK3588

```bash
cp .env.example .env                      # 按实机修改：FPGA 串口、相机、点位、离线 LLM / TTS
./scripts/install_backend_service.sh      # qhxd-backend.service
./scripts/install_rkllm_runtime.sh        # 板载大模型运行库（/opt/rkllm/1.3.1）
./scripts/install_yuntuo_services.sh --mock-fpga --with-llm --with-tts
                                          # udev、fpga_bridge、感知、模拟 FPGA、大模型、语音合成、qhxd-boot（同时停用旧的 Nav2 执行器）
./scripts/status_public_robot.sh
```

模型下载位置、服务端口、回滚方法见 `docs/YUNTUO.md` 第 6、7 节；上机核对清单见第 8 节（串口设备号、Astra 内参与安装、场地点位等）。

## 测试

```bash
python -m pytest yuntuo/tests             # 协议、链路、感知、bridge + 模拟器闭环
cd backend && python -m pytest            # 后端
cd frontend && npm run build              # 含类型检查
```

## 公网

云服务器只运行 Nginx、静态前端、`cloud_gateway`（反代到 RK3588 后端）与 MediaMTX，部署方式见 `cloud_gateway/README.md`
与 `streaming/README.md`。同步前端、改网关配置或 `PUBLIC_CONTROL_ENABLED` 都是生产变更，先备份再操作；Token 与 `.env` 不入库。

历史：本仓库原为 QHXD（NUC + Nav2 + C 板）车载中台，相关代码与过程文档保留在 `master` 分支与 git 历史中。
