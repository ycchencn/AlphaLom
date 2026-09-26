<!--
    StockValuationChartEcharts.vue
    DCF 三情景估值图（ECharts 实现）。

    ⚠️ 关键背景：本组件通常挂在 `v-show` 控制的分栏里（StockDetail 的技术面/基本面 tab），
    挂载瞬间父级 `display:none` → 容器宽高为 0 →
    此时 echarts.init() 会拿到一块 0 宽画布，且 `grid.left + grid.right`
    大于画布宽度，坐标轴标签互相叠在一起、数据全挤成左边一条。

    所以这里**不依赖挂载时机**：用 ResizeObserver 盯着容器，等它真正有了尺寸再初始化，
    之后尺寸变化（切 tab、改窗口、面板收起）自动 resize。
    与 StockValuationChart.vue（手绘 SVG 版）输入输出完全一致，仅渲染引擎不同；旧文件保留。
-->
<template>
    <div class="svc-root" :style="cardStyle">
        <!-- 顶部标题区：title 为空时不渲染（调用方已经有标题时避免重复） -->
        <div v-if="title" class="svc-header">
            <span class="svc-accent"></span>
            <h2 class="svc-title">{{ title }}</h2>
            <p v-if="ratingText" class="svc-rating">
                综合评级：<span :style="{ color: ratingColor, fontWeight: 'bold' }">{{ ratingText }}</span>
            </p>
        </div>

        <!-- 图表容器：外层给固定高度，内层交给 ECharts -->
        <div ref="wrapRef" class="svc-chart-wrap" :style="{ height: chartHeight + 'px' }">
            <div ref="chartRef" class="svc-chart"></div>
            <div v-if="!hasData" class="svc-empty">暂无 DCF 三情景估值数据</div>
        </div>

        <!-- X 轴说明：内边距对齐 grid，两段文字各自居中在「过去 / 未来」半区 -->
        <div
            v-if="showXAxisLabel && hasData"
            class="svc-xlabel"
            :style="{ paddingLeft: GRID.left + 'px', paddingRight: GRID.right + 'px' }"
        >
            <span class="svc-xlabel-half">过去一年</span>
            <span class="svc-xlabel-half">未来一年</span>
        </div>

        <!-- 图例：用线型色块表示，和图上线条一一对应 -->
        <div v-if="showLegend && hasData" class="svc-legend">
            <span class="svc-legend-item">
                <i class="svc-legend-line" :style="legendLineStyle(historyLineColor)"></i>历史走势
            </span>
            <span class="svc-legend-item">
                <i class="svc-legend-line" :style="legendLineStyle(conservativeLineColor)"></i>保守情景
            </span>
            <span class="svc-legend-item">
                <i class="svc-legend-line" :style="legendLineStyle(neutralLineColor, true)"></i>中性情景
            </span>
            <span class="svc-legend-item">
                <i class="svc-legend-line" :style="legendLineStyle(optimisticLineColor)"></i>乐观情景
            </span>
        </div>

        <!-- 估值建议 -->
        <div v-if="showAdvice" class="svc-advice">
            <span class="svc-advice-title">{{ adviceTitle }}：</span>
            <span>{{ adviceText }}</span>
        </div>
    </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import {
    COLORS, LINE, FONT,
    axisLabel, splitLine, tooltipBase, lineSeriesStyle, vLine, hLine, areaGradient, hexToRgba,
} from '@/utils/echartsTheme'

const props = defineProps({
    /** DCF 数据对象（含「每股内在价值」「估值判断」） */
    data: { type: Object, default: () => ({}) },
    /** 当前股价 */
    currentPrice: { type: [Number, String], default: 0 },
    /** 历史一年价格序列 */
    historyData: { type: Array, default: () => [] },
    /** 标题（为空则不渲染头部） */
    title: { type: String, default: '' },
    /** 评级文案 */
    ratingText: { type: String, default: '' },
    /** 评级颜色 */
    ratingColor: { type: String, default: '#f97316' },
    /** 固定 y 轴下限（>0 时覆盖自动计算） */
    minPrice: { type: Number, default: 0 },
    /** 固定 y 轴上限（>0 时覆盖自动计算） */
    maxPrice: { type: Number, default: 0 },
    /** 图表像素高度 */
    chartHeight: { type: Number, default: 300 },
    /** 是否显示图例 */
    showLegend: { type: Boolean, default: true },
    /** 是否显示 X 轴说明 */
    showXAxisLabel: { type: Boolean, default: true },
    /** 是否显示水平网格 */
    showGrid: { type: Boolean, default: true },
    /** 是否显示估值建议 */
    showAdvice: { type: Boolean, default: false },
    /** 估值建议标题 */
    adviceTitle: { type: String, default: '估值判断' },
    /** 卡片容器样式注意：默认不带边框/内边距，避免与外层容器形成「卡片套卡片」 */
    cardStyle: { type: Object, default: () => ({ width: '100%' }) },
    /** 配色：涨红跌绿（A 股习惯），故乐观=红、保守=绿 */
    historyLineColor: { type: String, default: '#3b82f6' },
    conservativeLineColor: { type: String, default: '#22c55e' },
    neutralLineColor: { type: String, default: '#94a3b8' },
    optimisticLineColor: { type: String, default: '#ef4444' }
})

