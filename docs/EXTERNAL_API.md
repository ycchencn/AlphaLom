# AlphaLom 对外 API（开放数据接口）

AlphaLom 提供一套**基于 API Key 鉴权、只读**的开放数据接口，方便你把投资组合、股票池与个股分析数据对接到第三方交易系统、BI 工具或自动化脚本里。

> 所有对外接口挂载在独立的子应用 `/api/ext` 下，自带独立的 Swagger 文档，与主应用（Web 控制台用的 `/docs`）互不干扰。

---

## 1. 概览

| 项 | 说明 |
|:--|:--|
| 数据面 Base Path | `/api/ext` |
| Swagger UI | `/api/ext/docs` |
| OpenAPI JSON | `/api/ext/openapi.json` |
| 鉴权方式 | API Key（`X-API-Key` 或 `Authorization: Bearer`） |
| 配额 | 按「用户 + 自然日」计，默认 1000 次/天，超限额 429 |
| 数据范围 | **只读**，且剥离敏感字段（见 §6） |
| 覆盖数据 | 投资组合（`/portfolios`）· 股票池（`/stocks/pools`、`/stocks/watchlist`）· 个股分析（`/stocks/{symbol}/*`、`/stocks/batch/analysis`、`/stocks/signals`） |

> 部署后访问 `https://<你的域名或IP>:8080/api/ext/docs` 即可看到交互式文档，并可点右上角 **Authorize** 填入密钥后直接试调。

---

## 2. 获取 API Key

对外接口需要用 API Key 调用。密钥**属于某个用户账号**，只能访问该用户自己的数据（投资组合 / 股票池 / 个股分析）。

> 推荐直接在 Web 控制台 **「系统管理 → API Key」** 页面创建与管理密钥（列表、创建、改名、启停、改配额、吊销）；创建成功后明文密钥**仅展示一次**，请立即复制保存。
> 也可通过下面的**管理接口**（编程方式）操作，两者走同一套后端。

### 通过管理接口创建

管理接口走的是**登录会话令牌**鉴权（和 Web 前端一致），不在 `/api/ext` 下，而在主应用的 `/api/v1/api-keys`。调用前需先以该用户身份登录拿到会话令牌（`Authorization: Bearer <session_token>`）。

```http
POST /api/v1/api-keys
Authorization: Bearer <你的登录会话令牌>
Content-Type: application/json

{
  "name": "my-script",        // 备注名，可选，默认 default
  "daily_quota": 2000,        // 单密钥每日配额覆盖，可选；不传则用全局默认
  "expires_at": "2026-12-31T23:59:59"  // 可选；不传表示长期有效
}
```

