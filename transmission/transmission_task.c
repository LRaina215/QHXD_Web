/*
* Change Logs:
* Date            Author          Notes
* 2023-10-09      ChenSihan     first version
* 2023-12-09      YangShuo     USB虚拟串口
*/

#include "transmission_task.h"
#include "drv_gpio.h"

#define DBG_TAG   "rm.task"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>
#define HEART_BEAT 500 //ms
/* -------------------------------- 线程间通讯话题相关 ------------------------------- */
static struct gimbal_cmd_msg gim_cmd;
static struct ins_msg ins_data;
static struct gimbal_fdb_msg gim_fdb;
static struct referee_fdb_msg referee_fdb; // 裁判系统数据
struct trans_fdb_msg trans_fdb; //和djimotor通讯用
/*------------------------------传输数据相关 --------------------------------- */
#define RECV_BUFFER_SIZE 64  // 接收环形缓冲区大小
rt_uint8_t r_buffer[RECV_BUFFER_SIZE];  // 接收环形缓冲区
rt_uint8_t *r_buffer_point; //用于清除环形缓冲区buffer的指针
struct rt_ringbuffer receive_buffer ; // 环形缓冲区对象控制块指针
rt_uint8_t buf[31] = {0};
RpyTypeDef rpy_tx_data={
        .HEAD = 0XFF,
        .D_ADDR = MAINFLOD,
        .ID = GIMBAL,
        .LEN = FRAME_RPY_LEN,
        .DATA={0},
        .SC = 0,
        .AC = 0,
};
RpyTypeDef rpy_rx_data; //接收解析结构体

//新增接收结构体

GBRXTypeDef     gimbal_rx_date;
HEATTypeDef     heart_rx_data;


static rt_uint32_t heart_dt;
static struct rt_can_msg send_msg[6] = {
        [0] = {.id = 0x3ff, .ide  = RT_CAN_STDID, .rtr = RT_CAN_DTR, .len  = 0x08, .data = {0}},
        [1] = {.id = 0x300, .ide  = RT_CAN_STDID, .rtr = RT_CAN_DTR, .len  = 0x08, .data = {0}},
        [2] = {.id = 0x310, .ide  = RT_CAN_STDID, .rtr = RT_CAN_DTR, .len  = 0x08, .data = {0}},
        [3] = {.id = 0x320, .ide  = RT_CAN_STDID, .rtr = RT_CAN_DTR, .len  = 0x08, .data = {0}},
        [4] = {.id = 0x330, .ide  = RT_CAN_STDID, .rtr = RT_CAN_DTR, .len  = 0x08, .data = {0}},
        [5] = {.id = 0x340, .ide  = RT_CAN_STDID, .rtr = RT_CAN_DTR, .len  = 0x08, .data = {0}},
};
/* ---------------------------------usb虚拟串口数据相关 --------------------------------- */
static rt_device_t vs_port = RT_NULL;
/* -------------------------------- 线程间通讯话题相关 ------------------------------- */
static publisher_t *pub_trans;
static subscriber_t *sub_cmd,*sub_ins,*sub_gim,*sub_refer;
static void trans_sub_pull(void);
static void trans_pub_push(void);
static void trans_sub_init(void);
static void trans_pub_init(void);
/* -------------------------------- can通讯相关 ------------------------------- */
static rt_device_t gimbal_can = RT_NULL;
static void Can_send(float data1_original,float data2_original,struct rt_can_msg data_send);
/**
 * @brief trans 线程中所有订阅者初始化（如有其它数据需求可在其中添加）
 */
static void trans_sub_init(void)
{
    sub_cmd = sub_register("gim_cmd", sizeof(struct gimbal_cmd_msg));
    sub_ins = sub_register("ins_msg", sizeof(struct ins_msg));
    sub_gim = sub_register("gim_fdb", sizeof(struct gimbal_fdb_msg));
    sub_refer = sub_register("referee_fdb", sizeof(struct referee_fdb_msg));
}

/**
 * @brief trans 线程中所有订阅者获取更新话题（如有其它数据需求可在其中添加）
 */
static void trans_sub_pull(void)
{
    sub_get_msg(sub_cmd, &gim_cmd);
    sub_get_msg(sub_ins, &ins_data);
    sub_get_msg(sub_gim, &gim_fdb);
    sub_get_msg(sub_refer, &referee_fdb);
}

/**
 * @brief cmd 线程中所有发布者初始化
 */
static void trans_pub_init(void)
{
    pub_trans = pub_register("trans_fdb",sizeof(struct trans_fdb_msg));
}

