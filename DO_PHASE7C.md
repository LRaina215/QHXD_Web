# DO_PHASE7C.md

# Phase 7C：项目级前端设计规范与 Dashboard 重设计

## 1. 阶段目标

Phase 7C 的目标不是继续零散修补页面，而是为当前 RK3588 车载中台前端建立一套稳定、可复用、可约束 Codex 的前端设计规范，并在不破坏既有功能的前提下，重新整理 Dashboard 的视觉风格、信息架构和组件边界。

本阶段最终产出应包括：

```text
1. 一份项目级前端设计 Skill / 规范文件
2. 一版符合项目定位的 Dashboard 设计方案
3. 按设计方案完成的前端视觉重构
4. 不删除、不破坏原有功能的回归验收
```

本阶段要解决的问题：

```text
Codex 自由发挥导致页面风格不稳定
Dashboard 信息层级混乱
语音、LLM、YOLO、任务状态、导航预留区展示不统一
前端设计缺少固定约束
后续继续迭代时容易改坏已有功能
```

---

## 2. 当前前端必须保留的功能

无论如何美化、重构布局或优化组件，以下功能必须保留，不允许删除、不允许改坏、不允许绕过原有 API。

## 2.1 系统状态展示

必须保留：

```text
mock / real 模式显示
NUC 在线 / 离线状态
RK3588 后端状态
当前任务状态
task_status 展示
nav_status 展示
robot_pose 展示
alerts / fault 信息展示
WebSocket 状态推送展示
```

## 2.2 任务与 mission 相关功能

必须保留：

```text
任务状态展示
当前目标点展示
mission 命令结果展示
mock / real 模式下任务反馈展示
```

不得修改：

```text
mission_gateway 行为
后端 mission API 路径
任务状态字段含义
```

## 2.3 语音识别功能

必须保留：

```text
文本命令入口
RK3588 板端录音入口
/api/voice/record_command 调用
FunASR 识别结果展示
recognized_text 展示
intent / command 展示
waypoint_id 展示
asr_time_s 展示
```

不得新增或混淆：

```text
不要把板端录音误改成浏览器麦克风录音
不要删除板端录音按钮
不要改变 /api/voice/record_command 调用逻辑
```

## 2.4 LLM 语义解析与确认功能

必须保留：

```text
LLM 解析结果展示
need_confirm 状态展示
pending_command_id 处理
移动类任务确认弹窗
/api/voice/confirm_command 调用
确认执行 / 取消任务按钮
```

不得破坏：

```text
移动类任务必须确认后才能执行
取消任务不能触发 mission
pending 过期必须有错误提示
未知命令不能触发 mission
```

## 2.5 YOLO 本地识别展示

必须保留：

```text
detection_status 展示
YOLO enabled / offline 状态
模型名称展示
最近检测对象展示
检测事件展示
视觉告警展示
```

本阶段不做：

```text
视频流展示
检测框实时画面
YOLO 逻辑修改
```

## 2.6 导航实时可视化预留区

必须保留并强化：

```text
导航实时可视化区域
当前位姿展示
当前目标点展示
导航状态展示
地图 / 路径占位区域
等待接入 NUC 导航实时流的提示
```

本阶段不做：

```text
真实地图渲染
Canvas 路径绘制
ROS2 话题直连前端
真实导航 WebSocket 协议改造
```

---

## 3. 本阶段不允许做的事情

Codex 在本阶段禁止执行以下操作：

```text
不允许删除现有功能入口
不允许修改后端 API 路径
不允许修改 WebSocket 协议
不允许改 mission / voice / LLM / YOLO 业务逻辑
不允许整仓迁移 SoybeanAdmin、vue-pure-admin 或其他模板
不允许引入 pretext
不允许更换前端框架
不允许重写状态管理体系
不允许新增浏览器本地录音
不允许新增 OpenClaw
不允许新增唤醒词
不允许接入真实导航地图
不允许做大屏炫酷动画导致信息不可读
不允许为了美观隐藏错误信息或调试状态
```

