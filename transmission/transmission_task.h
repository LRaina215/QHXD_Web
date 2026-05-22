/*
* Change Logs:
* Date            Author          Notes
* 2023-10-09      ChenSihan     first version
* 2023-12-09      YangShuo     USB虚拟串口
*/

#ifndef RTTHREAD_TRANSMISSION_TASK_H
#define RTTHREAD_TRANSMISSION_TASK_H
#include "rtthread.h"
#include "rm_config.h"
#include "rm_algorithm.h"
#include "rm_module.h"
#include "rm_task.h"
#include "rtdevice.h"

/* BCP通讯协议相关 */
//TODO: 考虑不同帧长的情况
#define FRAME_MAX_LEN 36        /* 通讯帧的最大长度 */
#define FRAME_XYA_LEN 6         /* 速度控制方式数据长度 */
#define FRAME_AUTO_LEN 22         /* 自瞄发送方式控制数据长度 */
#define FRAME_RPY_LEN 25         /* 欧拉角rpy方式控制数据长度 */
#define FRAME_ODOM_LEN 36       /* 里程计控制方式数据长度 */
#define FRAME_CTRL_LEN 24       /* 角/线速度控制方式数据长度 */
#define FRAME_SHOOT_LEN 7       /* 发射机构数据长度 */
#define FRAME_IMU_LEN 24        /* imu控制方式数据长度 */

//新增
#define GIM_ADV_LEN   30         /*云台控制指令包*/


/* 目标地址表 */
#define BROADCAST   0x00        /* 广播 */
#define MAINFLOD    0x01        /* 上位机 */
#define SENTRY_UP   0x02        /* 哨兵机器人上云台 */
#define SENTRY_DOWN 0x03        /* 哨兵机器人下云台 */
#define INFANTRY    0x04        /* 步兵机器人 */
#define ENGINEER    0x05        /* 工程机器人 */
#define HERO        0x06        /* 英雄机器人 */
#define AIR         0x07        /* 空中机器人 */
#define RADAR       0x08        /* 雷达站 */
#define GATHER      0x09        /* 视觉采集台 */
#define STANDARD    0x10        /* AI机器人/全自动步兵机器人 */
/* 功能码表 */
#define CHASSIS                 0x10        /* 速度方式控制 */
#define CHASSIS_ODOM            0x11        /* 里程计方式控制 */
#define CHASSIS_CTRL            0x12        /* 角/线速度方式控制 */
#define CHASSIS_IMU             0x13        /* 底盘imu数据 */
#define POSE_CTRL               0x15        /* 姿态系统数据 */
#define GIMBAL                  0x20        /* 欧拉角rpy方式控制 */
#define GAME_STATUS             0x30        /* 比赛类型数据*/
#define ROBOT_HP                0x31        /* 机器人血量数据 */
#define ICRA_BUFF_DEBUFF_ZONE   0x32        /* 增益区数据 */
#define GAME_MODE               0x33        /* 机器人颜色数据 */
#define ROBOT_COMMAND           0x34        /* 机器人位置信息 */
#define CLIENT_MAP_COMMAND      0x35        /* 雷达发送目标位置信息 */
#define BARREL                  0x40        /* 发射机构数据 */
#define MANIFOLD_CTRL           0x50        /* 控制模式 */
#define MODE                    0x60        /* 模式控制 */
#define DEV_ERROR               0xE0        /* 故障信息 */
#define HEARTBEAT               0xF0        /* 心跳数据 */

#define CMD_GIMBAL_CONTROL      0x0503   // 云台控制指令
#define CMD_HEARTBEAT           0x0500   // 心跳状态


/**
  * @brief  通讯帧结构体 （BCP通讯协议） 此为最大DATA长度的帧，用于接收中转
  */
typedef  struct
{
    rt_uint8_t HEAD;  				    /*! 帧头 */
    rt_uint8_t D_ADDR;                 /*! 目标地址 */
    rt_uint8_t ID;                     /*! 功能码 */
    rt_uint8_t LEN;                    /*! 数据长度 */
    rt_int8_t DATA[FRAME_MAX_LEN];     /*! 数据内容 */
    rt_uint8_t SC;                     /*! 和校验 */
    rt_uint8_t AC;                     /*! 附加校验 */
}__attribute__((packed)) BCPFrameTypeDef;