/**
 * @brief cmd 线程中所有发布者推送更新话题
 */
static void trans_pub_push(void)
{
    pub_push_msg(pub_trans,&trans_fdb);
}

/* --------------------------------- 通讯线程入口 --------------------------------- */
static float trans_dt;

void transmission_task_entry(void* argument)
{
    static float trans_start;
    static float heart_start;

    /*订阅数据初始化*/
    trans_sub_init();
    /*发布数据初始化*/
    trans_pub_init();
    /* step1：查找名为 "vcom" 的虚拟串口设备*/
    vs_port = rt_device_find("vcom");
    /* step2：打开串口设备。以中断接收及轮询发送模式打开串口设备*/
    if (vs_port)
        rt_device_open(vs_port, RT_DEVICE_FLAG_INT_RX);
    /*环形缓冲区初始化*/
    rt_ringbuffer_init(&receive_buffer, r_buffer, RECV_BUFFER_SIZE);
    /*清除buffer的指针赋地址*/
    r_buffer_point=r_buffer;
    /* 设置接收回调函数 */
    rt_device_set_rx_indicate(vs_port, usb_input);
    gimbal_can = rt_device_find(CAN_GIMBAL);
    LOG_I("Transmission Task Start");
    while (1)
    {
        trans_start = dwt_get_time_ms();
        /*订阅数据更新*/
        trans_sub_pull();
        /* ==================================================
           【新增】在线程中解析接收到的上位机数据
           ================================================== */
        uint8_t byte;
        // 只要环形缓冲区有数据，就在线程级别去消耗和解析，不占用中断时间
        while (rt_ringbuffer_getchar(&receive_buffer, (char*)&byte) == 1) {
            parse_byte(byte);
        }
/*--------------------------------------------------具体需要发送的数据--------------------------------- */
        // if((dwt_get_time_ms()-heart_dt)>=HEART_BEAT)
        // {
        //     rt_device_close(vs_port);
        //     rt_device_open(vs_port, RT_DEVICE_FLAG_INT_RX);
        //     heart_dt=dwt_get_time_ms();
        // }
        // Send_to_pc(rpy_tx_data);
            Send_to_pc_new();
#ifndef BSP_USING_GIMBAL_CAN_RECEIVE
        Can_send(ins_data.gyro[2],ins_data.yaw_total_angle,send_msg[0]);
        Can_send(trans_fdb.angular_x,trans_fdb.angular_y,send_msg[1]);
        Can_send(trans_fdb.angular_z,trans_fdb.linear_x,send_msg[2]);
        Can_send(trans_fdb.linear_y,trans_fdb.linear_z,send_msg[3]);

#endif /* BSP_USING_GIMBAL_CAN_RECEIVE */
/*--------------------------------------------------具体需要发送的数据---------------------------------*/
        /* 发布数据更新 */
        trans_pub_push();
        /* 用于调试监测线程调度使用 */
        trans_dt = dwt_get_time_ms() - trans_start;
        if (trans_dt > 1)
                LOG_E("Transmission Task is being DELAY! dt = [%f]", &trans_dt);
        rt_thread_mdelay(1);
    }
}

