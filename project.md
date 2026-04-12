# PROJECT：RK3588 中台开发进度与下一步计划

## 1. 文档目的

本文档用于记录 RK3588 车载交互与状态中台项目的当前开发状态、已知问题、阶段目标、下一步计划和变更记录，作为 AI 与人协同开发时的最新进度文档。

---

## 2. 当前项目状态

### 当前阶段

第一阶段：空壳中台 Bootstrap 已通过当前验收

### 当前结论

项目采用 **NUC11 + RK3588 + RT-Thread** 三节点协同：

- NUC11：主智能计算平台
- RT-Thread：底层实时执行与安全闭环
- RK3588：状态中台、任务入口、Web 服务、日志与后续扩展节点

当前 NUC11 仍在推进主导航闭环，因此 RK3588 第一阶段以 **独立可运行的空壳中台** 为目标，不承担主导航任务。

### 当前已完成交付

- 文档四件套已同步
- 后端 / 前端骨架可启动
- typed state models 与 mission contracts 已实现
- mock 状态链路已打通
- WebSocket 状态推送可用
- SQLite 本地持久化可用
- 单页 Dashboard 可展示并更新状态
- mission 命令可进入后端并写日志
- README 可复现启动与最小验证

---

## 3. 当前已确定事项

### 3.1 系统角色分工

- **NUC11**：SLAM、定位、路径规划、主视觉、任务主状态机
- **RT-Thread**：电机控制、IMU/编码器、姿态稳定、急停、失联保护
- **RK3588**：状态中台、任务入口、Web 服务、日志、巡检数据服务预留

### 3.2 第一阶段重点

第一阶段只做 RK3588 空壳中台：

- 后端服务框架
- WebSocket
- SQLite
- 模拟数据
- 页面框架
- 数据模型
- API 草案

### 3.3 已落地技术栈

- 后端：FastAPI + WebSocket + SQLite
- 前端：Vue 3 + TypeScript + Vite
- 文档：Markdown
- 版本控制：Git

---

## 4. 当前未完成事项

### 文档层面

- 页面线框图尚未补充
- API 示例响应还可以进一步细化
- 数据字段与真实 NUC / RT-Thread 输出尚未逐项对齐

### 工程层面

- 独立 Mission / Devices / Logs 页面尚未拆出
- `.env.example` 尚未补充
- 更细粒度的 Git 切片提交纪律仍可继续加强

### 集成层面

- NUC11 → RK3588 的真实状态接口尚未定义完成
- RT-Thread → RK3588 的真实状态接入方式尚未最终确认
- 任务接口与 NUC11 Mission Manager 的真实桥接尚未落地

---

## 5. 第一阶段开发清单

### P0-Doc：文档固化

- [x] 明确 RK3588 定位
- [x] 输出 `prd.md`
- [x] 输出 `arc.md`
- [x] 输出 `project.md`
- [ ] 补页面线框图
- [ ] 补 JSON 示例与 API 请求示例

### P0-Repo：仓库准备

- [x] 初始化 Git 仓库
- [x] 建立 `backend/`、`frontend/` 目录
- [x] 添加 `.gitignore`
- [x] 建立 `README.md`
- [ ] 建立 `.env.example`

### P0-Backend：后端空壳

- [x] 初始化 FastAPI 项目
- [x] 添加 `/health`
- [x] 添加 `GET /api/state/latest`
- [x] 添加 `GET /api/alerts`
- [x] 添加 `POST /api/mission/*` 占位接口
- [x] 添加 `WS /ws/state`

### P0-Frontend：前端空壳

- [x] 初始化 Vue 3 + TS 项目
- [x] 建立 Dashboard 页面
- [ ] 建立 Mission 页面
- [ ] 建立 Devices 页面
- [ ] 建立 Logs 页面
- [x] 接入模拟 WebSocket 数据

### P0-Mock：模拟数据

- [x] 设计模拟状态更新逻辑
- [x] 模拟位姿变化
- [x] 模拟任务状态变化
- [x] 模拟电量下降
- [x] 模拟告警触发

### P0-Validation：最小验证

- [x] 后端可启动
- [x] `/health` 可调用
- [x] WebSocket 可推送变化状态
- [x] Dashboard 可展示并更新状态
- [x] mission 命令可写入日志
- [x] README 可复现运行步骤
- [x] 已补最小后端自检

---

## 6. 已知问题与风险

### 风险 1：RK3588 需求容易膨胀

如果在第一阶段就接入语音、大模型、图传、真实多机通信，极易拖慢进度。必须坚持先做空壳中台，再逐步接真实链路。

### 风险 2：真实设备字段可能不一致

NUC11 与 RT-Thread 后续真实字段可能和当前 mock 模型不完全一致，因此需要采用“内部统一模型 + 外部适配层”的方式。

### 风险 3：页面与字段若不及时同步文档，后续会返工

后续修改状态模型、接口或页面结构时，必须同步 `README.md`、`prd.md`、`arc.md`、`project.md`。

---

## 7. 下一步执行计划

### 下一步目标

1. 设计 NUC11 真实状态适配器边界
2. 设计 RT-Thread 真实状态适配器边界
3. 评估是否拆分 Mission / Devices / Logs 独立页面
4. 细化 API 示例与字段文档
5. 为真实联调补充更完整的测试与错误处理

### 后续目标

1. 替换 mock 数据为真实数据
2. 引入语音入口模块
3. 引入巡检传感器数据服务
4. 扩展命令校验、错误处理与日志查询

---

## 8. 变更记录（Changelog）

### 2026-04-11

- 确认最终系统采用 NUC11 + RK3588 + RT-Thread 三节点协同
- 确认 RK3588 第一阶段定位为“车载交互与状态中台”
- 完成 `prd.md`、`arc.md`、`project.md` 初稿

### 2026-04-12

- 完成 FastAPI 后端骨架、typed schemas、mission mock 接口与 WebSocket 状态推送
- 完成 SQLite 命令日志、告警与状态快照持久化
- 完成 Vue 3 Dashboard 单页验收版，支持实时状态展示与基础 mission 操作
- 完成 README 运行说明与最小后端自检
- 按当前验收标准确认 Phase 1 通过

---

## 9. 当前阶段完成定义

当满足以下条件时，认为当前“第一阶段 Bootstrap”完成：

1. 文档四件套已同步
2. 项目目录结构建立完成
3. FastAPI 后端可启动并提供基本接口
4. Vue 前端可显示并更新 Dashboard 页面
5. mock 数据可驱动状态刷新
6. README 可复现运行方式，且最小验证可通过
