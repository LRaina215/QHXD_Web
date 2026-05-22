# Phase 6 Protocol Review

## 结论摘要

当前链路已经具备“RK3588 与 C 板通过 USB 虚拟串口收发数据”的基础，但它服务的是自瞄/裁判系统数据，不是 ROS2 Nav2 导航闭环。

当前代码可以作为 Phase 6 的串口、帧头、CRC、异步接收参考；但要满足 Nav2，还需要新增导航专用的 `ODOM / IMU / STAT / CMD / HB / STOP` 语义。

## 参考代码

- `transmission/transmission_task.c`
- `transmission/transmission_task.h`
- `timedserial/UartIMU/packet.hpp`
- `timedserial/UartIMU/uart_driver.cpp`
- `timedserial/serial_interface.hpp`

## 当前传输方式

### C 板 / RT-Thread

- 设备：USB 虚拟串口 `vcom`
- 打开方式：`rt_device_find("vcom")` 后 `rt_device_open(vs_port, RT_DEVICE_FLAG_INT_RX)`
- 接收方式：中断回调 `usb_input()` 将数据写入 `rt_ringbuffer`，线程中逐字节 `parse_byte()` 状态机解析
- 发送方式：`rt_device_write(vs_port, 0, frame, total_len)`
- 同时存在 CAN 转发：`Can_send()` 将 `ins_data` 和 `trans_fdb` 的部分字段发到 CAN ID `0x3ff/0x300/0x310/...`

### 上位机 timedserial

- 设备：构造 `UartDriver(device_name)` 时传入端口，例如 `/dev/ttyUSB0` 或 USB CDC 设备
- 波特率：`m_serial.open(m_device_name, 115200)`
- 接收方式：`RMCVSerial` 注册 cmd_id handler 后异步接收
- 发送方式：`m_serial.send(cmd_id, data, len)`

## 当前二进制帧格式

当前新版上下位机协议使用 RoboMaster 裁判系统风格帧：

```text
sof           1 byte   固定 0xA5
data_length   2 bytes  小端，不含 cmd_id 和 CRC
seq           1 byte
crc8          1 byte   对前 4 字节计算，init=0xFF，多项式表见 transmission_task.h
cmd_id        2 bytes  小端
data          N bytes
crc16         2 bytes  对前 total_len-2 字节计算，init=0xFFFF，小端
```

C 板发送函数 `send_frame_to_pc()` 总长度为：

```text
5 byte header + 2 byte cmd_id + data_length + 2 byte crc16
```

解析状态机：

```text
STEP_SOF -> STEP_LEN_LOW -> STEP_LEN_HIGH -> STEP_SEQ -> HEADER_CRC8 -> DATA_CRC16
```

异常处理：

- SOF 不为 `0xA5` 时继续等待；
- `data_len >= 200` 时丢弃；
- CRC8 / CRC16 错误时重置状态机；
- 未知 cmd_id 或长度不匹配时忽略。

## 当前 cmd_id 与数据

### C 板上发 RK3588

| cmd_id | 名称 | payload | 频率 | 当前用途 |
|---|---|---|---|---|
| `0x1021` | `CMD_MCU_DATA` | `pc_mcu_data_t`，17 bytes | 线程内高频发送，代码注释为 1000Hz | yaw/pitch/roll、shoot_speed、autoaim_mode |
| `0x1022` | `CMD_ROBOT_DATA` | `robot_data_t`，33 bytes | 分频约 20Hz | 裁判系统血量、robot_id |

`pc_mcu_data_t` 字段：

```c
float curr_yaw;
float curr_pitch;
float curr_roll;
float shoot_speed;
uint8_t autoaim_mode;
```

`robot_data_t` 字段主要是红蓝双方 HP 与 `robot_id`。

### RK3588 下发 C 板

| cmd_id | 名称 | payload | 当前用途 |
|---|---|---|---|
| `0x0503` | `CMD_GIMBAL_CONTROL` / `GIMAdvv_CMD_ID` | `GBRXTypeDef` / `advv_detection_t`，30 bytes | 自瞄云台目标、角速度、加速度、距离、射击、目标 ID |
| `0x0500` | `CMD_HEARTBEAT` / `STS_CMD_ID` | `HEATTypeDef` / `detection_sts_t`，1 byte | 自瞄状态/心跳模式 |

旧 BCP 帧仍在注释或结构体中保留：

```text
HEAD=0xFF, D_ADDR, ID, LEN, DATA, SC, AC
```

旧协议可表达 `CHASSIS_CTRL`、`CHASSIS_IMU`、`HEARTBEAT` 等功能码，但当前 active 新版解析只处理 `0x0503` 和 `0x0500`。

## 当前链路已有能力

| 能力 | 当前状态 | 备注 |
|---|---|---|
| USB CDC / 串口收发 | 有 | C 板 `vcom`，上位机 115200 |
| 异步接收与环形缓冲 | 有 | RT-Thread 侧已实现 |
| 帧头/长度/CRC | 有 | 0xA5 + CRC8 + CRC16 |
| IMU 姿态上发 | 部分有 | 当前只有 yaw/pitch/roll，不含完整 `/imu/data` 的 gyro/accel/quaternion |
| 裁判/状态上发 | 部分有 | HP、robot_id、autoaim_mode；没有导航 estop/fault/battery 明确定义 |
| 速度下发 | 导航意义上没有 | 当前下发是云台/自瞄控制，不是 chassis `vx/vy/wz` |
| 里程计上发 | 没有 | 没有 x/y/yaw 或 vx/vy/wz 的 nav odom 帧 |
| 心跳 | 部分有 | `0x0500` mode，但不是导航安全心跳规范 |
| 超时停车 | 需要 C 板补齐 | 当前代码未看到导航 CMD/HB 超时停车策略 |
| 急停上发 | 没有明确导航字段 | 需要 `STAT.estop` |

## 与 ROS2 导航接口的缺口

Nav2 / slam_toolbox 需要：

- `/odom`：`nav_msgs/msg/Odometry`
- `odom -> base_link` 动态 TF
- `/imu/data` 或 `/imu/data_raw`：`sensor_msgs/msg/Imu`
- `/cmd_vel`：`geometry_msgs/msg/Twist` 下发到底盘
- 安全策略：cmd_vel 超时、串口断开、bridge 崩溃、C 板急停都必须停车

当前代码缺口：

1. C 板没有上发导航 ODOM 帧。
2. 当前 IMU 上发不包含 `gx/gy/gz/ax/ay/az`，不足以构造完整 `sensor_msgs/msg/Imu`。
3. 当前状态帧不包含 `battery_mv/estop/fault_code`。
4. 当前下发命令不是 `vx/vy/wz`，不能直接对接 `/cmd_vel`。
5. 当前心跳没有定义 C 板“多久没收到 CMD/HB 自动停车”的策略。
6. 当前 timedserial 非 ROS2 节点，不能发布标准 topic / TF。

## Phase 6 采用策略

- 保留现有 0xA5 二进制帧作为 C 板改造参考；
- Phase 6 bridge 第一版实现文本导航协议，便于串口调试和人工验收；
- 文本协议稳定后，可以将同一字段映射回 0xA5 二进制 payload，减少带宽和解析成本；
- ROS2 bridge 不修改 C 板 PID/底盘闭环，只做标准 ROS topic 与 C 板协议转换。
