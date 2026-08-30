# 04 — 动图 → 动画 WebP

**What to build:** 订阅命中 ugoira 作品：取 metadata + 帧 zip（带认证与 Referer）→ Pillow 按帧序与 delay（毫秒）合成动画 WebP，作为单页混排进 CBZ（页 ID 为 作品ID_webp）；转换失败的作品跳过、不阻塞同画廊其余作品；每个跳过记为失败下载事件（作品标题 + 原因），出现在摘要通知的失败汇总。跳过清单经向后兼容的可选钩子由源回传下载服务，由下载服务写事件（源不直接写持久化）。

**Blocked by:** 02 — 插画日榜端到端（tracer bullet）

**Status:** ready-for-agent

- [ ] 内存帧 zip fixture → 合法动画 WebP（Pillow 可打开、帧数 > 1）
- [ ] 混合 jpg + webp 页的卷打包成功，CBZ 命名/分卷不受影响
- [ ] metadata 的 delay（毫秒）正确作用于帧时长
- [ ] 转换失败：同画廊其余作品正常打包，CBZ 产出不中断
- [ ] 每次跳过以 failed 下载事件记录（标题 + 原因），摘要按订阅分组展示（沿用现有每订阅 ≤5 条上限）
- [ ] 现有源（exhentai/nhentai）下载流程回归不变（可选钩子默认空实现）
