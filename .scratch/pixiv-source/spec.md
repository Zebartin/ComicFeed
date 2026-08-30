Status: ready-for-agent

# Spec: Pixiv 源

## Problem Statement

用户希望自动收集 pixiv 上**特定画师**和**热门榜单**的作品（插画、漫画、动图），像现有 exhentai/nhentai 源一样通过订阅定时巡检、增量更新、打包 CBZ 由 Komga 索引。当前 ComicFeed 只有 exhentai 和 nhentai 两个源，无法订阅 pixiv 内容；且 pixiv 的内容组织方式（画师/榜单是作品集合，而非单个画廊）与现有 Gallery 模型不完全一致，需要一套明确的映射和增量语义。

## Solution

新增一个 pixiv Source 插件（遵循 ADR 0001 的源插件模型，`key="pixiv"`，`AuthSchema.TOKEN`，凭 refresh_token 访问 app-api）。核心映射：**一个画师或一个榜单 = 一个 Gallery，画师/榜单中的作品 = 页面**；订阅检查用 `check_updates` 按作品 ID 差集检测新作品，作为新页面增量追加到已有 CBZ 卷（满了自动开新卷）。动图（ugoira）作品转换为**动画 WebP**，作为单页与其他图片页混排进 CBZ（打包器已按魔数支持 `.webp` 页）。标签使用 pixiv 官方翻译（`Accept-Language: zh-cn` → `tags[].translated_name`），无官方翻译时回退日文原文。R-18 作品与 R-18 榜单直接支持，取决于账号自身的「显示 R-18/R-18G」设置，无需 premium。

## User Stories

1. 作为一个 ComicFeed 用户，我想要在源配置页面看到 pixiv 源并填入我的 refresh_token，以便让系统能访问我的 pixiv 账号数据。
2. 作为一个 ComicFeed 用户，我想要对 pixiv 源执行「测试连接」，以便确认 refresh_token 有效、能取到 access_token。
3. 作为一个 ComicFeed 用户，我想要凭证（refresh_token）被加密存储，以便凭据不落明文。
4. 作为一个 ComicFeed 用户，我想要粘贴画师主页 URL 创建 pixiv「特定画廊」订阅，以便自动收集该画师的作品。
5. 作为一个 ComicFeed 用户，我想要粘贴榜单 URL（如插画日榜、动图周榜）创建 pixiv 订阅，以便自动收集榜单上的作品。
6. 作为一个 ComicFeed 用户，我想要粘贴 R-18 榜单 URL 创建订阅，以便在账号开启 R-18 显示后收集 R-18 榜作品。
7. 作为一个 ComicFeed 用户，我想要画师订阅首次检查时自动建立完整作品集（受订阅的搜索深度上限保护），以便一次到位、无需手工补录。
8. 作为一个 ComicFeed 用户，我想要画师订阅后续巡检只翻最新一页并按作品 ID 差集增量追加新作品，以便巡检轻量、更新及时。
9. 作为一个 ComicFeed 用户，我想要榜单订阅每次检查只取榜单第一页（约 30 个作品）并跳过已收录作品，以便榜单 Gallery 只增不缩、不重复下载。
10. 作为一个 ComicFeed 用户，我想要同一画师同时发布单页插画和多页漫画时全部页都被收录，以便内容完整、不丢失任何页面。
11. 作为一个 ComicFeed 用户，我想要动图作品自动转换为动画 WebP 并作为单页混排进 CBZ，以便动图也能进入 Komga 索引、与静态页同卷保存。
12. 作为一个 ComicFeed 用户，我想要新作品增量追加到已有 CBZ 的最后一卷、卷满自动开新卷，以便长期收集一个画师而不破坏已下载的旧卷。
13. 作为一个 ComicFeed 用户，我想要订阅的筛选条件（收藏数≥、页数≥、上传日期≤）对 pixiv 按作品逐个生效，以便只收录符合我兴趣的作品。
14. 作为一个 ComicFeed 用户，我想要画师 Gallery 的标题显示为「画师名(画师id)」，以便在画廊页和 CBZ 文件名中一眼识别画师。
15. 作为一个 ComicFeed 用户，我想要榜单 Gallery 的标题显示为「Pixiv {内容}{周期}榜」，以便区分不同榜单的收藏。
16. 作为一个 ComicFeed 用户，我想要作品标签优先使用官方中文翻译、缺失时回退日文原文，以便在画廊页和 ComicInfo.xml 中看到可读的中文标签。
17. 作为一个 ComicFeed 用户，我想要在画廊页点击「打开源站链接」跳到对应的 pixiv 作品/画师页面，以便溯源。
18. 作为一个 ComicFeed 用户，我想要在搜索页对 pixiv 执行关键词搜索并浏览结果，以便快速发现内容并保存为订阅。
19. 作为一个 ComicFeed 用户，我想要下载请求带上正确 Referer 并以 app 客户端身份请求，以便图片和接口不被 403 拒绝。
20. 作为一个 ComicFeed 用户，我想要系统在遇到 429 限流时指数退避并遵循 Retry-After，以便巡检在 pixiv 限流下仍能稳定完成。
21. 作为一个 ComicFeed 用户，我想要 access_token 在进程内自动刷新（refresh_token 换新），以便长期运行无需人工重新授权。
22. 作为一个 ComicFeed 用户，我想要个别已删除/受限作品被跳过并记录日志而不阻塞整体检查，以便巡检健壮。
23. 作为一个 ComicFeed 用户，我想要 CBZ 分卷上限、输出目录、代理等全局设置对 pixiv 订阅照常生效，以便行为与现有源一致。