// void Send_to_pc(RpyTypeDef data_r)
// {
//     // ==========================================
//     // 1. 发送云台姿态 (原样保持，高频 1000Hz 发送保证 IMU 丝滑)
//     // ==========================================
//     pack_Rpy(&data_r, (gim_fdb.yaw_offset_angle - ins_data.yaw), (ins_data.pitch), ins_data.roll);
//     Check_Rpy(&data_r);
//     rt_device_write(vs_port, 0, (uint8_t*)&data_r, sizeof(data_r));
//
//     // ==========================================
//     // 引入静态分频计数器，降低低频数据的发送速率
//     // 1000Hz / 100 = 10Hz
//     // ==========================================
//     static uint16_t send_cnt = 0;
//     send_cnt++;
//     if (send_cnt >= 100)
//     {
//         send_cnt = 0; // 重置计数器
//
//         // ==========================================
//         // 2. 发送哨兵姿态数据 (降频至 10Hz)
//         // ==========================================
//         uint8_t pose_buf[7] = {0};
//         pose_buf[0] = 0xFF;
//         pose_buf[1] = 0x01;
//         pose_buf[2] = 0x06;
//         pose_buf[3] = 0x01;
//
//         uint8_t sentry_pose = (referee_fdb.sentry_info.sentry_info_2 >> 12) & 0x03;
//         pose_buf[4] = sentry_pose;
//
//         uint8_t sum_p = 0, add_p = 0;
//         for(int i = 0; i < 5; i++) {
//             sum_p += pose_buf[i];
//             add_p += sum_p;
//         }
//         pose_buf[5] = sum_p;
//         pose_buf[6] = add_p;
//
//         rt_device_write(vs_port, 0, pose_buf, 7);
//
//
//         // ==========================================
//         // 3. 发送机器人血量数据 (降频至 10Hz，大幅节省算力)
//         // ==========================================
//         uint8_t hp_buf[38] = {0};
//         hp_buf[0] = 0xFF;
//         hp_buf[1] = 0x01;
//         hp_buf[2] = 0x31;
//         hp_buf[3] = 32;
//
//         // 取出真实的 uint16_t 血量 (如果是测试，就改成 100)
//         uint16_t red_hp = referee_fdb.game_robot_HP.red_7_robot_HP;
//         uint16_t blue_hp = referee_fdb.game_robot_HP.blue_7_robot_HP;
//
//         hp_buf[14] = red_hp & 0xFF;
//         hp_buf[15] = (red_hp >> 8) & 0xFF;
//
//         hp_buf[30] = blue_hp & 0xFF;
//         hp_buf[31] = (blue_hp >> 8) & 0xFF;
//
//         uint8_t sum_h = 0, add_h = 0;
//         for(int i = 0; i < 36; i++) {
//             sum_h += hp_buf[i];
//             add_h += sum_h;
//         }
//         hp_buf[36] = sum_h;
//         hp_buf[37] = add_h;
//
//         rt_device_write(vs_port, 0, hp_buf, 38);
//     }
// }


// 通用发送函数：打包并发送一帧
// 参数：cmd_id - 命令ID（0x1021, 0x1022）
//      data - 数据指针
//      len  - 数据长度（字节）
// 返回值：RT-Thread 设备写入的字节数，-1 表示错误
static int send_frame_to_pc(uint16_t cmd_id, const uint8_t *data, uint16_t len)
{
    // 计算总帧长度：头(sof 1 + len 2 + seq 1 + crc8 1) + cmd_id 2 + data + crc16 2
    uint16_t total_len = 5 + 2 + len + 2;
    if (total_len > 256) return -1;  // 缓冲区限制

    uint8_t frame[256];
    uint8_t *ptr = frame;

    // 1. 帧头
    *ptr++ = 0xA5;                       // sof
    *ptr++ = (uint8_t)(len & 0xFF);      // data_length 低字节
    *ptr++ = (uint8_t)((len >> 8) & 0xFF); // data_length 高字节
    *ptr++ = 0;                          // seq (可自行维护序列号，本例固定0)
    // CRC8 占位，稍后计算
    ptr++;  // 跳过 CRC8 位置

    // 2. 命令ID（小端）
    *ptr++ = (uint8_t)(cmd_id & 0xFF);
    *ptr++ = (uint8_t)((cmd_id >> 8) & 0xFF);

    // 3. 数据
    memcpy(ptr, data, len);
    ptr += len;

    // 4. 计算 CRC8（仅对前4字节：sof, data_length低, data_length高, seq）
    uint8_t crc8 = generate_crc8_checksum(frame, 4, 0xFF);
    frame[4] = crc8;  // 填入

    // 5. 计算 CRC16（对整个帧，不包括末尾2字节的 CRC16）
    uint16_t crc16 = generate_crc16_checksum(frame, total_len - 2, 0xFFFF);
    frame[total_len - 2] = (uint8_t)(crc16 & 0xFF);      // 低字节在前
    frame[total_len - 1] = (uint8_t)((crc16 >> 8) & 0xFF);

    // 6. 通过串口发送（vs_port 是全局串口设备，原代码中使用）
    return rt_device_write(vs_port, 0, frame, total_len);
}

static void send_imu_data_to_pc(const pc_mcu_data_t *data)
{
    send_frame_to_pc(0x1021, (const uint8_t*)data, sizeof(pc_mcu_data_t));
}

static void send_robot_data_to_pc(const robot_data_t *data)
{
    send_frame_to_pc(0x1022, (const uint8_t*)data, sizeof(robot_data_t));
}