/* ==================== 常量 ==================== */

/** 网格留白：右侧留出末端标签的位置，左侧留 y 轴刻度 */
const GRID = { top: 28, left: 58, right: 130, bottom: 24 }
/** x 轴数值范围：0~X_NOW 为历史，「现在」= X_NOW，X_NOW~X_END 为未来预测（1:1 等宽） */
const X_NOW = 400
const X_END = 800
/** 中国习惯：涨红跌绿（取自 echartsTheme.COLORS） */

/* ==================== 数据解析 ==================== */

const num = (v) => {
    const n = typeof v === 'string' ? parseFloat(v) : Number(v)
    return Number.isFinite(n) ? n : 0
}
/** 容忍中英文两种键名 */
const pick = (obj, ...keys) => {
    if (!obj || typeof obj !== 'object') return 0
    for (const k of keys) {
        const v = obj[k]
        if (v !== undefined && v !== null && v !== '') return num(v)
    }
    return 0
}

const rawScenario = computed(() => props.data?.每股内在价值 || props.data?.内在价值 || {})
const conservativeValue = computed(() => pick(rawScenario.value, '保守情景', '保守'))
const neutralValue = computed(() => pick(rawScenario.value, '中性情景', '中性'))
const optimisticValue = computed(() => pick(rawScenario.value, '乐观情景', '乐观'))
const adviceText = computed(() => props.data?.估值判断 || '暂无估值建议')

/** 有效历史序列（过滤空值/停牌 0 值） */
const historyValid = computed(() => props.historyData.map(num).filter((p) => p > 0))

/** 基准价：现价缺失时退化为中性情景，避免整条线塌到 0 */
const anchorPrice = computed(() => {
    const cur = num(props.currentPrice)
    if (cur > 0) return cur
    return neutralValue.value || optimisticValue.value || conservativeValue.value || 0
})

const hasData = computed(
    () =>
        anchorPrice.value > 0 ||
        conservativeValue.value > 0 ||
        neutralValue.value > 0 ||
        optimisticValue.value > 0
)

/** 参与 y 轴范围计算的全部数值 */
const allValues = computed(() =>
    [
        ...historyValid.value,
        anchorPrice.value,
        conservativeValue.value,
        neutralValue.value,
        optimisticValue.value
    ].filter((p) => p > 0)
)

/**
 * y 轴刻度取整：把「min~max」扩到步长整数倍，刻度才是 ¥10/¥20 这种整值，
 * 而不是 ¥14.31 这种被 padding 顶出来的怪数。
 */