成功响应（信封格式，见 §7）：

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "id": 12,
    "name": "my-script",
    "key_prefix": "flp_AbCdEfGh",   // 仅用于展示，不泄露完整密钥
    "status": "active",
    "daily_quota": 2000,
    "last_used_at": null,
    "created_at": "2026-09-26 11:00:00",
    "expires_at": "2026-12-31 23:59:59",
    "key": "flp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefgh"   // ⚠️ 仅此一次返回明文
  }
}
```

密钥格式固定以 `flp_` 开头，便于在日志与 Swagger 里与登录令牌区分。明文**只在这一次创建响应里展示**，请立即复制保存；之后任何接口都不会再返回明文。

> 列出、改名、启停、吊销密钥同样走管理接口，详见 §8。

---

## 3. 调用鉴权

每个对外请求都要带密钥，下面两种写法等价：

```http
X-API-Key: flp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefgh
```

或

```http
Authorization: Bearer flp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefgh
```

- **不传 / 传错密钥** → `401`，响应头带 `WWW-Authenticate: ApiKey`。
- 鉴权失败（无效 / 已吊销 / 过期）统一返回 `401`，不会透露密钥是否存在。

---

## 4. 速率限制（配额）

配额按「**用户 + 自然日**」统计，同一用户的多个密钥**共享**额度。

- 默认每用户每天 `1000` 次（可用环境变量 `API_DAILY_QUOTA` 调整，或用单密钥的 `daily_quota` 字段覆盖）。
- 接近上限时，响应头会带剩余额度：
  - `X-RateLimit-Limit`：当日额度上限
  - `X-RateLimit-Remaining`：当日剩余次数
- 超限返回 `429`，并带 `Retry-After` 头（到次日 00:00 的秒数）。

> 配额计数依赖 Redis；若 Redis 短暂抖动，按 fail-open 放行，不会打死正常业务。

---

## 5. 数据接口

所有路径均相对于 Base Path `/api/ext`。响应为**原始 JSON**（无 `{code,msg,data}` 信封），字段与内部模型对齐。

### 5.1 列出投资组合

```http
GET /api/ext/portfolios
```

返回当前用户的所有投资组合数组，每个对象含一个 `summary`（最新每日汇总），**不含持仓明细**。

```bash
curl -H "X-API-Key: $API_KEY" https://<host>:8080/api/ext/portfolios
```

<details><summary>示例响应</summary>

```json
[
  {
    "portfolio_id": "12345678-1234-5678-1234-567812345678",
    "portfolio_name": "我的主组合",
    "user_id": 7,
    "base_currency": "CNY",
    "initial_capital": 1000000.0,
    "current_value": 1123450.0,
    "total_return": 0.12345,
    "created_at": "2026-01-02 09:30:00",
    "summary": {
      "date": "2026-09-25",
      "total_value": 1123450.0,
      "daily_return": 0.0042,
      "cumulative_return": 0.12345,
      "max_drawdown": 0.058,
      "sharpe": 1.31
    }
  }
]
```

</details>

### 5.2 获取单个投资组合详情

```http
GET /api/ext/portfolios/{portfolio_id}
```

返回该组合的完整详情：`assets`（持仓明细，已按 `stock_code=symbol` 关联补全行业信息）、`summary`（最新每日汇总）、`daily_pnl`（每日盈亏序列）。

```bash
curl -H "X-API-Key: $API_KEY" https://<host>:8080/api/ext/portfolios/12345678-1234-5678-1234-567812345678
```

### 5.3 每日统计序列

```http
GET /api/ext/portfolios/{portfolio_id}/daily-summary
```

返回该组合的每日统计（净值、收益、回撤、夏普等）数组，按日期升序。

### 5.4 交易记录

```http
GET /api/ext/portfolios/{portfolio_id}/transactions
```

返回该组合的交易流水数组（买卖、金额、时间等）。

> 上述接口若 `{portfolio_id}` 不属于当前密钥所属用户，统一返回 `404`（不泄露该组合是否存在）。

### 5.5 股票池

按密钥所属用户隔离，只返回该用户自己的自选数据。

```http
GET /api/ext/stocks/pools
```

列出当前用户的全部股票池分组（含每组股票数；未分组的归入「未分组」虚拟分组）。

```http
GET /api/ext/stocks/pools/{group_name}?market=cn
```

取某个分组的成员；`group_name` 传 `__ungrouped__` 取未分组的票。可选 `market` 筛选：`cn` 沪深 / `hk` 港股 / `us` 美股。

```http
GET /api/ext/stocks/watchlist?market=cn
```

当前用户全部自选股的扁平列表，每条含 `symbol` / `name` / `market` / `industry` / `group_name` / `ohlc_last`（最新报价），并批量注入 `fear_greed`（恐贪指数）、`main_force_behavior_phase`（主力行为阶段）、52 周高低位——外部决策系统一次调用即可拿到持仓全景。

### 5.6 个股分析

`{symbol}` 为股票代码（如 `600519`），非法代码返回 `400`。

| 端点 | 说明 |
|:--|:--|
| `GET /stocks/{symbol}/profile` | 公司概况（名称、主营、行业、注册资本等） |
| `GET /stocks/{symbol}/fundamentals` | 基本面评分（盈利能力 / 成长 / 估值 / 财务质量等维度打分） |
| `GET /stocks/{symbol}/factors?lookback_days=400` | 技术面因子：`dashboard`（均线排列 / 关键位 / ATR / 动量-波动象限 / 主力阶段 / 超买超卖）+ `board`（全因子最新值与历史分位）；`lookback_days` 60–2000 |
| `GET /stocks/{symbol}/financials?report_type=Balance&periods=12` | 财务报表，`report_type`：`Balance`（默认 `PershareIndex`）/ `Income` / `CashFlow` / `Capital` / `PershareIndex`；`periods` 1–40 |
| `GET /stocks/{symbol}/fear-greed` | 最新个股恐贪指数记录（含 `trade_date`），无数据返回 `null` |
| `GET /stocks/{symbol}/analysis` | **聚合端点**：一次拿全概况 + 基本面 + 技术因子 + 恐贪 + 最新财务摘要；单个分项失败不影响其他分项 |

### 5.7 批量分析与信号扫描

```http
GET /api/ext/stocks/batch/analysis?symbols=600519,000001&market=cn
```

一次调用返回多只票的核心分析数据（报价 + 因子 + 恐贪 + 基本面评分），供外部系统扫描/排序整个股票池。**不传 `symbols` 则分析当前用户整个池**；股票、因子、恐贪、评分各走一次批量查询，因此**即使池中有上百只票也只计 1 次调用配额**。可选 `factors` 指定因子集（逗号分隔，默认核心因子集）。

```http
GET /api/ext/stocks/signals?signal=macd_golden_cross&limit=100
```

技术信号扫描（纯规则、零 LLM 成本），范围限定**当前用户股票池**。`signal` 必填（如 `macd_golden_cross` / `rsi_oversold` / `ma_bullish` / `near_52w_high` / `volume_surge` 等），`limit` 默认 100（1–1000）。返回命中标的及信号值、asof 交易日。

> 字段的确切结构以 Swagger（`/api/ext/docs`）为准；模型迭代后会自动同步，本文档不逐字段罗列以免失准。

---

## 6. 数据安全与剥离字段

对外接口是**只读**的，且会主动剔除以下敏感字段，绝不外泄：

- `llm_prompt` —— AI 调仓提示词
- `position_plan` / `position_plan_reason` —— AI 调仓计划及理由
- `llm_setting` —— 模型配置
- `quantstat_json` —— 量化回测原始报告

---

## 7. 错误响应

鉴权 / 配额类错误统一为信封格式：

```json
{ "code": 401, "message": "API Key 无效或已吊销" }
```

| HTTP | 含义 | 关键响应头 |
|:--|:--|:--|
| `401` | 缺密钥 / 密钥无效 / 已吊销 | `WWW-Authenticate: ApiKey` |
| `403` | 密钥所属用户被禁用 | — |
| `404` | 资源不存在 / 不归属当前用户（组合、分组、个股数据均同） | — |
| `429` | 当日配额已用尽 | `Retry-After`、`X-RateLimit-*` |
| `503` | 鉴权服务（Redis）暂不可用 | — |

> 管理面接口（§8）统一使用 `{ "code", "msg", "data" }` 信封；数据面接口（§5）返回原始 JSON。

---

## 8. 密钥管理接口（编程）

用于自动化地管理你自己的密钥，均挂在主应用 `/api/v1` 下，**用登录会话令牌鉴权**（`Authorization: Bearer <session_token>`），返回 `{code,msg,data}` 信封。Web 控制台的「系统管理 → API Key」页面即调用这组接口，日常操作建议直接用页面。

| 方法 | 路径 | 说明 |
|:--|:--|:--|
| `POST` | `/api/v1/api-keys` | 创建密钥（明文仅返回一次） |
| `GET` | `/api/v1/api-keys` | 列出当前用户全部密钥（不含明文） |
| `GET` | `/api/v1/api-keys/{id}` | 单枚密钥详情（归属不符一律 404） |
| `PUT` | `/api/v1/api-keys/{id}` | 更新：改名 / 启停（`active`\|`revoked`）/ 改配额（部分字段即可） |
| `DELETE` | `/api/v1/api-keys/{id}` | 吊销密钥，立即失效（后续外部请求均 401） |

`POST` 请求体字段：`name`(str, 可选)、`daily_quota`(int, 可选)、`expires_at`(ISO 时间字符串, 可选)。  
`PUT` 请求体字段（均可单独传）：`name`、`status`、`daily_quota`(`null` 表示回退全局默认)。

---

## 9. 调用示例

### cURL

```bash
export API_KEY="flp_你的密钥"

