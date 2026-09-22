<script setup>
/**
 * 沪深大盘监控
 *
 * 页面结构（自上而下）：
 *   1. 指数卡片行    —— GET /api/v1/index/last_tick（F1：补全沪深300、空值跳过、真实数据时间）
 *   2. 大盘恐惧贪婪  —— GET /api/v1/market/fear_greed（F4：综合值 + 近一年走势 + 分量拆解）
 *   3. 申万行业排行  —— GET /api/v1/market/sectors（F3：一级/二级/三级可切换）
 *
 * 刷新策略（F2）：默认 60s 轮询，页面切到后台自动暂停；指数 tick 与恐惧贪婪
 * 分开刷新 —— 前者是盘中盯盘数据（后端缓存 20s），后者是日线（后端缓存 1h），
 * 用一个定时器同时刷会让日线数据被无意义地重复请求。
 */
import {ref, onMounted, onUnmounted, computed, watch, nextTick} from 'vue'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import axios from 'axios'
import * as echarts from 'echarts'
import ProgressBar200p from '@/components/ProgressBar200p.vue'

// ========================
// 常量
// ========================
// ⚠️ 必须与后端 routes/index.py 的 INDEX_CODES 保持一致：
// 前端有名字而后端不返回的指数，卡片根本不会渲染（不是显示空值），很隐蔽。
const INDICES_NAME = {
    '000001': '上证指数',
    '399001': '深证成指',
    '399006': '创业板指',
    '000688': '科创50',
    '000692': '科创200',
    '000300': '沪深300'
}

// 恐惧贪婪可选的指数（上游 /cn/market/fear_greed 只覆盖这 4 个，
// 深证成指 / 科创50 / 科创200 上游暂无该数据）
const FEAR_GREED_INDICES = [
    {label: '上证指数', value: '000001'},
    {label: '沪深300', value: '000300'},
    {label: '创业板指', value: '399006'},
    {label: '中证500', value: '000905'}
]

const SECTOR_TYPES = [
    {label: '申万一级', value: 'sw1'},
    {label: '申万二级', value: 'sw2'},
    {label: '申万三级', value: 'sw3'}
]

const TICK_REFRESH_MS = 30 * 1000      // 指数行情刷新间隔
const FEAR_GREED_REFRESH_MS = 10 * 60 * 1000   // 恐惧贪婪为日线，刷太勤没意义

// ========================
// 状态
// ========================
const index_last_tick = ref([])
const data_time = ref('')          // 真实数据时间（取所有指数 tick_time 的最大值）

const sectors = ref([])
const sector_type = ref('sw1')
const sectors_loading = ref(false)

const fear_greed_index = ref('000001')
const fear_greed_list = ref([])
const fear_greed_loading = ref(false)

const auto_refresh = ref(true)

// ========================
// 工具函数
// ========================
const getChangeColor = (val) => (val >= 0 ? 'var(--color-up)' : 'var(--color-down)')
const formatSign = (val) => (val > 0 ? `+${val.toFixed(2)}` : val.toFixed(2))

const getPctColorClass = (value) => {
    if (value > 0) return 'text-up'
    if (value < 0) return 'text-down'
    return 'text-flat'
}

// 恐惧贪婪 0~100 的情绪分档。阈值参考主流 Fear & Greed 口径：
// 0-25 极度恐惧 / 25-45 恐惧 / 45-55 中性 / 55-75 贪婪 / 75-100 极度贪婪
const fearGreedLabel = (val) => {
    if (val == null) return '--'
    if (val < 25) return '极度恐惧'
    if (val < 45) return '恐惧'
    if (val < 55) return '中性'
    if (val < 75) return '贪婪'
    return '极度贪婪'
}

// 情绪色带：恐惧偏绿、贪婪偏红（与 A 股红涨绿跌一致）
const fearGreedColor = (val) => {
    if (val == null) return '#909399'
    if (val < 25) return '#12783c'
    if (val < 45) return '#4a9e6b'
    if (val < 55) return '#909399'
    if (val < 75) return '#e8874a'
    return '#ef4444'
}

