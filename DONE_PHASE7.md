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


---

# Phase 7C - 项目级前端设计规范与 Dashboard 重设计

## 使用的前端设计 Skill

本轮按用户要求参考并落实两个前端设计 Skill：

- `frontend-design`：确定本轮设计方向为清爽、克制、适合机器人中台答辩展示的技术控制台，而不是通用后台模板或炫酷大屏。
- `ui-design-brain`：采用 Header、Card、Badge、Button group、Modal、Alert/List、Empty state 等组件模式，统一状态色、按钮层级、卡片层级和响应式断点。

## UI 审计结果

改代码前对当前 Dashboard 做了审计，主要问题如下：

- 页面虽然已经恢复 YOLO 最新图像、Mock/Real 切换和导航占位，但整体仍偏调试面板堆叠，比赛答辩时第一眼的系统态势不够明确。
- 顶部状态栏承担了过多信息，但模式、NUC、RK3588、告警、时间的视觉权重没有形成稳定“指挥栏”。
- 核心状态卡片信息完整，但任务、链路、电量/急停、感知、告警没有形成固定的 readiness strip。
- 语音/LLM 卡片功能完整，但 recognized_text、intent、waypoint_id、need_confirm/pending_command_id 的层级还可以更清楚。
- YOLO 卡片保留了 `/api/perception/latest_frame`，但检测事件和对象列表需要更像状态列表而不是散字段。
- 导航预留区存在，但需要更突出“未来 NavMapCanvas 替换位”和当前 pose/goal/navState。
- 响应式布局已有基础，但宽屏和窄屏仍需要更明确的 grid track，避免按钮和状态 badge 在极端宽度下撑坏。

必须保留且本轮未删除的功能：Mock/Real 切换、mission 控制、板端录音、文本命令、LLM 移动确认弹窗、YOLO 最新图像/状态、导航占位、事件/告警、WebSocket 状态展示。

## 设计改造方案

页面结构调整为：

```text
顶部：command header
  - 系统名称、RK3588 中台定位
  - Mock/Real、NUC、RK3588、告警、时间
  - Mock / Real 切换按钮

第一行：readiness strip
  - 当前任务
  - 机器人链路
  - 电量 / 急停 / 故障
  - 感知状态
  - 最近告警

主区域：operations grid
  - 左侧：导航实时可视化预留区 + mission 快捷控制
  - 右侧：语音/LLM 任务入口 + YOLO 检测状态

底部：observability
  - 最近事件
  - IMU / 环境 / 故障运行信息
```

本轮只做 UI 与文档重构，不改后端 API、不改 WebSocket、不接真实 ROS2 地图、不新增浏览器麦克风、不新增视频流业务逻辑。

## 本次修改文件

### 1. `docs/skills/rk3588-dashboard-design/SKILL.md`

新增项目级前端设计规范：

- 第 1-3 行：定义 `rk3588-dashboard-design` Skill 元信息。
- 第 8-12 行：明确项目定位是 RK3588 车载机器人业务中台，目标是比赛答辩展示 + 实际联调操作。
- 第 14-29 行：列出不可破坏功能，包括 Mock/Real、NUC/RK3588、mission、板端录音、LLM 确认、YOLO、导航占位。
- 第 31-41 行：固定 Dashboard 信息架构。
- 第 55-68 行：统一状态颜色规范。
- 第 80-99 行：固定导航预留区规则与未来 `NavMapCanvas` 替换边界。
- 第 101-111 行：固定移动类任务确认安全规则。
- 第 113-124 行：新增每次前端修改后的自检清单。

### 2. `frontend/src/App.vue`

关键改动：

