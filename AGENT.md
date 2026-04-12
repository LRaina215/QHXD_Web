# AGENT.md

## 项目概览

本仓库是 RK3588 车载交互与状态中台。
系统采用三节点协同：

- `NUC11`：主计算节点，负责 SLAM、定位、导航、感知与任务管理
- `RT-Thread`：底层实时控制与安全闭环
- `RK3588`：状态聚合、任务入口、Web 服务、Dashboard、日志与后续语音入口

## 当前阶段

当前处于 **Phase 1：空壳中台 Bootstrap 已通过当前验收**。

当前阶段已经具备：

- 可启动的 FastAPI 后端
- 可启动的 Vue 3 + TypeScript + Vite 前端
- mock 状态生成与 WebSocket 推送
- mission mock 接口
- SQLite 本地日志与状态快照
- 单页 Dashboard 展示与操作

当前阶段明确不做：

- 真实 NUC 通信
- 真实 RT-Thread 通信
- SLAM / Nav2 / 主视觉推理迁移到 RK3588
- 真实语音 / 图传 / 视频能力

## 文档真源

开始工作前优先阅读并遵循：

1. `README.md`
2. `prd.md`
3. `arc.md`
4. `project.md`

注意：

- 本仓库当前没有 `docs/` 目录，文档位于仓库根目录
- 如果文档和代码不一致，优先检查 `README.md` 与 `project.md` 中的当前交付状态，并明确报告差异

## RK3588 负责范围

RK3588 当前负责：

- 状态聚合
- 任务入口 API
- WebSocket 状态推送
- 本地 SQLite 持久化
- Web Dashboard
- 面向 NUC11 的业务桥接预留
- 面向 RT-Thread 的底层状态接入预留

RK3588 当前不负责：

- SLAM
- 主导航栈
- 全局 / 局部规划
- 主视觉推理
- 电机控制
- 急停闭环
- 低层实时安全控制

## 工作约束

- 改动必须小而清晰，方便 review
- 只改当前任务直接需要的文件
- 不顺手重构无关代码
- 不擅自改 UI 方向
- 优先 mock，后接真实适配器
- 保持前后端契约显式且有类型
- 优先成熟、简单、可验证的技术方案

## 推荐技术栈

后端：

- FastAPI
- Pydantic
- WebSocket
- SQLite

前端：

- Vue 3
- TypeScript
- Vite

## 数据契约纪律

后端是公开状态契约的真源。
当前状态模型至少覆盖：

- `robot_pose`
- `nav_status`
- `task_status`
- `device_status`
- `env_sensor`
- `alert_event`

当前 mission 命令至少覆盖：

- `go_to_waypoint`
- `start_patrol`
- `pause`
- `resume`
- `return_home`

不要发明重复语义字段；如果改字段，必须同步更新 `README.md`、`prd.md`、`arc.md`、`project.md` 中相关说明。

## 文件更新要求

如果任务影响以下内容，必须同步文档：

- 架构边界或模块职责：更新 `arc.md`
- 当前阶段状态、清单或计划：更新 `project.md`
- 运行方式或当前范围：更新 `README.md`
- 验收口径、页面口径、功能边界：更新 `prd.md`

## 验证要求

每次任务完成后：

- 运行最小必要验证
- 明确写出执行过的命令
- 明确写出 blocker
- 总结改动文件
