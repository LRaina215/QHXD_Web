# AGENT.md

给在本仓库工作的 AI / 开发者的约定（yuntuo-fpga 分支）。

## 项目

云拓-多模态复杂地形轮腿机器人的 RK3588 任务层。导航与运动控制在 FPGA 上（共同工程位于 SOC_FPGA_NAV，含 control/），
本仓库负责视觉、语音、任务编排、Web 控制台与公网中继。总说明：`README.md`，细节：`docs/YUNTUO.md`。

## 硬约束

- RK3588 不向底盘发速度；任务只以 NV 报文（目标点 / 模式 / 视觉目标 / 位姿 / 地图）下发给 FPGA 导航。
- 运动类语音命令必须经确认（`/api/voice/confirm_command`）；LLM 输出必须过 `llm_safety` 白名单与置信度校验。
- fpga_bridge 是唯一占用 FPGA 链路的进程；其他组件经它的 :9101 接口或感知 UDP 端口通信。
- 不提交 `.env`、Token、密钥；云服务器上的改动先确认再做。

## 改动前后

- 改协议：与导航仓库 `fw/nav/proto.h`、`docs/2_interface/icd.md` 逐字段核对，并更新 `yuntuo/tests/test_fpga_link.py`。
- 改任务流程：跑 `python -m pytest yuntuo/tests`（含 bridge + 模拟器闭环）与 `cd backend && python -m pytest`。
- 改界面：先读 `docs/skills/rk3588-dashboard-design/SKILL.md`，`npm run build` 通过并在 1600 / 1366 / 390 宽度截图检查。
- 在 Windows 上编辑的脚本要保持 LF 换行与可执行位（`git update-index --chmod=+x`）。

## 文档

README 介绍功能、结构和使用方式；设计与接口说明记录当前机制、参数和约束。测试过程、发布状态、故障与会话交接保留在记录文档中，避免把临时运行状态堆到设计正文。代码入口链接维护分支。
