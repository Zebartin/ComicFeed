# 02 — 插画日榜端到端（tracer bullet）

**What to build:** 用户粘贴插画日榜 URL（mode=daily&content=illust）创建订阅 → 首次检查返回第一页约 30 个作品的结果卡片（封面/标题/页数/收藏数）→ 手动下载选中 → 单页与多页作品的全部页带 Referer 下载并打包成 CBZ（页 ID 为 作品ID_p页码）。榜单 URL 解析出榜单 Gallery 的 native_id。此阶段遇到动图作品先跳过（记日志），由 04 补齐。

**Blocked by:** 01 — pixiv 源骨架 + OAuth 认证 + 测试连接

**Status:** resolved

- [ ] 榜单 URL 解析：插画日榜/动图榜等 → 榜单 native_id；垃圾 URL 返回 None
- [ ] 检查返回第一页作品的标题/封面/页数/收藏数（样本 JSON 离线断言）
- [ ] 多页作品详情解析出全部页 URL 与逐页 ID
- [ ] 图片下载携带 Referer 与 iOS App 身份头（离线 mock 断言请求头）
- [ ] 单页与多页作品各打包出页数正确的 CBZ，ComicInfo 含基本字段
- [ ] 榜单 Gallery 中动图作品被跳过（有日志）且不阻塞其余作品
