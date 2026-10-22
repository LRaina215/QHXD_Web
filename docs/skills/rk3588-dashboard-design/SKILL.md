---
name: rk3588-dashboard-design
description: 云拓（yuntuo-fpga 分支）控制台前端的设计规则。改动 frontend/ 的界面前先读。
---

# 云拓控制台设计规则

## 定位

比赛展示与实车联调共用的机器人控制台：评委第一眼要看懂"机器人在做什么、在哪、看到了什么"，操作者要能一键下任务和急停。
不是通用后台模板，也不是大屏动画。

## 视觉语言（frontend/src/style.css 里的令牌）

- 浅色仪器盘：暖白画布 `--canvas` + 白色卡片 `--surface`，层级靠留白、字号和轻阴影，不靠描边和渐变。
- 唯一品牌色 `--brand`（钴蓝 #2f5bff）只用于主操作按钮、当前选中、进度；其他颜色只表达状态。
- 场地图与相机放在深色舞台 `--stage` 上（画面类内容在深底上更清晰），这是页面里唯一的深色区域。
- 状态色语义固定：`ok` 绿（在线 / 完成）、`run` 蓝（执行中）、`wait` 黄（暂停 / 待确认）、`warn` 橙（受阻）、
  `bad` 红（故障 / 急停 / 失败）、`off` 灰（离线 / 未接入）、`mock` 紫灰（模拟）。用 `.tag.<tone>`，不要在组件里自造颜色。
- 字体：Inter Variable（随包打包，离线可用）负责数字与拉丁字符，中文回落系统字体；数值一律 `.num`（等宽数字）。
- 图标：lucide-vue-next（版本锁定），线宽默认，尺寸 16–22。
- 圆角 16 / 12 / 8，按钮高 44（小按钮 34），间距 8 的倍数。

## 信息架构（App.vue 的网格）

1. 头部：品牌、四条链路（RK3588 / FPGA 导航 / FPGA 控制 / 视觉）、模拟 / 实车、Token、时钟、急停。
2. 当前任务横幅 `MissionHero`：任务名用大字号，进度、剩余距离、暂停 / 继续 / 取消 / 返航。
3. 舞台 `StageCard`：场地图（`FieldMap` 画布）与相机二选一做主视图，另一个画中画，左下角速度 / 位姿 / 定位 HUD。
4. 右栏：`CommandCard`（视觉任务 / 定点 / 巡检）+ `VoiceCard`（对话式语音助手）。
5. 下排：`TelemetryCard`（FPGA 平台）、`ObjectsCard`（视觉目标 + 视野俯视图）、`ActivityCard`（动态）。
6. 底部：`ArchitecturePanel` 分层架构（答辩讲解用，链路在线时点亮）。

手机（≤ 960 px）单列；≤ 560 px 头部不再吸顶，急停改为右下角常驻悬浮按钮。

## 不能破坏的功能

- 急停任何时候可见、一键可达；运动类语音命令必须经 `VoiceConfirmDialog` 确认（`/api/voice/confirm_command`）。
- 模拟 / 实车切换（`/api/system/mode/switch`）、任务接口 `/api/mission/*`、急停 `/api/platform/estop`。
- 智能语音：文字 `/api/voice/smart_command`、网页麦克风 `/api/voice/browser_smart_command`（云端网关转码）、
  车载麦克风 `/api/robot/voice/onboard_smart_command`。
- 实时数据走 `/ws/state`、`/ws/navigation`；状态 / 告警 / 任务事件有 HTTP 兜底轮询。
- 视频：`CloudVideoPlayer`（公网 WebRTC → HLS → 本机 MJPEG 回退），不要改它的会话与回退逻辑。
- 不改后端接口路径、WS 协议和任务 / 语音 / LLM 安全行为；纯视觉改动只动 frontend/。

## 自检

- 1600×1000、1366×768、390×844 三种宽度截图：无横向滚动、无文字重叠、首屏能看到任务横幅与舞台。
- 后端 + `scripts/start_yuntuo_sim.sh` 跑起来后，"寻找红色水瓶"从输入到确认到完成全流程走一遍。
- `npm run build`（含 vue-tsc 类型检查）通过。
