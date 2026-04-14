# project_p3.md

## 1. 当前阶段定义

### 阶段名称

**Phase 3：三机真实闭环与 P0 收口阶段**

### 当前背景

已完成：

- RK3588 Phase 1：空壳中台
- RK3588 Phase 2：NUC 真实状态上送 + mission bridge

当前需要推进：

- 让 RT-Thread 真实状态并入 NUC -> RK3588 状态链路
- 让前端命令继续真正影响到底层执行链路
- 完成 P0 的真实闭环收口，而不是继续做 P1/P2 增强功能。fileciteturn11file4turn11file3

---

## 2. 当前阶段总目标

本阶段的总目标是：

> 完成前端、RK3588、NUC、RT-Thread 的真实命令与状态闭环，使系统首次具备“可下发真实任务、可执行真实底层动作、可上送真实设备状态、可在页面回显”的完整能力。

---

## 3. 本阶段任务分解清单

### T3-1：冻结 Phase 3 三机状态字段

目标：

- 确认 NUC 内部状态 + RT-Thread 底层状态如何合并映射到 RK3588 契约

产出：

- 字段映射表
- 枚举值表
- 异常来源表

完成标准：

- 组内不再对 `battery_percent`、`fault_code`、`online`、`env_sensor` 的来源含糊不清

本轮冻结结果：

- `robot_pose`、`nav_status`、`task_status` 继续由 NUC 高层状态直接提供
- `device_status.battery_percent`、`emergency_stop`、`fault_code`、`online` 明确冻结为 **RT-Thread 经 NUC 归一化后提供**
- `env_sensor` 允许在真实传感器未接入时保留 `null + offline` 占位
- RK3588 公开契约维持 Phase 2 结构，不新增 `rtt_*` 平行字段

---

### T3-2：接入 RT-Thread 真实状态采集

目标：

- 在 NUC 上增加 `rtt_state_collector`
- 获取底层真实状态

优先字段：

- `battery_percent`
- `emergency_stop`
- `fault_code`
- `online`
- `velocity`（如有）

完成标准：

- NUC 本地能稳定拿到底层状态
- 状态变化时 NUC 内部可观察到变化

---

### T3-3：完成 NUC 状态包升级并上送 RK3588

目标：

- 把 RT-Thread 真实状态并入 NUC 状态上送包
- RK3588 页面能看到真实底层设备状态

完成标准：

- `GET /api/state/latest` 中 `device_status` 为真实值
- Dashboard 上急停/电量/在线状态变化可见

---

### T3-4：完成 mission 到底层执行的真实闭环

目标：

- 让 `go_to_waypoint`、`pause_task`、`resume_task`、`return_home` 的执行结果反映到底层链路

完成标准：

- 至少 3 个命令形成真实闭环
- 页面上任务状态变化与底层执行状态一致

---

### T3-5：完成基础巡检真实接入

目标：

- 将基础设备/环境数据纳入页面展示

优先顺序：

1. 电量
2. 急停
3. fault_code
4. 温湿度 / 舱温（如果已具备）

完成标准：

- 页面至少有两类真实底层/巡检数据
- 数据不依赖 mock

---

### T3-6：完成 Phase 3 阶段验收

目标：

- 做一次完整的三机联调验收

完成标准：

- 命令、状态、异常、页面四条链路全部通过

---

## 4. 当前阶段不做清单

- 不做语音入口真实接入
- 不做 OpenClaw
- 不做图传
- 不做 YOLO 异常检测联动
- 不做 LLM 总结
- 不做复杂前端重构
- 不做 RK3588 直连 RT-Thread 主链路

---

## 5. 任务优先级

### P0 收口优先级（必须先做）

1. T3-2 RT-Thread 真实状态采集
2. T3-3 NUC 状态包升级并上送
3. T3-4 mission 真实闭环
4. T3-5 基础巡检真实接入
5. T3-6 阶段验收

### 暂缓项

- 语音
- 图传
- 视觉增强
- LLM

---

## 6. 已知风险与阻塞点

### 风险 1：RT-Thread 状态字段来源不统一

说明：

