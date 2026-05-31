# ComicFeed — 领域术语表

一个从多漫画源自动抓取、去重、打包为 CBZ 的订阅系统。通过 WebUI 管理订阅和源配置，下载内容由 Komga 索引。

---

## 源 (Source)

漫画数据提供商。一个源是一个 Python 模块，放置于 `sources/` 目录，实现 `BaseSource` 定义的接口。ComicFeed 内置的源包括 exhentai、nhentai 等。

每个源声明自己：
- **域名列表** (`domains`)：可用的 API 域名，系统自动探测可用
- **动态域名刷新** (`resolve_domain()`)：可选的钩子，在域名全部不可用时从外部渠道获取新域名
- **认证模式** (`auth_schema`)：声明需要什么凭证（cookie / username+password / token / 无）
- **代理需求**：可配独立的 HTTP/SOCKS5 代理及认证凭证

用户在 WebUI 可为每个源：
- 手动覆盖域名
- 填入凭证
- 配置独立代理
- 点击"测试连接"验证凭证和域名是否可用

添加源的方式：手动放置 `.py` 文件到 `sources/`、WebUI 上传、或从 URL 拉取。

## 画廊 (Gallery)

一个可下载的图片集合，是最小下载单位。无论源如何称呼其内容（画廊/漫画/章节），都映射为 Gallery。

关键属性：
- **统一 ID**：格式 `{source_key}:{native_id}`，如 `exhentai:1234567`
- **归一化标题**：爬取时即去除括号标签 `(C97)` `[Digital]`、统一大小写、去空格。用于去重匹配、CBZ 文件命名、Gallery 列表显示
- **报告页数**：源声称的页数（含可能的广告页）
- **实际页数**：去广告后鉴定的有效页数
- **页面 ID 列表**：每个页面在源上的唯一标识符（如 exhentai 的 `cc58247135`），用于增量更新时判定页面是否已下载

## 系列 (Series)

可选的上层概念。当源有章节层级时（如 PicaComic 的"漫画"包含多个"章节"），Series 包含多个 Gallery。对于扁平源（exhentai/nhentai），Gallery 不归属任何 Series。

## 页面 (Page)

Gallery 中的一张图片。系统在内存中下载和处理单页，不落磁盘。只有在打包 CBZ 时才将图片写入文件。

末尾的广告页（最多 10 页）通过页面内容检测（如二维码识别）在去重阶段剔除。

## 订阅 (Subscription)

一个"类 RSS"的抓取规则，由以下组成：
- **源**：从哪个源获取
- **查询串** (`query`)：用户手写的搜索关键词/标签组合（如 `artist:oujiro`），由源自行拼接为搜索 URL 或 API 参数
- **订阅模式**：
  - **搜索条件** (`SEARCH`)：源上搜索到的新 Gallery 即为"更新"
  - **特定画廊** (`SPECIFIC_GALLERY`)：追踪特定 Gallery ID 的更新。exhentai 上表现为"newer versions available"检测 + 逐页 ID 对比；nhentai 上为一次性下载无后续更新
  - **特定作者** (`SPECIFIC_ARTIST`)：搜索条件的特化，query 固定为 `artist:xxx`
- **检查间隔**：多久检查一次（默认全局间隔，可覆盖）
- **搜索深度** (`max_search_pages`)：一次检查最多翻多少页搜索结果。0 表示只翻第 1 页。新建订阅后首次检查翻全部（5 页 + 可继续加载），后续定时巡检只翻第 1 页
- **CBZ 分卷上限** (`cbz_max_pages`，记作 N)：单个 CBZ 文件最多包含的页数
- **输出目录**：可覆盖默认下载路径，直接指向 Komga library 目录
- **启用状态** (`enabled`)：能否被调度器触发

一个 Gallery 可被多个订阅命中（N:M），物理存储只保留一份 CBZ，通过关联表追踪归属。

每个订阅可配置**筛选条件** (`filter_rules`)：在搜索结果返回后、去重前，对页数、收藏数等做本地过滤（≥/≤）。

## CBZ

最终存储格式。CBZ 本质是 ZIP 文件，按以下规则组织：

- **文件名**：`[{native_id}] {归一化标题} ({起始页}-{结束页}).cbz`
- **分卷**：当 Gallery 总页数超过 N 时，拆分为多个 CBZ，每卷 ≤ N 页
- **增量更新**：新页面追加到最后一个 CBZ。若该卷已满（已含 N 页），则新建一卷
- **更新检测**：文件名中页数范围变化 → Komga 感知文件变化并重新扫描

