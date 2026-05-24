# DO_PHASE7B.md

# Phase 7B：Dashboard 视觉收口与导航可视化预留

## 1. 阶段目标

当前系统已经完成语音识别、LLM 语义解析确认、YOLO 本地识别、任务桥接和状态展示等核心功能。Phase 7B 的目标不是新增后端能力，而是对现有前端进行一次**演示级视觉收口**，提升答辩展示效果，并为后续导航实时可视化预留稳定的页面结构。

本阶段目标：

```text
在不改变后端 API、不改变业务逻辑、不重构前端项目的前提下，参考 SoybeanAdmin 等清爽后台系统的视觉风格，优化 Dashboard 信息层级、状态卡片、语音交互、LLM 确认、YOLO 检测、告警展示，并预留导航实时可视化区域。
```

---

## 2. 当前阶段边界

## 2.1 本阶段要做

- 优化 Dashboard 页面布局
- 统一卡片、按钮、状态标签、弹窗视觉风格
- 优化语音识别结果展示
- 优化 LLM 移动任务确认弹窗
- 优化 YOLO 检测结果展示
- 优化系统状态、任务状态、告警信息展示
- 新增导航实时可视化预留区
- 新增 `NavMapPlaceholder` 或等价组件
- 保留后续升级为 `NavMapCanvas` 的接口边界
- 保证现有功能均可正常使用

## 2.2 本阶段不做

- 不整仓迁移 SoybeanAdmin / vue-pure-admin / 其他后台模板
- 不引入 `pretext`
- 不更换前端框架
- 不重写前端状态管理
- 不修改后端 API
- 不修改 WebSocket 数据协议
- 不修改语音、LLM、YOLO、mission 业务逻辑
- 不接入真实导航数据
- 不做 Canvas 地图绘制
- 不做 ROS2 话题直连前端
- 不做视频图传
- 不做复杂大屏动画

---

## 3. 设计参考方向

本阶段只参考成熟后台系统的视觉风格，不复制其工程结构。

推荐参考方向：

```text
主参考：SoybeanAdmin 的清爽后台风格
次参考：vue-pure-admin / V3 Admin Vite 的中后台信息层级和组件组织
机器人信息架构参考：Foxglove / robotics-ui 的机器人状态面板组织方式
```

视觉关键词：

```text
清爽科技风
蓝白主色
卡片式布局
状态颜色明确
适合正式答辩展示
不做过度炫酷大屏
不做复杂动效
```

---

## 4. 推荐页面布局

Dashboard 推荐调整为三层结构。

## 4.1 顶部状态栏

展示：

- 项目名称
- 当前系统模式：`mock / real`
- NUC 连接状态
- RK3588 服务状态
- 当前时间

示例：

```text
配送巡检一体化哨兵机器人中台 | REAL | NUC Online | RK3588 Online | 2026-xx-xx xx:xx:xx
```

## 4.2 第一行：核心状态卡片

建议包含 4 张卡片：

1. 当前任务
2. 机器人在线状态
3. 电量 / 急停
4. 最近告警

## 4.3 第二行：主功能区域

建议采用左右布局：

```text
左侧：导航实时可视化预留区
右侧：语音交互 + LLM 确认 + YOLO 检测
```

其中导航区域本阶段只做占位，不接真实导航流。

## 4.4 第三行：日志与事件区域

展示：

- 最近语音命令
- 最近 LLM 解析结果
- 最近 YOLO 检测事件
- 最近 mission 事件
- 系统调试信息

---

## 5. 状态颜色规范

前端应统一状态颜色，不要每个组件各用一套颜色。

建议规范：

| 状态类型 | 颜色倾向 | 说明 |
|---|---|---|
| 在线 / 正常 | 绿色 | online / normal |
| 运行中 | 蓝色 | running / navigating |
| 等待确认 | 黄色 | need_confirm / pending |
| 告警 | 橙色 | warning / alert |
| 故障 / 急停 | 红色 | fault / emergency_stop |
| 离线 / 未知 | 灰色 | offline / unknown |

