<template>
    <div
        class="stock-mini-trend"
        :style="cardStyle"
        @click="$emit('click')"
        style="cursor: pointer;"
    >
        <!-- SVG迷你走势图 -->
        <svg
            width="100%"
            :height="chartHeight"
            :viewBox="`0 0 200 ${chartHeight - 10}`"
            style="display: block;"
        >
            <!-- 背景网格（和原组件风格一致，默认关闭） -->
            <line v-if="showGrid" x1="50" y1="0" x2="50" :y2="chartHeight - 10" stroke="#eee" stroke-dasharray="2 2"/>
            <line v-if="showGrid" x1="100" y1="0" x2="100" :y2="chartHeight - 10" stroke="#eee" stroke-dasharray="2 2"/>
            <line v-if="showGrid" x1="150" y1="0" x2="150" :y2="chartHeight - 10" stroke="#eee" stroke-dasharray="2 2"/>
            <!-- 走势折线（和原组件线条样式完全一致） -->
            <path
                :d="trendPath"
                :stroke="lineColor"
                stroke-width="2"
                fill="none"
            />
            <!-- 当前价标记点（和原组件圆点样式一致） -->
            <circle
                v-if="showCurrentDot"
                cx="200"
                :cy="priceToY(currentPrice)"
                r="3"
                :fill="lineColor"
            />
            <!-- 右上角涨跌幅标签（可选） -->
            <text
                v-if="showChangeTag"
                x="0"
                y="16"
                :fill="changeRate >=0 ? riseColor : fallColor"
                font-size="12"
                font-weight="bold"
            >
                {{ changeRate >= 0 ? '+' : '' }}{{ (changeRate * 100).toFixed(1) }}%
            </text>
        </svg>
    </div>
</template>

<script setup>
import {computed} from 'vue'

const emit = defineEmits(['click'])

const props = defineProps({
    /** 必填：近1个月收盘价数组，正序（旧数据在前，新数据在后，和原组件historyData格式完全一致） */
    historyData: {
        type: Array,
        required: true,
        validator: val => val.length >= 1
    },
    /** 可选：当前价，不传默认取历史数据最后一条 */
    currentPrice: {
        type: Number,
        default: 0
    },
    /** 可选：涨跌幅（小数，0.05=涨5%），不传自动计算（近1月涨跌幅） */
    changeRate: {
        type: Number,
        default: null
    },
    /** 图表高度，列表用默认80px足够 */
    chartHeight: {
        type: Number,
        default: 80
    },
    /** 是否显示网格（默认关闭，列表更简洁） */
    showGrid: {
        type: Boolean,
        default: false
    },
    /** 是否显示当前价圆点标记 */
    showCurrentDot: {
        type: Boolean,
        default: true
    },
    /** 是否显示左上角涨跌幅标签 */
    showChangeTag: {
        type: Boolean,
        default: false
    },
    /** 线条颜色（默认和原组件历史线一致#3b82f6，设为true则自动根据涨跌变红/绿） */
    lineColor: {
        type: [String, Boolean],
        default: '#3b82f6'
    },
    /** 上涨颜色（默认A股红涨） */
    riseColor: {
        type: String,
        default: '#ef4444'
    },
    /** 下跌颜色（默认A股绿跌） */
    fallColor: {
        type: String,
        default: '#22c55e'
    },
    /** 卡片样式，默认适合列表嵌入 */
    cardStyle: {
        type: Object,
        default: () => ({
            width: '100%',
            padding: '4px',
            background: '#fff'
        })
    }
})

// 数据提取&容错
const validHistory = computed(() => props.historyData.filter(p => p && p > 0))
const finalCurrentPrice = computed(() => props.currentPrice || validHistory.value.at(-1) || 0)
const startPrice = computed(() => validHistory.value[0] || finalCurrentPrice.value)

// 自动计算涨跌幅（未传入时）
const finalChangeRate = computed(() => {
    if (props.changeRate !== null) return props.changeRate
    return startPrice.value ? (finalCurrentPrice.value / startPrice.value - 1) : 0
})

// 自动计算价格区间（和原组件逻辑一致，上下留5% padding）
const minPrice = computed(() => {
    const minVal = Math.min(...validHistory.value, finalCurrentPrice.value)
    return Math.max(0, minVal * 0.95)
})
const maxPrice = computed(() => {
    const maxVal = Math.max(...validHistory.value, finalCurrentPrice.value)
    return maxVal * 1.05
})

// 动态线条颜色（如果lineColor设为true则自动涨跌变色）
const finalLineColor = computed(() => {
    if (typeof props.lineColor === 'string') return props.lineColor
    return finalChangeRate.value >= 0 ? props.riseColor : props.fallColor
})

/** 价格转Y坐标（完全复用原组件逻辑，风格统一） */
const priceToY = (price) => {
    const validHeight = props.chartHeight - 10
    if (maxPrice.value === minPrice.value) return validHeight / 2
    const safePrice = Math.max(minPrice.value, Math.min(price, maxPrice.value))
    return validHeight - ((safePrice - minPrice.value) * validHeight / (maxPrice.value - minPrice.value))
}

/** 生成走势路径（近1月数据自动适配宽度） */
const trendPath = computed(() => {
    const data = validHistory.value
    if (data.length === 1) {
        return `M 0 ${priceToY(data[0])} L 200 ${priceToY(finalCurrentPrice.value)}`
    }
    let path = `M 0 ${priceToY(data[0])}`
    const step = 200 / (data.length - 1)
    data.forEach((price, index) => {
        if (index === 0) return
        path += ` L ${index * step} ${priceToY(price)}`
    })
    path += ` L 200 ${priceToY(finalCurrentPrice.value)}`
    return path
})
</script>