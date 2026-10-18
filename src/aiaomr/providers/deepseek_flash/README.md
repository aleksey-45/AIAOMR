# deepseek_flash 接入说明（V-13）

- **接入日期**：2026-10-18（v3 首次接入）
- **模型版本串**：`deepseek-flash` = DeepSeek-V4.1-Flash-1017；旧名 `deepseek-v4-flash` /
  `deepseek-v4-flash-vision-exp` 仍被接受，但本仓库只写 `deepseek-flash`。
- **Endpoint**：`https://api.deepseek.com/chat/completions`（OpenAI 兼容）
- **认证**：`Authorization: Bearer $DEEPSEEK_API_KEY`；密钥只从环境变量或调用参数进，
  禁止写进仓库、日志、fixture、`calls/*.json`。

## 计费口径

人民币 / 百万 token，**谷价**（空闲时段）为基准，峰价是谷价的两倍：

| 项 | 谷价 | 峰价 |
|---|---|---|
| 输入（cache miss） | ¥1.00 | ¥2.00 |
| 输入（cache hit） | ¥0.02 | ¥0.04 |
| 输出 | ¥4.00 | ¥8.00 |

峰时段 = 北京时间周一至周五 09:00–12:00、14:00–18:00（中国法定节假日除外）。
成本一律按谷价归一化记账，峰时的实际花费另记（§2.3.2）。

## 图像 token

`1024 × clamp(P, 0.296MP, 1.69MP) / 1.69MP`，下限 180。P0 实测见 `docs/p0-results.md`：
1.6 MP 的整系统裁片约 1024 token，读数明显比 0.88 MP 稳。

## 已踩的坑

1. **空返回是偶发的**。JSON 模式也会返回空 `content`，按 `retry_empty` 重试；重试提示只带
   截断后的说明，不回传上一次完整回复（V-05b）。
2. **thinking 开着会失控**。整系统读数时模型把 `max_tokens` 全花在 reasoning 上、不产出答案
   （P0 实测 16000 token、76 秒、¥0.0642）。当前配置 `thinking = false`。
3. **401/403 一次都不能重试**，重试只会继续烧配额；429/5xx/超时按指数退避，优先用
   `Retry-After`。
4. **图片只能放 user 消息**，放 system 会 400（V-02）。
5. **提示词前缀要逐字节稳定**，否则命中不了缓存；缓存命中价是未命中的 1/50（V-11）。
6. **`max_tokens` 必须显式设**，不能依赖默认值（§4.1）。

## 与 base prompt 的差异

v3 只接这一家 provider，`providers/deepseek_flash/prompts/` 暂时为空；以后要按厂商改口径时，
只写差异、覆盖 base 对应段落，禁止复制整份 base（§4.2）。

## 离线回放

`StubClient` 按 `callId` 读 `<replay_dir>/<callId>.resp.json`，不发任何网络请求（V-10）。
真实调用的留证在 `out/<song>/calls/<callId>.req.json` / `.resp.json`（V-08）。
