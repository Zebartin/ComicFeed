# 07 — 画廊源站链接 + 搜索页透传

**What to build:** 画廊页「打开源站链接」对 pixiv 跳转到对应作品/画师页面；搜索页选择 pixiv 执行关键词搜索可浏览结果卡片。关键词订阅（SEARCH 模式）不在范围：pixiv 搜索结果不提供按关键词保存订阅的入口，UI 给出明确提示。

**Blocked by:** 03 — 画师订阅：全量首检 + 增量巡检；06 — R-18 映射 + 官方中文标签 + 标题元数据

**Status:** ready-for-agent

- [ ] 画师与榜单 native_id 映射为正确的 www.pixiv.net 页面 URL（画廊页可跳转）
- [ ] 搜索透传 /v1/search/illust 并解析结果（样本 JSON）
- [ ] 搜索页对 pixiv 可搜索、可浏览结果
- [ ] pixiv 搜索页不提供 SEARCH 模式保存入口，有明确提示（关键词订阅不在范围）
