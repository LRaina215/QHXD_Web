# DONE_PHASE7 - 前端 Phase 7 修复与收口记录

## 本次修复背景

用户指出 Phase 7B 前端视觉收口后出现功能回退与排版问题：

- `5704d55f546bd7326332b70bc219d0a98a1f3c7f` 版本中存在的 YOLO 最新识别图像展示被新页面遗漏；
- Mock / Real 数据模式切换入口被新页面遗漏；
- 新页面在过窄或过宽分辨率下网格和按钮排版不稳定；
- 部分按钮在宽屏被拉得过大，个别卡片对齐效果差；
- 需要在继续修改前端时把改动写入 `DONE_PHASE7.md`。

本次修复目标是：在保留 Phase 7B 新增的导航占位、事件聚合、清爽后台视觉风格的同时，恢复旧版本已经可用的关键功能入口，并收敛响应式布局。

## 对照来源

对照提交：

```text
5704d55f546bd7326332b70bc219d0a98a1f3c7f
Tag6.1 接入LLMapi实现复杂语音解析
```

对照确认到旧版前端具备：

- `refreshLatestFrame()` 轮询 `/api/perception/latest_frame`；
- `latestFrameUrl` / `latestFrameAvailable` 状态；
- Perception 卡片中的 `<div class="latest-frame-box">` 最新识别画面；
- 顶部区域中的“切到 Mock / 切到 Real”按钮；
- `switchMode('mock')` / `switchMode('real')` 调用 `/api/system/mode/switch`。

## 本次修改文件

### 1. `frontend/src/App.vue`

关键改动：

- 第 1098-1113 行：恢复顶部 Mock / Real 模式切换按钮。
  - `@click="switchMode('mock')"`
  - `@click="switchMode('real')"`
  - 保留原有禁用条件：当前模式下不可重复点击。
- 第 1147-1153 行：保留 Phase 7B 新增的 `NavMapPlaceholder` 导航可视化预留区。
- 第 1288-1298 行：恢复 YOLO 最新识别图像显示。
  - 继续使用 `latestFrameAvailable`；
  - 继续使用 `latestFrameUrl`；
  - 继续使用 `handleLatestFrameError()` / `handleLatestFrameLoad()`；
  - 不新增视频流，不改变后端 API。
- 第 1300-1348 行：补齐 YOLO 检测状态卡片信息。
  - 来源；
  - 模型；
  - 最近目标；
  - 当前检测；
  - 最近检测；
  - 更新时间；
  - 最近事件；
  - 视觉事件列表。
- 第 382-508 行：保留统一事件列表聚合逻辑。
  - voice；
  - LLM；
  - YOLO；
  - mission；
  - alerts。

### 2. `frontend/src/style.css`

关键改动：

- 第 27-30 行：为 `.dashboard` 增加最大宽度与居中布局，避免超宽屏内容无限拉伸。
- 第 79-100 行：新增 `.mode-switch-group` 与 `.compact-button`，恢复模式切换入口的同时避免按钮在宽屏过大。
- 第 170-175 行：核心状态卡改为 `repeat(auto-fit, minmax(230px, 1fr))`，适配不同宽度。
- 第 217-223 行：主功能区改为稳定的左右布局：
  - 左侧导航 / mission；
  - 右侧 voice / YOLO；
  - 使用明确 `minmax`，避免卡片错位。
- 第 226-229 行：事件区使用稳定 `minmax` 双列结构。
- 第 244-254 行：限制 section header 中 badge 宽度，避免长语音摘要把标题区域撑坏。
- 第 328-342 行：按钮不再默认 `flex: 1` 拉满，语音操作区改成固定上限的三列网格。
- 第 481-506 行：恢复并重新样式化 YOLO 最新识别图像区域。
- 第 508-517 行：`1180px` 以下主功能区与事件区切换为单列，避免中等窄屏左右挤压。
- 第 542-558 行：移动端按钮一列展示，但仅在窄屏生效。
- 第 571-578 行：超宽屏主功能区进一步稳定左右比例。
- 新增 `.detection-event-lines`：视觉事件多行展示，避免文本挤在一行。

### 3. `frontend/src/components/NavMapPlaceholder.vue`

保留 Phase 7B 新增导航占位组件：

- 第 18-23 行：预留 `robotPose`、`goal`、`globalPath`、`navState` props；
- 第 37-80 行：展示导航实时可视化占位、当前位姿、目标点、导航状态、路径点；
- 本阶段仍不接 ROS2 直连、不画真实地图、不新增导航后端逻辑。

### 4. `frontend/src/components/VoiceConfirmDialog.vue`

保留 Phase 7A/7B LLM 移动任务确认能力，并统一为浅色后台风格：

- 第 49-107 行：确认弹窗仍展示识别文本、intent、command、waypoint、confidence、parser/LLM 信息、detail；
- 第 97-103 行：保留“取消任务 / 确认执行”按钮；
- 第 109 行以后：弹窗视觉改为与主 Dashboard 一致的蓝白后台风格。

## 恢复的关键功能

### YOLO 最新识别图像

已恢复：

```text
/api/perception/latest_frame
latestFrameUrl
latestFrameAvailable
latest-frame-box
```

页面中 Perception 卡片会继续显示最新识别画面，不做视频流，不改变后端接口。

### Mock / Real 模式切换

已恢复顶部切换按钮：

```text
切到 Mock
切到 Real
```

仍调用原有逻辑：

```ts
switchMode('mock')
switchMode('real')
```

后端接口路径未改变：

```text
POST /api/system/mode/switch
```

### 响应式布局

已调整：

- 超宽屏：页面最大宽度居中，按钮不再被拉得过大；
- 常规桌面：保持导航左、语音/YOLO 右的演示结构；
- 中等宽度：主功能区切成单列，避免挤压错位；
- 移动端：按钮和卡片自然堆叠。

## 验证记录

已执行：

```bash
cd /home/robomaster/QHXD/frontend
npx vue-tsc --noEmit
npm run build
```

结果：

```text
vue-tsc 通过
vite build 通过
```

构建产物 `frontend/dist` 已恢复，没有把打包文件混入源码修改。

源码检查确认：

```text
frontend/src/App.vue:1103 switchMode('mock')
frontend/src/App.vue:1110 switchMode('real')
frontend/src/App.vue:1288 latest-frame-box
frontend/src/App.vue:1149 NavMapPlaceholder
```

## 未改变内容

- 未修改后端 API；
- 未修改 WebSocket 协议；
- 未修改 mission / voice / LLM / YOLO 业务逻辑；
- 未新增 ROS2 前端直连；
- 未新增视频图传；
- 未整仓迁移外部后台模板；
- 未引入新依赖。

## 当前注意事项

`newcommunication` 是独立子仓/嵌套仓状态，当前仍显示 dirty，本次未触碰。