/**
  * @brief  自瞄发送结构体
  */
typedef  struct
{
    rt_uint16_t head;				    /*! 帧头 */
/*    float pitchAngleGet;    	    *//*! pitch轴角度 *//*
    float yawAngleGet;      	    *//*! yaw轴角度 *//*
    rt_uint8_t rotateDirection;        *//*! 旋转方向 1 *//*
    float timeBais;         	    *//*! 预测时间偏置 *//*
    float compensateBais;   	    *//*! 弹道补偿偏置 *//*
    rt_uint8_t gimbal_mode;	 	    *//*! 云台模式 *//*
    rt_uint32_t index;                 *//*! 帧序号 */
    rt_int8_t DATA[FRAME_AUTO_LEN];  /*! 数据内容 FRAME_AUTO_LEN=18 */
    rt_uint8_t index[4];
}__attribute__((packed)) SendFrameTypeDef;

/**
  * @brief  速度方式控制通讯帧结构体
  */
typedef  struct
{
    rt_uint8_t HEAD;  				   /*! 帧头 */
    rt_uint8_t D_ADDR;                /*! 目标地址 */
    rt_uint8_t ID;                    /*! 功能码 */
    rt_uint8_t LEN;                   /*! 数据长度 */
    rt_int8_t DATA[FRAME_XYA_LEN];    /*! 数据内容 */
    rt_uint8_t SC;                    /*! 和校验 */
    rt_uint8_t AC;                    /*! 附加校验 */
}__attribute__((packed)) XyaTypeDef;

/**
  * @brief  欧拉角rpy方式控制通讯帧结构体
  */
typedef  struct
{
    rt_uint8_t HEAD;  				    /*! 帧头 */
    rt_uint8_t D_ADDR;                 /*! 目标地址 */
    rt_uint8_t ID;                     /*! 功能码 */
    rt_uint8_t LEN;                    /*! 数据长度 */
    rt_int8_t DATA[FRAME_RPY_LEN];    /*! 数据内容 */
    rt_uint8_t SC;                     /*! 和校验 */
    rt_uint8_t AC;                     /*! 附加校验 */
}__attribute__((packed)) RpyTypeDef;

/**
  * @brief  角/线速度方式控制通讯帧结构体
  */
typedef  struct
{
    rt_uint8_t HEAD;  				    /*! 帧头 */
    rt_uint8_t D_ADDR;                 /*! 目标地址 */
    rt_uint8_t ID;                     /*! 功能码 */
    rt_uint8_t LEN;                    /*! 数据长度 */
    rt_int8_t DATA[FRAME_CTRL_LEN];    /*! 数据内容 */
    rt_uint8_t SC;                     /*! 和校验 */
    rt_uint8_t AC;                     /*! 附加校验 */
}__attribute__((packed)) CtrlTypeDef;

/**
  * @brief  里程计方式控制通讯帧结构体
  */
typedef  struct
{
    rt_uint8_t HEAD;  				    /*! 帧头 */
    rt_uint8_t D_ADDR;                 /*! 目标地址 */
    rt_uint8_t ID;                     /*! 功能码 */
    rt_uint8_t LEN;                    /*! 数据长度 */
    rt_int8_t DATA[FRAME_ODOM_LEN];    /*! 数据内容 */
    rt_uint8_t SC;                     /*! 和校验 */
    rt_uint8_t AC;                     /*! 附加校验 */
}__attribute__((packed)) OdomTypeDef;

/**
  * @brief  imu方式控制通讯帧结构体
  */
typedef  struct
{
    rt_uint8_t HEAD;  				    /*! 帧头 0XFF */
    rt_uint8_t D_ADDR;                 /*! 目标地址 0X01 */
    rt_uint8_t ID;                     /*! 功能码 0X13 */
    rt_uint8_t LEN;                    /*! 数据长度 40 */
    rt_int8_t DATA[FRAME_IMU_LEN];    /*! 数据内容 */
    rt_uint8_t SC;                     /*! 和校验 */
    rt_uint8_t AC;                     /*! 附加校验 */
}__attribute__((packed)) ImuTypeDef;

/**
  * @brief  发射机构数据通讯帧结构体
  */