## Implementation Decisions

- **新源插件**：pixiv 实现为独立 Source 插件（ADR 0001 模型），`key="pixiv"`、`AuthSchema.TOKEN`，无沙箱、随启动扫描加载。
- **Gallery 映射语义**：画师 = 一个 Gallery（native_id 为**纯数字 uid**），榜单 = 一个 Gallery（native_id 为 `ranking_{mode}_{content}`，mode 可含下划线、content ∈ all/illust/manga/ugoira；all=综合榜全类型混排）；Gallery 的页面 = 作品的全部页。这是 pixiv 源与现有两个源的语义差异，仅存在于源插件内部，不改动系统 Gallery 模型。
- **页面 ID 与增量**：插画/漫画页的 page_native_id 为 `{illust_id}_p{n}`，动图页为 `{illust_id}_webp`；`check_updates` 按作品 ID 差集返回 `new_page_ids`，复用现有「新页追加到最后 CBZ 卷」的增量机制。
- **页序**：画师 Gallery 按作品 ID 升序（旧→新，新作自然追加到末尾）；榜单 Gallery 按首次收录顺序。
- **榜单检查边界**：榜单订阅每次检查只取第一页；按作品 ID 在画廊内去重（该榜单 Gallery 中已收录的作品永不再收录于其中；不同榜单 Gallery 之间不做跨画廊去重，物理上各存各卷）。
- **画师检查深度**：首次检查翻全部作品页（受订阅 `max_search_pages` 上限保护：0=只翻第 1 页；1（订阅默认）=翻到底；≥2=上限 N 页）；后续巡检只翻第 1 页做差集。
- **筛选语义**：订阅的筛选条件（收藏数/页数/上传日期）对 pixiv 按**作品**逐个应用，不达标的作品不收录；收藏数使用 app-api 的公开收藏数（`total_bookmarks`），页数使用作品页数。
- **认证**：refresh_token OAuth 2.0（X-Client-Time/X-Client-Hash 签名头），access_token 进程内缓存、过期自动用 refresh_token 换新；不做密码登录（reCAPTCHA 风控）、不做 PHPSESSID 通道。
- **API 端点**：`/v1/illust/ranking`（榜单）、`/v1/user/illusts`（画师作品）、`/v1/illust/detail`（详情与页 URL）、`/v1/ugoira/metadata`（动图帧与 delay）、`/v1/search/illust`（搜索页最小透传）。
- **画质选项**：源配置暴露「画质」下拉（original 默认 / large 600×1200 / medium 540×540）。**只用 API 原生字段**：多页用 `meta_pages[i].image_urls`，单页用顶层 `image_urls`（p0）；字段缺失或未知画质回退原图。不做 URL 变换（实测 pixiv 对未达尺寸的图不生成对应档位，变换会 404）；动图（ugoira）固定用官方帧包不受影响。
- **动图转换**：下载 ugoira 帧 zip（带 Referer）→ 按 metadata 的 frames 顺序与 delay（毫秒）用 Pillow 合成动画 WebP（save_all + duration），作为单页 bytes 交给打包流程；不做 GIF/APNG 输出。转换失败的作品跳过、不阻塞同画廊其余作品，但**记录为失败下载事件（作品标题 + 原因）**，进入摘要通知的失败汇总（沿用现有每订阅 ≤5 条的展示上限）。跳过清单带画廊归属、由源回传给下载服务、由下载服务按当前画廊匹配后写事件（源不直接写持久化；通过向后兼容的可选钩子，现有源零改动）。
- **标签翻译**：所有 app-api 请求带 `Accept-Language: zh-hans`（实测 `zh-cn` 被服务端忽略、返回英文默认翻译）。选译规则：`translated_name` **含汉字**才采用（官方中文）；否则回退 `name`（日文原文）——官方翻译表对角色名/作品名常给罗马音或英文（如 `九条裟羅→Kujou Sara`、`原神→Genshin Impact`），对中文用户不如原文；原文无汉字的标签直接丢弃（`_pick_tag` 返回 None）。里程碑标签（`\d+users入り` 及其翻译形态 `\d+收藏`）直接丢弃。v1 不接 EhTagTranslation。
- **元数据**：画师 Gallery 标题 `画师名`（不带 id 后缀）、writer=画师名、封面不特殊处理；榜单 Gallery 标题 `Pixiv {内容}{周期}榜`、writer 为空；作品标题经 `normalize_title` 归一化（无官方翻译字段）。**展示 ID**（`GalleryDetail.display_id`）：画师用纯数字 uid 进入 CBZ 文件名与 ComicInfo Number；榜单为非数字 ID，文件名省略 `[id]` 前缀、ComicInfo Number 留空（增量追加拿标题匹配旧卷）。
- **URL 解析**：`parse_url` 识别画师主页与榜单 URL（含 R-18 模式），web 榜单 mode 参数映射到 app-api mode（如 `daily_r18` → `day_r18`）；app-api 无等价物的模式（如 `daily_r18g`，app 端仅有周 R-18G）明确报错而非静默错榜；订阅走现有「特定画廊」贴 URL 流程。
- **R-18 策略**：R-18 作品/榜单直接通过 app-api 获取，取决于账号的「显示 R-18/R-18G」设置；源配置 hint 文案说明该依赖；未开启时 R-18 被 pixiv 静默过滤，源不做额外标记或告警。
- **网络行为**：模拟 iOS App UA + `Referer: app-api.pixiv.net`；图片下载复用 `retry_get`（429 指数退避 + Retry-After + 永久错误不重试）；页间节流默认 0.1s（源配置「请求间隔」可调，0/- 关闭）；API 翻页间 0.5s；429 触发全局冷却（后续请求先等待 30s）；代理沿用现有源级/全局代理机制。
- **Web 层改动**：画廊页「打开源站链接」增加 pixiv 分支（native_id → 对应 pixiv 页面）；新增 `/api/cover` 封面代理（pixiv 图片服务器防盗链要求 Referer 为 pixiv 域，浏览器直连 403；仅放行 i.pximg.net 主机、带内存缓存、认证豁免），模板中 pixiv 封面统一走该代理；其余（配置表单、订阅创建、搜索页）复用通用流程。
- **search() 实现**：透传 `/v1/search/illust` 的最小可用实现（复用同一解析器），供 WebUI 搜索页使用；订阅创建不为 pixiv 引导 SEARCH 模式。
- **无 schema 变更**：不新增表/列，不动 Gallery/Page 模型。