CBZ 内还包含 `ComicInfo.xml`，含标题、作者、标签（经 EhTagTranslation 翻译为中文）、Series、Volume 等元数据字段。

## ComicInfo.xml

CBZ 内的元数据描述文件，字段包括：Title、Writer、Year/Month/Day、Number（gallery ID）、Web（源 URL）、Tags（翻译后的中文标签）、Series、Volume。

标签通过 [EhTagTranslation/Database](https://github.com/EhTagTranslation/Database) 自动翻译为中文。翻译表本地缓存于 SQLite，定时从上游更新。

## 去重 (Deduplication)

两阶段判断两个 Gallery 是否为同一内容：

**阶段 1（下载前）**：归一化标题做字符串相似度匹配（基于 Levenshtein / difflib），相似度超过阈值的 Gallery 标记为"疑似重复"候选组。

**阶段 2（候选组判定）**：对候选组内 Gallery 各下载最后 ≤ 10 页，鉴定广告页并剔除，对比实际有效页数：
- 差异 ≤ 15% → 判为重复，保留页数多者。页数相同则保留 Gallery ID 较新者
- 差异 > 15% → 都保留


## 下载队列与并发

全局 worker 池 + 每源独立队列 + 每源最大槽位限制：
- 所有待下载的页面进入各自源的队列
- 全局固定 N 个 worker（可配）
- 每个源最多占用 M 个 worker（可配，M ≤ N）
- 空闲 worker 自动从非空队列取任务
- 画廊间优先级：先来先服务

## 通知通道 (Notification Channel)

下载完成后由 `services/notification.py` 直接发送通知（邮件 + Webhook + Komga 扫描），无需事件总线中转。内置支持：
- **Webhook**：通用 HTTP POST，可对接钉钉/飞书/Discord 等
- **邮件**：SMTP 发送
- **Komga**：下载完成后自动触称 library 扫描

通知含封面图、画廊链接、页数。失败时显示失败项及错误日志摘要。

## Komga 集成

下载目录直接设为 Komga library 路径。下载完成后通过 Komga REST API (`POST /api/v1/libraries/{id}/scan`) 触发扫描。Komga URL、API Key、Library ID 在全局设置中配置。

## EhTagTranslation

外部标签翻译数据库。首次运行时拉取翻译表存入本地 SQLite 缓存，之后定时更新。生成 ComicInfo.xml 时自动将英文/日文标签翻译为中文。

## 调度器 (Scheduler)

内置 APScheduler。全局统一检查间隔 + 每订阅可覆盖。抵达检查时间时自动执行"搜索/检测 → 去重 → 下载 → 打包 → Komga 扫描"全流水线，无需人工确认。

## 配置体系

全部配置存储在 SQLite 中，WebUI 统一管理。凭证字段（cookie/token/password）加密存储（cryptography.fernet）。

## 代码结构

```
comicfeed/
  models.py              # SQLAlchemy ORM 模型
  infrastructure/        # 基础设施（DB、日志、配置、缓存、源管理、翻译、通知、调度）
  services/              # 业务编排（下载、订阅检查、去重、队列追踪）
  repositories/          # 数据访问层（Gallery/Page CRUD）
  io/                    # 纯 I/O（CBZ 打包、广告检测、页面下载）
  sources/               # 漫画源插件（base + exhentai + nhentai）
  web/                   # FastAPI Web 层（路由 + 模板）
```

## 数据目录布局

项目配置和用户数据分离：
- **应用数据目录** 项目根目录：数据库文件（`*.db`）、EhTagTranslation 缓存、`.cache/` 页面下载缓存
- **下载目录**：用户指定的路径（可设为 Komga library 目录），CBZ 文件落盘于此

## WebUI 认证

WebUI 暴露在局域网/公网环境下需要登录保护。采用 HTTP Basic Auth 或简单密码保护。认证凭证加密存储于 SQLite。

## API 优先架构

所有功能通过 REST API 暴露，WebUI 通过 REST API 与后端通信。Jinja2 模板仅用于服务初始 SSR 页面，后续交互通过 API 调用完成。这为未来移动端客户端预留了基础。

全局设置中的 API 文档开关可控制是否公开 `/docs`（Swagger UI）。

## 手动触发

WebUI 中支持：
- **立即检查**：对某个订阅立即执行一次完整的"检查→去重→下载→打包"流水线
- **按 ID/链接下载**：手动输入 Gallery ID 或源 URL，绕过订阅直接下载，遵守去重规则

## 数据库迁移

启动时自动执行 schema 迁移：检测缺失列 `ALTER TABLE ADD COLUMN`，删除已知过时列 `ALTER TABLE DROP COLUMN`。无需外部工具。
