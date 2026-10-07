<script setup>
/**
 * 指数卡片（沪深大盘 / 美股大盘两页共用）。
 *
 * 为什么要抽成组件：两个页面的指数卡片是**同一套视觉**（名称+代码、点位、
 * 当日涨跌、近 60 交易日迷你走势、近 5 日 / 年初至今、数据日期）。分成两个
 * 文件各写一份，改一处忘一处就会「A 页加了个指标、B 页没有」。
 * 数据侧同源见 `service/index_card_common.py`（算法也只写一次）。
 *
 * 数据来源：`GET /index/cn_cards`（沪深，含实时 tick）或 `GET /index/us_cards`
 * （美股，只有日线）。两者响应结构**完全一致**，所以本组件不需要知道是哪个市场。
 *
 * ⚠️ 迷你走势用**纯 SVG polyline**而不是 ECharts：
 *   - 一页十来张卡各起一个 canvas 实例太重，ResizeObserver 生命周期也容易踩坑；
 *   - SVG 用 viewBox + preserveAspectRatio="none" 直接拉伸，配
 *     vector-effect="non-scaling-stroke" 保持线宽不被非等比缩放拉粗。
 *
 * ⚠️ 涨跌色不用 `.text-up/.text-down` class —— 全站并没有定义这两个全局类
 * （只有 CSS 变量 --color-up/--color-down），用 class 会静默不生效，必须内联 style。
 */
import {computed} from 'vue'
import Card from 'primevue/card'
import Tag from 'primevue/tag'

const props = defineProps({
    // 卡片数据（cn_cards / us_cards 的 items 元素）
    item: {type: Object, required: true},
    // 点位小数位。指数都是 2 位，留成 prop 是为了将来复用到别的资产不改组件。
    digits: {type: Number, default: 2},
    // 「恐慌指数」这类标签文案；不传则不渲染标签
    tagText: {type: String, default: ''},
})

const isVolatility = computed(() => props.item.is_volatility === true)

// 涨跌色。VIX（波动率指数）反转：涨=恐慌用绿色（跌色），跌=平静用红色（涨色）。
// 判定依据只来自后端 `is_volatility`，组件内不再自己判断代码。
const trendColorOf = (value) => {
    if (value == null || Number.isNaN(Number(value))) return 'var(--color-flat)'
    const v = Number(value)
    if (v === 0) return 'var(--color-flat)'
    const rising = v > 0
    const up = isVolatility.value ? !rising : rising
    return up ? 'var(--color-up)' : 'var(--color-down)'
}

const formatSign = (v, digits = 2) => {
    if (v == null || Number.isNaN(Number(v))) return '--'
    const n = Number(v)
    return `${n > 0 ? '+' : ''}${n.toFixed(digits)}`
}

const formatPct = (v) => (v == null || Number.isNaN(Number(v)) ? '--' : `${formatSign(v)}%`)

const formatPrice = (v) => {
    if (v == null || Number.isNaN(Number(v))) return '--'
    return Number(v).toLocaleString('en-US', {
        minimumFractionDigits: props.digits,
        maximumFractionDigits: props.digits,
    })
}

// 走势线的着色依据：**区间净涨跌**（末根 vs 首根），不是当日涨跌。
// 线的形态画的是近 60 日趋势，用当日涨跌去染色会出现「线明显向上但染成绿色」
// 的自相矛盾（VIX 尤其明显：涨=恐慌，绿色 + 上行线看着像在跌）。
const sparkChange = computed(() => {
    const pts = props.item.spark || []
    if (pts.length < 2) return null
    const first = Number(pts[0].close)
    const last = Number(pts[pts.length - 1].close)
    if (!Number.isFinite(first) || !Number.isFinite(last) || first === 0) return null
    return (last - first) / first * 100
})