- 第 305-312 行：修正电量为空时显示 `--`，避免 UI 出现 `null%`。
- 第 1086-1127 行：重构顶部为 `command-header`，集中展示系统名、Mock/Real、NUC、RK3588、告警、时间，并保留 `switchMode('mock')` / `switchMode('real')`。
- 第 1129-1176 行：新增 `readiness-strip` 核心状态带，第一屏即可看到任务、链路、电量/急停、感知、最近告警。
- 第 1178-1235 行：重排主操作区左侧，保留 `NavMapPlaceholder` 和全部 mission API 入口。
- 第 1239-1322 行：重排语音/LLM 卡片，保留文本命令、板端录音 `/api/voice/record_command`，强化 recognized_text、ASR、intent、waypoint_id、accepted/need_confirm、pending_command_id、LLM 模型显示。
- 第 1333-1399 行：保留 YOLO 最新图像 `/api/perception/latest_frame`，优化 detection_status、对象列表和视觉事件展示。
- 第 1403 行以后：保留最近事件与运行信息区域，继续聚合 voice / LLM / YOLO / mission / alerts。
- 第 632 行：确认流仍调用 `/api/voice/confirm_command`。
- 第 964 行：板端录音仍调用 `/api/voice/record_command`。

### 3. `frontend/src/style.css`

关键改动：

- 第 1-47 行：建立项目级 CSS 变量、蓝白科技风色板、统一字体与背景。
- 第 50-97 行：统一 `command-header`、panel、metric card 的卡片边界、阴影和顶部状态栏布局。
- 第 122-184 行：统一 `status-badge` / `tone-*` 状态色。
- 第 198-249 行：实现 readiness strip 与核心状态卡样式。
- 第 256-277 行：实现 operations grid 与底部 event grid 的稳定左右布局。
- 第 294-387 行：统一表单、按钮、按钮组、focus、hover 和 44px 操作目标。
- 第 389-474 行：统一语音结果详情、状态提示、错误/等待状态。
- 第 477-526 行：保留并优化 YOLO 最新图像区域。
- 第 528-613 行：优化对象 pill、mini event、事件列表和空状态。
- 第 615-727 行：新增 1380px、1120px、820px、460px、1580px 响应式断点，避免宽屏/窄屏错位和按钮异常拉伸。

### 4. `frontend/src/components/NavMapPlaceholder.vue`

关键改动：

- 第 1-35 行：保留 `robotPose`、`goal`、`globalPath`、`navState` props，方便后续替换为 `NavMapCanvas`。
- 第 37-87 行：强化导航实时可视化占位区，显示当前位姿、Frame、当前目标点、导航状态、路径点。
- 第 94-224 行：重做地图占位视觉，保留“等待接入 NUC 导航实时流”的明确提示，不直连 ROS2 话题。

### 5. `frontend/src/components/VoiceConfirmDialog.vue`

关键改动：

- 第 49-107 行：保留移动任务确认弹窗结构，继续展示识别文本、intent、command、waypoint、confidence、parser/LLM、detail。
- 第 97-103 行：保留“取消任务 / 确认执行”按钮，对应原有 confirm/cancel emit。
- 第 109 行以后：重做弹窗视觉，突出橙色风险边界、风险说明、错误提示和 44px 操作按钮。

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

启动验证：

```bash
./scripts/start_backend.sh
./scripts/start_frontend.sh
curl --noproxy '*' http://127.0.0.1:8000/health
curl --noproxy '*' -I http://127.0.0.1:5173/
```

结果：

```text
backend /health 返回 {"status":"ok"}
frontend Vite 首页返回 HTTP/1.1 200 OK
```

构建后已恢复 `frontend/dist`，未把打包产物混入源码改动。

## 未改变内容

- 未修改后端 API 路径；
- 未修改 WebSocket 协议；
- 未修改 mission / voice / LLM / YOLO / navigation 业务逻辑；
- 未新增浏览器麦克风录音；
- 未新增视频流业务逻辑；
- 未接 ROS2 话题；
- 未迁移外部后台模板；
- 未引入新依赖。

## 当前回归结论

Phase 7C 本轮前端已满足：

- 项目级前端设计 Skill 已建立；
- Dashboard 信息架构改为机器人中台结构；
- Mock/Real、任务、语音、LLM 确认、YOLO、告警、导航预留区全部保留；
- 样式层加入统一状态色和多断点响应式约束；
- 类型检查和生产构建通过。

---

# Phase 7C 设计返工 - Sentinel Mission Deck

## 返工原因

用户反馈上一版前端仍然太丑，并明确要求本轮不再遵循 `DO_PHASE7C.md` 中的清爽蓝白风格限制，而是按照 `frontend-design` 与 `ui-design-brain` 两个前端设计 skill 发挥设计能力。