void Send_to_pc_new(void)
{
    // ==========================================
    // 1. 发送 IMU 姿态数据（高频 1000Hz，每帧都发）
    // ==========================================
    // 假设 gim_fdb 和 ins_data 是全局变量
    pc_mcu_data_t imu_data;
    imu_data.curr_yaw   = gim_fdb.yaw_offset_angle - ins_data.yaw;  // 根据你的计算
    imu_data.curr_pitch = ins_data.pitch;
    imu_data.curr_roll  = ins_data.roll;
    imu_data.shoot_speed = referee_fdb.shoot_data.initial_speed ;                // 目前还没有
    imu_data.autoaim_mode = gim_cmd.autoaim_mode;               //

    send_imu_data_to_pc(&imu_data);  // 高频发送

    // ==========================================
    // 2. 引入分频计数器，将血量数据降频至 10Hz - 20Hz
    // ==========================================
    static uint16_t robot_send_cnt = 0;
    robot_send_cnt++;

    if (robot_send_cnt >= 50) // 1000Hz / 50 = 20Hz (每50ms发送一次)
    {
        robot_send_cnt = 0; // 清零计数器

        robot_data_t robot = {0};
        // 从 referee_fdb 中复制血量数据
        robot.red_1_robot_HP   = referee_fdb.game_robot_HP.red_1_robot_HP;
        robot.red_2_robot_HP   = referee_fdb.game_robot_HP.red_2_robot_HP;
        robot.red_3_robot_HP   = referee_fdb.game_robot_HP.red_3_robot_HP;
        robot.red_4_robot_HP   = referee_fdb.game_robot_HP.red_4_robot_HP;
        robot.red_5_robot_HP   = referee_fdb.game_robot_HP.red_5_robot_HP;
        robot.red_7_robot_HP   = referee_fdb.game_robot_HP.red_7_robot_HP;
        robot.red_outpost_HP    = referee_fdb.game_robot_HP.red_outpost_HP;
        robot.red_base_HP       = referee_fdb.game_robot_HP.red_base_HP;
        robot.blue_1_robot_HP   = referee_fdb.game_robot_HP.blue_1_robot_HP;
        robot.blue_2_robot_HP   = referee_fdb.game_robot_HP.blue_2_robot_HP;
        robot.blue_3_robot_HP   = referee_fdb.game_robot_HP.blue_3_robot_HP;
        robot.blue_4_robot_HP   = referee_fdb.game_robot_HP.blue_4_robot_HP;
        robot.blue_5_robot_HP   = referee_fdb.game_robot_HP.blue_5_robot_HP;
        robot.blue_7_robot_HP   = referee_fdb.game_robot_HP.blue_7_robot_HP;
        robot.blue_outpost_HP    = referee_fdb.game_robot_HP.blue_outpost_HP;
        robot.blue_base_HP       = referee_fdb.game_robot_HP.blue_base_HP;
        robot.robot_id           = 200;   //referee_fdb.robot_status.robot_id;  // 根据实际情况

        send_robot_data_to_pc(&robot);
    }
}


void pack_Rpy(RpyTypeDef *frame, float yaw, float pitch,float roll)
{
    int8_t rpy_tx_buffer[FRAME_RPY_LEN] = {0} ;
    int32_t rpy_data = 0;
    uint32_t *gimbal_rpy = (uint32_t *)&rpy_data;

    rpy_tx_buffer[0] = 0;
    rpy_data = yaw * 1000;
    rpy_tx_buffer[1] = *gimbal_rpy;
    rpy_tx_buffer[2] = *gimbal_rpy >> 8;
    rpy_tx_buffer[3] = *gimbal_rpy >> 16;
    rpy_tx_buffer[4] = *gimbal_rpy >> 24;
    rpy_data = pitch * 1000;
    rpy_tx_buffer[5] = *gimbal_rpy;
    rpy_tx_buffer[6] = *gimbal_rpy >> 8;
    rpy_tx_buffer[7] = *gimbal_rpy >> 16;
    rpy_tx_buffer[8] = *gimbal_rpy >> 24;
    rpy_data = roll *1000;
    rpy_tx_buffer[9] = *gimbal_rpy;
    rpy_tx_buffer[10] = *gimbal_rpy >> 8;
    rpy_tx_buffer[11] = *gimbal_rpy >> 16;
    rpy_tx_buffer[12] = *gimbal_rpy >> 24;

    memcpy(&frame->DATA[0], rpy_tx_buffer,13);

    frame->LEN = FRAME_RPY_LEN;
}

void Check_Rpy(RpyTypeDef *frame)           //协议进行了一定的更改
{
    uint8_t sum = 0;
    uint8_t add = 0;

    sum += frame->HEAD;
    add += sum;
    sum += frame->D_ADDR;
    add += sum;
    sum += frame->ID;
    add += sum;
    sum += frame->LEN;
    add += sum;

    for (int i = 0; i < frame->LEN; i++)
    {
        sum += frame->DATA[i];
        add += sum;
    }

    frame->SC = sum & 0xFF;
    frame->AC = add & 0xFF;
}