const yRange = computed(() => {
    let min = 0
    let max = 1
    if (props.minPrice > 0 || props.maxPrice > 0) {
        min = props.minPrice > 0 ? props.minPrice : Math.min(...allValues.value)
        max = props.maxPrice > 0 ? props.maxPrice : Math.max(...allValues.value)
        return { min, max, step: (max - min) / 4 }
    }
    if (!allValues.value.length) return { min: 0, max: 1, step: 0.25 }
    const rawMin = Math.min(...allValues.value)
    const rawMax = Math.max(...allValues.value)
    // 上下各留 6% 呼吸空间
    const pad = (rawMax - rawMin) * 0.06 || rawMax * 0.1 || 1
    const lo = Math.max(0, rawMin - pad)
    const hi = rawMax + pad
    const span = hi - lo
    /**
     * 在「1/2/2.5/5 × 10^k」的候选步长里，取**最细**且满足三条约束的那个：
     * ① 刻度 3~6 段（不至于只剩两三根线）；② ③ 上下因取整多出来的空白不超过区间的 28%。
     * 只用「区间/4 再取整」的粗算法会把 11.5~55.6 扩成 0~60，
     * 底部白白多出 20% 死空间（就是之前「上下留白大」的同类问题）。
     */
    const candidates = []
    for (let k = -3; k <= 6; k++) {
        for (const m of [1, 2, 2.5, 5]) candidates.push(m * Math.pow(10, k))
    }
    candidates.sort((a, b) => a - b)
    let picked = null
    for (const step of candidates) {
        if (step <= 0) continue
        const tMin = Math.max(0, Math.floor(lo / step) * step)
        const tMax = Math.ceil(hi / step) * step
        const ticks = (tMax - tMin) / step
        if (ticks < 3 || ticks > 6) continue
        if (lo - tMin > span * 0.28 || tMax - hi > span * 0.28) continue
        picked = { min: tMin, max: tMax, step }
        break
    }
    if (!picked) {
        const step = span / 4 || 1
        picked = { min: lo, max: hi, step }
    }
    return picked
})

/** 小数位数直接由步长决定：步长 2.5 时若按 0 位显示会把 12.5 印成 13 */
const decimalsOf = (n) => {
    const s = String(n)
    if (s.includes('e-')) return Number(s.split('e-')[1])
    const dot = s.indexOf('.')
    return dot < 0 ? 0 : s.length - dot - 1
}

const formatAxisValue = (v) => {
    const digits = Math.min(2, decimalsOf(yRange.value.step))
    return '¥' + Number(v).toFixed(digits)
}

/** 三情景元数据（末端标签用） */
const scenarios = computed(() => {
    const cur = anchorPrice.value
    return [
        { key: 'con', name: '保守情景', value: conservativeValue.value, color: props.conservativeLineColor, dashed: false },
        { key: 'neu', name: '中性情景', value: neutralValue.value, color: props.neutralLineColor, dashed: true },
        { key: 'opt', name: '乐观情景', value: optimisticValue.value, color: props.optimisticLineColor, dashed: false }
    ]
        .filter((d) => d.value > 0)
        .map((d) => {
            const pct = cur > 0 ? ((d.value - cur) / cur) * 100 : 0
            const up = pct >= 0
            return {
                ...d,
                pct,
                up,
                text: `¥${d.value.toFixed(2)} ${up ? '↑ +' : '↓ '}${up ? pct.toFixed(1) : Math.abs(pct).toFixed(1)}%`
            }
        })
})

/* ==================== 工具 ==================== */

// hexToRgba 取自 echartsTheme（见顶部 import）

const legendLineStyle = (color, dashed = false) => {
    if (dashed) {
        return {
            backgroundImage: `repeating-linear-gradient(90deg, ${color} 0 4px, transparent 4px 7px)`,
            backgroundColor: 'transparent'
        }
    }
    return { background: color }
}

/* ==================== ECharts 配置 ==================== */

/** 未来预测区底纹 + 「现在」竖线 + 现价横线（统一挂在一个不可见系列上） */
const buildDecoSeries = () => ({
    name: '__deco',
    type: 'scatter',
    data: [],
    silent: true,
    symbol: 'none',
    tooltip: { show: false },
    z: 0,
    markArea: {
        silent: true,
        z: 0,
        itemStyle: { color: COLORS.markBg },
        data: [[{ xAxis: X_NOW }, { xAxis: X_END }]]
    },
    markLine: {
        silent: true,
        symbol: 'none',
        precision: 10,
        data: [
            vLine({
                xAxis: X_NOW,
                label: { formatter: '现在', position: 'insideEndTop', rotate: 0, color: COLORS.axisLabel, fontSize: FONT.axis }
            }),
            hLine({ yAxis: anchorPrice.value })
        ]
    }
})

