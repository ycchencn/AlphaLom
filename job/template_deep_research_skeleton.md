# 研报 HTML 结构骨架（样式由系统注入，你只需按此结构产出正文）

> 系统会在生成时自动注入 `<head>`（含全部 CSS 与 ECharts CDN）与图表渲染脚本，
> 并自动包裹 `<div class="container"><header class="report-header"><h1>…</h1><div class="subtitle">…</div></header>` 标题块。
> 你**只需输出从 TL;DR 开始到免责声明为止的正文**，严格使用下面这些 class，不要输出 `<html>/<head>/<style>/<script>/<header>/<h1>`。

## 1) TL;DR 首屏结论卡
```html
<div class="tldr-card">
  <div class="tldr-left">
    <h2>核心结论（TL;DR）</h2>
    <p><span class="bold">一句话本质：</span>（买这家公司本质是在买 ____）</p>
    <p><span class="bold">投资逻辑：</span>（2–4 条，每条含逻辑+为何成立+对业绩/估值影响）</p>
    <p><span class="bold">估值位置：</span>（当前 PE/股息率 + 历史分位 + 一致预期）</p>
    <p><span class="bold">主要风险：</span><span class="risk-tag">短期</span>…<span class="risk-tag">中期</span>…</p>
  </div>
  <div class="tldr-right">
    <div class="kpi-box"><div class="label">最新收盘价</div><div class="value">¥__</div><div class="note">YYYY-MM-DD 交易所</div></div>
    <div class="kpi-box"><div class="label">总市值</div><div class="value">__亿</div><div class="note">YYYY-MM-DD</div></div>
    <div class="kpi-box"><div class="label">动态PE（TTM）</div><div class="value">__倍</div><div class="note">口径</div></div>
    <div class="kpi-box"><div class="label">股息率</div><div class="value">__%</div><div class="note">近12月</div></div>
    <div class="kpi-box"><div class="label">归母净利（最近一期）</div><div class="value">__亿</div><div class="note">同比__%</div></div>
    <div class="kpi-box"><div class="label">ROE（最近年度）</div><div class="value">__%</div><div class="note">加权</div></div>
  </div>
</div>
```

## 2) 六大章节（每个 `<div class="section">` 都要有实质内容，禁止空壳）
```html
<div class="section">
  <h2>1. 公司与业务结构</h2>
  <!-- 业务模块收入/利润贡献，区分现金牛/增长引擎/边缘业务；可用表格 -->
  <div class="table-wrap"><table>…</table></div>
  <p class="source-note">来源：公司年报/财报　时点：YYYY-MM-DD</p>
</div>

<div class="section">
  <h2>2. 行业格局与公司地位</h2>
  <!-- 行业阶段/空间/竞争强度 + 可量化地位指标 -->
</div>

<div class="section">
  <h2>3. 核心投资逻辑</h2>
  <!-- 2–4 条，每条：逻辑本身 + 为什么成立 + 对业绩/估值影响 + 是否已定价 -->
</div>

<div class="section">
  <h2>4. 市场共识与预期差</h2>
  <!-- 已共识 + 超额收益预期差 + 反向声音 -->
</div>

<div class="section">
  <h2>5. 估值框架与位置</h2>
  <!-- 公司类型→估值法→当前反映的预期→纵向分位+横向对比→重估触发 -->
  <div class="chart-container" id="chart-pe-band" data-chart='{"kind":"peband","title":"PE TTM 历史走势（YYYY-MM至YYYY-MM，周频）"}'></div>
</div>

<div class="section">
  <h2>6. 风险提示</h2>
  <!-- 短期/中期分开，具体到最可能爆雷环节；用 <span class="risk-tag">短期</span> 标注 -->
</div>

<div class="section">
  <h2>财务趋势与分红</h2>
  <div class="chart-container" id="chart-trend-main" data-chart='{…双轴 option…}'></div>
  <div class="chart-container" id="chart-dividend" data-chart='{…柱状 option…}'></div>
  <p class="source-note">来源：…　时点：…</p>
</div>
```

## 3) 图表容器（必须出现在对应章节内，每个都写 data-chart）
```html
<!-- 业务结构饼图 -->
<div class="chart-container" id="chart-business-mix" data-chart='{"title":{"text":"YYYYHn 业务结构","left":"center","textStyle":{"fontSize":14,"color":"#0a4b78"}},"tooltip":{"trigger":"item"},"series":[{"type":"pie","radius":["40%","65%"],"data":[{"value":__,"name":"__","itemStyle":{"color":"#1e7a4f"}},…],"label":{"formatter":"{b}: {c}%"}}]}'></div>

<!-- 同业对比双轴：两个 yAxis + series 用 yAxisIndex 区分 -->
<div class="chart-container" id="chart-peers" data-chart='{"title":{"text":"同业对比：ROE vs 动态PE","left":"center"},"legend":{"data":["ROE (%)","动态PE (x)"]},"xAxis":{"type":"category","data":["__","__","__"]},"yAxis":[{"name":"ROE (%)"},{"name":"动态PE (x)"}],"series":[{"name":"ROE (%)","type":"bar","data":[__]},{"name":"动态PE (x)","type":"line","yAxisIndex":1,"data":[__]}]}'></div>

<!-- 营收&净利趋势双轴 -->
<div class="chart-container" id="chart-trend-main" data-chart='{"title":{"text":"营收与归母净利润趋势"},"xAxis":{"type":"category","data":["2021A","2022A","2023A","2024A","2025A*","2026H1"]},"yAxis":[{"name":"营收(亿)"},{"name":"净利(亿)"}],"series":[{"name":"营收(亿)","type":"bar","data":[__]},{"name":"净利(亿)","type":"line","yAxisIndex":1,"data":[__]}]}'></div>

<!-- 分红趋势 -->
<div class="chart-container" id="chart-dividend" data-chart='{"title":{"text":"近五年每股分红趋势"},"xAxis":{"type":"category","data":["2021","2022","2023","2024","2025"]},"series":[{"type":"bar","data":[__],"label":{"show":true,"position":"top"}}]}'></div>

<!-- PE TTM 走势：用 kind:peband 让系统生成确定性示意曲线；有真实周频数据可改普通 line -->
<div class="chart-container" id="chart-pe-band" data-chart='{"kind":"peband","title":"PE TTM 历史走势（YYYY-MM至YYYY-MM，周频）"}'></div>

<!-- 无数据的图表：写 empty 并在 div 内说明，不要留空白 -->
<div class="chart-container" id="chart-xxx" data-chart='{"empty":true,"msg":"该标的近五年分红数据未披露"}'>该标的近五年分红数据未披露</div>
```
- 属性用单引号包裹、JSON 内用双引号；`data-chart` 必须是合法 JSON（`echarts.init` 会 `JSON.parse`）。
- 数值轴用 ECharts；股权/产业链关系用 SVG 或 CSS 盒子；多维对照用 `<div class="table-wrap"><table>`。

## 4) 文末免责声明（原样保留）
```html
<div class="disclaimer">以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。</div>
```