// 串口接收到数据后产生中断，调用此回调函数
// static rt_err_t usb_input(rt_device_t dev, rt_size_t size)
// {
//     memset(buf, 0, sizeof(buf));
//
//     // 从串口读取数据并保存到环形接收缓冲区
//     rt_uint32_t rx_length;
//     while ((rx_length = rt_device_read(vs_port, 0, buf, sizeof(buf))) > 0)
//     {
//         // 将接收到的数据放入环形缓冲区
//         rt_ringbuffer_put_force(&receive_buffer, buf, rx_length);
//     }
//     rt_uint8_t frame_rx[sizeof(RpyTypeDef)]={0};
//     rt_ringbuffer_get(&receive_buffer, frame_rx, sizeof(frame_rx));
//     if(*(uint8_t*)frame_rx==0xFF)
//     {
//         memcpy(&rpy_rx_data,&frame_rx,sizeof(rpy_rx_data));
//         switch (rpy_rx_data.ID) {
//             case CHASSIS_CTRL:{
//                 trans_fdb.linear_x = (*(int32_t *) &rpy_rx_data.DATA[0] / 10000.0);
//                 trans_fdb.linear_y = (*(int32_t *) &rpy_rx_data.DATA[4] / 10000.0);
//                 trans_fdb.linear_z = (*(int32_t *) &rpy_rx_data.DATA[8] / 10000.0);
//                 trans_fdb.angular_x = (*(int32_t *) &rpy_rx_data.DATA[12] / 10000.0);
//                 trans_fdb.angular_y = (*(int32_t *) &rpy_rx_data.DATA[16] / 10000.0);
//                 trans_fdb.angular_z = (*(int32_t *) &rpy_rx_data.DATA[20] / 10000.0);
//             }break;
//             case GIMBAL:{
//                 // if (rpy_rx_data.DATA[0]) {//相对角度控制
//                 //     trans_fdb.yaw = -(*(int32_t *) &rpy_rx_data.DATA[1] / 1000.0);
//                 //     trans_fdb.pitch = (*(int32_t *) &rpy_rx_data.DATA[5] / 1000.0);
//                 //     trans_fdb.roll = (*(int32_t *) &rpy_rx_data.DATA[9] / 1000.0);
//                 // }
//                 // else{//绝对角度控制
//                     trans_fdb.yaw = -(*(int32_t *) &rpy_rx_data.DATA[1] / 1000.0);
//                     trans_fdb.pitch = (*(int32_t *) &rpy_rx_data.DATA[5] / 1000.0);
//                     trans_fdb.roll = (*(int32_t *) &rpy_rx_data.DATA[9] / 1000.0);
//                 // }
//                 trans_fdb.mode = (*(int32_t *) &rpy_rx_data.DATA[13] / 1000.0);
//             }break;
//             case POSE_CTRL:{
//                     trans_fdb.pose = (*(uint8_t *) &rpy_rx_data.DATA[0]);
//                     if (trans_fdb.pose == 3)//移动
//                     {
//                         trans_fdb.chassis_power_limit = 150;
//                         trans_fdb.shooter_17mm_cooling_heat = 10/3;
//                     }
//                     else if (trans_fdb.pose == 2)//防御
//                     {
//                         trans_fdb.chassis_power_limit = 50;
//                         trans_fdb.shooter_17mm_cooling_heat = 10/3;
//                     }
//                     else if (trans_fdb.pose == 1)//进攻
//                     {
//                         trans_fdb.chassis_power_limit = 50;
//                         trans_fdb.shooter_17mm_cooling_heat =30;
//                     }
//             }break;
//             case HEARTBEAT:{
//                 trans_fdb.heartbeat = (*(uint8_t *) &rpy_rx_data.DATA[0]);
//                 heart_dt=dwt_get_time_ms();
//             }break;
//         }
//         memset(&rpy_rx_data, 0, sizeof(rpy_rx_data));
//     }
//     return RT_EOK;
// }




static uint8_t dbg_byte = 0;
static unpack_step_t step = STEP_SOF;
static uint8_t rx_buffer[256];      // 存储当前解析的帧
static uint16_t rx_index = 0;
static uint16_t expected_len = 0;
static uint16_t data_len = 0;