## Testing Decisions

- **好测试的标准**：只测外部可观察行为——接口方法的返回结构、输出字节的合法性、SourceManager 加载结果、URL 解析映射——不测内部 HTTP 细节、不断言私有实现。
- **接缝**：全部测试走 `BaseSource` 接口这一条最高接缝（离线样本 JSON fixture），不新增接缝；不触真实网络（pixiv 需要 refresh_token，无法进离线测试）。
- **测试模块**：pixiv 源的解析与行为（榜单 JSON 解析、画师列表解析、多页作品详情解析、标签翻译回退、check_updates 差集与榜单 1 页边界、parse_url 各形态、搜索透传）；SourceManager 对 pixiv 插件的加载/校验。
- **动图测试**：用内存构造的帧 zip + metadata fixture 驱动转换，断言输出为合法动画 WebP（Pillow 可打开、帧数 > 1、魔数正确），不触网。
- **先例**：对齐现有 `test_nhentai.py`（样本 JSON 驱动的解析器级测试）与 `test_sources.py`（SourceManager 加载与校验测试）的风格。

## Out of Scope

- **SEARCH 模式订阅**：关键词搜索仅作为搜索页功能透传实现，不引导、不支持创建 pixiv 关键词订阅。
- 收藏（bookmarks）、关注（following）订阅。
- PHPSESSID cookie 通道、密码登录、第三方镜像站兜底。
- EhTagTranslation 翻译兜底（官方 translated_name 缺失时回退日文原文）。
- Series/章节层级模型（不引入新表）。
- 已收录作品的**页级**增量（作品本身补页的追踪）：v1 按作品粒度去重，作品一旦收录不再检测其页数变化。
- 人气排序与私有收藏数筛选（premium-only 能力）。
- 动图的 GIF/APNG 输出与静态拼接输出。
- 画廊页/通知中对 R-18 作品的特殊标记。

## Further Notes

- 调研已确认：R-18 的显示由账号设置控制而非 premium；「R-18 搜索/榜单需要 premium」为过时 lore。真正 premium-only 的是人气排序与收藏数筛选（本 spec 未使用）。
- `Accept-Language` 已实测：`zh-cn` 不生效（返回英文翻译），`zh-hans` 生效（官方中文）。其余不确定项：refresh_token 有效期（官方不公布）；数据中心 IP 403（社区报告，需用户环境实测）。
- Komga 官方文档确认 GIF/WebP 均为支持的 CBZ 页格式；动画是否播放取决于客户端。
- pixiv 官方 translated_name 覆盖有限，小众/R-18 标签常为 null，回退日文原文是预期行为。
- 源可执行任意代码（ADR 0001 无沙箱），pixiv 源仅使用仓库既有依赖（curl_cffi/httpx/Pillow），不引入新依赖。