- 可能存在多个底层状态源，字段定义不一致

应对：

- 先冻结最小字段，不追求一次性全接完
- 在 NUC `state_mapper` 中统一做一次归一化，不把底层多套命名直接暴露给 RK3588

### 风险 2：命令在 NUC 状态层闭环，但未真实触发底层动作

说明：

- 这是最容易误判“已经完成”的地方

应对：

- Phase 3 验收必须检查真实底层状态变化

### 风险 3：底层异常状态缺少明确可视化

说明：

- 页面可能只看到任务状态，却看不到设备异常

应对：

- 强制把 `fault_code`、`online`、`emergency_stop` 上屏

---

## 7. Phase 3 验收清单

### A. 状态链路

- [ ] NUC 能采到底层真实状态
- [ ] NUC 能把底层状态并入上送包
- [ ] RK3588 能接收真实状态
- [ ] Dashboard 能看到真实 `device_status`

### B. 命令链路

- [ ] `go_to_waypoint` 真实闭环
- [ ] `pause_task` 真实闭环
- [ ] `return_home` 真实闭环

### C. 巡检链路

- [ ] 电量可真实显示
- [ ] 急停状态可真实显示
- [ ] 至少一类额外设备/环境状态可真实显示

### D. 异常链路

- [ ] 底层离线有提示
- [ ] `fault_code` 非空有提示
- [ ] real 状态超时有提示

---

## 8. 给 Codex 的分轮次开发策略

本阶段继续遵循“小步迭代、每轮一个目标、每轮可验证、每轮后 commit”的方式。fileciteturn11file11

---

## Round 1：冻结 Phase 3 契约与字段映射

### 目标

只完成 Phase 3 的字段对齐与契约确认，不做大规模功能开发。

### 本轮交付口径

- 输出最终字段映射表
- 明确哪些字段来自 NUC，哪些字段来自 RT-Thread 经 NUC 上送
- 记录当前仍未完全收敛的歧义项，供 T3-2 实现时逐条确认

### Prompt

```text
Read docs/prd_p3.md, docs/arc_p3.md, docs/project_p3.md and follow AGENTS.md.

Task:
Freeze the Phase 3 state-contract mapping for the three-node system.

Goal:
Define how NUC high-level state and RT-Thread low-level state map into the RK3588 public state contract.

Requirements:
1. Identify the minimum RT-Thread-derived fields required in Phase 3:
   - battery_percent
   - emergency_stop
   - fault_code
   - online
   - optional env_sensor placeholders if real sensors are not ready
2. Add or update mapping documentation / code comments where appropriate
3. Keep the RK3588 public contract stable; do not redesign the whole API
4. Do not implement new UI or unrelated features

Constraints:
- Small, reviewable changes only
- No refactor outside mapping-related files
- Preserve mock/real dual-mode behavior

Validation:
- Summarize the final field mapping table
- Explain which fields come from NUC directly vs RT-Thread via NUC
- List any unresolved ambiguities

Only modify files required for this mapping task.
```

---

## Round 2：实现 NUC 侧 RT-Thread 状态采集适配层

### 目标

只在 NUC 侧引入最小 `rtt_state_collector`，不碰无关导航主逻辑。

### Prompt

```text
Read docs/prd_p3.md, docs/arc_p3.md, docs/project_p3.md and follow AGENTS.md.

Task:
Implement the minimal RT-Thread low-level state collector on the NUC side for Phase 3.

Goal:
Expose a normalized low-level device state that NUC can merge into the RK3588 state upload payload.

Requirements:
1. Add a minimal collector module for RT-Thread-derived fields:
   - battery_percent
   - emergency_stop
   - fault_code
   - online
   - optional velocity if already available
2. Keep the collector isolated from the main navigation logic
3. Use placeholder/mock adapters if the real RT-Thread source is not fully available yet, but keep the interface future-proof
4. Do not touch RK3588 frontend or mission bridge logic in this round

Constraints:
- Small changes only
- No broad refactor
- Do not redesign the NUC main stack

Validation:
- Show how the collector can produce a normalized low-level status object
- Explain how this object will be consumed by the NUC state mapper
- List any remaining TODOs for real RT-Thread integration

Only modify files needed for the NUC-side collector.
```