// 每次从环形缓冲区取一个字节，调用此函数
static void parse_byte(uint8_t byte) {
    switch (step) {
        case STEP_SOF:
            dbg_byte = byte;  // 用linkscope观察这个变量
            if (byte == 0xA5) {

                rx_buffer[rx_index++] = byte;
                step = STEP_LEN_LOW;
            }
             break;
        case STEP_LEN_LOW:

            data_len = byte;
            rx_buffer[rx_index++] = byte;
            step = STEP_LEN_HIGH;
            break;
        case STEP_LEN_HIGH:
            data_len |= (byte << 8);
            rx_buffer[rx_index++] = byte;
            if (data_len < 200) {   // 合理长度检查
                step = STEP_SEQ;
            } else {
                // 长度非法，重置
                step = STEP_SOF;
                rx_index = 0;
            }
            break;
        case STEP_SEQ:
            rx_buffer[rx_index++] = byte;
            step = HEADER_CRC8;
            break;
        case HEADER_CRC8:
            rx_buffer[rx_index++] = byte;
            // 校验头CRC8 (前4字节)
            if (verify_crc8_checksum(rx_buffer, 5)) {
                // 注意：verify_crc8_checksum需要实现为仅计算前len-1字节并与最后字节比较
                // 因为我们把crc8也放进rx_buffer了，所以传入长度4，函数内部会计算前3字节并与第4字节比较
                step = DATA_CRC16;
            } else {
                // CRC8错误，丢弃整个帧
                step = STEP_SOF;
                rx_index = 0;
            }
            break;
        case DATA_CRC16: {
            uint16_t total_len = 5 + 2 + data_len + 2; // 头(5) + cmd(2) + data + crc16(2)

                if (total_len > sizeof(rx_buffer)) {
                    step = STEP_SOF;
                    rx_index = 0;
                    break;
                }

            if (rx_index < total_len) {
                rx_buffer[rx_index++] = byte;
            }
            if (rx_index == total_len) {
                // 完整帧接收完毕，进行CRC16校验
                if (verify_crc16_checksum(rx_buffer, total_len)) {
                    // 提取cmd_id
                    uint16_t cmd_id = *(uint16_t*)(rx_buffer + 5); // 头占用5字节
                    uint8_t *data_ptr = rx_buffer + 5 + 2;         // 跳过头部和cmd_id
                    // 处理数据
                    if (cmd_id == CMD_GIMBAL_CONTROL && data_len == sizeof(GBRXTypeDef)) {
                        GBRXTypeDef temp_gimbal;
                        // 用 memcpy 代替指针强转，安全跨越非对齐内存
                        memcpy(&temp_gimbal, data_ptr, sizeof(GBRXTypeDef));

                        // 拷贝完后，再去平移赋值
                        memcpy(&gimbal_rx_date, &temp_gimbal, sizeof(GBRXTypeDef));
                        //数据接收
                        trans_fdb.yaw = gimbal_rx_date.yaw;
                        trans_fdb.pitch = gimbal_rx_date.pit;
                        trans_fdb.yaw_spd = gimbal_rx_date.yaw_spd;
                        trans_fdb.yaw_acc = gimbal_rx_date.yaw_acc;
                        trans_fdb.pitch_acc = gimbal_rx_date.pitch_acc;
                        trans_fdb.pitch_spd = gimbal_rx_date.pitch_spd;
                        trans_fdb.dist = gimbal_rx_date.dist;
                        trans_fdb.shoot = gimbal_rx_date.shoot;
                        trans_fdb.target_id = gimbal_rx_date.target_id;
                    } else if (cmd_id == CMD_HEARTBEAT && data_len == sizeof(HEATTypeDef)) {
                        HEATTypeDef temp_heart;
                        memcpy(&temp_heart, data_ptr, sizeof(HEATTypeDef));
                        memcpy(&heart_rx_data, &temp_heart, sizeof(HEATTypeDef));
                        //数据接收
                        trans_fdb.heartbeat = heart_rx_data.mode;

                    } else {
                        // 未知命令或长度不匹配
                    }
                } else {
                    step = STEP_SOF;
                    rx_index = 0;
                }
                // 重置状态机，准备下一帧
                step = STEP_SOF;
                rx_index = 0;
            }
            break;
        }
        default:
            step = STEP_SOF;
            rx_index = 0;
            break;
    }
}


static rt_err_t usb_input(rt_device_t dev, rt_size_t size)
{
    uint8_t buf[64];
    rt_uint32_t rx_length;

    // 将新数据放入环形缓冲区（保持不变）
    while ((rx_length = rt_device_read(vs_port, 0, buf, sizeof(buf))) > 0) {
        rt_ringbuffer_put_force(&receive_buffer, buf, rx_length);
    }

    // // 逐字节解析
    // uint8_t byte;
    // while (rt_ringbuffer_getchar(&receive_buffer, (char*)&byte) == 1) {
    //     parse_byte(byte);
    // }

    return RT_EOK;
}