// ========================
// 指数行情（F1）
// ========================
// 上游 tick 的时间字段是 `time`（毫秒时间戳），**不是 `tick_time`**。
// 原实现读 `item.tick_time` 拿到 undefined，`new Date(undefined)` 得到
// Invalid Date 并被静默丢弃（因为当时没有任何地方显示它）。
// 这里两种字段名都兼容，且同时接受毫秒数、秒数与 ISO 字符串。
const parseTickTime = (item) => {
    const raw = item?.time ?? item?.tick_time
    if (raw == null || raw === '') return null
    if (typeof raw === 'number') {
        // 13 位毫秒；10 位秒
        return new Date(raw < 1e12 ? raw * 1000 : raw)
    }
    const d = new Date(raw)
    return Number.isNaN(d.getTime()) ? null : d
}

const fetchIndexTick = async () => {
    const res = await axios.get('/api/v1/index/last_tick')
    const list = Array.isArray(res.data) ? res.data : []
    list.forEach((item) => {
        // 上游偶发字段缺失，逐个兜底 —— 直接 toFixed 会因 undefined 抛错让整块渲染失败
        const lastPrice = Number(item.lastPrice ?? 0)
        const lastClose = Number(item.lastClose ?? 0)
        item.change = lastClose ? lastPrice - lastClose : 0
        item.changePercent = lastClose ? (item.change / lastClose) * 100 : 0
        const t = parseTickTime(item)
        item.formatTime = t ? t.toLocaleString() : '--'
        item._ts = t ? t.getTime() : null
    })
    index_last_tick.value = list

    // F1：标题栏显示「数据时间」而非渲染时刻。原实现用 new Date() ，
    // 页面开着不动就会一直显示当前时间，让人误以为数据是新的。
    const times = list.map((i) => i._ts).filter((t) => t != null)
    data_time.value = times.length ? new Date(Math.max(...times)).toLocaleString() : '--'
}

// ========================
// 申万行业（F3）
// ========================
const fetchSectors = async () => {
    sectors_loading.value = true
    try {
        const res = await axios.get('/api/v1/market/sectors', {
            params: {sector_type: sector_type.value}
        })
        sectors.value = Array.isArray(res.data) ? res.data : []
    } finally {
        sectors_loading.value = false
    }
}

watch(sector_type, fetchSectors)

// ========================
// 恐惧贪婪（F4）
// ========================
const fearGreedLatest = computed(() => fear_greed_list.value[fear_greed_list.value.length - 1] || null)

const fetchFearGreed = async () => {
    fear_greed_loading.value = true
    try {
        const res = await axios.get('/api/v1/market/fear_greed', {
            params: {index_code: fear_greed_index.value, days: 365}
        })
        fear_greed_list.value = Array.isArray(res.data) ? res.data : []
        renderFearGreedChart()
    } finally {
        fear_greed_loading.value = false
    }
}

watch(fear_greed_index, fetchFearGreed)

// ========================
// ECharts：恐惧贪婪走势
// ========================
const fgChartRef = ref(null)
let fgChart = null

/**
 * 懒初始化 ECharts 实例。
 *
 * ⚠️ 图表容器在 `v-if="fearGreedLatest"` 内部 —— 首屏 onMounted 时数据还没到、
 * fearGreedLatest 为 null，那个 div 根本没进 DOM，fgChartRef.value 是 **null**。
 * 此时调 echarts.init(null) 会在 echarts 内部抛
 * `Cannot read properties of null (reading 'getAttribute')`，而且这个异常发生在
 * 渲染阶段，会把整个组件的挂载链打断 —— 表现是**页面所有数据都不渲染**，
 * 但接口其实一个都没发出去（极易误判成后端问题）。
 * 所以必须在数据到位、DOM 真正存在之后再 init。
 */
const ensureChart = () => {
    if (fgChart || !fgChartRef.value) return fgChart
    fgChart = echarts.init(fgChartRef.value)
    return fgChart
}