/** 情景扇形带：栈式面积（下层不可见 + 上层叠差值），配纵向渐变 */
const buildBandSeries = () => {
    const cur = anchorPrice.value
    const con = conservativeValue.value
    const neu = neutralValue.value
    const opt = optimisticValue.value
    const bands = []

    const push = (stack, bottom, top, color, strongAtTop) => {
        const delta = top - bottom
        if (Math.abs(delta) < 0.01) return
        // 渐变方向：每条带都在**自己对应的那条情景线**上最浓
        // （保守带靠保守线=底边最浓，乐观带靠乐观线=顶边最浓）
        const from = strongAtTop ? 0.30 : 0.03
        const to = strongAtTop ? 0.03 : 0.30
        bands.push(
            {
                name: '__' + stack + 'l',
                type: 'line',
                stack,
                symbol: 'none',
                silent: true,
                tooltip: { show: false },
                lineStyle: { opacity: 0 },
                areaStyle: { opacity: 0 },
                z: 1,
                data: [
                    [X_NOW, cur],
                    [X_END, bottom]
                ]
            },
            {
                name: '__' + stack + 'u',
                type: 'line',
                stack,
                symbol: 'none',
                silent: true,
                tooltip: { show: false },
                lineStyle: { opacity: 0 },
                z: 1,
                areaStyle: {
                    color: areaGradient(color, from, to)
                },
                data: [
                    [X_NOW, 0],
                    [X_END, delta]
                ]
            }
        )
    }

    // 保守带：保守线 ~ 中性线（越靠保守线越浓）
    if (con > 0 && neu > 0) push('b1', con, neu, props.conservativeLineColor, false)
    // 乐观带：中性线 ~ 乐观线（越靠乐观线越浓）
    if (neu > 0 && opt > 0) push('b2', neu, opt, props.optimisticLineColor, true)
    return bands
}

const buildHistorySeries = () => {
    const hd = historyValid.value
    if (hd.length < 2) return null
    const step = X_NOW / (hd.length - 1)
    const data = hd.map((p, i) => [i * step, p])
    data.push([X_NOW, anchorPrice.value])
    return {
        name: '历史走势',
        type: 'line',
        smooth: 0.25,
        symbol: 'none',
        data,
        z: 3,
        ...lineSeriesStyle({ color: props.historyLineColor, area: true, areaFrom: 0.16, areaTo: 0, shadow: true }),
    }
}

const buildCurrentDot = () => {
    const cur = anchorPrice.value
    if (cur <= 0) return null
    return {
        name: '现价',
        type: 'scatter',
        symbolSize: 11,
        z: 10,
        data: [[X_NOW, cur]],
        itemStyle: {
            color: COLORS.dotBg,
            borderColor: props.historyLineColor,
            borderWidth: LINE.primary,
            shadowBlur: 5,
            shadowColor: hexToRgba(props.historyLineColor, 0.4)
        },
        label: {
            show: true,
            position: 'bottom',
            distance: 6,
            formatter: `¥${cur.toFixed(2)}`,
            color: props.historyLineColor,
            fontSize: FONT.label,
            fontWeight: 'bold'
        }
    }
}

const buildScenarioSeries = () =>
    scenarios.value.map((m) => ({
        name: m.name,
        type: 'line',
        symbol: 'none',
        z: 5,
        data: [
            [X_NOW, anchorPrice.value],
            [X_END, m.value]
        ],
        ...lineSeriesStyle({ color: m.color, dashed: m.dashed }),
        endLabel: {
            show: true,
            distance: 6,
            backgroundColor: '#fff',
            borderColor: '#eef0f3',
            borderWidth: 1,
            borderRadius: 4,
            padding: [3, 6],
            formatter: () => `{v|¥${m.value.toFixed(2)}} {p|${m.up ? '↑ +' : '↓ '}${m.up ? m.pct.toFixed(1) : Math.abs(m.pct).toFixed(1)}%}`,
            rich: {
                v: { color: COLORS.textStrong, fontSize: FONT.label, fontWeight: 'bold' },
                p: { color: m.up ? COLORS.up : COLORS.down, fontSize: FONT.label, fontWeight: 'bold' }
            }
        }
    }))