---

## Round 3：将 RT-Thread 真实状态并入 NUC -> RK3588 状态上送

### 目标

让 RK3588 页面第一次看到真实底层状态。

### Prompt

```text
Read docs/prd_p3.md, docs/arc_p3.md, docs/project_p3.md and follow AGENTS.md.

Task:
Merge RT-Thread-derived low-level device state into the NUC -> RK3588 real-state upload path.

Goal:
Upgrade the existing NUC state upload so that RK3588 receives real device_status and basic env/device state instead of placeholder-only values.

Requirements:
1. Update the NUC state mapper to merge:
   - high-level nav/task state
   - low-level RT-Thread device state
2. Keep the existing POST /api/internal/nuc/state contract stable
3. Preserve compatibility with mock/real mode on RK3588
4. Do not add unrelated endpoints

Constraints:
- Keep changes scoped to the NUC-side sender/mapping path and the smallest RK3588 compatibility changes if strictly necessary
- No frontend redesign

Validation:
- Demonstrate that the RK3588 latest state now includes real device_status values
- Verify dashboard-visible fields conceptually or through existing APIs
- Summarize which values are now truly sourced from RT-Thread

Only modify files needed for this state-upload upgrade.
```

---

## Round 4：打通 mission 到底层执行的真实闭环

### 目标

让命令不是只改高层状态，而是真实影响执行链路。

### Prompt

```text
Read docs/prd_p3.md, docs/arc_p3.md, docs/project_p3.md and follow AGENTS.md.

Task:
Complete the Phase 3 real mission-execution feedback loop.

Goal:
Ensure that mission commands coming from RK3588 through NUC are reflected in the downstream execution path and then back into state updates.

Required commands in scope:
- go_to_waypoint
- pause_task
- resume_task
- return_home

Requirements:
1. Connect mission handling to the execution-side bridge on NUC
2. Ensure resulting execution-state changes are visible in the next uploaded state package
3. Preserve existing mission API contracts on RK3588
4. Do not implement voice, video, or unrelated enhancements

Constraints:
- Small, traceable changes only
- Preserve mock mode
- Avoid broad rewrites of the main nav stack

Validation:
- Explain the full command path from frontend to execution-side effect to dashboard feedback
- Confirm at least 3 commands can form a real closed loop
- Summarize any command still remaining as partial

Only modify files required for the mission closed-loop task.
```

---

## Round 5：Phase 3 验收与最小收尾

### 目标

做阶段收尾，不扩展范围。

### Prompt

```text
Read docs/prd_p3.md, docs/arc_p3.md, docs/project_p3.md and follow AGENTS.md.

Task:
Prepare the project for Phase 3 acceptance review.

Goal:
Make the three-node closed-loop state visible, testable, and easy for teammates to verify.

Requirements:
1. Update or add the minimal docs/run notes needed for Phase 3 verification
2. Ensure the acceptance checklist in docs/project_p3.md is aligned with the implemented behavior
3. Add the smallest useful validation helpers/tests if practical
4. Do not expand scope beyond Phase 3

Constraints:
- No broad refactor
- No new big features
- Keep changes reviewable

Validation:
- Summarize what is now truly closed-loop
- Summarize what is still intentionally deferred to Phase 4/P1
- List exact manual verification steps for teammates

Only modify files required for acceptance preparation.
```

---

## 9. 本阶段建议的 Git 节奏

- Round 1 后 commit：字段冻结
- Round 2 后 commit：RT-Thread collector
- Round 3 后 commit：state upload upgraded
- Round 4 后 commit：mission real closed loop
- Round 5 后 commit：acceptance prep

---

## 10. Phase 3 完成后进入的下一阶段

### 下一阶段名称

**Phase 4：P1 增强能力阶段**

### 进入条件

- 三机真实闭环通过
- P0 收口完成
- Phase 3 验收 checklist 全部通过

### 下一阶段优先级

1. 语音任务入口
2. 环境传感器增强
3. 图传与路线同步
4. 视觉异常检测
5. 精准停靠增强
