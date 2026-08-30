# 06 — R-18 映射 + 官方中文标签 + 标题元数据

**What to build:** R-18 榜单 URL（daily_r18 等）按 web→app 模式映射后可直接订阅；所有 app-api 请求携带 Accept-Language: zh-cn；标签优先官方中文 translated_name、缺失回退日文原文；画师 Gallery 标题「画师名(画师id)」、writer=画师名；榜单 Gallery 标题「Pixiv {内容}{周期}榜」；作品标题经归一化（去除括号标注等）。

**Blocked by:** 02 — 插画日榜端到端（tracer bullet）；03 — 画师订阅：全量首检 + 增量巡检

**Status:** resolved

- [ ] web 榜单 mode（含各 R-18 模式）→ app mode 映射表正确
- [ ] 请求携带 Accept-Language: zh-cn（mock 断言）
- [ ] translated_name 有值用官方中文、null 回退日文原文（样本覆盖两种）
- [ ] 画师/榜单 Gallery 标题与 writer 按约定格式生成
- [ ] ComicInfo 与画廊页展示正确的标题与标签
