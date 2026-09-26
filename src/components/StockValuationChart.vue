<!-- StockValuationChart.vue -->
<template>
    <div
        class="stock-valuation-card"
        :style="cardStyle"
    >
        <!-- 顶部标题区 -->
        <div v-if="showHeader" class="sv-header">
            <div class="sv-title-wrap">
                <span class="sv-accent"></span>
                <h2 :style="titleStyle">{{ title }}</h2>
            </div>
            <p class="sv-rating" :style="ratingStyle">
                综合评级：<span :style="{color: ratingColor, fontWeight: 'bold'}">{{ ratingText }}</span>
            </p>
        </div>

        <!-- SVG核心图表：显式 width/height 属性提供明确宽高比，CSS 再等比缩放，避免 letterbox 留白或高度塌陷 -->
        <svg
            :width="1040"
            :height="chartHeight"
            :viewBox="`0 0 1040 ${chartHeight}`"
            preserveAspectRatio="xMidYMid meet"
            style="display: block; width: 100%; height: auto;"
        >
            <defs>
                <!-- 扇形带渐变：越靠近对应情景线颜色越浓 -->
                <linearGradient :id="`cvBand-${uid}`" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" :stop-color="conservativeLineColor" stop-opacity="0.30"/>
                    <stop offset="100%" :stop-color="conservativeLineColor" stop-opacity="0.04"/>
                </linearGradient>
                <linearGradient :id="`optBand-${uid}`" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" :stop-color="optimisticLineColor" stop-opacity="0.04"/>
                    <stop offset="100%" :stop-color="optimisticLineColor" stop-opacity="0.30"/>
                </linearGradient>
                <!-- 历史区间下方淡蓝渐变 -->
                <linearGradient :id="`histFill-${uid}`" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" :stop-color="historyLineColor" stop-opacity="0.14"/>
                    <stop offset="100%" :stop-color="historyLineColor" stop-opacity="0"/>
                </linearGradient>
                <!-- 当前价圆点柔和投影 -->
                <filter :id="`softShadow-${uid}`" x="-50%" y="-50%" width="200%" height="200%">
                    <feDropShadow dx="0" dy="1" stdDeviation="2" flood-color="#0f172a" flood-opacity="0.25"/>
                </filter>
            </defs>

            <!-- 未来预测区底纹（区分过去/未来） -->
            <rect x="400" y="0" :width="640" :height="chartHeight" fill="#3b82f6" fill-opacity="0.025"/>

            <!-- 水平参考网格（动态均匀分布） -->
            <line v-for="(gy, gi) in gridLines" :key="gi" x1="0" :y1="gy" x2="800" :y2="gy" stroke="#f1f2f6" stroke-width="1"/>

            <!-- 历史区间面积（淡蓝渐变） -->
            <path :d="historyAreaPath" :fill="`url(#histFill-${uid})`"/>

            <!-- 预测扇形带（保守→中性、中性→乐观） -->
            <path
                :d="`M 400 ${priceToY(currentPrice)} L 800 ${priceToY(conservativeValue)} L 800 ${priceToY(neutralValue)} Z`"
                :fill="`url(#cvBand-${uid})`"
            />
            <path
                :d="`M 400 ${priceToY(currentPrice)} L 800 ${priceToY(neutralValue)} L 800 ${priceToY(optimisticValue)} Z`"
                :fill="`url(#optBand-${uid})`"
            />

            <!-- 历史走势折线 -->
            <path
                :d="historyPath"
                :stroke="historyLineColor"
                stroke-width="2.5"
                fill="none"
                stroke-linecap="round"
                stroke-linejoin="round"
            />

            <!-- 预测线 -->
            <line
                x1="400"
                :y1="priceToY(currentPrice)"
                x2="800"
                :y2="priceToY(conservativeValue)"
                :stroke="conservativeLineColor"
                stroke-width="2.5"
                stroke-linecap="round"
            />
            <line
                x1="400"
                :y1="priceToY(currentPrice)"
                x2="800"
                :y2="priceToY(neutralValue)"
                :stroke="neutralLineColor"
                stroke-width="2"
                stroke-dasharray="6 5"
                stroke-linecap="round"
            />
            <line
                x1="400"
                :y1="priceToY(currentPrice)"
                x2="800"
                :y2="priceToY(optimisticValue)"
                :stroke="optimisticLineColor"
                stroke-width="2.5"
                stroke-linecap="round"
            />

            <!-- "现在"分隔线 -->
            <line x1="400" :y1="PAD_TOP" x2="400" :y2="chartHeight - PAD_BOTTOM" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="3 4"/>
            <text x="400" :y="PAD_TOP + 12" text-anchor="middle" font-size="11" fill="#94a3b8">现在</text>

            <!-- 当前价格标记 -->
            <circle cx="400" :cy="priceToY(currentPrice)" r="6" :fill="historyLineColor" stroke="#fff" stroke-width="2.5" :filter="`url(#softShadow-${uid})`"/>
            <text
                x="400"
                :y="priceToY(currentPrice) - 18"
                text-anchor="middle"
                font-size="13"
                font-weight="700"
                fill="#1f2937"
            >
                现价 {{ currentPrice }}
            </text>

            <!-- 右侧情景标签：色块 + 估值 + 涨跌幅 -->
            <g v-for="s in scenarioLabels" :key="s.key">
                <rect x="812" :y="priceToY(s.value) - 14" width="92" height="28" rx="14" :fill="s.color"/>
                <text x="858" :y="priceToY(s.value)" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-size="13" font-weight="600">{{ s.name }}</text>
                <text :x="924" :y="priceToY(s.value) - 4" font-size="13" font-weight="600" fill="#1f2937">¥{{ s.value.toFixed(2) }}</text>
                <text :x="924" :y="priceToY(s.value) + 12" font-size="11" :fill="s.pctColor">{{ s.pctText }}</text>
            </g>
        </svg>

        <!-- X轴说明 -->
        <div v-if="showXAxisLabel" class="sv-xlabel" :style="xLabelStyle">
            <span>过去1年走势</span>
            <span>未来1年预测</span>
        </div>

        <!-- 图例 -->
        <div v-if="showLegend" class="sv-legend">
            <span class="sv-legend-item"><i class="sv-dot" :style="{background: conservativeLineColor}"></i>保守情景</span>
            <span class="sv-legend-item"><i class="sv-dot sv-dot--dash" :style="{background: neutralLineColor}"></i>中性情景</span>
            <span class="sv-legend-item"><i class="sv-dot" :style="{background: optimisticLineColor}"></i>乐观情景</span>
        </div>

        <!-- 估值说明区 -->
        <div v-if="showAdvice" class="sv-advice" :style="adviceStyle">
            <h4 v-if="adviceTitle" style="margin: 0 0 10px 0; font-size: 16px;">{{ adviceTitle }}</h4>
            <p style="margin: 0; line-height: 1.6; color: #333;">{{ adviceText }}</p>
        </div>
    </div>