// ==================== CRC8 函数实现 ====================

uint8_t generate_crc8_checksum(const uint8_t *data, uint16_t len, uint8_t init)
{
    uint8_t crc = init;
    while (len--)
    {
        crc = CRC8_TAB[crc ^ *data++];
    }
    return crc;
}

uint8_t verify_crc8_checksum(const uint8_t *data, uint16_t len)
{
    if (data == NULL || len < 2) return 0;
    uint8_t expected = generate_crc8_checksum(data, len - 1, 0xFF);
    return (expected == data[len - 1]);
}

void append_crc8_checksum(uint8_t *data, uint16_t len)
{
    if (data == NULL || len < 2) return;
    uint8_t crc = generate_crc8_checksum(data, len - 1, 0xFF);
    data[len - 1] = crc;
}

// ==================== CRC16 函数实现 ====================

uint16_t generate_crc16_checksum(const uint8_t *data, uint32_t len, uint16_t init)
{
    uint16_t crc = init;
    while (len--)
    {
        crc = (crc >> 8) ^ CRC16_TAB[((crc) ^ (*data++)) & 0xFF];
    }
    return crc;
}

uint8_t verify_crc16_checksum(const uint8_t *data, uint32_t len)
{
    if (data == NULL || len < 2) return 0;
    uint16_t expected = generate_crc16_checksum(data, len - 2, 0xFFFF);
    uint16_t received = (uint16_t)data[len - 2] | ((uint16_t)data[len - 1] << 8);
    return (expected == received);
}

void append_crc16_checksum(uint8_t *data, uint32_t len)
{
    if (data == NULL || len < 2) return;
    uint16_t crc = generate_crc16_checksum(data, len - 2, 0xFFFF);
    data[len - 2] = (uint8_t)(crc & 0xFF);
    data[len - 1] = (uint8_t)((crc >> 8) & 0xFF);
}