typedef  struct
{
    rt_uint8_t HEAD;  				    /*! 帧头 */
    rt_uint8_t D_ADDR;                 /*! 目标地址 */
    rt_uint8_t ID;                     /*! 功能码 */
    rt_uint8_t LEN;                    /*! 数据长度 */
    rt_int8_t DATA[FRAME_SHOOT_LEN];    /*! 数据内容 */
    rt_uint8_t SC;                     /*! 和校验 */
    rt_uint8_t AC;                     /*! 附加校验 */
}__attribute__((packed)) ShootTypeDef;


/***************************************************更改版通信********************************************/
//下位机接收
// 控制指令包 (30 bytes)
typedef struct __attribute__((packed)) {
  float yaw;          // 目标yaw角度
  float pit;          // 目标pitch角度
  float yaw_spd;      // yaw角速度
  float pitch_spd;    // pitch角速度
  float yaw_acc;      // yaw角加速度
  float pitch_acc;    // pitch角加速度
  float dist;         // 目标距离
  uint8_t shoot;      // 射击指令
  uint8_t target_id;  // 目标类型ID
}  GBRXTypeDef;


// 心跳状态包 (1 byte)
typedef struct __attribute__((packed)) {
  uint8_t mode;       // 自瞄状态模式
}  HEATTypeDef;

//上位机发送
// IMU位姿数据包 (17 bytes)
typedef struct __attribute__((packed)) {
  float curr_yaw;     // 当前yaw角度
  float curr_pitch;   // 当前pitch角度
  float curr_roll;    // 当前roll角度
  float shoot_speed;  // 子弹初速度
  uint8_t autoaim_mode; // 自瞄模式标志
} pc_mcu_data_t;

// 赛场状态数据包 (33 bytes)
typedef struct __attribute__((packed)) {
  uint16_t red_1_robot_HP;
  uint16_t red_2_robot_HP;
  uint16_t red_3_robot_HP;
  uint16_t red_4_robot_HP;
  uint16_t red_5_robot_HP;
  uint16_t red_7_robot_HP;
  uint16_t red_outpost_HP;
  uint16_t red_base_HP;
  uint16_t blue_1_robot_HP;
  uint16_t blue_2_robot_HP;
  uint16_t blue_3_robot_HP;
  uint16_t blue_4_robot_HP;
  uint16_t blue_5_robot_HP;
  uint16_t blue_7_robot_HP;
  uint16_t blue_outpost_HP;
  uint16_t blue_base_HP;
  uint8_t robot_id;
} robot_data_t;

//帧头结构
// 与上位机完全一致
typedef struct __attribute__((packed)) {
  uint8_t sof;
  uint16_t data_length;   // 小端
  uint8_t seq;
  uint8_t crc8;
} frame_header_t;

// 接收状态机
typedef enum {
  STEP_SOF = 0,
  STEP_LEN_LOW,
  STEP_LEN_HIGH,
  STEP_SEQ,
  HEADER_CRC8,
  DATA_CRC16
} unpack_step_t;

//校验的函数
// CRC8 相关函数
uint8_t generate_crc8_checksum(const uint8_t *data, uint16_t len, uint8_t init);
uint8_t verify_crc8_checksum(const uint8_t *data, uint16_t len);
void append_crc8_checksum(uint8_t *data, uint16_t len);

// CRC16 相关函数
uint16_t generate_crc16_checksum(const uint8_t *data, uint32_t len, uint16_t init);
uint8_t verify_crc16_checksum(const uint8_t *data, uint32_t len);
void append_crc16_checksum(uint8_t *data, uint32_t len);

