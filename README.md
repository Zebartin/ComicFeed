# ComicFeed

多漫画源自动抓取、去重、打包为 CBZ 的订阅系统。通过 WebUI 管理订阅，下载内容可由 [Komga](https://komga.org/) 直接索引。

## 功能

- **多源支持** — exhentai、nhentai，源为插件式可扩展
- **订阅模式** — 搜索条件订阅（自动发现新画廊）、特定画廊追踪（增量更新检测），按间隔定时巡检
- **增量更新** — exhentai 画廊新增页面后自动检测，只下载新页，合并到已有 CBZ
- **本地筛选** — 收藏数、页数、上传日期条件过滤
- **CBZ 打包** — 含 ComicInfo.xml 元数据（标题 / 作者 / 标签 / 日期），标签自动中文翻译
- **分卷** — 单 CBZ 超过设定页数自动拆卷
- **广告检测** — 自动识别并移除末尾广告页
- **下载队列** — 待处理 / 进行中 / 已完成 / 失败 全生命周期可视化，失败可重试
- **通知** — 邮件 + Webhook，含封面、标题、页数、源站链接，支持失败汇总
- **Komga 集成** — 下载完成后自动触发 library 扫描
- **搜索页** — 不创建订阅也能直接搜索源，一键保存为订阅

## 截图

<!-- TODO: 替换为实际截图 -->
```
┌─────────────────────────────────────────────┐
│              订阅管理页                      │
│            [screenshot: subscriptions]       │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│              搜索 + 结果面板                 │
│            [screenshot: search]              │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│              下载队列页                      │
│            [screenshot: queue]               │
└─────────────────────────────────────────────┘
```

## 快速开始（Docker）

```bash
git clone <repo-url> comicfeed && cd comicfeed
docker compose up -d
```

访问 `http://localhost:8000`，默认用户名 `admin`。

更新代码：`git pull && docker compose up -d --build`

## 手动安装

要求 Python ≥ 3.11，Linux 需安装 `libzbar`。

```bash
git clone <repo-url> comicfeed && cd comicfeed
uv venv
uv pip install .
python main.py
```

启动参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `127.0.0.1` | 监听地址 |
| `--port` | `8000` | 端口 |
| `--db` | `comicfeed.db` | 数据库路径 |
| `--auth-user` | `admin` | WebUI 用户名 |
| `--auth-pass` | 空 | WebUI 密码（空=无验证） |
| `--debug` | 否 | 输出 DEBUG 日志 |

## 配置

### 源凭证

各源的 Cookie / Token 在「设置 → 源配置」页面填入，加密存储。

exhentai 需要配置 `ipb_member_id`、`ipb_pass_hash`、`igneous`，nhentai 通常无需凭证。

### 全局设置

| 设置项 | 说明 |
|--------|------|
| 下载路径 | CBZ 输出目录，可直接设为 Komga library 路径 |
| 代理 | 全局 HTTP 代理 |
| 巡检间隔 | 自动检查订阅的间隔（分钟） |
| 并发数 | 同时下载任务数 |
| 下载重试次数 | 单页/单批次失败重试次数 |
| SMTP | 邮件通知配置 |
| Webhook | 通用 Webhook URL |
| Komga | URL + 账号 + Library ID |

## 使用

### 1. 创建订阅

点击「新建订阅」→ 填写：

- **查询串**：搜索关键词，如 `chinese`、`artist:oujiro`。可附加 exhentai 参数：`chinese&f_cats=1021`
- **模式**：「搜索条件」按关键词搜索新画廊；「特定画廊」粘贴画廊 URL 追踪更新
- **间隔**：多久检查一次（分钟）
- **CBZ 分卷**：每卷最多页数，0=不分卷
- **筛选条件**（可选）：收藏数 ≥、页数 ≥、上传日期距今 ≤

保存后自动执行首次检查。

### 2. 检查结果

检查完成后弹出结果面板，卡片展示封面、标题、页数、标签。
选中卡片 → 点击「下载选中」→ 加入队列。
若有更多结果可点击「加载更多」翻页。

### 3. 下载队列

队列页显示全部任务状态：等待中 → 下载中 → 已完成 / 失败。
失败任务可点击「重试」重新下载。
已完成任务可「清除」清空列表。

### 4. 搜索（不创建订阅）

搜索页可直接搜索任意源的任意关键词，结果展示方式与订阅检查一致。搜到感兴趣的结果可点击「保存为订阅」一键创建。

### 5. 画廊管理

已下载的画廊在「画廊」页面浏览，可按源筛选、排序。不再需要的画廊可直接删除。

### 6. 通知

下载完成后自动发送邮件通知（含成功/失败汇总），同时触发 Komga 扫描。配置 SMTP 和 Komga 后即可生效。

## 目录结构

```
comicfeed/
  models.py              # SQLAlchemy ORM
  infrastructure/        # 数据库、日志、配置、缓存、通知、调度器
  services/              # 下载编排、订阅检查、去重、队列
  repositories/          # Gallery / Page 数据访问
  io/                    # CBZ 打包、广告检测、页面下载
  sources/               # 漫画源插件（exhentai / nhentai）
  web/                   # FastAPI 路由 + Jinja2 模板
```

## 技术栈

Python · FastAPI · SQLAlchemy (aiosqlite) · APScheduler · BeautifulSoup · curl-cffi · Jinja2 · cryptography

## Vibe Coding 声明

本项目约 90% 的代码由 Claude Code (DeepSeek V4 Pro ) 生成。人类负责需求定义、架构决策、领域知识（exhentai 行为）、代码审查和手工测试。所有 AI 生成的代码均经过人类审查后合入。