本阶段允许做：

```text
重排 Dashboard 布局
优化组件样式
统一卡片视觉
统一状态颜色
优化弹窗信息层级
优化语音 / LLM / YOLO / 告警展示
新增前端设计规范文件
新增轻量 UI 工具类或组件
局部拆分展示组件
```

---

## 4. 项目级前端设计 Skill 要求

## 4.1 新增设计规范文件

建议新增：

```text
docs/skills/rk3588-dashboard-design/SKILL.md
```

若项目已有 skills 目录，则放入现有目录。

该文件必须作为 Codex 后续修改前端前的强制阅读文件。

## 4.2 Skill 内容必须包含

```text
1. 项目前端定位
2. 不允许破坏的业务功能
3. Dashboard 信息架构
4. 视觉风格规范
5. 状态颜色规范
6. 组件设计规范
7. 导航可视化预留规范
8. 弹窗与危险操作确认规范
9. 每次修改后的自检清单
```

## 4.3 前端定位

Skill 中应明确：

```text
这是 RK3588 车载机器人业务中台 Dashboard
不是普通后台管理系统
不是炫酷大屏
不是纯调试页面
目标是比赛答辩展示 + 实际联调操作
```

## 4.4 设计风格

建议采用：

```text
清爽科技风
蓝白主色
深色背景可选
卡片式布局
信息层级清楚
状态颜色明确
适合正式答辩展示
```

禁止：

```text
过度花哨
过多渐变
大面积霓虹
无意义动画
遮挡状态信息
弱化错误提示
```

---

## 5. Dashboard 信息架构要求

## 5.1 推荐整体布局

Dashboard 应按以下信息层级设计：

```text
顶部：系统状态栏
第一行：核心状态卡片
第二行：导航可视化预留区 + 语音/LLM/YOLO 功能区
第三行：告警、事件、日志区域
```

## 5.2 顶部状态栏

展示：

```text
系统名称
当前模式 mock / real
NUC 连接状态
RK3588 服务状态
当前时间
关键告警摘要
```

## 5.3 核心状态卡片

至少包含：

```text
当前任务
机器人状态
电量 / 急停 / fault
最近告警
```

## 5.4 主功能区域

左侧：

```text
导航实时可视化预留区
```

右侧：

```text
语音任务入口
LLM 确认状态
YOLO 检测状态
```

## 5.5 底部事件区域

展示：

```text
最近语音事件
最近 LLM 解析事件
最近 YOLO 检测事件
最近 mission 事件
最近系统告警
```

---

## 6. 状态颜色规范

必须统一状态颜色，不允许各组件自由发挥。

| 状态类型 | 推荐颜色倾向 | 说明 |
|---|---|---|
| online / normal | 绿色 | 在线、正常 |
| running / navigating | 蓝色 | 运行中、导航中 |
| pending / need_confirm | 黄色 | 等待确认 |
| warning / alert | 橙色 | 告警、注意 |
| fault / emergency_stop | 红色 | 故障、急停 |
| offline / unknown | 灰色 | 离线、未知 |
| mock | 紫色或灰紫 | 模拟模式 |
| real | 蓝色或绿色 | 真实模式 |

建议新增统一组件：

```text
StatusBadge.vue
```

或统一 CSS class：

```text
.status-badge--online
.status-badge--running
.status-badge--pending
.status-badge--warning
.status-badge--danger
.status-badge--offline
```

---

## 7. 组件设计要求

## 7.1 卡片组件规范

所有核心模块应采用统一卡片风格：

```text
统一圆角
统一阴影
统一标题字号
统一内容间距
统一状态角标
统一空状态样式
```

## 7.2 语音卡片

必须展示：

```text
板端录音按钮
识别文本
ASR 后端
ASR 耗时
intent
waypoint_id
accepted / need_confirm
最近一次执行结果
```

## 7.3 LLM 确认弹窗

必须突出：

```text
这是移动类任务确认
该操作会使机器人移动或改变任务状态
识别文本是什么
解析目标是什么
确认后才执行
取消后不执行
```

