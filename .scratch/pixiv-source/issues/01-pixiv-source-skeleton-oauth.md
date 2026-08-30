# 01 — pixiv 源骨架 + OAuth 认证 + 测试连接

**What to build:** ComicFeed 出现 pixiv 源：设置页源配置里可选 pixiv、填入 refresh_token（加密存储）与代理、看到 R-18 账号显示设置说明；「测试连接」能验证 token 可用性（有效/无效都有明确反馈）；access_token 在进程内缓存，过期自动用 refresh_token 换新。测试连接走新增的通用「测试源连接」端点（对齐 test-webhook 先例），任何源可复用。

**Blocked by:** None — 可立即开始

**Status:** resolved

- [ ] 启动扫描后 pixiv 源被加载（key/name/version/domains/auth_schema 校验通过）
- [ ] 配置表单渲染 refresh_token（加密存储）与代理字段、R-18 显示设置 hint 文案
- [ ] 测试连接：有效 refresh_token 成功；无效/过期 token 明确报错
- [ ] token 刷新请求携带 X-Client-Time / X-Client-Hash 签名头（离线 mock 传输层断言请求构造）
- [ ] access_token 缓存与自动刷新（有效期内复用、过期换新）
- [ ] 通用测试连接端点不破坏现有源（exhentai/nhentai 配置页行为回归不变）