const renderFearGreedChart = async () => {
    // nextTick：数据赋值 → v-if 变真 → DOM 出现，等这一拍再 init
    await nextTick()
    const chart = ensureChart()
    if (!chart) return

    const rows = fear_greed_list.value
    if (!rows.length) {
        chart.clear()
        return
    }
    chart.setOption({
        grid: {left: 32, right: 12, top: 16, bottom: 22},
        tooltip: {
            trigger: 'axis',
            formatter: (params) => {
                const p = params[0]
                const d = rows[p.dataIndex]
                return `${d.trade_date}<br/>综合: <b>${d.fear_greed}</b>（${fearGreedLabel(d.fear_greed)}）`
                    + `<br/>波动分: ${d.vol_score ?? '--'}<br/>动量分: ${d.mom_score ?? '--'}`
            }
        },
        xAxis: {
            type: 'category',
            data: rows.map((r) => r.trade_date),
            show: false
        },
        yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            splitNumber: 2,
            axisLabel: {fontSize: 9, color: '#94a3b8'},
            splitLine: {lineStyle: {color: '#eef1f6'}}
        },
        series: [{
            type: 'line',
            data: rows.map((r) => r.fear_greed),
            smooth: true,
            showSymbol: false,
            lineStyle: {width: 1.5, color: '#ef4444'},
            areaStyle: {
                color: {
                    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [
                        {offset: 0, color: 'rgba(239,68,68,0.28)'},
                        {offset: 1, color: 'rgba(239,68,68,0.02)'}
                    ]
                }
            },
            // 50 为多空分界参考线
            markLine: {
                silent: true,
                symbol: 'none',
                label: {show: false},
                lineStyle: {type: 'dashed', color: '#cbd5e1'},
                data: [{yAxis: 50}, {yAxis: 25}, {yAxis: 75}]
            }
        }]
    })
}

const resizeCharts = () => fgChart?.resize()
// ========================
// 生命周期（F2：自动刷新）
// ========================
let tickTimer = null
let fgTimer = null

const startTimers = () => {
    stopTimers()
    tickTimer = setInterval(fetchIndexTick, TICK_REFRESH_MS)
    fgTimer = setInterval(fetchFearGreed, FEAR_GREED_REFRESH_MS)
}

const stopTimers = () => {
    if (tickTimer) clearInterval(tickTimer)
    if (fgTimer) clearInterval(fgTimer)
    tickTimer = null
    fgTimer = null
}

watch(auto_refresh, (on) => (on ? startTimers() : stopTimers()))

// 页面切到后台时暂停轮询：盯盘页面开一天会产生上万次无意义请求，
// 既压上游也让服务端日志噪音很大。切回来立刻补一次，避免看到过期数据。
const onVisibilityChange = () => {
    if (document.hidden) {
        stopTimers()
    } else if (auto_refresh.value) {
        fetchIndexTick()
        startTimers()
    }
}

onMounted(async () => {
    // ⚠️ 这里**不能**直接 echarts.init(fgChartRef.value)：图表容器在 v-if 里，
    // 首屏此刻还没渲染，ref 是 null（详见 ensureChart 注释）。真正的 init
    // 放在 fetchFearGreed -> renderFearGreedChart -> ensureChart 里。
    window.addEventListener('resize', resizeCharts)
    document.addEventListener('visibilitychange', onVisibilityChange)

    // 首屏并发拉取：三个接口互不依赖，串行等待会让首屏白屏时间翻倍。
    // 用 allSettled：任一接口挂掉不应该让另外两个也不显示。
    await Promise.allSettled([fetchIndexTick(), fetchSectors(), fetchFearGreed()])
    startTimers()
})

onUnmounted(() => {
    stopTimers()
    window.removeEventListener('resize', resizeCharts)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    fgChart?.dispose()
    fgChart = null
})
</script>