## 7.4 YOLO 卡片

必须展示：

```text
YOLO 模块状态
模型名称
最近检测对象
置信度
最近事件
视觉告警
```

## 7.5 导航占位组件

建议组件名：

```text
NavMapPlaceholder.vue
```

必须展示：

```text
导航实时可视化
当前位姿
当前目标点
导航状态
地图占位区域
等待接入 NUC 导航实时流
```

后续替换为：

```text
NavMapCanvas.vue
```

---

## 8. 任务清单

## Task 1：新增项目级前端设计 Skill

### 任务要求

新增文件：

```text
docs/skills/rk3588-dashboard-design/SKILL.md
```

内容包含：

```text
项目定位
不可破坏功能清单
Dashboard 信息架构
视觉风格规范
状态颜色规范
组件设计规范
导航预留规范
前端修改自检清单
```

### 验收标准

```text
[ ] 新增设计 Skill 文件
[ ] Skill 明确禁止修改后端 API 和业务逻辑
[ ] Skill 明确保留语音、LLM、YOLO、导航预留区
[ ] Skill 可被 Codex 后续任务引用
```

---

## Task 2：执行前端 UI 审计

### 任务要求

Codex 必须先只阅读前端代码，不修改代码，输出当前 Dashboard 的问题列表。

审计维度：

```text
布局混乱问题
信息层级问题
状态颜色不统一问题
组件重复问题
弹窗可读性问题
语音卡片可用性问题
YOLO 卡片展示问题
导航预留区缺失或不清晰问题
移动端/小屏展示问题
```

### 验收标准

```text
[ ] Codex 先输出 UI 审计结果
[ ] 未直接开始改代码
[ ] 审计结果覆盖主要功能区
[ ] 审计结果指出哪些功能不能删除
```

---

## Task 3：输出 Dashboard 设计改造方案

### 任务要求

Codex 在动代码前，先输出页面结构方案，包括：

```text
顶部状态栏布局
核心状态卡片布局
导航预留区布局
语音/LLM/YOLO 区域布局
告警与事件区域布局
组件拆分方案
```

### 验收标准

```text
[ ] 给出清晰页面分区
[ ] 明确每个区域展示哪些字段
[ ] 保留全部原有功能入口
[ ] 明确不会改 API
[ ] 明确导航区只做占位不接真实流
```

---

## Task 4：实现 Dashboard 视觉重构

### 任务要求

按设计方案重构 Dashboard 页面展示，但不得改业务逻辑。

必须完成：

```text
统一卡片布局
优化顶部状态栏
优化核心状态卡片
优化主功能区排布
优化事件与告警区域
```

### 验收标准

```text
[ ] Dashboard 不再像调试页面
[ ] 第一屏能看到核心系统状态
[ ] 语音、LLM、YOLO、任务、告警均可见
[ ] 页面打开无白屏
[ ] 后端接口调用未被改动
```

---

## Task 5：优化语音与 LLM 确认区域

### 任务要求

优化：

```text
语音识别卡片
板端录音按钮
识别结果展示
LLM 解析信息展示
移动任务确认弹窗
```

### 验收标准

```text
[ ] 板端录音按钮仍然可用
[ ] recognized_text 清楚显示
[ ] intent / waypoint_id 清楚显示
[ ] need_confirm=true 时确认弹窗出现
[ ] 确认后调用 /api/voice/confirm_command
[ ] 取消后不触发 mission
```

---

## Task 6：优化 YOLO 与告警展示区域

### 任务要求

优化：

```text
YOLO 检测卡片
检测对象列表
检测事件展示
告警列表
事件列表
```

### 验收标准

```text
[ ] YOLO 状态清晰可见
[ ] 最近检测对象清晰可见
[ ] 告警等级颜色统一
[ ] 空状态有合理提示
[ ] 不新增视频流逻辑
[ ] 不修改 detection_status 数据结构
```

---

## Task 7：新增或强化导航可视化预留区