建议统一封装状态 badge 样式，例如：

```text
StatusBadge.vue
```

或在现有组件内抽象统一 class。

---

## 6. 组件任务清单

## Task 1：Dashboard 布局重构为演示级信息面板

### 任务要求

- 重新组织 Dashboard 页面结构
- 使用卡片式布局
- 优化间距、字体层级、标题层级
- 保留现有所有数据来源和 API 调用
- 不改变业务逻辑
- 不删除现有功能入口

### 验收标准

```text
[ ] Dashboard 打开后信息层级清楚
[ ] 第一屏能看到任务、状态、电量、告警
[ ] 页面不再像纯调试页面
[ ] 现有数据正常展示
[ ] 不影响语音、LLM、YOLO、mission 功能
```

---

## Task 2：新增导航实时可视化预留区

### 任务要求

新增一个导航占位组件，推荐命名：

```text
NavMapPlaceholder.vue
```

当前显示占位内容：

- 标题：导航实时可视化
- 当前位姿：`x / y / yaw`
- 当前目标点
- 导航状态
- 路径区域占位图
- 提示文案：`等待接入 NUC 导航实时流`

本阶段不接真实地图、不画真实路径。

### 未来预留接口

组件设计时预留 props 或数据结构：

```ts
robotPose?: {
  x: number
  y: number
  yaw: number
  frame_id?: string
}

goal?: {
  id?: string
  x?: number
  y?: number
  yaw?: number
}

globalPath?: Array<{ x: number; y: number }>

navState?: string
```

### 验收标准

```text
[ ] Dashboard 中出现导航可视化预留区
[ ] 预留区不影响现有功能布局
[ ] 当前位姿可从已有 robot_pose 字段读取并展示
[ ] 当前目标点可从 current_goal / task_status 读取并展示
[ ] 组件边界清晰，后续可替换为 NavMapCanvas
[ ] 没有接入 ROS2 直连逻辑
```

---

## Task 3：优化语音交互卡片

### 任务要求

优化现有语音交互区域，展示：

- 识别文本 `recognized_text`
- ASR 后端 `asr_backend`
- ASR 耗时 `asr_time_s`
- 解析意图 `intent`
- 目标点 `waypoint_id`
- 执行状态 `accepted / need_confirm`
- 任务反馈 `detail`

若当前已支持 RK3588 板端录音按钮，应保留。

### 验收标准

```text
[ ] 语音识别结果显示清楚
[ ] 用户能区分“识别文本”和“解析意图”
[ ] ASR 耗时可见
[ ] 任务是否已受理可见
[ ] 未识别命令时提示明确
[ ] 不改变 /api/voice/record_command 调用逻辑
```

---

## Task 4：优化 LLM 移动任务确认弹窗

### 任务要求

优化确认弹窗视觉与信息层级，弹窗应展示：

- 识别文本
- LLM 解析结果
- intent / command
- waypoint_id
- confidence，如已有
- 风险提示
- 确认执行按钮
- 取消任务按钮

建议移动类任务使用更醒目的黄色/蓝色确认风格，不要误导用户以为已经执行。

### 验收标准

```text
[ ] need_confirm=true 时弹窗清楚出现
[ ] 弹窗内容能说明将要执行什么任务
[ ] 点击确认后调用 /api/voice/confirm_command
[ ] 点击取消后不触发 mission
[ ] pending 过期或失败时有提示
[ ] 不改变后端确认接口路径
```

---

## Task 5：优化 YOLO 检测卡片

### 任务要求

优化 YOLO 检测区域，展示：

- 检测模块状态：enabled / offline
- 模型名称
- 最近检测对象
- 置信度
- 最近事件
- 告警等级

不做视频流显示，不做检测框画面。

### 验收标准

```text
[ ] YOLO 状态显示清楚
[ ] 最近检测对象可见
[ ] 检测事件可见
[ ] 无检测结果时有空状态提示
[ ] 不影响 detection_status 数据接收
[ ] 不新增视频图传逻辑
```

