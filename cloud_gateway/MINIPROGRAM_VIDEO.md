# 微信小程序视频接入

小程序通过 HLS 播放 MediaMTX 的 `robot/front` 视频，与 Web 共用 RK3588 上传的同一路媒体源。云网关负责签发限时播放地址、校验媒体请求并转发清单和分片。

RK 统一采集、推理和编码，Web 与小程序分别建立云端观看连接，出口流量随观看数量增加。

## 接口契约

`POST /api/video/miniprogram/session` 使用现有 `Authorization: Bearer <PUBLIC_API_TOKEN>`，受现有会话创建限流保护，不要求开启公网运动控制。返回：

```json
{
  "success": true,
  "data": {
    "protocol": "hls",
    "playback_url": "/api/video/miniprogram/hls/<lease>/robot/front/index.m3u8",
    "expires_in": 600
  }
}
```

`playback_url` 相对于发起 API 请求的同一域名。`lease` 是绑定当前流路径的限时签名，不是长期 API Token；默认有效期沿用 `VIDEO_SESSION_TTL_SECONDS`。签名与 Web Cookie 使用不同用途标识，不能互换。创建接口不设置 Cookie。

播放器通过 GET / HEAD 读取该前缀下的清单和分片，每次均校验租期。只代理配置流下的 `.m3u8`、`.ts`、`.mp4` 和 `.m4s`；禁止其他路径、外部 URI 和任意查询参数。主 / 子清单、MAP / PART URI 均重写到同一个受保护前缀。透传单段 Range 与允许的 HLS 控制参数，不向 MediaMTX 传递用户 Bearer Token、Cookie 或任意请求头。

现役 MediaMTX 会把初始清单重定向至同一文件的 `cookieCheck=1`，随后清单使用 `session=<UUID>`。代理只在同一上游域名和同一文件内跟随最多两次重定向，并使用无 Cookie 的查询会话方式；不把内部 Location 暴露给播放器。`MEDIA_HLS_BASE_URL` 默认 `http://127.0.0.1:8888`。不需修改 Nginx /video 路由，已有 /api 代理即可承载新入口。

媒体响应带 `no-store` 与仅针对本媒体路由的 `Access-Control-Allow-Origin: *`，解决微信开发者工具的视频 WebView 跨域请求。媒体访问依赖每条 URL 中的租期签名；没有取消鉴权，也没有放宽其他 API 的跨域策略。播放 URL 是临时访问凭据，不应写入公开截图、报告或应用日志。

## 小程序行为

小程序使用 `<video>` 播放 HLS，提供原生与手动播放入口。加载时展示检测图片作为 poster，收到有效播放进度后停止图片轮询；失败后回退图片。

首次加载窗口为 30 秒，播放后缓冲恢复窗口为 15 秒，无新进度检查为 8 秒。已知缓冲错误在窗口内保留播放器，超时释放并按 5—60 秒退避重试。无 Token 或鉴权拒绝时保持图片；切页、切地址或 Token 变化后释放旧会话并隔离旧响应。

租期到期前更新播放会话。云端 HLS 使用约 2 秒 MPEG-TS 分片，播放延时由编码、分片、网络与终端缓冲共同决定。

## 部署与测试记录

[2026-10-25 网关部署与测试](records/miniprogram_video_20261025.md)保存配置备份和回退信息；后续播放器修复与手机发布记录见[小程序维护记录](https://github.com/LRaina215/QHXD_Miniprogram/blob/yuntuo/MAINTENANCE.md)。
