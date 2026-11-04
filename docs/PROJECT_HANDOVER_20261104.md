# RK3588 / Web阶段交接（2026-11-04）

项目交付版本和整车维护入口统一见[NAV阶段收尾与交接](https://github.com/LRaina215/SOC_FPGA_NAV/blob/main/docs/3_guide/project_handover_20261104.md)。本页补充RK本地操作，不另立整车状态表。

## 真实FPGA与地图

共同工程为PNR100/136KiB，Flash内置swingunlock；RK最后确认选择地图2radius35（13:21:29、61,712B），应用通过既有keeper加载。不要把旧128KiB位流与136KiB应用混用，也不要把Flash版本等同ACTIVE。

生产配置为`YUNTUO_FPGA_LINK=uart:/dev/ttyACM0`、`YUNTUO_CONTROL_TELEMETRY=serial:/dev/ttyUSB0@230400`、`YUNTUO_FPGA_IS_MOCK=false`，设备名按实际枚举/已有规则选择。桥接统一拥有两串口。P11-40是控制遥测，CH口是导航命令/地图，不要求新增P11-39接收。

NVMP v3上传支持包校验、进度和READY；Web的预览与真正下发分开。两套地图各有巡航点配置，切图后核对相同坐标系、目标点和返航点。FPGA同时装载一套选中地图；不要用删除RK上的地图文件来估算片上RAM节省。

清障STATUS保留原长度，原保留16位承载`clearing_ms`，旧固件值0。后端最多为单次清障提供35s观察宽限，暂停/取消/急停和任务归属优先。最终地图2演示的350mm仅用于指定SEARCH路线的经过半径，不改通用GOTO精度声明。

## 局域网网页

`qhxd-backend`从`frontend/dist`提供前端及API，RK桌面打开`http://127.0.0.1:8000/`，同局域网设备访问`http://<RK局域网IP>:8000/`。离线前准备模型、依赖和静态构建，启动方式见[YUNTUO.md](YUNTUO.md)。源码开发可用`./scripts/start_frontend.sh`和5173端口，生产演示不需要再起Vite。

公网仍由lingxunrobot.cn与API网关服务；局域网网页和本地模型支持不经过公网的演示。微信识别、公网访问及云视频各自有网络条件，不概括成全部离线。

## 本地AI处理终端

RK图形桌面执行：

```bash
cd ~/QHXD
./scripts/open_ai_demo.sh
```

默认显示真实请求的ASR、LLM、TTS等处理窗口。它观察现有服务，不另起一套模型；桌面窗口关闭不等于关闭后端。SSH用`python3 scripts/observe_ai_pipeline.py --console all`查看同一流程，`--arrange`可重排已打开窗口。`--standalone`仅用于明确选择的独立问答演示，不应替代真实页面处理记录。

模型组合为SenseVoice INT8、Qwen3-1.7B W8A8/RKLLM、Matcha+Vocos；YOLO26n使用RKNN，和Qwen共享NPU。模型及私有.env不进入仓库。Astra接RK提供目标和Web视频，OV5640接FPGA提供本地LCD，两路不能互换。

## 停止、验证与维护

网页停止撤销导航运动目标并保留4500平衡。`YUNTUO_ARRIVE_NEED_WHEEL_STOP`决定是否把轮速静止作为到达门；演示配置false不表示车体已物理停稳。页面反馈、控制锁停与保持平衡的运行停止分别显示。

项目保留清障实车未恢复持续前进、定位/摆动、真实停止距离及新版手机视频验收等维护事项。测试数字按对应冻结版本引用，不因文档收尾重新运行测试或改线上服务。桥接/感知/前端还有本地实现改动时，应单独审阅后提交，不将文档提交冒称已发布这些实现。
