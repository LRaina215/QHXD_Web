# Phase 6 Navigation Protocol v1

## 目标

用于 `rtt_nav_bridge` 与 C 板 / RT-Thread 之间的最小导航通信协议，覆盖：

```text
C板 -> RK3588: ODOM / IMU / STAT
RK3588 -> C板: CMD / HB / STOP
```

第一版采用 ASCII 行协议，便于串口助手、日志和人工验收。每帧一行，以 `\n` 结束。

## 坐标系

遵循 ROS REP-103 常用移动机器人坐标：

```text
x: 前方
y: 左方
z: 上方
angular.z: 绕 z 轴逆时针为正
```

默认 TF：

```text
map -> odom -> base_link -> livox_frame
                      -> imu_link
```

## 串口参数

默认参数：

```text
port: /dev/ttyACM0
baudrate: 115200
encoding: utf-8 ASCII
line ending: \n
```

如果实际 USB CDC 设备不同，通过 ROS 参数 `port` 修改。

## C板 -> RK3588

### ODOM 完整帧

```text
ODOM,timestamp_ms,x,y,yaw,vx,vy,wz
```

| 字段 | 单位 | 说明 |
|---|---|---|
| `timestamp_ms` | ms | C 板时间戳 |
| `x` | m | odom 坐标系 x |
| `y` | m | odom 坐标系 y |
| `yaw` | rad | 逆时针为正 |
| `vx` | m/s | base_link x 方向速度，前方为正 |
| `vy` | m/s | base_link y 方向速度，左方为正 |
| `wz` | rad/s | z 轴角速度，逆时针为正 |

推荐频率：30Hz ~ 50Hz。

### ODOM 速度帧

若 C 板暂时不能输出融合位姿，可先输出速度：

```text
ODOM,timestamp_ms,vx,vy,wz
```

此时 RK3588 可在 `integrate_odom=true` 时临时积分 `x/y/yaw`。长期建议 C 板输出完整位姿。

### IMU 四元数帧

```text
IMU,timestamp_ms,qw,qx,qy,qz,gx,gy,gz,ax,ay,az
```

| 字段 | 单位 | 说明 |
|---|---|---|
| `qw/qx/qy/qz` | unit | IMU 姿态四元数 |
| `gx/gy/gz` | rad/s | 角速度 |
| `ax/ay/az` | m/s^2 | 线加速度 |

推荐频率：50Hz ~ 100Hz。

### IMU 欧拉角帧

如果 C 板只能输出欧拉角：

```text
IMU,timestamp_ms,roll,pitch,yaw,gx,gy,gz,ax,ay,az
```

RK3588 会转换为四元数后发布 `/imu/data`。

### STAT 状态帧

```text
STAT,timestamp_ms,mode,battery_mv,estop,fault_code
```

| 字段 | 说明 |
|---|---|
| `mode` | C 板控制模式字符串或数字 |
| `battery_mv` | 电池电压，mV |
| `estop` | 急停状态，0/1 |
| `fault_code` | 故障码，0 表示正常 |

推荐频率：5Hz ~ 10Hz。

## RK3588 -> C板

### CMD 速度命令帧

```text
CMD,timestamp_ms,vx,vy,wz
```

字段来自 ROS2 `/cmd_vel`：

| ROS 字段 | 协议字段 | 单位 |
|---|---|---|
| `linear.x` | `vx` | m/s |
| `linear.y` | `vy` | m/s |
| `angular.z` | `wz` | rad/s |

RK3588 必须先限幅再发送：

```text
max_vx: 0.5 m/s
max_vy: 0.5 m/s
max_wz: 1.0 rad/s
```

真实调车初期建议更保守，例如 `0.15 / 0.15 / 0.3`。

### HB 心跳帧

```text
HB,timestamp_ms
```

推荐频率：10Hz。

### STOP 安全停车帧

```text
STOP,timestamp_ms,reason
```

C 板收到后应立即清零底盘速度。`reason` 建议使用无空格短字符串，例如：

```text
cmd_timeout
bridge_shutdown
serial_error
estop
manual
```

## 安全策略

### RK3588 bridge

1. `/cmd_vel` 超过 `cmd_timeout_ms` 未更新，发送 `CMD,t,0,0,0`，并发送 `STOP,t,cmd_timeout`。
2. 串口未连接时拒绝发送非零速度。
3. `STAT.estop=1` 时拒绝转发非零速度，并发送 0 速度。
4. 所有速度先按 `max_vx/max_vy/max_wz` 限幅。
5. 解析异常帧只增加错误计数，不更新 odom/imu。
6. 节点退出时尽量发送 `STOP,t,bridge_shutdown`。

### C 板

1. 超过 300ms 未收到 `CMD`，底盘速度清零。
2. 超过 500ms 未收到 `HB`，底盘速度清零。
3. 收到 `STOP` 立即停车。
4. 急停优先级高于任何速度命令。
5. C 板本地 PID / 安全闭环保持最高优先级，不被上位机绕过。

## 调试样例

C 板上发：

```text
ODOM,123456,1.20,0.30,0.10,0.05,0.00,0.01
IMU,123456,0.9987,0.0,0.0,0.0500,0.0,0.0,0.01,0.0,0.0,9.81
STAT,123456,auto,24000,0,0
```

RK3588 下发：

```text
CMD,123500,0.10,0.00,0.00
HB,123500
STOP,124000,cmd_timeout
```

## 与当前 0xA5 帧的关系

现有代码已经支持 0xA5 + CRC8 + CRC16 的二进制帧。导航协议字段稳定后，可定义新的 cmd_id：

| cmd_id | 方向 | payload |
|---|---|---|
| `0x1101` | C板 -> RK3588 | Nav ODOM binary payload |
| `0x1102` | C板 -> RK3588 | Nav IMU binary payload |
| `0x1103` | C板 -> RK3588 | Nav STAT binary payload |
| `0x0601` | RK3588 -> C板 | Nav CMD binary payload |
| `0x0602` | RK3588 -> C板 | Nav HB binary payload |
| `0x0603` | RK3588 -> C板 | Nav STOP binary payload |

第一版 ROS2 bridge 默认使用文本协议，后续可在参数 `protocol=binary_v1` 时切换。
