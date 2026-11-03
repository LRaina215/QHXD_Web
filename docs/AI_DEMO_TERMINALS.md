# RK3588 离线 AI 三终端演示

在 **RK 图形桌面**运行：

```bash
cd ~/QHXD
bash scripts/open_ai_demo.sh
```

自动弹出 ASR、LLM、TTS 三个窗口。在 ASR 窗口按回车，录音时说一句话。
ASR 识别后交给本机 LLM，LLM 回复交给本机 TTS，再通过 RK 扬声器播放。
各窗口显示真实输入、输出和耗时。`t 文字` 跳过 ASR 做文字问答；`f /路径/音频.wav`
使用一段不超过 10 秒的 16-bit PCM 单声道 WAV。输入 `q` 或关闭任一窗口退出本次演示。

安装桌面及应用菜单快捷方式（一次即可）：

```bash
bash scripts/open_ai_demo.sh --install-desktop
```

然后双击“云拓离线AI三终端”。桌面首次提示时选择“允许启动”。必须先登录 RK
桌面；普通 SSH 会话不能直接弹窗。服务与声卡检查：

```bash
bash scripts/open_ai_demo.sh --check
```

## 实现范围

- 不下载模型、不用云 API、不执行车辆或任务接口、不修改 FPGA/导航/桥接。
- ASR 窗口独立加载 `.env` 指定的 SenseVoice，用于本次演示；可能与业务后端已有
  ASR 实例同时驻留，关闭演示后释放。需要系统 Python 已安装 sherpa-onnx。
- LLM/TTS 复用正在运行的 `yuntuo-llm` 和 `yuntuo-tts`。未启动时显示实际错误，
  不自动重启模型服务。检查无误后可由维护终端启动对应服务。
- ASR 录音读取 `AUDIO_DEVICE`/`AUDIO_RECORD_SECONDS`；播放读取 `TTS_PLAYER_CMD`。
  直接使用已配置声卡，不调整音量、不切换系统音频。录音期间避免同时使用网页录音。
- LLM 整段返回，不模拟流式 token；TTS 请求耗时可能包含排队或命中缓存，不冒称
  纯模型合成时间。文字输入明确标记“跳过ASR”。
- 单次只允许一个演示会话，防止反复打开导致 ASR 多份加载。
- 小日志在 `~/.cache/yuntuo-ai-demo/session-*/`，包含演示输入/输出。
  默认退出时删除本次录音与回复 WAV；只保留处理日志。异常断电时可残留临时 WAV。
- 已支持 RK 当前安装的 xfce4-terminal，并兼容 gnome-terminal、xterm。

这条脚本演示的是独立问答链，不代表网页运动指令的任务执行或导航验收。