---

## Task 6：优化告警与事件列表

### 任务要求

统一展示最近事件，包括：

- 语音命令事件
- LLM 确认事件
- YOLO 检测事件
- mission 状态事件
- 系统告警事件

每条事件至少展示：

- 时间
- 来源
- 等级
- 内容

### 验收标准

```text
[ ] 最近事件列表样式统一
[ ] warning/error 类事件有明显颜色区分
[ ] 空状态显示合理
[ ] 不影响原有 alert 接口
[ ] 不重复触发请求风暴
```

---

## Task 7：统一基础 UI 样式

### 任务要求

统一以下样式：

- 卡片圆角
- 阴影
- 标题字号
- 内容字号
- 状态 badge
- 按钮风格
- 弹窗风格
- 空状态风格
- 错误提示风格

可以使用 scoped CSS 或现有全局 CSS。

### 验收标准

```text
[ ] 页面整体风格统一
[ ] 不同卡片不再像不同人写的
[ ] 状态颜色规范统一
[ ] 按钮主次层级清楚
[ ] 不引入大规模新依赖
```

---

## 7. Codex 执行 Prompt

将下面内容直接交给 Codex：

```text
Read AGENTS.md, README.md, and current frontend code.

Task:
Implement Phase 7B: Dashboard visual polish and navigation visualization placeholder.

Goal:
Improve the presentation quality of the existing Dashboard without changing backend APIs, business logic, or the current frontend framework. The style should be inspired by clean Vue admin dashboards such as SoybeanAdmin, but do not migrate or copy any whole repository.

Requirements:
1. Do not change backend API paths.
2. Do not change WebSocket protocol.
3. Do not change mission, voice, LLM, YOLO, or state logic.
4. Do not introduce pretext.
5. Do not migrate SoybeanAdmin or other admin templates.
6. Keep the current Vue/Vite/TypeScript structure.
7. Improve Dashboard layout into clear sections:
   - top system status bar
   - core status cards
   - navigation visualization placeholder
   - voice interaction card
   - LLM confirmation area/dialog
   - YOLO detection card
   - alerts/events area
8. Add a navigation visualization placeholder component, such as NavMapPlaceholder.vue.
9. The navigation placeholder should show:
   - current pose if available
   - current goal if available
   - nav state if available
   - placeholder map area
   - message: waiting for NUC navigation stream
10. Improve status badge styles and unify status colors.
11. Improve voice result display.
12. Improve LLM confirmation dialog visual hierarchy.
13. Improve YOLO detection status display.
14. Improve alerts/events display.
15. Keep the UI lightweight and suitable for competition presentation.
16. Do not add real map rendering or ROS2 integration in this phase.

Validation:
- frontend starts successfully
- Dashboard renders without blank screen
- existing state data still displays
- voice command UI still works
- LLM confirmation dialog still works
- YOLO detection status still displays
- alerts/events still display
- navigation placeholder appears and does not break layout
- no backend API path is changed

Only modify files required for frontend visual polish and navigation placeholder.
```

---

## 8. 本阶段总体验收标准

Phase 7B 通过条件：

```text
[ ] Dashboard 视觉观感明显提升
[ ] 信息层级清楚，适合答辩展示
[ ] 语音、LLM、YOLO、告警、任务状态均正常显示
[ ] 导航实时可视化区域已经预留
[ ] 后续可平滑升级为 NavMapCanvas
[ ] 没有破坏任何现有接口和业务链路
[ ] 没有整仓迁移外部模板
[ ] 没有引入与当前需求无关的大型依赖
```

---

## 9. 本阶段完成后下一步

Phase 7B 完成后，后续可进入：

```text
Phase 8A：NUC 导航状态流接入
Phase 8B：NavMapCanvas 实时二维地图显示
Phase 8C：路径、目标点、机器人位姿联动显示
```

Phase 7B 只负责把页面结构和视觉风格准备好，不负责真实导航数据接入。