</template>

<script setup>
import {computed} from 'vue'
import {
    parseNumber
} from '@/utils/function.js';

// 用于隔离多个实例的渐变/滤镜 id，避免页面内冲突
const uid = Math.random().toString(36).slice(2, 8)

const props = defineProps({
    /**
     * 估值核心数据，必填
     * @type {Object}
     * @property {string} 当前股价 - 股票当前价格
     * @property {string} 估值判断 - 估值建议文本
     * @property {Object} 每股内在价值 - 三个情景的估值
     * @property {string} 每股内在价值.保守情景 - 保守目标价
     * @property {string} 每股内在价值.中性情景 - 中性目标价
     * @property {string} 每股内在价值.乐观情景 - 乐观目标价
     */
    data: {
        type: Object,
        required: true,
        validator: (val) => {
            return val?.估值判断 && val?.每股内在价值
        }
    },
    /** 组件标题 */
    title: {
        type: String,
        default: '个股估值预测'
    },
    /** 评级文字 */
    ratingText: {
        type: String,
        default: '买入'
    },
    /** 评级文字颜色 */
    ratingColor: {
        type: String,
        default: '#f43f5e'
    },
    /** 当前股价 */
    currentPrice: {
        type: Number,
        default: 0
    },
    /** 价格区间最小值，用于坐标映射 */
    minPrice: {
        type: Number,
        default: 0
    },
    /** 价格区间最大值，用于坐标映射 */
    maxPrice: {
        type: Number,
        default: 0
    },
    /** 图表高度（viewBox 纵向基准，实际显示高度按宽度等比自适应） */
    chartHeight: {
        type: Number,
        default: 300
    },
    /** 历史走势数据，数组格式，不传则自动生成模拟数据 */
    historyData: {
        type: Array,
        default: () => []
    },
    /** 是否显示顶部头部 */
    showHeader: {
        type: Boolean,
        default: false
    },
    /** 是否显示网格线 */
    showGrid: {
        type: Boolean,
        default: true
    },
    /** 是否显示X轴说明 */
    showXAxisLabel: {
        type: Boolean,
        default: false
    },
    /** 是否显示图例 */
    showLegend: {
        type: Boolean,
        default: true
    },
    /** 是否显示估值建议 */
    showAdvice: {
        type: Boolean,
        default: false
    },
    /** 估值建议标题 */
    adviceTitle: {
        type: String,
        default: '估值判断'
    },
    /** 自定义卡片样式 */
    cardStyle: {
        type: Object,
        default: () => ({
            maxWidth: '960px',
            margin: '0px auto',
            padding: '20px 22px',
            background: '#fff',
            border: '1px solid #eef0f3',
            borderRadius: '16px',
            boxShadow: '0 4px 20px rgba(15, 23, 42, 0.06)'
        })
    },
    /** 配色自定义 */
    historyLineColor: {type: String, default: '#3b82f6'},
    conservativeLineColor: {type: String, default: '#22c55e'},
    neutralLineColor: {type: String, default: '#6b7280'},
    optimisticLineColor: {type: String, default: '#ef4444'},
    conservativeAreaColor: {type: String, default: 'rgba(34, 197, 94, 0.15)'},
    optimisticAreaColor: {type: String, default: 'rgba(239, 68, 68, 0.15)'}
})



