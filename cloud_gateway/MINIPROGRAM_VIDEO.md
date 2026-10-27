# 微信小程序连续视频（2026-10-25）

**2026-10-27说明对账：** 本文保留初次接口和部署记录。小程序b8ed624已加入原生启动/手动播放入口及有限缓冲恢复，开发者工具公网同一播放器可跨三次缓冲错误继续播放；新版手机和微信新包发布尚未取得验收记录。Web侧10月27日补齐Cookie保护的浏览器HLS代理，不能再将旧/video/hls的404当作当前全局状态。两端仍复用同一robot/front，媒体不经过FPGA；不因视频HTTP200或RK在线推定整车运动可用。当前系统关系见[总体架构](https://github.com/LRaina215/SOC_FPGA_NAV/blob/codex/integration-g2-20261022/docs/system_architecture.md)。

本改动复用 `robot/front` 的现有 MediaMTX 流。RK3588 继续只采集、编码和上传一路；小程序增加一个云端观看连接，增加云出口流量，不占用或替换 WebRTC 观看会话，不经过 FPGA。未修改 MediaMTX、RK 推流、浏览器视频会话或任务桥接。

上线后只读查询实际 MediaMTX 控制 API：默认配置和 `robot/front` 的 `maxReaders` 均为 0（不限制观看连接数），流为 ready，当时同时列出 3 个 HLS 观看会话。没有“只能一个客户端观看”的配置限制；这不等于无限带宽，也不替代 Web 与手机同时播放的真机验收。

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

小程序 `<video>` 播放 HLS，图片轮询用于连接期间和故障回退。收到实际变化的播放进度后才显示视频并停止取图；8 秒没有新进度或初次加载超时则释放视频并恢复图片，重试按 5—60 秒退避。无 Token 或鉴权拒绝保持图片，不持续创建会话；切地址 / Token / 页面会作废旧响应和事件；租期到期前重建会话。

HLS 连续播放不等于 WebRTC 低延迟。当前云端实际清单是 MPEG-TS、约 2 秒分片；本轮未测端到端延迟，也未修改线上 HLS 参数。

## 验证与交付边界

- 新网关定向检查 7 项通过；原视频鉴权和健康别名兼容检查此前 6 项通过。使用本地假 Token、模拟上游，不连接设备。首次因测试环境缺 python-multipart 未能导入，补在独立依赖目录后通过。
- 小程序新增 8 组视频生命周期检查、原 4 组相机回归、静态检查通过。
- 通过验证主机身份的只读 SSH 隧道，将实际云端 MediaMTX 接到本机新网关；主清单、子清单和 TS 分片均返回 200。初次定位并补齐了 cookieCheck 重定向、UUID 查询及媒体跨域支持。
- 微信开发者工具中以本机测试会话临时驱动新播放器，观察到播放位置从约 49 增至约 143，进度保持更新、播放器 1 个、图片轮询停止。位置数值是媒体时间，不是端到端延迟或测得的连续观看时长。切回地图后播放器 / 视频定时器 / 图片定时器均为 0；测试方法覆盖已恢复，临时网关与隧道已关闭，未修改用户 API 地址或 Token 缓存。
- 云网关已部署，默认公网 API 域名下的小程序实际视频播放通过；无 Token 的会话和无效租期的媒体请求返回 401，原 WebRTC 入口仍受鉴权保护。尚未上传 / 发布微信代码包或完成手机验收；未重新执行控制、模型、音响或 FPGA 测试。

## 部署范围与回退

部署前只读确认：线上 `/opt/lingxun-cloud-gateway/cloud_gateway.py` 与本次改动前的仓库基线文本一致，未做 SHA 校验。服务器当前网关与 MediaMTX 均为 active。

用户本轮明确要求继续接通视频入口、鉴权和小程序，按这一限定授权已部署 `4afe8d4`：仅备份并替换 `cloud_gateway.py`，用现有虚拟环境导入检查，再重启 `lingxun-cloud-gateway`。Web 状态推送会短暂重连；未重启 RK、MediaMTX 或控制服务，未复制 `.env`、其他会话的任务桥接 / 前端改动或本地测试文件。

首次探测早于端口监听，脚本自动恢复原文件并重启原网关；确认恢复 HTTP 200 后，增加有限启动等待，第二次部署成功。备份为 `/opt/lingxun-cloud-gateway/backups/cloud_gateway.pre-minivideo-20261025-134651-396fa6.py`。部署后网关健康且 RK 在线，小程序已用原默认 API / Token 实际公网播放，使用公网同源地址而不是本机测试端口。

已补验新会话、受保护媒体和小程序连续播放，并核对既有网关健康与 Web 视频入口；过期边界由本地模拟验证，没有为了等租期反复拉流十分钟。不重跑整套已通过的控制测试。后续若需回退，恢复本次保存的单文件备份并重启同一个网关，再确认原接口恢复。