本轮重新确定视觉方向为：

```text
Sentinel Mission Deck
```

目标是让 Dashboard 更像比赛现场可展示的机器人任务指挥台，而不是普通表单后台。视觉关键词：近黑指挥栏、象牙白仪表卡片、安全橙、电气蓝、状态绿、地图雷达感、紧凑但有层级的信息密度。

## 本轮设计原则

- 保留所有现有功能入口，不改业务逻辑。
- 用强视觉顶部 command header 建立第一眼记忆点。
- 使用更鲜明的任务台色彩系统，而不是普通蓝白后台。
- 继续遵守 `ui-design-brain` 的组件规则：Header、Card、Badge、Button group、Modal、Alert/List、Empty state。
- 继续保证按钮 44px 操作目标、状态 badge 语义色、长文本换行、响应式断点。

## 本次修改文件

### 1. `frontend/src/style.css`

关键改动：

- 第 1-25 行：重建全局视觉 token，改为象牙白 / 近黑 / 安全橙 / 电气蓝 / 状态绿的任务台配色。
- 第 29-46 行：新增带网格纹理的页面背景，避免普通纯色后台感。
- 第 60-107 行：把顶部重做为深色 `command-header`，加入 `SENTINEL / RK3588` 巨型低对比字标和左侧状态色条。
- 第 216-223 行：让顶部状态 badge 在深色 header 中统一为半透明仪表胶囊。
- 第 309-373 行：重做 readiness strip 核心状态卡，加入侧边语义色和仪表刻度装饰。
- 第 383-401 行：保留 operations grid / event grid，但调整比例与间距，使页面更像指挥台布局。
- 第 613-656 行：重做 YOLO 最新图像框，增加 `LIVE FRAME` 角标和黑色画面容器。
- 第 758-879 行：保留多断点响应式约束，确保宽屏、平板、小屏不会把按钮或 badge 撑坏。

### 2. `frontend/src/components/NavMapPlaceholder.vue`

关键改动：

- 第 47-63 行：新增雷达环、深色导航画布、路径线、机器人 marker、目标 marker、`NUC NAV STREAM RESERVED` 提示。
- 第 96-172 行：导航占位区改为深色地图仪表视觉。
- 第 175-211 行：机器人与目标点 marker 改成更清晰的任务台视觉符号。
- 第 213-239 行：保留未来 `NavMapCanvas` 替换提示，并明确当前不直连 ROS2 话题。

### 3. `frontend/src/components/VoiceConfirmDialog.vue`

关键改动：

- 第 123-135 行：确认弹窗改为带安全橙边界的任务确认面板。
- 第 174-189 行：风险提示和错误提示改为高对比但不刺眼的安全信息块。
- 第 234-252 行：确认按钮改为安全橙主按钮，取消按钮为象牙白次按钮。

## 保留的功能

本轮没有改动以下业务调用：

```text
/api/state/latest
/api/alerts
/ws/state
/ws/imu
/api/voice/text_command
/api/voice/record_command
/api/voice/confirm_command
/api/perception/latest_frame
/api/system/mode/switch
/api/mission/go_to_waypoint
/api/mission/pause
/api/mission/resume
/api/mission/return_home
```

仍保留：

- Mock / Real 切换；
- mission 快捷控制；
- 文本命令；
- RK3588 板端录音；
- LLM 移动任务确认弹窗；
- YOLO 最新图像与 detection_status；
- 导航可视化预留区；
- 事件列表与运行状态。

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

服务验证：

```bash
curl --noproxy '*' http://127.0.0.1:8000/health
curl --noproxy '*' -I http://127.0.0.1:5173/
```

结果：

```text
backend /health 返回 {"status":"ok"}
frontend 返回 HTTP/1.1 200 OK
```

当前运行进程：

```text
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
vite --host 0.0.0.0 --port 5173
```

构建产物 `frontend/dist` 已恢复，未纳入源码改动。

---

# Phase 7C 排版修复 - 解决左右列高度错位

## 问题