// 数据提取&容错
const currentPrice = computed(() => parseNumber(props.currentPrice))
const conservativeValue = computed(() => parseNumber(props.data?.每股内在价值?.保守情景))
const neutralValue = computed(() => parseNumber(props.data?.每股内在价值?.中性情景))
const optimisticValue = computed(() => parseNumber(props.data?.每股内在价值?.乐观情景))
const adviceText = computed(() => props.data?.估值判断 || '暂无估值建议')

// 右侧情景标签（含相对现价的涨跌幅）
const scenarioLabels = computed(() => {
    const cur = currentPrice.value
    const defs = [
        {key: 'opt', name: '乐观', value: optimisticValue.value, color: props.optimisticLineColor},
        {key: 'neu', name: '中性', value: neutralValue.value, color: props.neutralLineColor},
        {key: 'con', name: '保守', value: conservativeValue.value, color: props.conservativeLineColor}
    ]
    return defs.map(d => {
        const pct = cur > 0 ? (d.value - cur) / cur * 100 : 0
        const up = pct >= 0
        return {
            ...d,
            pctText: (up ? '↑ +' : '↓ ') + pct.toFixed(1) + '%',
            pctColor: up ? '#16a34a' : '#dc2626'
        }
    })
})

// ★ 自动计算动态价格上下限，自动覆盖历史+当前+DCF估值全区间
const dynamicMinPrice = computed(() => {
    // 优先用用户传入的固定minPrice
    if (props.minPrice > 0) return props.minPrice
    // 收集所有有效价格（过滤空值/停牌0值）
    const allValidPrices = [
        ...props.historyData.filter(p => p && p > 0),
        currentPrice.value,
        conservativeValue.value,
        neutralValue.value,
        optimisticValue.value
    ].filter(p => typeof p === 'number' && isFinite(p) && p > 0)
    if (!allValidPrices.length) return 0
    const minVal = Math.min(...allValidPrices)
    const maxVal = Math.max(...allValidPrices)
    // 仅留 4% 区间余量（原来 10% 会撑出大片空白），最低不小于 0
    const pad = (maxVal - minVal) * 0.04
    return Math.max(0, minVal - pad)
})
const dynamicMaxPrice = computed(() => {
    // 优先用用户传入的固定maxPrice
    if (props.maxPrice > 0) return props.maxPrice
    const allValidPrices = [
        ...props.historyData.filter(p => p && p > 0),
        currentPrice.value,
        conservativeValue.value,
        neutralValue.value,
        optimisticValue.value
    ].filter(p => typeof p === 'number' && isFinite(p) && p > 0)
    if (!allValidPrices.length) return 1
    const minVal = Math.min(...allValidPrices)
    const maxVal = Math.max(...allValidPrices)
    // 仅留 4% 区间余量
    const pad = (maxVal - minVal) * 0.04
    return maxVal + pad
})
// 绘图区纵向边距：仅留刚好容纳「现价/情景」标签的最小空间，避免上下空白
const PAD_TOP = 16
const PAD_BOTTOM = 12
/**
 * ★ 优化价格转坐标逻辑，铺满整个 viewBox，消除上下空白
 * @param {number} price 股票价格
 * @returns {number} Y坐标值
 */