<template>
    <div class="dashboard-container">
        <!-- 顶部标题栏 -->
        <div class="header">
            <h1 class="title">沪深大盘监控</h1>
            <div class="header-right">
                <span class="update-time">数据时间: {{ data_time || '--' }}
                    <span v-if="index_last_tick[0]?.formatTime" class="tick-time">
                        （最新行情 {{ index_last_tick[0].formatTime }}）
                    </span>
                </span>
                <label class="auto-refresh">
                    <ToggleSwitch v-model="auto_refresh" />
                    <span>{{ auto_refresh ? '自动刷新 30s' : '已暂停' }}</span>
                </label>
            </div>
        </div>

        <!-- 指数卡片行 -->
        <div class="indices-row">
            <Card v-for="item in index_last_tick" :key="item.index_code" class="index-card">
                <template #content>
                    <div class="card-content">
                        <div class="index-name">{{ INDICES_NAME[item.index_code] || item.index_code }}</div>
                        <div class="index-code">{{ item.index_code }}</div>
                        <div class="index-price">{{ Number(item.lastPrice ?? 0).toFixed(2) }}</div>
                        <div class="index-change" :style="{ color: getChangeColor(item.change) }">
                            <span>{{ formatSign(item.change) }}</span>
                            <span class="change-percent">{{ formatSign(item.changePercent) }}%</span>
                        </div>
                    </div>
                </template>
            </Card>
            <div v-if="!index_last_tick.length" class="empty-tip">暂无指数行情</div>
        </div>

        <!-- F4 大盘恐惧贪婪 -->
        <Card class="fear-greed-card">
            <template #title>
                <div class="card-title-row">
                    <span>大盘恐惧贪婪指数</span>
                    <SelectButton
                        v-model="fear_greed_index"
                        :options="FEAR_GREED_INDICES"
                        optionLabel="label"
                        optionValue="value"
                        :allowEmpty="false"
                        size="small"
                    />
                </div>
            </template>
            <template #content>
                <div v-if="fearGreedLatest" class="fear-greed-body">
                    <!-- 左：当前值 -->
                    <div class="fg-current">
                        <div class="fg-value" :style="{ color: fearGreedColor(fearGreedLatest.fear_greed) }">
                            {{ Number(fearGreedLatest.fear_greed ?? 0).toFixed(2) }}
                        </div>
                        <div class="fg-label" :style="{ color: fearGreedColor(fearGreedLatest.fear_greed) }">
                            {{ fearGreedLabel(fearGreedLatest.fear_greed) }}
                        </div>
                        <div class="fg-date">{{ fearGreedLatest.trade_date }}</div>

                        <!-- 分量拆解：用迷你条直观表达两个 0~100 分项的相对高低 -->
                        <div class="fg-scores">
                            <div class="fg-score">
                                <span class="score-name">波动分</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: Math.min(100, Number(fearGreedLatest.vol_score ?? 0)) + '%',
                                                    background: fearGreedColor(fearGreedLatest.vol_score) }"></span>
                                </span>
                                <span class="score-val">{{ Number(fearGreedLatest.vol_score ?? 0).toFixed(1) }}</span>
                            </div>
                            <div class="fg-score">
                                <span class="score-name">动量分</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: Math.min(100, Number(fearGreedLatest.mom_score ?? 0)) + '%',
                                                    background: fearGreedColor(fearGreedLatest.mom_score) }"></span>
                                </span>
                                <span class="score-val">{{ Number(fearGreedLatest.mom_score ?? 0).toFixed(1) }}</span>
                            </div>
                            <div class="fg-score">
                                <span class="score-name">指数点位</span>
                                <span class="score-val score-val-wide">
                                    {{ Number(fearGreedLatest.close ?? 0).toFixed(2) }}
                                </span>
                            </div>
                        </div>
                    </div>
                    <!-- 右：近一年走势 -->
                    <div class="fg-chart-wrap">
                        <div class="fg-chart-title">近一年走势</div>
                        <div ref="fgChartRef" class="fg-chart" :class="{'is-loading': fear_greed_loading}"></div>
                    </div>
                </div>
                <div v-else class="empty-tip">
                    {{ fear_greed_loading ? '加载中…' : '该指数暂无恐惧贪婪数据' }}
                </div>
            </template>
        </Card>

        <!-- F3 申万行业涨跌排行（一级/二级/三级可切换） -->
        <Card class="chart-card sector-card-custom">
            <template #title>
                <div class="card-title-row">
                    <span>申万行业涨跌排行</span>
                    <SelectButton
                        v-model="sector_type"
                        :options="SECTOR_TYPES"
                        optionLabel="label"
                        optionValue="value"
                        :allowEmpty="false"
                        size="small"
                    />
                </div>
            </template>
            <template #content>
                <DataTable
                    :value="sectors"
                    :loading="sectors_loading"
                    stripedRows
                    size="small"
                    class="sector-table"
                    :sortField="'change_pct'"
                    :sortOrder="-1"
                    sortMode="single"
                    removableSort
                    :rowHover="true"
                    scrollable
                    scrollHeight="420px"
                >
                    <Column field="sector_name" header="板块" :filter="true" filterPlaceholder="搜索板块"/>
                    <Column field="top_stock" header="领涨股">
                        <template #body="{ data }">
                            <span class="text-up">
                              {{ data.top_stock || '--' }}
                              <span class="text-xxs">({{ data.top_stock_pct?.toFixed(2) }}%)</span>
                            </span>
                        </template>
                    </Column>
                    <Column field="bottom_stock" header="领跌股">
                        <template #body="{ data }">
                            <span class="text-down">
                              {{ data.bottom_stock || '--' }}
                              <span class="text-xxs">({{ data.bottom_stock_pct?.toFixed(2) }}%)</span>
                            </span>
                        </template>
                    </Column>
                    <Column field="change_pct" header="涨跌幅" style="min-width: 200px;" sortable>
                        <template #body="{ data }">
                            <!-- ⚠️ ProgressBar200p 把 width 内联写死成 100px，而这一列实测有 ~237px，
                                 所以进度条只能占不到一半列宽、填充块又从中线往右伸一点点，
                                 看起来几乎不可见。这里用外层容器 + :deep 覆盖成撑满列宽，
                                 组件本身不动（其它页面还在用它的默认宽度）。 -->
                            <div class="pct-cell">
                                <ProgressBar200p
                                    :barHeight="20"
                                    :value="Number(data.change_pct ?? 0)"
                                    :times="10"
                                />
                            </div>
                        </template>
                    </Column>
                    <Column field="up_count" header="上涨/平盘/下跌" sortable>
                        <template #body="{ data }">
                            <span class="text-up">{{ data.up_count ?? 0 }}</span> /
                            <span class="text-flat">{{ data.flat_count ?? 0 }}</span> /
                            <span class="text-down">{{ data.down_count ?? 0 }}</span>
                        </template>
                    </Column>
                    <Column field="total_trade_amount" header="总成交额" sortable style="min-width: 100px">
                        <template #body="{ data }">
                            {{ data.total_trade_amount ? `${Number(data.total_trade_amount).toFixed(1)} 亿` : '--' }}
                        </template>
                    </Column>
                    <Column field="up_down_ratio" header="涨跌比" sortable style="min-width: 80px">
                        <template #body="{ data }">
                            <span :class="getPctColorClass((data.up_down_ratio ?? 1) - 1)">
                              {{ data.up_down_ratio?.toFixed(2) ?? '--' }}
                            </span>
                        </template>
                    </Column>
                    <template #empty>
                        <div class="empty-tip">暂无板块数据</div>
                    </template>
                </DataTable>
            </template>
        </Card>

    </div>