用户截图指出当前页面的主要问题不是功能缺失，而是排版错位：左侧导航与 Mission 控制区域较短，右侧 Voice / YOLO 区域较高，导致 Mission 下方出现大面积空白，页面像两列独立堆叠的内容柱，而不是一个整体 Dashboard。

## 修复思路

原布局是：

```text
operations-grid
  left stack: Nav + Mission
  right stack: Voice + YOLO
```

这种结构会被右侧 YOLO 卡片高度撑开，左侧无法自然回填。现改为让四个模块进入同一个 CSS grid：

```text
nav      voice
nav      yolo
mission  yolo
```

同时压缩导航占位区和 YOLO 最新画面高度，避免单个视觉模块无意义撑高页面。

## 修改文件

### `frontend/src/style.css`

- 新增 `grid-template-areas`，将 Nav / Mission / Voice / YOLO 放入同一个 Dashboard grid。
- 将 `.operations-primary` 与 `.operations-secondary` 改为 `display: contents`，避免嵌套栈阻止子模块参与主网格排版。
- 为 `.nav-map`、`.mission-panel`、`.voice-panel`、`.perception-panel` 分配明确 grid area。
- 将 YOLO `latest-frame-box` 从 `16 / 9` 调整为更扁的 `21 / 9`，并设置 `max-height`，减少右侧卡片过高造成的左侧空洞。
- 在 `1120px` 以下恢复单列顺序：Nav -> Mission -> Voice -> YOLO，保证窄屏不乱。
- 在宽屏断点同步调整 `operations-grid` 与 `event-grid`，让上下区域宽度对齐。

### `frontend/src/components/NavMapPlaceholder.vue`

- 将导航画布高度从 `clamp(330px, 34vw, 500px)` 调整为 `clamp(260px, 26vw, 380px)`。
- 保留导航占位视觉、机器人 marker、目标 marker、路径线和 NUC 流预留提示。

## 验证

已执行：

```bash
cd /home/robomaster/QHXD/frontend
npx vue-tsc --noEmit
npm run build
curl --noproxy '*' -I http://127.0.0.1:5173/
```

结果：

```text
vue-tsc 通过
vite build 通过
frontend 返回 HTTP/1.1 200 OK
```

构建产物 `frontend/dist` 已恢复，未纳入源码改动。

---

# Phase 7C 导航卡片留白修复 - 增加导航联调态势区

## 问题

用户指出导航卡片内部仍有较多空白。这个空白不是单纯样式问题，而是导航卡片目前只显示地图占位和少量基础指标；在左侧区域被主 Dashboard grid 拉高后，卡片内部信息密度不足。

## 处理方案

没有新增后端接口，也没有接 ROS2 前端直连。本轮只基于 `NavMapPlaceholder.vue` 已有 props 派生展示：

```text
robotPose
goal
globalPath
navState
```

新增“导航联调态势区”，用于填充空白并提升联调价值。

## 修改文件

### `frontend/src/components/NavMapPlaceholder.vue`

新增派生信息：

- `headingDegLabel`：由 `robotPose.yaw` 换算为 0~360 度朝向角。
- `originDistanceLabel`：由 `robotPose.x/y` 计算离原点距离。
- `goalDistanceLabel`：如果后续 goal 提供 x/y，则计算目标距离；否则显示“等待目标坐标”。
- `readinessItems`：聚合位姿输入、目标锁定、路径缓存、导航状态。

新增 UI 区域：

- 基础指标从 5 项扩展到 8 项：当前位姿、Frame、目标点、导航状态、路径点、朝向角、离原点距离、目标距离。
- 新增 `Navigation readiness / 接入态势` 面板。
- 新增 4 个 readiness 卡片：位姿输入、目标锁定、路径缓存、导航状态。
- 新增 handoff list：Pose、Path、Safety 三项接入说明，明确当前状态和下一步 NavMapCanvas 替换方向。

## 验证

已执行：

```bash
cd /home/robomaster/QHXD/frontend
npx vue-tsc --noEmit
npm run build
curl --noproxy '*' -I http://127.0.0.1:5173/
```

结果：

```text
vue-tsc 通过
vite build 通过
frontend 返回 HTTP/1.1 200 OK
```

构建产物 `frontend/dist` 已恢复，未纳入源码改动。