// ==================== CRC8 表 ====================
// 多项式：x^8 + x^5 + x^4 + 1 (0x31)
static const uint8_t CRC8_TAB[256] = {
    0x00, 0x5e, 0xbc, 0xe2, 0x61, 0x3f, 0xdd, 0x83, 0xc2, 0x9c, 0x7e, 0x20, 0xa3, 0xfd, 0x1f, 0x41,
    0x9d, 0xc3, 0x21, 0x7f, 0xfc, 0xa2, 0x40, 0x1e, 0x5f, 0x01, 0xe3, 0xbd, 0x3e, 0x60, 0x82, 0xdc,
    0x23, 0x7d, 0x9f, 0xc1, 0x42, 0x1c, 0xfe, 0xa0, 0xe1, 0xbf, 0x5d, 0x03, 0x80, 0xde, 0x3c, 0x62,
    0xbe, 0xe0, 0x02, 0x5c, 0xdf, 0x81, 0x63, 0x3d, 0x7c, 0x22, 0xc0, 0x9e, 0x1d, 0x43, 0xa1, 0xff,
    0x46, 0x18, 0xfa, 0xa4, 0x27, 0x79, 0x9b, 0xc5, 0x84, 0xda, 0x38, 0x66, 0xe5, 0xbb, 0x59, 0x07,
    0xdb, 0x85, 0x67, 0x39, 0xba, 0xe4, 0x06, 0x58, 0x19, 0x47, 0xa5, 0xfb, 0x78, 0x26, 0xc4, 0x9a,
    0x65, 0x3b, 0xd9, 0x87, 0x04, 0x5a, 0xb8, 0xe6, 0xa7, 0xf9, 0x1b, 0x45, 0xc6, 0x98, 0x7a, 0x24,
    0xf8, 0xa6, 0x44, 0x1a, 0x99, 0xc7, 0x25, 0x7b, 0x3a, 0x64, 0x86, 0xd8, 0x5b, 0x05, 0xe7, 0xb9,
    0x8c, 0xd2, 0x30, 0x6e, 0xed, 0xb3, 0x51, 0x0f, 0x4e, 0x10, 0xf2, 0xac, 0x2f, 0x71, 0x93, 0xcd,
    0x11, 0x4f, 0xad, 0xf3, 0x70, 0x2e, 0xcc, 0x92, 0xd3, 0x8d, 0x6f, 0x31, 0xb2, 0xec, 0x0e, 0x50,
    0xaf, 0xf1, 0x13, 0x4d, 0xce, 0x90, 0x72, 0x2c, 0x6d, 0x33, 0xd1, 0x8f, 0x0c, 0x52, 0xb0, 0xee,
    0x32, 0x6c, 0x8e, 0xd0, 0x53, 0x0d, 0xef, 0xb1, 0xf0, 0xae, 0x4c, 0x12, 0x91, 0xcf, 0x2d, 0x73,
    0xca, 0x94, 0x76, 0x28, 0xab, 0xf5, 0x17, 0x49, 0x08, 0x56, 0xb4, 0xea, 0x69, 0x37, 0xd5, 0x8b,
    0x57, 0x09, 0xeb, 0xb5, 0x36, 0x68, 0x8a, 0xd4, 0x95, 0xcb, 0x29, 0x77, 0xf4, 0xaa, 0x48, 0x16,
    0xe9, 0xb7, 0x55, 0x0b, 0x88, 0xd6, 0x34, 0x6a, 0x2b, 0x75, 0x97, 0xc9, 0x4a, 0x14, 0xf6, 0xa8,
    0x74, 0x2a, 0xc8, 0x96, 0x15, 0x4b, 0xa9, 0xf7, 0xb6, 0xe8, 0x0a, 0x54, 0xd7, 0x89, 0x6b, 0x35,
};

