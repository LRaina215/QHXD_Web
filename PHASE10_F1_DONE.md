# Phase 10 F1 完成记录

完成日期：2026-07-06

## 已完成

- Real Mission 已从历史 `nuc_adapter` 切换到独立 Nav2 Mission Executor。
- 新增 `qhxd-nav-mission.service`，开机启用、异常退出自动重启。
- Executor 使用 ROS 2 `NavigateToPose` Action，支持：
  - `go_to_waypoint`
  - `return_home`
  - `start_patrol`
  - `pause_task`
  - `resume_task`
  - `cancel_task`
- pause 定义为取消 Action 并保留上下文；resume 重新发送原目标；cancel 不可恢复。
- 单任务互斥，不允许新目标静默抢占活动任务。
- waypoint 增加 `map_id/pose/group/enabled/configured`，统一用于语音和 Mission。
- 新增 waypoint 唯一性、别名冲突、有限坐标与地图归属校验。
- 新增 `patrol_routes.json`，默认路线依次经过 `wp_001/wp_002/wp_201` 并返航。
- Action feedback 最多 2Hz 回写；地图与位姿仍由既有只读导航桥处理。
- 新增 SQLite `task_events`，生命周期事件持久化并按 event ID 去重；progress 不逐帧落库。
- 新增 API：
  - `GET /api/waypoints`
  - `GET /api/waypoints/{id}`
  - `GET /api/tasks/events`
  - `POST /api/mission/cancel`
  - `POST /api/internal/mission/update`
- Web 任务面板改为后端点位列表，并增加取消任务按钮。
- 微信小程序任务页改为读取 `/api/waypoints`，移除一号/二号点硬编码；正式取消操作改用 `/api/mission/cancel`，不再错误映射为 pause。
- Cloud Gateway 和公网前端已部署上述读取与控制入口。

## 安全边界

- 未修改 `livox_ws`、Point-LIO、AMCL、Nav2 参数或控制器。
- 未修改 `handleBcpChassisOdomFrame`、C 板协议、TF 发布权或 `/cmd_vel` 链路。
- LLM、YOLO 和天气仍不能直接发送 Goal 或速度。
- 点位坐标缺失、地图不一致、定位过期、急停、阻断故障或 Executor 不可用时拒绝任务。
- 当前点位坐标全部为 `null`，不会把假坐标发给 Nav2。
- 公网 `PUBLIC_CONTROL_ENABLED=false` 保持不变。

## 自动验收结果

- Python/JSON/Bash 静态检查通过。
- 原后端回归 27 项通过。
- Phase 10 F1 新增测试 4 项通过：点位校验、未配置点位拒绝、任务事件去重、C 板心跳准入。
- 导航 Web 回归 1 项通过。
- Vue TypeScript 与生产构建通过。
- Cloud Gateway 5 项测试通过。
- 本地与公网 `/api/waypoints` 返回 4 个点位，均明确 `configured=false`。
- Real 模式调用 `wp_001` 返回“目标点尚未配置地图坐标”，未进入 Action。
- 无活动任务时 cancel 被安全拒绝。
- Executor systemd 为 enabled/active；无 Nav2 Server 时 health 正确显示 `action_server_ready=false`。
- Executor 稳态 CPU 实测约 `0~3%` 单核，RSS 约 `35~67MB`。

## C 板恢复后追加验收

- `/serial/imu_backend` 实测约 `19Hz`，publisher 为 `standard_robot_pp_ros2`，subscriber 为 C++ IMU bridge。
- 发现 C++ libcurl 继承 `http_proxy=http://127.0.0.1:7897` 后错误代理本机 backend，已对 `127.0.0.1/localhost/::1` 设置 `CURLOPT_NOPROXY`。
- `/api/imu/latest` 现持续返回 `source=rk3588_cboard_ros2`，时间戳实时刷新。
- 历史 NUC `device_status.online` 不再是当前架构的唯一准入依据；其离线时，Mission 使用已有 C++ bridge 心跳判断 C 板链路，无新增节点或高频轮询。
- 修复了 HTTP 等待 Action accepted 导致的“网页报超时，Goal 仍在后台执行”风险：命令入队后立即返回 pending，Action 结果异步回写。
- ActionClient 改为独立 `ReentrantCallbackGroup` 与 2 线程 executor，避免命令 timer 阻塞 goal/result 回调；稳态内存实测约 `38~67MB`。
- 导航栈稳定后进行一次临时原地目标验收：Mission API `167ms` 返回 accepted/pending，Executor 收敛为 `running -> completed`，Nav2 goal/result 回调分别约 `10ms/105ms`。
- SQLite 已记录同一 task 的 `started -> arrived -> completed`；临时 `wp_001` 坐标已恢复为 `pose=null`，Executor 也已重启回未配置状态。
- 后端回归测试更新为 `32 passed`。

## 备份

```text
/home/robomaster/QHXD_backups/phase10_f1_20260706_183009.tar.gz
```

云端 Gateway 与静态前端部署前也已创建带 `phase10_f1_<timestamp>` 的备份。

## 需要用户完成的现场配置

在 `backend/app/config/waypoints.json` 填写当前 `sentinel_map` 中的真实坐标：

```text
wp_001: x / y / yaw
wp_002: x / y / yaw
wp_201: x / y / yaw
home:   x / y / yaw
```

填写后运行：

```bash
cd /home/robomaster/QHXD
source /opt/ros/humble/setup.bash
source install/setup.bash
source /home/robomaster/livox_ws/install/setup.bash
python3 scripts/nav2_mission_executor.py --check-config
sudo systemctl restart qhxd-nav-mission
```

## 交给用户的实车验收

必须先使能状态安全、场地清空并准备急停。

1. 底盘失能，分别发送 `wp_001/wp_002/wp_201/home`，核对 Goal 坐标、反馈和结果。
2. 底盘失能重复 Goal/Cancel 10 次，确认没有残留 Action。
3. 验证 pause 后 `/cmd_vel` 明确归零，resume 回到原目标，cancel 后不能 resume。
4. 低速使能后测试前进、横移、斜向和带转弯目标。
5. 执行默认巡检，核对每点 arrived、进度、返航和 task events。
6. 放置/移除动态障碍，验证 costmap marking/clearing、停车与绕行。
7. 连续运行 30 分钟，记录 Nav2、TF、Executor、WebSocket、CPU 与内存。
8. 在微信开发者工具和真机确认动态点位、未配置提示、pause/resume/cancel 与公网安全开关。

任何测试中只要 Cancel/失败后未观察到明确零速，立即停止后续使能验收并处理安全停车问题。