const priceToY = (price) => {
    const top = PAD_TOP
    const bottom = props.chartHeight - PAD_BOTTOM
    const minP = dynamicMinPrice.value
    const maxP = dynamicMaxPrice.value
    // 边界处理：所有价格相等时，返回垂直居中坐标，避免除以0报错
    if (maxP === minP) {
        return (top + bottom) / 2
    }
    // 限制价格在区间内，防止异常价格溢出画布
    const safePrice = Math.max(minP, Math.min(price, maxP))
    return top + (maxP - safePrice) * (bottom - top) / (maxP - minP)
}
// 动态均匀参考线（随绘图区自适应）
const gridLines = computed(() => {
    if (!props.showGrid) return []
    const top = PAD_TOP
    const bottom = props.chartHeight - PAD_BOTTOM
    return [1, 2, 3].map(i => top + (bottom - top) * i / 4)
})
/**
 * ★ 优化历史路径生成，处理数据不足的边界情况
 */
const historyPath = computed(() => {
    if (props.historyData.length) {
        // 边界处理：只有1条历史数据时直接画水平线
        if (props.historyData.length === 1) {
            return `M 0 ${priceToY(props.historyData[0])} L 400 ${priceToY(currentPrice.value)}`
        }
        let path = `M 0 ${priceToY(props.historyData[0])}`
        const step = 400 / (props.historyData.length - 1)
        props.historyData.forEach((price, index) => {
            if (index === 0) return
            path += ` L ${index * step} ${priceToY(price)}`
        })
        path += ` L 400 ${priceToY(currentPrice.value)}`
        return path
    }
    // 没有传入则生成模拟数据
    let path = 'M 0 120'
    let lastY = 120
    for (let i = 1; i < 10; i++) {
        lastY += (Math.random() - 0.5) * 40
        lastY = Math.max(30, Math.min(lastY, props.chartHeight - 50))
        path += ` L ${i * 40} ${lastY}`
    }
    path += ` L 400 ${priceToY(currentPrice.value)}`
    return path
})
// 历史区间下方淡色面积：用 historyPath 闭合到绘图区底部
const historyAreaPath = computed(() => {
    const p = historyPath.value
    if (!p) return ''
    const bottom = props.chartHeight - PAD_BOTTOM
    return `${p} L 400 ${bottom} L 0 ${bottom} Z`
})
</script>

<style scoped>
.stock-valuation-card {
    font-family: inherit;
    box-sizing: border-box;
}

.sv-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
}

.sv-title-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
}

.sv-accent {
    display: inline-block;
    width: 4px;
    height: 18px;
    border-radius: 2px;
    background: linear-gradient(180deg, #3b82f6, #6366f1);
}

.sv-header h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 700;
    color: #1f2937;
}

.sv-rating {
    margin: 0;
    font-size: 13px;
    color: #6b7280;
}

.sv-xlabel {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #9ca3af;
    padding: 2px 4px 0;
}

.sv-legend {
    display: flex;
    gap: 18px;
    justify-content: center;
    margin-top: 8px;
    font-size: 12px;
    color: #6b7280;
}

.sv-legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
}

.sv-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    display: inline-block;
}

.sv-dot--dash {
    background: transparent !important;
    border: 2px dashed #6b7280;
}
</style>