/*
void Getdata()
{
    rt_uint8_t frame_rx[sizeof(RpyTypeDef)]={0};
    rt_ringbuffer_get(&receive_buffer, frame_rx, sizeof(frame_rx));
    if(*(uint8_t*)frame_rx==0xFF)
    {
        memcpy(&rpy_rx_data,&frame_rx,sizeof(rpy_rx_data));
        switch (rpy_rx_data.ID) {
            case CHASSIS_CTRL:{
                trans_fdb.liner_x = (*(int32_t *) &rpy_rx_data.DATA[0] / 1000.0);
                trans_fdb.liner_y = (*(int32_t *) &rpy_rx_data.DATA[4] / 1000.0);
                trans_fdb.liner_z = (*(int32_t *) &rpy_rx_data.DATA[8] / 1000.0);
                //trans_fdb.angler_x = (*(int32_t *) &rpy_rx_data.DATA[12] / 1000.0);
                //trans_fdb.angler_y = (*(int32_t *) &rpy_rx_data.DATA[16] / 1000.0);
                //trans_fdb.angler_z = (*(int32_t *) &rpy_rx_data.DATA[20] / 1000.0);
            }break;

            case GIMBAL:{
                if (rpy_rx_data.DATA[0]) {//相对角度控制
                    trans_fdb.yaw = - (*(int32_t *) &rpy_rx_data.DATA[1] / 1000.0);
                    trans_fdb.pitch = (*(int32_t *) &rpy_rx_data.DATA[5] / 1000.0);
                }
                else{//绝对角度控制
                    trans_fdb.yaw = - (*(int32_t *) &rpy_rx_data.DATA[1] / 1000.0);
                    trans_fdb.pitch = (*(int32_t *) &rpy_rx_data.DATA[5] / 1000.0);
                }
            }break;
        }
        memset(&rpy_rx_data, 0, sizeof(rpy_rx_data));
    }
}*/
static void Can_send(float data1_original,float data2_original,struct rt_can_msg data_send){

    uint32_t *temp_data1;
    uint32_t *temp_data2;

    temp_data1= (uint32_t *)&data1_original;
    temp_data2= (uint32_t *)&data2_original;

    data_send.data[3] = *temp_data1 >> 24;
    data_send.data[2] = *temp_data1 >> 16;
    data_send.data[1] = *temp_data1 >> 8;
    data_send.data[0] = *temp_data1;
    data_send.data[7] = *temp_data2 >> 24;
    data_send.data[6] = *temp_data2 >> 16;
    data_send.data[5] = *temp_data2 >> 8;
    data_send.data[4] = *temp_data2;

    rt_device_write(gimbal_can, 0, &data_send, sizeof(data_send));

}
void gimbal_down_rx_callback(rt_device_t dev, uint32_t id, uint8_t *data){
    gimbal_can = rt_device_find(CAN_GIMBAL);
    uint32_t data1;
    uint32_t data2;
    uint16_t data3;
    uint16_t data4;
    uint8_t data5;
    uint8_t data6;
    uint16_t data7;
    // 找到对应的实例后再调用decode_dji_motor进行解析
    if (dev == gimbal_can && id == send_msg[0].id)
    {
        uint8_t *rxbuff = data;
        data1 = (uint32_t )rxbuff[0] | (((uint32_t )rxbuff[1]) << 8) | (((uint32_t )rxbuff[2]) << 16)
                | (((uint32_t )rxbuff[3]) << 24) ;
        data2 = (uint32_t )rxbuff[4] | (((uint32_t )rxbuff[5]) << 8) | (((uint32_t )rxbuff[6]) << 16)
                | (((uint32_t )rxbuff[7]) << 24) ;
        // trans_fdb.gyro_down_z = *((float *)&data1);
        // trans_fdb.yaw_down_total_angle = *((float *)&data2);
    }
    else if (dev == gimbal_can && id == send_msg[1].id)
    {
        uint8_t *rxbuff = data;
        // 从 CAN 报文中解析出数据
        data3 = (uint16_t)rxbuff[0] << 8 | rxbuff[1];  // data1（uint16_t）
        data4 = (uint16_t)rxbuff[2] << 8 | rxbuff[3];  // data2（uint16_t）
        data5 = rxbuff[4];                              // data3（uint8_t）
        data6 = rxbuff[5];                              // data4（uint8_t）
        data7 = (uint16_t)rxbuff[6] << 8 | rxbuff[7];  // data5（uint16_t）
        // 将解析出的数据赋值到目标变量
        // trans_fdb.chassis_power_limit = data3;
        // trans_fdb.chassis_buffer_energy = data4;
        // // trans_fdb.linear_z = data5;
        // trans_fdb.game_progress = data6;
        // trans_fdb.shooter_17mm_cooling_heat = data7;
    }
    else if (dev == gimbal_can && id == send_msg[2].id)
    {
        uint8_t *rxbuff = data;
        data1 = (uint32_t )rxbuff[0] | (((uint32_t )rxbuff[1]) << 8) | (((uint32_t )rxbuff[2]) << 16)
                | (((uint32_t )rxbuff[3]) << 24) ;      // data1（float）
        data3 = (uint16_t)rxbuff[4] << 8 | rxbuff[5];   // data2（uint16_t）
        data5 = rxbuff[6];                              // data3（uint8_t）
        data6 = rxbuff[7];                              // data4（uint8_t）
        // trans_fdb.angular_z= (*((float *)&data1));
        // if(trans_fdb.angular_z == -1)
        // {
        //     trans_fdb.angular_z=0;
        // }
        // trans_fdb.angular_z_degree = trans_fdb.angular_z * RADIAN_COEF;
        // trans_fdb.shooter_barrel_heat_limit = data3;
        // trans_fdb.armor_id = data5;
        // trans_fdb.hurt_type = data6;
    }
    else if (dev == gimbal_can && id == send_msg[3].id)
    {
        uint8_t *rxbuff = data;
        data1 = (uint32_t )rxbuff[0] | (((uint32_t )rxbuff[1]) << 8) | (((uint32_t )rxbuff[2]) << 16)
                | (((uint32_t )rxbuff[3]) << 24) ;
        data2 = (uint32_t )rxbuff[4] | (((uint32_t )rxbuff[5]) << 8) | (((uint32_t )rxbuff[6]) << 16)
                | (((uint32_t )rxbuff[7]) << 24) ;
        // trans_fdb.linear_y = *((float *)&data1);
        // trans_fdb.linear_x = *((float *)&data2);
    }
    else if (dev == gimbal_can && id == send_msg[4].id)
    {
        uint8_t *rxbuff = data;
        data1 = (uint32_t )rxbuff[0] | (((uint32_t )rxbuff[1]) << 8) | (((uint32_t )rxbuff[2]) << 16)
                | (((uint32_t )rxbuff[3]) << 24) ;
        data2 = (uint32_t )rxbuff[4] | (((uint32_t )rxbuff[5]) << 8) | (((uint32_t )rxbuff[6]) << 16)
                | (((uint32_t )rxbuff[7]) << 24) ;
        // trans_fdb.current_HP = *((float *)&data1);
        // trans_fdb.maximum_HP = *((float *)&data2);  //保留，默认发0
    }
    else{

    }
}