</template>

<style scoped lang="scss">

.dashboard-container {
    padding: 1.5rem;
    background: #f5f7fb;
    min-height: 100vh;
}

// 头部
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
    gap: 0.5rem;

    .title {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1e293b;
        margin: 0;
    }

    .header-right {
        display: flex;
        align-items: center;
        gap: 1rem;
    }

    .update-time {
        color: #64748b;
        font-size: 0.9rem;

        .tick-time {
            color: #94a3b8;
        }
    }

    // 自动刷新开关
    .auto-refresh {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        color: #475569;
        font-size: 0.9rem;
        cursor: pointer;
        user-select: none;
    }
}

// 指数卡片行
.indices-row {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 1.5rem;

    .index-card {
        flex: 1 1 calc(16.66% - 1rem);
        min-width: 160px;
        transition: all 0.2s ease;

        &:hover {
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }
    }
}

.card-content {
    display: flex;
    flex-direction: column;
    align-items: center;

    .index-name {
        font-size: 1rem;
        color: #475569;
        font-weight: 600;
        white-space: nowrap;
    }

    .index-code {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-top: 0.2rem;
    }

    .index-price {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0f172a;
        margin: 0.5rem 0;
        line-height: 1;
    }

    .index-change {
        display: flex;
        gap: 0.5rem;
        font-size: 0.95rem;

        .change-percent {
            color: inherit;
        }
    }
}