// ==================== CRC16 表 ====================
// 多项式：标准 CRC-16-CCITT (x^16 + x^12 + x^5 + 1) = 0x1021
static const uint16_t CRC16_TAB[256] = {
    0x0000, 0x1189, 0x2312, 0x329b, 0x4624, 0x57ad, 0x6536, 0x74bf,
    0x8c48, 0x9dc1, 0xaf5a, 0xbed3, 0xca6c, 0xdbe5, 0xe97e, 0xf8f7,
    0x1081, 0x0108, 0x3393, 0x221a, 0x56a5, 0x472c, 0x75b7, 0x643e,
    0x9cc9, 0x8d40, 0xbfdb, 0xae52, 0xdaed, 0xcb64, 0xf9ff, 0xe876,
    0x2102, 0x308b, 0x0210, 0x1399, 0x6726, 0x76af, 0x4434, 0x55bd,
    0xad4a, 0xbcc3, 0x8e58, 0x9fd1, 0xeb6e, 0xfae7, 0xc87c, 0xd9f5,
    0x3183, 0x200a, 0x1291, 0x0318, 0x77a7, 0x662e, 0x54b5, 0x453c,
    0xbdcb, 0xac42, 0x9ed9, 0x8f50, 0xfbef, 0xea66, 0xd8fd, 0xc974,
    0x4204, 0x538d, 0x6116, 0x709f, 0x0420, 0x15a9, 0x2732, 0x36bb,
    0xce4c, 0xdfc5, 0xed5e, 0xfcd7, 0x8868, 0x99e1, 0xab7a, 0xbaf3,
    0x5285, 0x430c, 0x7197, 0x601e, 0x14a1, 0x0528, 0x37b3, 0x263a,
    0xdecd, 0xcf44, 0xfddf, 0xec56, 0x98e9, 0x8960, 0xbbfb, 0xaa72,
    0x6306, 0x728f, 0x4014, 0x519d, 0x2522, 0x34ab, 0x0630, 0x17b9,
    0xef4e, 0xfec7, 0xcc5c, 0xddd5, 0xa96a, 0xb8e3, 0x8a78, 0x9bf1,
    0x7387, 0x620e, 0x5095, 0x411c, 0x35a3, 0x242a, 0x16b1, 0x0738,
    0xffcf, 0xee46, 0xdcdd, 0xcd54, 0xb9eb, 0xa862, 0x9af9, 0x8b70,
    0x8408, 0x9581, 0xa71a, 0xb693, 0xc22c, 0xd3a5, 0xe13e, 0xf0b7,
    0x0840, 0x19c9, 0x2b52, 0x3adb, 0x4e64, 0x5fed, 0x6d76, 0x7cff,
    0x9489, 0x8500, 0xb79b, 0xa612, 0xd2ad, 0xc324, 0xf1bf, 0xe036,
    0x18c1, 0x0948, 0x3bd3, 0x2a5a, 0x5ee5, 0x4f6c, 0x7df7, 0x6c7e,
    0xa50a, 0xb483, 0x8618, 0x9791, 0xe32e, 0xf2a5, 0xc03c, 0xd1b5,
    0x2942, 0x38cb, 0x0a50, 0x1bd9, 0x6f66, 0x7eef, 0x4c74, 0x5dfd,
    0xb58b, 0xa402, 0x9699, 0x8710, 0xf3af, 0xe226, 0xd0bd, 0xc134,
    0x39c3, 0x284a, 0x1ad1, 0x0b58, 0x7fe7, 0x6e6e, 0x5cf5, 0x4d7c,
    0xc60c, 0xd785, 0xe51e, 0xf497, 0x8028, 0x91a1, 0xa33a, 0xb2b3,
    0x4a44, 0x5bcd, 0x6956, 0x78df, 0x0c60, 0x1de9, 0x2f72, 0x3efb,
    0xd68d, 0xc704, 0xf59f, 0xe416, 0x90a9, 0x8120, 0xb3bb, 0xa232,
    0x5ac5, 0x4b4c, 0x79d7, 0x685e, 0x1ce1, 0x0d68, 0x3ff3, 0x2e7a,
    0xe70e, 0xf687, 0xc41c, 0xd595, 0xa12a, 0xb0a3, 0x8238, 0x93b1,
    0x6b46, 0x7acf, 0x4854, 0x59dd, 0x2d62, 0x3ceb, 0x0e70, 0x1ff9,
    0xf78f, 0xe606, 0xd49d, 0xc514, 0xb1ab, 0xa022, 0x92b9, 0x8330,
    0x7bc7, 0x6a4e, 0x58d5, 0x495c, 0x3de3, 0x2c6a, 0x1ef1, 0x0f78
};
/**
  * @brief CDC上下位机通信线程入口函数
  */
void transmission_task_entry(void* argument);

/**
  * @brief 拆分并填充rpy欧拉角数据
  */
void pack_Rpy(RpyTypeDef *frame, float yaw, float pitch,float roll);

/**
  * @brief 和校验，附加校验
  */
void Check_Rpy(RpyTypeDef *frame);

/**
  * @brief 执行发送动作
  */
void Send_to_pc(RpyTypeDef data_r);

void Send_to_pc_new(void);


/**
  * @brief 执行接收解析动作
  */
void Getdata();

/**
  * @brief 接受回调函数
  */
static rt_err_t usb_input(rt_device_t dev, rt_size_t size);

/**
  * @brief   接收区清空标志位回馈
  */
typedef enum
{
    trans_OK=1,   //执行清空操作
    trans_NO=0,  //不执行清空操作
} trans_back_e;
void gimbal_down_rx_callback(rt_device_t dev, uint32_t id, uint8_t *data);

static void parse_byte(uint8_t byte);
#endif // RTTHREAD_TRANSMISSION_TASK_H