// 迷你走势的 SVG path。归一化到 0~100 的 viewBox 坐标，纵向不按数值比例
// （否则几个点之间 0.5% 的差异会被压成一条直线）；横向等距即可。
// computed 只依赖 item，天然只算一次（原实现用模块级 Map 按 code 缓存，
// 抽成组件后每张卡一个实例，computed 已足够、且不会跨实例串数据）。
const sparkPath = computed(() => {
    const pts = props.item.spark || []
    if (pts.length < 2) return {line: '', area: ''}
    const values = pts.map((p) => Number(p.close))
    if (values.some((v) => !Number.isFinite(v))) return {line: '', area: ''}

    const min = Math.min(...values)
    const max = Math.max(...values)
    const span = max - min || 1
    const stepX = 100 / (values.length - 1)
    // 上下留 8% 余量，避免最高/最低点贴着 SVG 边缘被卡片裁掉。
    const pad = 0.08
    const coords = values.map((v, i) => {
        const x = i * stepX
        const y = pad + (1 - (v - min) / span) * (1 - pad * 2)
        return `${x.toFixed(2)},${(y * 100).toFixed(2)}`
    })
    return {
        line: `M${coords.join(' L')}`,
        area: `M0,100 L${coords.join(' L')} L100,100 Z`,
    }
})

const sparkColor = computed(() => trendColorOf(sparkChange.value))
</script>

<template>
    <Card class="index-card">
        <template #content>
            <div class="card-body">
                <div class="card-head">
                    <div class="name-block">
                        <div class="index-name" :title="item.name">{{ item.name }}</div>
                        <div class="index-code">{{ item.code }}</div>
                    </div>
                    <Tag v-if="tagText" severity="warn" :value="tagText" class="vol-tag" />
                </div>

                <div class="index-price">{{ formatPrice(item.close) }}</div>

                <div class="index-change" :style="{color: trendColorOf(item.chg_pct)}">
                    <span>{{ formatSign(item.chg_amount) }}</span>
                    <span class="change-percent">{{ formatPct(item.chg_pct) }}</span>
                </div>

                <!-- 近 60 交易日迷你走势 -->
                <svg
                    v-if="sparkPath.line"
                    class="spark"
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                >
                    <path :d="sparkPath.area" :fill="sparkColor" opacity="0.10" />
                    <path
                        :d="sparkPath.line"
                        fill="none"
                        :stroke="sparkColor"
                        stroke-width="1.5"
                        stroke-linejoin="round"
                        stroke-linecap="round"
                        vector-effect="non-scaling-stroke"
                    />
                </svg>
                <div v-else class="spark-empty">走势数据不足</div>

                <div class="metric-row">
                    <div class="metric">
                        <span class="metric-label">近5日</span>
                        <span class="metric-value" :style="{color: trendColorOf(item.pct_5d)}">
                            {{ formatPct(item.pct_5d) }}
                        </span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">年初至今</span>
                        <span class="metric-value" :style="{color: trendColorOf(item.pct_ytd)}">
                            {{ formatPct(item.pct_ytd) }}
                        </span>
                    </div>
                </div>

                <div class="card-foot">{{ item.trade_date }}</div>
            </div>
        </template>
    </Card>
</template>

<style scoped lang="scss">
.card-body {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    height: 100%;
}

.card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.5rem;
}

.name-block {
    min-width: 0;
}

.index-name {
    font-size: 0.95rem;
    color: #475569;
    font-weight: 600;
    /* 长名字（芝加哥期权交易所波动率指数）不换行会顶出卡片，
       这里截断并用 title 挂全文。 */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.index-code {
    font-size: 0.72rem;
    color: #94a3b8;
    margin-top: 0.15rem;
}

.vol-tag {
    flex: 0 0 auto;
    font-size: 0.68rem;
    padding: 0.1rem 0.35rem;
}

.index-price {
    font-size: 1.7rem;
    font-weight: 700;
    color: #0f172a;
    line-height: 1.1;
    /* 点位可达 5 位 + 2 位小数，窄列下不能被压缩换行 */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.index-change {
    display: flex;
    gap: 0.5rem;
    font-size: 0.92rem;
    font-weight: 600;
    flex-wrap: wrap;
}

.spark {
    width: 100%;
    height: 44px;
    margin-top: 0.2rem;
    display: block;
}

.spark-empty {
    height: 44px;
    margin-top: 0.2rem;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    color: #cbd5e1;
}

.metric-row {
    display: flex;
    gap: 1rem;
    margin-top: 0.15rem;
    padding-top: 0.45rem;
    border-top: 1px solid #f1f5f9;
}

.metric {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    min-width: 0;

    .metric-label {
        font-size: 0.72rem;
        color: #94a3b8;
    }

    .metric-value {
        font-size: 0.88rem;
        font-weight: 600;
    }
}

.card-foot {
    margin-top: auto;
    padding-top: 0.3rem;
    font-size: 0.72rem;
    color: #cbd5e1;
}
</style>