# 列出组合
curl -H "X-API-Key: $API_KEY" \
  https://<host>:8080/api/ext/portfolios

# 自选股全景（含报价 / 恐贪 / 主力阶段 / 52 周区间）
curl -H "X-API-Key: $API_KEY" \
  https://<host>:8080/api/ext/stocks/watchlist

# 个股分析聚合（一次拿全：概况 + 基本面 + 技术因子 + 恐贪 + 财务摘要）
curl -H "X-API-Key: $API_KEY" \
  https://<host>:8080/api/ext/stocks/600519/analysis

# 批量扫描整个股票池（只计 1 次配额）
curl -H "X-API-Key: $API_KEY" \
  https://<host>:8080/api/ext/stocks/batch/analysis
```

### Python（`requests`）

```python
import requests

API_KEY = "flp_你的密钥"
BASE = "https://<host>:8080/api/ext"

r = requests.get(f"{BASE}/portfolios", headers={"X-API-Key": API_KEY})
r.raise_for_status()
for p in r.json():
    print(p["portfolio_name"], p["current_value"])
```

### Node.js（`fetch`）

```javascript
const API_KEY = "flp_你的密钥";
const BASE = "https://<host>:8080/api/ext";

const res = await fetch(`${BASE}/portfolios`, {
  headers: { "X-API-Key": API_KEY },
});
const portfolios = await res.json();
console.log(portfolios);
```

---

## 10. 服务端配置

在 `.env` 中可调整对外 API 的行为（详见 `.env.sample`）：

| 环境变量 | 默认 | 说明 |
|:--|:--|:--|
| `API_KEY_PREFIX` | `alphalom:apikey:` | Redis 中密钥校验索引的键前缀 |
| `API_KEY_TTL` | `31536000`（1 年） | 密钥 Redis 索引的过期秒数；`0` 表示长期有效 |
| `API_DAILY_QUOTA` | `1000` | 单用户每日调用默认配额 |

> 部署说明见主仓库 `README.md`。对外子应用在 SPA 兜底路由之前挂载，确保 `/api/ext/*` 优先命中 API 而非被当成前端页面。
