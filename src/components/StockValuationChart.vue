<!-- StockValuationChart.vue -->
<template>
    <div
        class="stock-valuation-card"
        :style="cardStyle"
    >
        <!-- 顶部标题区 -->
        <div v-if="showHeader" class="sv-header">
            <h2 :style="titleStyle">{{ title }}</h2>
            <p class="sv-rating" :style="ratingStyle">
                综合评级：<span :style="{color: ratingColor, fontWeight: 'bold'}">{{ ratingText }}</span>
            </p>
        </div>

        <!-- SVG核心图表 -->
        <svg
            width="100%"
            :height="chartHeight"
            :viewBox="`0 0 920 ${chartHeight - 40}`"
            style="display: block;"
        >
            <!-- 背景网格线 -->
            <line v-if="showGrid" x1="200" y1="20" x2="200" :y2="chartHeight - 60" stroke="#eee"
                  stroke-dasharray="4 4"/>
            <line v-if="showGrid" x1="400" y1="20" x2="400" :y2="chartHeight - 60" stroke="#eee"
                  stroke-dasharray="4 4"/>
            <line v-if="showGrid" x1="600" y1="20" x2="600" :y2="chartHeight - 60" stroke="#eee"
                  stroke-dasharray="4 4"/>
            <line v-if="showGrid" x1="0" y1="70" x2="800" y2="70" stroke="#eee" stroke-dasharray="4 4"/>
            <line v-if="showGrid" x1="0" y1="150" x2="800" y2="150" stroke="#eee" stroke-dasharray="4 4"/>
            <line v-if="showGrid" x1="0" y1="230" x2="800" y2="230" stroke="#eee" stroke-dasharray="4 4"/>
            <!-- 预测区间填充 -->
            <path
                :d="`M 400 ${priceToY(currentPrice)} L 800 ${priceToY(conservativeValue)} L 800 ${priceToY(neutralValue)} Z`"
                :fill="conservativeAreaColor"
            />
            <path
                :d="`M 400 ${priceToY(currentPrice)} L 800 ${priceToY(neutralValue)} L 800 ${priceToY(optimisticValue)} Z`"
                :fill="optimisticAreaColor"
            />
            <!-- 历史走势折线 -->
            <path
                :d="historyPath"
                :stroke="historyLineColor"
                stroke-width="2"
                fill="none"
            />
            <!-- 预测线 -->
            <line
                x1="400"
                :y1="priceToY(currentPrice)"
                x2="800"
                :y2="priceToY(conservativeValue)"
                :stroke="conservativeLineColor"
                stroke-width="2"
            />
            <line
                x1="400"
                :y1="priceToY(currentPrice)"
                x2="800"
                :y2="priceToY(neutralValue)"
                :stroke="neutralLineColor"
                stroke-width="2"
                stroke-dasharray="4 4"
            />
            <line
                x1="400"
                :y1="priceToY(currentPrice)"
                x2="800"
                :y2="priceToY(optimisticValue)"
                :stroke="optimisticLineColor"
                stroke-width="2"
            />
            <!-- 当前价格标记 -->
            <circle cx="400" :cy="priceToY(currentPrice)" r="6" :fill="historyLineColor"/>
            <text
                x="400"
                :y="priceToY(currentPrice) - 20"
                text-anchor="middle"
                font-size="16"
                font-weight="bold"
            >
                现价 {{ currentPrice }}
            </text>
            <!-- 右侧外置标签，自动和对应估值线水平对齐 -->
            <rect x="810" :y="priceToY(optimisticValue) - 13" width="100" height="24" rx="3"
                  :fill="optimisticLineColor"/>
            <text x="860" :y="priceToY(optimisticValue)" text-anchor="middle" dominant-baseline="middle" fill="#fff"
                  font-size="14">
                乐观 {{ optimisticValue.toFixed(2) }}
            </text>
            <rect x="810" :y="priceToY(neutralValue) - 14" width="100" height="24" rx="3" :fill="neutralLineColor"/>
            <text x="860" :y="priceToY(neutralValue)" text-anchor="middle" dominant-baseline="middle" fill="#fff"
                  font-size="14">
                中性 {{ neutralValue.toFixed(2) }}
            </text>
            <rect x="810" :y="priceToY(conservativeValue) - 14" width="100" height="24" rx="3"
                  :fill="conservativeLineColor"/>
            <text x="860" :y="priceToY(conservativeValue)" text-anchor="middle" dominant-baseline="middle" fill="#fff"
                  font-size="14">
                保守 {{ conservativeValue.toFixed(2) }}
            </text>
        </svg>

        <!-- X轴说明 -->
        <div v-if="showXAxisLabel" class="sv-xlabel" :style="xLabelStyle">
            <span>过去1年走势</span>
            <span>未来1年预测</span>
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
    /** 图表高度 */
    chartHeight: {
        type: Number,
        default: 240
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
            maxWidth: '900px',
            margin: '0px auto',
            padding: '0px 10px',
            background: '#fff',
            border: '1px solid #eee',
            borderRadius: '0px',
            boxShadow: ''
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

/** 把可能是数字 / 带单位脏字符串的值，安全转成数字 */
function parseNumber(input, fallback = 0) {
    if (typeof input === 'number') return Number.isFinite(input) ? input : fallback
    if (typeof input !== 'string') return fallback

    // 全角数字转半角，去掉千分位逗号和所有空白
    const raw = input
        .replace(/[\uFF10-\uFF19]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
        .replace(/[,\s\u00A0]/g, '')
    if (!raw) return fallback

    // 抠出第一个数字（含负号、小数、科学计数法）
    const matched = raw.match(/-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/)
    if (!matched) return fallback          // "—"、"暂无"、"" 都会走到这里

    let n = Number(matched[0])
    // 中文数量单位（长的先匹配，避免 "千万" 被拆成 "千"）
    const unit = raw.match(/(千万|百万|十万|亿|万|千)/)
    if (unit) {
        const map = {千: 1e3, 万: 1e4, 十万: 1e5, 百万: 1e6, 千万: 1e7, 亿: 1e8}
        n *= map[unit[1]]
    }
    return Number.isFinite(n) ? n : fallback
}

// 数据提取&容错
const currentPrice = computed(() => parseNumber(props.currentPrice))
const conservativeValue = computed(() => parseNumber(props.data?.每股内在价值?.保守情景))
const neutralValue = computed(() => parseNumber(props.data?.每股内在价值?.中性情景))
const optimisticValue = computed(() => parseNumber(props.data?.每股内在价值?.乐观情景))
const adviceText = computed(() => props.data?.估值判断 || '暂无估值建议')

// ★ 新增：自动计算动态价格上下限，自动覆盖历史+当前+DCF估值全区间
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
    ]
    const minVal = Math.min(...allValidPrices)
    // 下浮10%做padding，避免价格贴到画布底部，最低不小于0
    return Math.max(0, minVal * 0.9)
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
    ]
    const maxVal = Math.max(...allValidPrices)
    // 上浮10%做padding，避免价格贴到画布顶部
    return maxVal * 1.1
})
/**
 * ★ 优化价格转坐标逻辑，处理边界异常
 * @param {number} price 股票价格
 * @returns {number} Y坐标值
 */
const priceToY = (price) => {
    const validHeight = props.chartHeight - 80
    const minP = dynamicMinPrice.value
    const maxP = dynamicMaxPrice.value
    // 边界处理：所有价格相等时，返回垂直居中坐标，避免除以0报错
    if (maxP === minP) {
        return (props.chartHeight - 40) / 2
    }
    // 限制价格在区间内，防止异常价格溢出画布
    const safePrice = Math.max(minP, Math.min(price, maxP))
    return (props.chartHeight - 40) - ((safePrice - minP) * validHeight / (maxP - minP))
}
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
</script>