### 任务要求

新增或优化：

```text
NavMapPlaceholder.vue
```

展示：

```text
当前位姿
当前目标点
导航状态
地图占位区域
等待 NUC 导航实时流
```

保留未来升级接口：

```ts
robotPose
currentGoal
globalPath
navState
```

### 验收标准

```text
[ ] Dashboard 中存在导航可视化预留区
[ ] 该区域视觉上足够显眼
[ ] 当前 robot_pose 能显示则显示
[ ] 无真实导航数据时有合理占位
[ ] 后续可替换为 NavMapCanvas
[ ] 不直接接 ROS2 话题
```

---

## Task 8：功能回归测试

### 任务要求

改完 UI 后必须验证全部已有功能。

### 验收标准

```text
[ ] 前端可正常启动
[ ] Dashboard 可正常打开
[ ] WebSocket 状态正常显示
[ ] 语音板端录音入口正常
[ ] LLM 确认弹窗正常
[ ] confirm_command 正常
[ ] YOLO 状态正常显示
[ ] 任务状态正常显示
[ ] 告警列表正常显示
[ ] 导航预留区正常显示
[ ] 无控制台严重报错
```

---

## 9. Codex 执行 Prompt

将下面内容交给 Codex：

```text
Read AGENTS.md, DO_PHASE7C.md, and the current frontend code.
If available, also read docs/skills/frontend-design/SKILL.md.

Task:
Implement Phase 7C: project-specific frontend design system and Dashboard redesign for the RK3588 robot middleware.

Goal:
Create a frontend design that matches this project: an RK3588-based robot interaction and status middleware for delivery + inspection sentinel robot. Improve the Dashboard visual design while preserving all existing functions.

Important constraints:
1. Do not change backend API paths.
2. Do not change WebSocket protocol.
3. Do not change mission, voice, LLM, YOLO, or navigation placeholder business logic.
4. Do not remove any existing feature entry.
5. Do not remove the RK3588 server-side voice recording entry.
6. Do not remove the LLM movement confirmation dialog.
7. Do not remove YOLO detection display.
8. Do not remove the navigation visualization placeholder.
9. Do not introduce browser microphone recording.
10. Do not introduce pretext.
11. Do not migrate an external admin template wholesale.
12. Do not implement real navigation map rendering in this phase.

Required process:
Step 1: Add docs/skills/rk3588-dashboard-design/SKILL.md.
Step 2: Audit the current Dashboard UI and list problems before coding.
Step 3: Propose a component-level redesign plan before coding.
Step 4: Implement the redesign in small scoped changes.
Step 5: Run or describe regression checks for all existing functions.

Design direction:
- clean robot control dashboard
- blue/white technical style
- card-based layout
- unified status badges
- clear hierarchy
- suitable for competition presentation
- navigation visualization area reserved for future NavMapCanvas

Must preserve and display:
- system mode mock/real
- NUC/RK3588 connection status
- current task
- robot pose
- voice recognition result
- LLM confirmation result
- YOLO detection status
- alerts/events
- navigation visualization placeholder

Validation:
- frontend starts successfully
- Dashboard opens without blank screen
- voice recording entry still works
- LLM confirmation still works
- YOLO card still works
- task status still works
- alerts/events still work
- navigation placeholder exists
- no backend API path changed
- no existing feature deleted

Only modify files required for frontend design system and Dashboard visual redesign.
```

---

## 10. 总体验收标准

Phase 7C 通过需要满足：

```text
[ ] 项目级前端设计 Skill 已建立
[ ] Dashboard 信息架构符合机器人中台需求
[ ] 页面观感明显提升
[ ] 语音、LLM、YOLO、任务、告警、导航预留区全部保留
[ ] 没有删除原前端任何核心功能
[ ] 没有修改后端 API
[ ] 没有破坏 WebSocket 状态流
[ ] 移动类任务确认仍然安全有效
[ ] 前端没有明显白屏、错位、文字溢出问题
[ ] 页面适合比赛答辩展示
```
