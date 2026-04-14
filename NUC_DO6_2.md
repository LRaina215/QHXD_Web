# NUC_DO6_2.md

## 1. 先说结论

对 `NUC_DONE6_1.md` 的复核结论如下：

- **NUC 侧新增的真实 ROS2 / IMU 接入代码是有效增量**
- **但这不等于完成了 `NUC_DO6_1.md` 原始目标**
- **本轮不能因为“IMU 方向代码已完成”就自动判定“真实 C 板低层状态已完成接入”**

原因很明确：

`NUC_DO6_1.md` 原始目标要求优先证明：

- `device_status.battery_percent`
- `device_status.emergency_stop`
- `device_status.fault_code`
- `device_status.online`

这些字段已经来自 **真实 C 板 / RT-Thread**

而 `NUC_DONE6_1.md` 实际完成的是：

- 新增了真实 `ros2` 采集入口
- 新增了 IMU 归一化结构
- 新增了 IMU HTTP 转发准备能力
- 但**没有证明上述 4 个核心 device_status 字段已经来自真实 C 板**
- 也**没有证明真实 IMU 已整链进入 RK3588**

所以当前最准确的判定是：

- **代码准备：部分完成**
- **原始验收目标：未完成**

---

## 2. 对 NUC 本轮工作的认可范围

以下内容可以确认是有效成果：

1. 已增加真实 `ros2` 采集模式
2. 已增加 IMU 标准化结构
3. 已增加 `inspect-rtt` / `send-imu-once`
4. 已新增配置样例和 README 说明
5. 已定位出当前现场阻塞：
   - C 板 BCP 帧不稳定 / 不存在
   - RK3588 当前没有 IMU 专用接口

这些成果说明：

- NUC 没有原地不动
- 真实 C 板接入方向已经开始推进

但这些成果**还不足以替代原始任务验收**。

---

## 3. 这轮为什么不能直接算通过

### 3.1 没有完成原始最小目标

原始最小目标是：

- 让真实 C 板低层状态进入现有 `device_status / env_sensor`

而不是：

- 先单独打通 IMU 新通道

### 3.2 NUC 单方面调整目标，不能自动替代原任务

NUC 在 `NUC_DONE6_1.md` 中把目标调整成了：

- “优先接 IMU”

这可以作为**新的方向建议**，但不能自动替代原始要求。

如果要改阶段目标，必须先和 RK / 项目侧明确同步，而不是在验收时默认改题。

### 3.3 NUC 向 RK 提出的新需求属于新 scope

NUC 提出的这些要求：

- `POST /api/internal/nuc/imu`
- `GET /api/imu/latest`
- `WS /ws/imu` 或状态流里的 IMU 通道
- 前端新增 IMU 展示区

它们都属于：

- **新的 Phase 3 子任务**

而不是本轮原始任务的必需前置条件。

本轮原始目标本来是：

- 继续复用现有 `POST /api/internal/nuc/state`
- 把低层状态并入已有契约

所以，**不能把“RK 还没做 IMU 专用接口”当作本轮原任务未通过的唯一理由**。

---

## 4. 下一步要求：请 NUC 先完成原始主线

下一步给 NUC 的验收要求非常明确：

### 主线要求

请优先回到原始主线，完成：

- **真实 C 板低层状态进入现有 `device_status / env_sensor` 契约**

也就是优先证明下面 4 个字段中的尽可能多项，已经来自真实 C 板：

- `device_status.battery_percent`
- `device_status.emergency_stop`
- `device_status.fault_code`
- `device_status.online`

如果现场条件限制，至少要先证明：

- `device_status.online`
- `fault_code`
- 或 `emergency_stop`

中至少 1 到 2 项已经来自真实链路，而不是 mock/file。

### 保持不变的要求

- 继续使用已有：
  - `POST /api/internal/nuc/state`
- 不新增平行公开字段
- 不要求 RK 先新增 IMU 专用接口，才能完成这一轮主线任务

---

## 5. 如果 NUC 要继续推进 IMU，可以，但要分成支线

IMU 方向不是不允许做，相反它是有价值的。

但从验收上必须和主线分开：

### 主线

- 真实 C 板低层状态进入 `device_status / env_sensor`

### 支线

- 真实 IMU 独立上传 / 展示链路

也就是说：

- **主线不通过，不能用支线成果顶替**
- IMU 可以继续推进，但请不要把它当作“本轮原任务已完成”的替代结论

---

## 6. 给 NUC 的下一轮验收要求

下面这些是下一轮必须满足的最低要求。

### A. 至少证明 1 到 2 个真实低层字段已经来自 C 板

推荐优先顺序：

1. `device_status.online`
2. `device_status.fault_code`
3. `device_status.emergency_stop`
4. `device_status.battery_percent`

说明：

- 如果现场暂时拿不到电量，允许先不强求 `battery_percent`
- 但至少要让 `online` / `fault_code` / `emergency_stop` 里的一部分真实跑通

### B. 必须走现有上送契约

要求：

- 继续走 `POST /api/internal/nuc/state`
- 通过现有：
  - `device_status`
  - `env_sensor`

把真实值送到 RK3588

### C. 必须留真实来源证据

至少留一组：

- C 板原始数据或原始报文
- NUC 本地标准化对象
- NUC 实际上送 payload
- RK3588 `/api/state/latest`

这四者之间的前后对应关系

### D. 必须做一次真实变化验证

至少做其中一项：

1. 让底层通信断开再恢复
2. 触发一次急停变化
3. 让 fault_code 变化
4. 让 online 状态变化

然后证明：

- C 板值变化
-> NUC 采集变化
-> RK3588 latest state 变化

---

## 7. 如果现场条件限制无法完成主线

如果 NUC 侧确认当前现场阶段确实无法拿到：

- 电量
- 急停
- 故障码

这些真实数据，那也需要**明确写出可落地的最小替代方案**，而不是直接改题。

可接受的最小替代方案示例：

- 先只完成 `device_status.online` 的真实来源验证
- 再把其余字段留为 `null / 默认值`

但前提是：

- 要明确说明这是**阶段性降级验收**
- 不是“原始任务已经全部完成”

---

## 8. IMU 方向何时单独验收

如果 NUC 继续推进 IMU，我这边接受单独开一个后续任务：

- 例如 `Round 3.2: IMU real upload path`

那时才会单独评审这些内容：

- `POST /api/internal/nuc/imu`
- `GET /api/imu/latest`
- `WS /ws/imu` 或状态流带 IMU
- 前端 IMU 展示

在那之前：

- **请不要把 IMU 新接口当作当前主线的前置要求**

---

## 9. 对 NUC 的最终要求表述

建议你直接把下面这段发给 NUC：

```text
本次复核结论：
你们新增的 ROS2 / IMU 接入代码是有效成果，但它没有完成 NUC_DO6_1 原始目标。

当前不能把“IMU 接入代码已完成”等同于“真实 C 板低层状态已完成接入”。

下一轮请优先回到原始主线：
1. 至少让 device_status.online / fault_code / emergency_stop / battery_percent 中的 1~2 项来自真实 C 板
2. 继续使用既有 POST /api/internal/nuc/state 契约
3. 提供原始来源 -> NUC 标准化对象 -> 上送 payload -> RK3588 /api/state/latest 的完整证据链
4. 至少做一次真实状态变化验证

IMU 方向可以继续推进，但请作为后续独立支线验收，不替代当前主线目标。
```