// 卡片标题行：标题 + 右侧切换控件
.card-title-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
}

// ========================
// 恐惧贪婪卡片
// ========================
.fear-greed-card {
    margin-bottom: 1.5rem;
    background: #fff;
}

.fear-greed-body {
    display: flex;
    gap: 1.5rem;
    align-items: stretch;

    .fg-current {
        flex: 0 0 300px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 0.5rem 0;

        .fg-value {
            font-size: 3rem;
            font-weight: 700;
            line-height: 1;
        }

        .fg-label {
            font-size: 1.1rem;
            font-weight: 600;
            margin-top: 0.4rem;
        }

        .fg-date {
            font-size: 0.8rem;
            color: #94a3b8;
            margin-top: 0.25rem;
        }

        .fg-scores {
            display: flex;
            flex-direction: column;
            gap: 0.45rem;
            margin-top: 1rem;
            width: 100%;

            .fg-score {
                display: flex;
                align-items: center;
                gap: 0.4rem;
                font-size: 0.9rem;
                color: #64748b;

                .score-name {
                    flex: 0 0 3.6rem;
                    white-space: nowrap;
                }

                // 迷你进度条：0~100 分项得分
                .score-track {
                    flex: 1;
                    height: 5px;
                    background: #eef1f6;
                    border-radius: 3px;
                    overflow: hidden;

                    .score-fill {
                        display: block;
                        height: 100%;
                        border-radius: 3px;
                        transition: width 0.3s ease;
                    }
                }

                .score-val {
                    flex: 0 0 3.2rem;
                    text-align: right;
                    font-weight: 600;
                    color: #0f172a;
                    font-variant-numeric: tabular-nums;
                }

                // 点位没有可归一化的量纲，不配进度条，占满右侧
                .score-val-wide {
                    flex: 1;
                }
            }
        }
    }

    .fg-chart-wrap {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;

        .fg-chart-title {
            font-size: 0.85rem;
            color: #94a3b8;
            margin-bottom: 0.3rem;
        }

        .fg-chart {
            flex: 1;
            min-height: 200px;
            width: 100%;
            transition: opacity 0.2s ease;

            // 项目未引入 element-plus，没有 v-loading 指令，用透明度表达加载态
            &.is-loading {
                opacity: 0.45;
            }
        }
    }
}

// ========================
// 板块表格
// ========================
.sector-table {
    td, th {
        padding: 0.4rem 0.5rem;
        font-size: 0.9rem;
    }

    // 让涨跌幅列的进度条撑满列宽（组件内联 width:100px 在这里太窄）
    .pct-cell {
        width: 100%;

        :deep(.progress-bar) {
            width: 100% !important;
        }
    }

    :deep(.p-datatable-header) {
        background: var(--header-bg);
        border-bottom: 1px solid var(--border-color);
        font-weight: 600;
    }

    :deep(.p-column-header) {
        text-align: left;
        padding: 10px 8px;
        background: var(--header-bg);
        font-weight: 600;
    }

    :deep(.p-datatable-tbody > tr > td) {
        padding: 10px 8px;
        border-bottom: 1px solid var(--border-color);
    }
}

// 颜色工具类（--color-up/down/flat 定义在 assets/layout/variables/_common.scss 的 :root）
.text-up {
    color: var(--color-up);
}

.text-down {
    color: var(--color-down);
}

.text-flat {
    color: var(--color-flat);
}

// 根字号 12px，text-xs 名义 9px —— 这里用 10.5px（sm 档）
.text-xxs {
    font-size: 0.875rem;
    opacity: 0.85;
}

.empty-tip {
    padding: 2rem 1rem;
    text-align: center;
    color: #94a3b8;
    font-size: 0.9rem;
}

@media (max-width: 1200px) {
    .fear-greed-body {
        flex-direction: column;

        .fg-current {
            flex: none;
        }

        .fg-chart {
            min-height: 180px;
        }
    }
}

@media (max-width: 768px) {
    .indices-row .index-card {
        flex: 1 1 calc(50% - 1rem);
    }
}

</style>
