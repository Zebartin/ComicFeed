# 05 — 榜单增量 + 作品级筛选

**What to build:** 榜单订阅自动巡检每轮只取第一页；按作品 ID 全局去重，重复上榜作品跳过，榜单 Gallery 只增不缩、页序按首次收录顺序；订阅筛选条件（收藏数≥ / 页数≥ / 上传日期≤）对 pixiv 按作品逐个应用，不达标作品不收录。服务层把 SPECIFIC_GALLERY 订阅的筛选条件传给源的 check_updates（新增可选参数，向后兼容）。

**Blocked by:** 02 — 插画日榜端到端（tracer bullet）；03 — 画师订阅：全量首检 + 增量巡检

**Status:** resolved

- [ ] 榜单巡检每次只请求第一页
- [ ] 已收录作品（含重复上榜）不再收录
- [ ] 榜单 Gallery 页按首次收录顺序追加
- [ ] 收藏数/页数/上传日期筛选对作品逐个生效（样本 JSON 覆盖各边界与组合）
- [ ] 筛选条件经 check_updates 可选参数传递；exhentai/nhentai 的 SPECIFIC_GALLERY 行为回归不变
