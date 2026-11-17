# MissKON 替代源调查

核实日期：2026-11-17（Asia/Hong_Kong）。

用户已取消 MissKON 接入。本次仅调查替代站点；接受条件为免费、公开、无需会员登录，并能通过网页或 API 获取全集图片。搜索关键词为 `Machi馬吉`、`miko酱ww`、`小仓千代w`。用户随后指定比较 Cosplaytele，并确认其 `mikomikoww` 与 `miko酱ww` 是同一作者。

## 结论

[4KHD](https://www.4khd.com/) 是目前证据最充分的候选。三个关键词均有相册；核对的六篇近期相册，正文图片数量均与标题标注一致。每个关键词选取一篇，共 230 个唯一图片链接，均通过匿名 HTTP 检查，且编号连续、无缺号。

补充调查的 [Cosplaytele](https://cosplaytele.com/) 也可通过匿名 WordPress API 读取站内全部相册图片。六篇样本共 406 个图片链接均可访问，数量与该站标题声明一致。就用户指定的三位作者而言，建议以 4KHD 为主；若接入两个站，Cosplaytele 可作为独立备用或补充源。只接入一个时优先 4KHD。

后续指定的 4KUP 尚缺公开全集证据；Hentai Cosplay 的普通请求当前可以访问，但内容重复与作者发行完整度未核实，暂不建议优先于上述两个候选。视频下载和跨源去重均已被用户排除在当前接入范围之外。

这里的“全集”指图片数量符合站内相册声明，并非已与作者原始发行内容逐张比对。公开图片是经过处理的版本，抽样实测宽 1300 像素；不能据此承诺原始分辨率或无损图片。站点还提供网盘压缩包入口，本结论不依赖这些入口。

## 4KHD 的直接证据

相册网页提供 `application/json` 链接，指向 WordPress REST API。下列文章接口均匿名返回 HTTP 200，`content.protected` 为 `false`；`content.rendered` 包含全篇图片，即使网页本身分页，也不需要逐页拼接图片列表。

| 关键词 | 相册与站点发布日期 | 标题张数 | API 唯一图片数 | 全部链接 HTTP 检查 | 文章 API |
| --- | --- | ---: | ---: | --- | --- |
| Machi馬吉 | [大黑塔 水着 Swimsuit The Herta 2](https://www.4khd.com/content/06/machi-magee-big-black-tower-water-swimsuit-the-herta-2.html)，2026-11-06 | 129 | 129 | 129/129 成功，001–129 连续 | [74323](https://www.4khd.com/wp-json/wp/v2/posts/74323) |
| miko酱ww | [甘古特](https://www.4khd.com/content/12/miko-sauce-ww-gangut.html)，2026-11-12 | 28 | 28 | 28/28 成功，001–028 连续 | [74506](https://www.4khd.com/wp-json/wp/v2/posts/74506) |
| 小仓千代w | [Fantia 2026 年 7 月会员订阅合集](https://www.4khd.com/content/10/chiyo-ogura-w-fantia-july-2026-membership-subscription-collection.html)，2026-08-10 | 73 | 73 | 73/73 成功，001–073 连续 | [71655](https://www.4khd.com/wp-json/wp/v2/posts/71655) |

小仓相册标题中的“会员订阅”描述作品合集名称；上表 4KHD API 和图片链接本身无需登录或付费。

另外核对三篇相册的正文数量，下列样本没有逐个检查全部图片链接：

| 相册 | 站点发布日期 | 标题张数 / API 唯一图片数 | 文章 API |
| --- | --- | --- | --- |
| [Machi馬吉 — Castorice Swimsuit](https://www.4khd.com/content/23/machi%e9%a6%ac%e5%90%89castoriceswimsuit.html) | 2026-10-23 | 131 / 131 | [73907](https://www.4khd.com/wp-json/wp/v2/posts/73907) |
| [miko酱ww — 胜利女神：妮姬 玛律恰娜](https://www.4khd.com/content/25/miko-sauce-ww-victory-goddess-nikki-maruchana.html) | 2026-10-25 | 34 / 34 | [73975](https://www.4khd.com/wp-json/wp/v2/posts/73975) |
| [小仓千代w — 2026 年 05 月 Fantia 订阅](https://www.4khd.com/content/06/ogura-chiyo-w-may-2026-fantia-subscription.html) | 2026-08-06 | 141 / 141 | [71546](https://www.4khd.com/wp-json/wp/v2/posts/71546) |

早期样本 [MACHI 馬吉](https://www.4khd.com/content/28/machi.html)（2025-10-28）标题标注 257 张，[API 62451](https://www.4khd.com/wp-json/wp/v2/posts/62451) 正文同样包含 257 张，编号 001–257。网页分为 13 页，API 一次返回全篇。因此可用性不只基于 2025 年文章。

### 匿名图片访问验证

验证时未提供账号、登录 Cookie 或授权令牌：

- 对 74323、74506、71655 正文中的全部 230 个唯一 `img[src]` 发起 HEAD 请求，全部返回 HTTP 200 和 `Content-Type: image/jpeg`。
- 对这三篇各自的首张、中间张、末张，共九张图片发起 GET，并在内存中用图片解码器核实尺寸和格式；九张均成功解码为 JPEG。未保存或展示图片内容。
- 74323 的抽样编号为 001、065、129，尺寸均为 1300 × 1733。
- 74506 的抽样编号为 001、015、028，尺寸均为 1300 × 1950。
- 71655 的抽样编号为 001、037、073，尺寸分别为 1300 × 1711、1300 × 1733、1300 × 1733。

图片 URL 使用 `i0.wp.com/pic.4khd.com/…/w1300-rw/…webp?w=1300`。扩展名与实际响应格式不一致；未来接入时应按响应内容处理格式。未验证绕过图片处理参数能否获得作者原图。

### 查询入口

站内搜索存在 [Machi馬吉](https://www.4khd.com/search/Machi%E9%A6%AC%E5%90%89)、[miko酱ww](https://www.4khd.com/search/miko%E9%85%B1ww)、[小仓千代w](https://www.4khd.com/search/%E5%B0%8F%E4%BB%93%E5%8D%83%E4%BB%A3w) 的结果。

公开文章列表 API 支持搜索，例如 [miko酱ww 的文章查询](https://www.4khd.com/wp-json/wp/v2/posts?search=miko%E9%85%B1ww&per_page=2)。本次以每个关键词最新两条结果核对文章元数据与正文，没有遍历全站相册。

## Cosplaytele 的直接证据

与 4KHD 一样，Cosplaytele 的相册网页提供指向 WordPress 文章 API 的 `application/json` 链接，例如 [大黑塔水着 Part 2 网页](https://cosplaytele.com/the-herta-swimsuit-2/) 声明 [API 532940](https://cosplaytele.com/wp-json/wp/v2/posts/532940)。下列六篇文章接口均匿名返回 HTTP 200，`content.protected=false`，`content.rendered` 内含全部站内图片。

| 作者与相册 | 站点发布日期 | 标题张数 / API 唯一图片数 | 全部链接 HTTP 检查 | 文章 API |
| --- | --- | --- | --- | --- |
| [Machi馬吉 — The Herta Swimsuit Part 2](https://cosplaytele.com/the-herta-swimsuit-2/) | 2026-11-14 | 90 / 90 | 90/90 成功 | [532940](https://cosplaytele.com/wp-json/wp/v2/posts/532940) |
| [Machi馬吉 — Evanescia](https://cosplaytele.com/evanescia/) | 2026-11-07 | 99 / 99 | 99/99 成功 | [531946](https://cosplaytele.com/wp-json/wp/v2/posts/531946) |
| [小仓千代w — Aemeath](https://cosplaytele.com/aemeath-5/) | 2026-08-05 | 76 / 76 | 76/76 成功 | [518092](https://cosplaytele.com/wp-json/wp/v2/posts/518092) |
| [小仓千代w — Shinano](https://cosplaytele.com/shinano-5/) | 2025-05-20 | 37 / 37 | 37/37 成功 | [450351](https://cosplaytele.com/wp-json/wp/v2/posts/450351) |
| [Miko酱 (mikomikoww) — Yae Miko](https://cosplaytele.com/yae-miko-45/) | 2024-08-09 | 63 / 63 | 63/63 成功 | [345202](https://cosplaytele.com/wp-json/wp/v2/posts/345202) |
| [Miko酱 (mikomikoww) — Kagarino Kirie](https://cosplaytele.com/kagarino-kirie/) | 2024-04-06 | 41 / 41 | 41/41 成功 | [271541](https://cosplaytele.com/wp-json/wp/v2/posts/271541) |

验证方式与范围：

- 未提供账号、登录 Cookie 或授权令牌，对全部 406 个唯一图片链接发起 HEAD 请求，均返回 HTTP 200 和图片 Content-Type。
- 每篇选取正文首张、中间张、末张，共 18 张，匿名 GET 读取前 4096 字节，从 WebP 文件头核实格式与尺寸；没有完整下载或展示这些图片。
- 五篇样本的正文文件编号顺序为 1–N；Shinano 的正文顺序为 37–1，编号集合同样完整。因此未来提取图片列表不能把正文倒序误判成缺图，也不应未经约定改变网页原有顺序。
- 图片来自 `cosplaytele.com/wp-content/uploads/…/*_result.webp`，无需依赖相册末尾的 Telegram 或网盘下载入口。

### 图片尺寸对比

Cosplaytele 的公开图片是 WebP。实际文件头抽样得到：

| 样本 | 抽样尺寸 |
| --- | --- |
| Machi — The Herta Swimsuit Part 2 | 1600 × 1200、2133 × 1600、1200 × 1600 |
| Machi — Evanescia | 三张均为 1200 × 1600 |
| 小仓 — Aemeath | 1200 × 1600、2133 × 1600、1200 × 1600 |
| 小仓 — Shinano | 1224 × 1600、1293 × 1600、1212 × 1600 |
| Miko — Yae Miko | 1067 × 1600、1067 × 1600、900 × 1600 |
| Miko — Kagarino Kirie | 800 × 1200、800 × 1200、801 × 1200 |

不能用“Cosplaytele 1600 像素、4KHD 1300 像素”直接比较画质，两个数字可能指不同方向。此前 4KHD 竖图实测为 1300 × 1733 或 1300 × 1950，而 Cosplaytele 多数竖图约 1200 × 1600；Cosplaytele 某些横图更大，旧图也可能更小。两站均未验证作者原图版本，亦未对同一张照片做清晰度或压缩损失比较。

### 三位作者的覆盖与更新

以下是同日文章列表 API 的搜索命中数，来自 `X-WP-Total`。数字代表关键词匹配文章数，不等于逐篇验证后的完整、独立作品套数；发布日期为站点文章日期，不是作者原始作品发行日期。

| 作者 | 4KHD 查询、命中数、最新日期 | Cosplaytele 查询、命中数、最新日期 |
| --- | --- | --- |
| Machi馬吉 | [Machi馬吉](https://www.4khd.com/wp-json/wp/v2/posts?search=Machi%E9%A6%AC%E5%90%89&per_page=1)：35，2026-11-06 | [Machi馬吉](https://cosplaytele.com/wp-json/wp/v2/posts?search=Machi%E9%A6%AC%E5%90%89&per_page=1)：26，2026-11-14 |
| miko酱ww / mikomikoww | [miko酱ww](https://www.4khd.com/wp-json/wp/v2/posts?search=miko%E9%85%B1ww&per_page=1)：62，2026-11-12 | [mikomikoww](https://cosplaytele.com/wp-json/wp/v2/posts?search=mikomikoww&per_page=1)：9，2024-08-09 |
| 小仓千代w | [小仓千代w](https://www.4khd.com/wp-json/wp/v2/posts?search=%E5%B0%8F%E4%BB%93%E5%8D%83%E4%BB%A3w&per_page=1)：126，2026-08-10 | [小仓千代w](https://cosplaytele.com/wp-json/wp/v2/posts?search=%E5%B0%8F%E4%BB%93%E5%8D%83%E4%BB%A3w&per_page=1)：14，2026-08-05 |

Cosplaytele 直接搜索 `miko酱ww` 返回零条，换成 `mikomikoww` 或 `miko酱` 返回九条；不能将精确名字未命中解释为该站未收录此作者。用户已确认两种名字对应同一作者。

### “站内全集”与发行版本的差别

两站 Machi 的大黑塔水着 Part 2 标题指向相近主题，但 [4KHD](https://www.4khd.com/wp-json/wp/v2/posts/74323) 标注并返回 129 张，[Cosplaytele](https://cosplaytele.com/wp-json/wp/v2/posts/532940) 标注并返回 90 张。此差异说明，仅用“正文数量等于标题数量”不能保证获得作者原始发行全集。

尚未逐张比对两站照片、核实原始发行清单或压缩包，因此不将这 39 张差异断言为 Cosplaytele 缺图，也不认定两篇必然为相同版本。以当前可见数量为依据，这一主题更适合优先使用 4KHD。

### 是否做成两个源

建议两个站分别作为独立 Source，4KHD 优先，Cosplaytele 用于备用或补充；只做一个时选择 4KHD。依据是指定作者在 4KHD 的覆盖更广，而两个站的匿名 API 与全篇图片获取方式接近。此建议不承诺二者内容互补的比例，也不保证 Cosplaytele 在某一作者上更新更快。

当前 `BaseSource` 已支持独立源的搜索、画廊详情和页面下载接口，两站均可将 WordPress 文章 ID 映射为原生画廊 ID。证据：[源接口](../../comicfeed/sources/base.py)、[源加载器](../../comicfeed/infrastructure/source_manager.py)。本次没有编写适配器。

需要明确双源对去重的影响：当前 [`existing_titles`](../../comicfeed/repositories/gallery.py) 按 `source_key` 查询已有标题，[搜索订阅服务](../../comicfeed/services/subscription.py) 也按当前源加载标题；[下载服务](../../comicfeed/services/download.py) 使用 `{source.key}:{gallery_id}` 作为画廊 ID。因此增加两个源不会自动合并跨站同一套照片。若同时订阅同一作者，可能重复下载；跨源去重应作为另外的需求评估，不应在添加源时隐含扩展实现范围。

用户已于 2026-11-17 明确决定：本次不考虑跨源去重，由用户自行管理。此项不作为双源接入的阻塞条件。

## Cosplaytele 视频可下载性

当前范围：用户已于 2026-11-17 决定暂不考虑视频下载。以下保留已完成的可行性调查，不作为本次接入需求。

用户随后询问能否同时下载相册中的视频。本次核实了 [Machi馬吉 — Cyrene](https://cosplaytele.com/wp-json/wp/v2/posts/506130) 样本（站点发布日期 2026-07-27）：标题标注 104 张图片与 1 个视频；API 正文包含 104 个图片元素和 1 个指向 `cossora.stream` 的 iframe，没有直接的 MP4 链接。

### 媒体访问证据

- 外部播放器不带站点 Referer 时，本次请求返回 HTTP 404；带 `Referer: https://cosplaytele.com/` 后返回 HTTP 200 播放页，未提供登录账号、登录 Cookie 或授权令牌。
- 播放页使用 JW Player 和 CryptoJS，视频地址需按公开播放器脚本中的链接解码逻辑解析。解析得到的媒体接口返回 HTTP 200，Content-Type 为 `application/vnd.apple.mpegurl`，实际是 HLS 播放清单，而非播放器标题中显示的单个 MP4 文件。
- 主清单为合法 `#EXTM3U`，公开提供一个 2386 × 1704 的视频档位，声明带宽为 7,984,123 bit/s。
- 对应媒体清单匿名返回 HTTP 200，共 14 个分片，声明总时长 203.983 秒，包含 `#EXT-X-ENDLIST`；清单未声明媒体加密方法。
- 首个和末个分片的 HEAD 请求均返回 HTTP 200、`Content-Type: video/mp2t`，声明大小分别为 15,790,120 字节和 9,432,900 字节。

上述请求仅核实播放器、脚本、文本清单与分片响应头，没有完整下载或播放视频，也没有逐个读取全部 14 个分片。证据支持该样本可以通过匿名 HLS 路径实现视频下载，但不构成全站所有视频均有效或完整下载已通过的保证。播放器解码规则和媒体地址可能变化，未来应在下载时重新解析，不能长期缓存本次地址。

### 项目现状与建议

当前 [`GalleryDetail`](../../comicfeed/sources/base.py) 仅定义图片页列表，`download_pages` 返回页字节列表；[页面下载器](../../comicfeed/io/page_fetcher.py) 按页缓存，[CBZ 打包器](../../comicfeed/io/cbz.py) 只识别图片扩展名，未知内容会回退为 `.jpg`。现有 `read_cbz_pages` 也会将 ZIP 中所有非 XML 文件计入页面。因此不能直接将 MP4 或 TS 分片混入图片页列表或 CBZ。

建议作为独立的视频附件流程接入：图片继续打包 CBZ；HLS 视频按公开档位获取并合并封装为独立视频文件，放在该画廊对应的视频目录中，与 CBZ 建立清晰的命名关联。尽量保留源视频质量，通常可通过 FFmpeg 合并封装而无需重编码；若实际编码无法直接封装为 MP4，再明确处理策略。当前开发机 PATH 中已有 FFmpeg，但仍需考虑运行项目的其他环境是否具备该依赖。

视频不计入图片页数与 CBZ 分卷。建议失败时保留已经完成的图片文件，明确记录视频失败并允许重试，避免将缺少视频的结果无提示地视为完整完成。视频存放布局、失败状态和运行环境依赖尚未形成用户确认的实现规格；本次仅完成可行性核实，没有修改源接口或下载流程。

## 4KUP 补充调查

用户指定的 [4KUP](https://4kup.net/) 首页与 WordPress REST API 均能通过普通匿名 HTTP 请求访问。本次首页返回 HTTP 200，服务端使用 Cloudflare，但没有返回验证页。

### 收录与公开正文

文章搜索接口支持三个作者关键词：[Machi馬吉](https://4kup.net/wp-json/wp/v2/posts?search=Machi%E9%A6%AC%E5%90%89&per_page=1) 命中 17 条，[miko酱ww](https://4kup.net/wp-json/wp/v2/posts?search=miko%E9%85%B1ww&per_page=1) 命中 95 条，[小仓千代w](https://4kup.net/wp-json/wp/v2/posts?search=%E5%B0%8F%E4%BB%93%E5%8D%83%E4%BB%A3w&per_page=1) 命中 147 条。这里的搜索命中不代表完整相册套数。Machi 使用更宽的 [Machi 查询](https://4kup.net/wp-json/wp/v2/posts?search=Machi&per_page=1) 命中 29 条，最新文章为 2026-11-04；仅使用 `Machi馬吉` 会漏掉使用其他名称写法的近期文章。

本次检查了六篇按原关键词取得的文章，以及一篇近期 Machi 文章。API 均返回 HTTP 200，正文不受密码保护；但公开图片数量较少，未找到可靠的原始发行张数声明。进一步核对三个近期样本的 API 正文与网页：

| 4KUP 样本 | 站点发布日期 | API 正文公开图片数 | 可比较的其他站样本 |
| --- | --- | ---: | --- |
| [Machi 近期文章 53385](https://4kup.net/wp-json/wp/v2/posts/53385) | 2026-11-04 | 18 | 未逐张比对其他站版本 |
| [miko酱ww — NIKKE 玛律恰娜 53281](https://4kup.net/wp-json/wp/v2/posts/53281) | 2026-10-27 | 19 | [4KHD 同主题 73975](https://www.4khd.com/wp-json/wp/v2/posts/73975) 为 34 张 |
| [小仓千代w — Fantia 2026 年 7 月 52394](https://4kup.net/wp-json/wp/v2/posts/52394) | 2026-08-19 | 20 | [4KHD 对应月份合集 71655](https://www.4khd.com/wp-json/wp/v2/posts/71655) 为 73 张 |

这三篇的真实图片地址位于 `img[data-src]`，`src` 是重复的内嵌占位图。提取 `data-src` 后分别得到 18、19、20 个唯一 URL，图片来自 `blogger.googleusercontent.com`，HTML 声明的尺寸常见约 1200 × 1600 或 1067 × 1600；本次没有下载或解码图片核实实际尺寸。

三个样本的正文均提供 `1024terabox.com` 下载入口；API 正文没有后续图片页链接，网页检查也未发现 `.page-links` 内的后续页。本次没有访问网盘、下载压缩包，也未发现其他匿名接口能补齐站外同主题相册的张数。

### 判断

4KUP 的公开接口好接入，作者收录较多，但目前证据更接近“少量公开图片加网盘下载入口”，尚不符合本次要求的可验证网页/API 全集。跨站数字差异仍可能包含版本差异，因此不直接断言每篇必然缺图；不过在取得完整性证据前，不建议将它纳入首批源。

## Hentai Cosplay 补充调查

用户指定的 [Hentai Cosplay](https://hentai-cosplay-xxx.com/) 需去掉原消息链接结尾误带的中文句号。用户关心两个问题：内容重复和 Cloudflare 反爬。本次仅检查目录元数据、HTML 获取方式及响应头，没有下载、展示或逐张比对该站图片。

### 普通 HTTP 可访问性

- 首页使用 Cloudflare，本次匿名 GET 返回 HTTP 200，并取得实际目录 HTML。
- 首页出现 `/cdn-cgi/challenge-platform/scripts/jsd/` 的 Cloudflare JavaScript Detection 脚本；没有 `Just a moment` 验证页，也没有 `cf-mitigated: challenge`。不能把脚本存在本身等同于当前请求被反爬拦截。
- 页面搜索表单声明 `POST /default/images/process-search/`，字段为 `keyword`。按页面表单提交 `mikomikoww` 后取得正常搜索页，HTTP 200，本页包含 25 个独立图集链接。
- 从该搜索页取得的 [Mikomikoww — C.C. 样本](https://hentai-cosplay-xxx.com/image/mikomikoww-cc/) 也返回 HTTP 200；正文 `.icon-overlay` 内包含 9 个图片链接，另有推荐图集缩略图和语言图标，不能把整页所有 `img` 都计入相册。
- 样本中两个图片链接的 HEAD 请求，在带来源页 Referer 时均返回 HTTP 200 和 `image/webp`，图片位于 `static17.hentai-cosplay-xxx.com`。没有请求图片正文。

因此 Cloudflare 在本次普通请求中没有成为阻塞条件，也没有证据说明当前必须引入浏览器或额外的挑战处理服务。以上只是当前访问环境下的少量样本，不代表长期定时任务、其他出口 IP 或所有图片节点都不会触发验证。

### 重复与完整度

首页按图集 URL 去除同一目录项的重复链接后，本次取得 71 个独立图集，未发现完全相同标题的不同图集；`mikomikoww` 搜索页的 25 个图集，原始标题及按项目 `normalize_title` 归一化后的标题也没有完全重复。这只能描述标题，不能否定用户观察到的图片内容重复，也不能据此计算图片重复率。

当前项目的标题去重依赖非常高的字符串相似度。不同标题、不同语言写法、拆分或重新上传的同一套照片，不能依靠原生图集 ID 或现有标题规则可靠识别。若未来采用此源，应该把这类内容重复与用户自行管理的使用成本讲清楚，而不是承诺现有去重已经覆盖。

本次样本有 9 个公开图片链接，页面也提供单独的图片下载入口，但未核实作者原始发行全集及该入口能否匿名返回完整压缩包。没有发现像前两个候选那样可直接使用的 WordPress 文章 API；当前证据主要支持按自定义 HTML 提取图集，仍不足以保证获取作者发行全集。

### 判断

此站当前访问情况比“有 Cloudflare 就不能抓取”更好，但不能把当前 HTTP 200 当作长期稳定保证。内容重复与发行完整度尚未得到图片层面的验证，加上独立 HTML 解析规则的维护需求，暂不建议排在 4KHD、Cosplaytele 前面。用户已排除跨源去重与视频下载，本次不会为了这个候选扩展相关功能。

## 其他站点

| 站点与直接样本 | 观察结果 | 本次判断 |
| --- | --- | --- |
| 秀色女神：[miko酱ww 2026 年 04 月订阅](https://www.xsnvshen.com/album/57450) | 标题标注 188P，网页正文明确写共 120 张、12 页；标题与实际收录数量不符。另有 [机械姬 25P](https://www.xsnvshen.com/album/52163) 样本数量一致，但未进一步验证全部链接。 | 暂不作为可靠全集源推荐；不据单篇推断全站每篇均不完整。 |
| 玩图志：[mikojiangww-remilia](https://wantuzhicos.com/mikojiangww-remilia) | 标注 26 张，公开内容为少量预览，网页明确提示付费后查看，价格 9.9，完整版走网盘。 | 不符合免费公开全集要求。 |
| 四五美图：[相册 1301488](https://45mt.com/1301488.html) | 标注 164 张，公开正文仅 6 张，隐藏内容要求 10 金币或 VIP。 | 不符合免费公开全集要求。 |
| 柚子肉：[miko 2026 年 4 月](https://www.youzirou.org/product/3704)、[小仓僵尸娘](https://www.youzirou.org/product/3347) | 分别标注 188P、45P，初始 HTML 只有部分压缩预览；下载提示 50 金币。存在“查看全部”入口，但本次未核实其读取接口是否匿名返回全部图片。 | 未确认，不将“付费下载”等同于“不能免费在线看全集”。 |

## 适用范围

推荐优先考虑 4KHD 的公开图片版本，Cosplaytele 可作为第二个独立源。现有证据覆盖 4KHD 七篇与 Cosplaytele 六篇的图片数量，以及前者三篇、后者六篇的全部链接可用性；未证明全站每篇都完整，也未证明图片与作者原始发行版本一一对应。当前没有开始接入新的项目源，亦未改动现有源代码。