const buildOption = () => {
    // 无数据时只留空态，不画坐标轴/网格/参考线（避免“坏图”观感）
    if (!hasData.value) {
        return {
            animation: false,
            grid: { ...GRID },
            xAxis: { type: 'value', min: 0, max: X_END, show: false },
            yAxis: { type: 'value', min: 0, max: 1, show: false },
            series: []
        }
    }

    const series = [buildDecoSeries(), ...buildBandSeries()]
    const hist = buildHistorySeries()
    if (hist) series.push(hist)
    const dot = buildCurrentDot()
    if (dot) series.push(dot)
    series.push(...buildScenarioSeries())

    return {
        animationDuration: 500,
        grid: { ...GRID },
        tooltip: tooltipBase({
            axisPointer: { type: 'line', lineStyle: { color: COLORS.guideStrong, type: 'dashed' } },
            formatter: (params) => {
                const list = (params || []).filter(
                    (p) => !String(p.seriesName || '').startsWith('__') && p.value !== null
                )
                if (!list.length) return ''
                return list
                    .map((p) => {
                        const y = Array.isArray(p.value) ? p.value[1] : p.value
                        if (y === null || y === undefined) return ''
                        return `${p.marker}${p.seriesName}　<b>¥${Number(y).toFixed(2)}</b>`
                    })
                    .filter(Boolean)
                    .join('<br/>')
            }
        }),
        xAxis: { type: 'value', min: 0, max: X_END, show: false },
        yAxis: {
            type: 'value',
            min: yRange.value.min,
            max: yRange.value.max,
            interval: yRange.value.step,
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: splitLine({ show: props.showGrid }),
            axisLabel: axisLabel({ formatter: formatAxisValue })
        },
        series
    }
}

/* ==================== 实例生命周期 ==================== */

const wrapRef = ref(null)
const chartRef = ref(null)
let chart = null
let observer = null

/** 容器真正有尺寸后才初始化；隐藏面板里（宽高 0）直接跳过，等 ResizeObserver 再触发 */
const ensureChart = () => {
    if (chart && !chart.isDisposed()) return chart
    const el = chartRef.value
    if (!el) return null
    if (el.clientWidth < 20 || el.clientHeight < 20) return null
    chart = echarts.init(el)
    chart.setOption(buildOption(), true)
    return chart
}

const resize = () => {
    const c = ensureChart()
    if (c) c.resize()
}

const refresh = () => {
    if (chart && !chart.isDisposed()) chart.setOption(buildOption(), true)
    else resize()
}

onMounted(() => {
    resize()
    if (typeof ResizeObserver !== 'undefined' && wrapRef.value) {
        observer = new ResizeObserver(() => resize())
        observer.observe(wrapRef.value)
    }
    window.addEventListener('resize', resize)
    // 兜底：flex / 栅格宽度常在下一帧才确定
    nextTick(() => setTimeout(resize, 80))
})

onBeforeUnmount(() => {
    window.removeEventListener('resize', resize)
    if (observer) {
        observer.disconnect()
        observer = null
    }
    if (chart) {
        chart.dispose()
        chart = null
    }
})

watch(
    () => [props.data, props.currentPrice, props.historyData, props.chartHeight, props.showGrid, props.minPrice, props.maxPrice],
    () => refresh(),
    { deep: true }
)
</script>

<style scoped>
.svc-root {
    box-sizing: border-box;
    font-family: inherit;
}

.svc-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
}

.svc-accent {
    display: inline-block;
    width: 4px;
    height: 18px;
    border-radius: 2px;
    background: linear-gradient(180deg, #3b82f6, #6366f1);
}

.svc-title {
    margin: 0;
    font-size: 0.85rem;
    font-weight: 700;
    color: #1f2937;
}

.svc-rating {
    margin: 0 0 0 auto;
    font-size: 10px;
    color: #6b7280;
}

.svc-chart-wrap {
    position: relative;
    width: 100%;
    /* 固定高度 + 不允许 flex 压缩：容器塌陷是这类图表最常见的“隐形”故障源 */
    flex: 0 0 auto;
    min-height: 120px;
}

.svc-chart {
    width: 100%;
    height: 100%;
}

.svc-empty {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    color: #9ca3af;
}

.svc-xlabel {
    display: flex;
    box-sizing: border-box;
    font-size: 10px;
    color: #9ca3af;
    margin-top: 2px;
}

.svc-xlabel-half {
    flex: 1 1 0;
    text-align: center;
}

.svc-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    justify-content: center;
    margin-top: 8px;
    font-size: 10px;
    color: #6b7280;
}

.svc-legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
}

.svc-legend-line {
    display: inline-block;
    width: 16px;
    height: 1.5px;
    border-radius: 2px;
}

.svc-advice {
    margin-top: 10px;
    font-size: 10px;
    color: #374151;
    background: #f8fafc;
    border-radius: 8px;
    padding: 8px 12px;
}

.svc-advice-title {
    font-weight: 600;
    color: #1f2937;
}
</style>
