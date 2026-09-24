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

// 恐惧贪婪可选的指数。
//
// ⚠️ 数据走上游 `/cn/market/fear_greed`（**直连不落库**，见 routes/market.py 的说明），
// 所以「下拉里有没有」完全取决于**上游覆盖范围**，而不是本地 stocks_fear_greed 表。
// 实测（2026-09-24，近一年回溯）：000001=263、000300=262、399006=265、000905=262、
// 000015=262、000688=268 条；000922 返 0 条。
// ⚠️ 红利用的是**上证红利 000015**，不是中证红利 000922 —— 后者本接口返 None（无数据）。
// 注意别被「本地能取到 000922 的行情」误导：那是 get_stock_history 走的路，
// 大盘页用的是 get_market_fear_greed，两条链路覆盖范围不同。
// ⚠️ ⚠️ 本路由 @cache(expire=3600)，**上游补齐数据后最多要 1 小时才可见**。
// 曾因此误判「科创50 只有 1 天数据」：实为上游刚接入时缓存住了那条响应，
// 稍后上游补齐历史、缓存到期后即为完整序列。排查此类问题请换 days 参数绕过缓存再测。
const FEAR_GREED_INDICES = [
    {label: '上证指数', value: '000001'},
    {label: '沪深300', value: '000300'},
    {label: '创业板指', value: '399006'},
    {label: '中证500', value: '000905'},
    {label: '上证红利', value: '000015'},
    {label: '科创50', value: '000688'}
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
    // ⚠️ 先清空再请求：否则切换指数期间旧指数的曲线会残留在图上，
    // 左栏（v-if 依赖 fearGreedLatest）也仍然显示上一个指数的读数 ——
    // 用户会以为「点了没反应」或「两个指数数据一样」。
    fear_greed_list.value = []
    try {
        const res = await axios.get('/api/v1/market/fear_greed', {
            params: {index_code: fear_greed_index.value, days: 365}
        })
        fear_greed_list.value = Array.isArray(res.data) ? res.data : []
    } catch (e) {
        // 上游不可用时保持空列表，界面落到「该指数暂无恐惧贪婪数据」而不是崩掉
        fear_greed_list.value = []
    } finally {
        fear_greed_loading.value = false
    }
    // 放在 finally 之后、且不 await：等这一拍渲染完（v-if 该真则真、该假则假），
    // 再决定是绘图还是清图 —— 容器是否存在的判断交给 ensureChart。
    renderFearGreedChart()
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
 *
 * ⚠️ 还有第二个坑（切换指数时必踩）：`v-if` 为 false 会把容器从文档里摘掉，
 * 但 `fgChart` 仍持有**已被移除的那个** DOM 引用。此后 `if (fgChart) return fgChart`
 * 会直接返回这个"孤儿实例"，`setOption` 画在脱离文档的 canvas 上 ——
 * 表现是**左栏数值正常、右边图表却空白**（坐标轴还在，因为那是新容器画的）。
 * 所以这里必须校验实例的宿主容器是否仍是当前的那个，不是就销毁重建。
 *
 * @see https://echarts.apache.org/zh/api.html#echarts.getInstanceByDom
 */
const ensureChart = () => {
    if (!fgChartRef.value) return null
    // 已有实例，但宿主容器已被 v-if 换掉（或已脱离文档）→ 必须先 dispose
    const host = fgChart && fgChart.getDom && fgChart.getDom()
    if (fgChart && host !== fgChartRef.value) {
        if (host && !document.contains(host)) {
            // 旧容器已不在文档中：dispose 它并重建
            fgChart.dispose()
            fgChart = null
        } else if (!host) {
            fgChart = null
        }
    }
    if (!fgChart) {
        // 容器宽高为 0 时 init 会得到一张尺寸为 0 的画布，echarts 会告警且画不出来
        const w = fgChartRef.value.clientWidth
        const h = fgChartRef.value.clientHeight
        if (!w || !h) return null
        fgChart = echarts.init(fgChartRef.value)
    }
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

const resizeCharts = () => {
    fgChart?.resize()
    gvChart?.resize()
}
// ========================
// 成长 vs 价值（比值走势）
// ========================
/**
 * 成长 vs 价值 = 创业板指(399006) ÷ 上证红利(000015)
 *
 * 比值**上行 = 成长跑赢价值**，下行 = 价值跑赢成长。比值本身没有绝对高低含义，
 * 所以后端返回的是「以区间首日归一为 1.0」的净值，同时给出两条成分腿的
 * 归一化净值 —— 只看比值看不到「是成长涨出来的还是红利跌出来的」，
 * 副轴叠两条线就能一眼分辨。
 *
 * ⚠️ 价值腿是上证红利、不是中证红利（上游对 000922 无 K 线），
 * 详见 service/growth_value_service.py 顶部说明。
 */
const GROWTH_VALUE_DAYS = 250   // ≈ 一年交易日

const growth_value = ref(null)
const growth_value_loading = ref(false)

const gvLatest = computed(() => growth_value.value?.points?.slice(-1)[0] || null)
const gvMeta = computed(() => growth_value.value?.meta || null)
const gvPeriods = computed(() => growth_value.value?.periods || [])

// 比值涨 → 成长占优（红）；跌 → 价值占优（绿）。与全站红涨绿跌一致。
const ratioColor = computed(() => {
    const v = gvLatest.value?.ratio
    if (v == null) return '#909399'
    if (v > 1) return 'var(--color-up)'
    if (v < 1) return 'var(--color-down)'
    return 'var(--color-flat)'
})

const gvChartRef = ref(null)
let gvChart = null

/**
 * 相对强度（归一化净值或比值）→ 迷你条宽度（%）。
 *
 * ⚠️ 不能用 `(值 - 1) * 100` 直接当宽度：成分腿一年期的偏离常见 10%~20%，
 * 看着还行；但**比值线**的偏离只有 1%~3%，直接当宽度就是不到 1px 的短线，
 * 等于没画。
 *
 * ⚠️ 也不能拿「每个数值各自归一」——那会让比值线和成分腿都占满条，三行一样长、
 * 完全看不出谁强。这里统一按「三者里最大偏离度」做相对归一：最大偏离的占满条，
 * 其余按比例缩短，相对强弱一眼可见。再用 12% 下限保证「有偏离就一定看得见」。
 * 宽度只表达相对强弱，精确数值由右侧文字给出。
 */
const gvBarWidth = (norm) => {
    if (norm == null) return 0
    const devs = [gvLatest.value?.ratio, gvLatest.value?.growth_norm, gvLatest.value?.value_norm]
        .filter((v) => v != null)
        .map((v) => Math.abs(Number(v) - 1))
    const maxDev = Math.max(...devs, 1e-9)
    return Math.max(12, Math.round((Math.abs(Number(norm) - 1) / maxDev) * 100))
}

// 成分腿的颜色：>1 表示该腿跑赢（红），<1 表示跑输（绿）
const gvLegColor = (norm) => {
    if (norm == null) return '#909399'
    if (norm > 1) return 'var(--color-up)'
    if (norm < 1) return 'var(--color-down)'
    return 'var(--color-flat)'
}

// 与恐惧贪婪图同样的坑：容器在 v-if 内，数据到位后 DOM 才存在，必须懒初始化
const ensureGvChart = () => {
    if (gvChart || !gvChartRef.value) return gvChart
    gvChart = echarts.init(gvChartRef.value)
    return gvChart
}

const fetchGrowthValue = async () => {
    growth_value_loading.value = true
    try {
        const res = await axios.get('/api/v1/market/growth_value', {
            params: {days: GROWTH_VALUE_DAYS}
        })
        growth_value.value = res.data || null
        renderGrowthValueChart()
    } catch (e) {
        growth_value.value = null
    } finally {
        growth_value_loading.value = false
    }
}

const renderGrowthValueChart = async () => {
    await nextTick()
    const chart = ensureGvChart()
    if (!chart) return

    const rows = growth_value.value?.points || []
    if (!rows.length) {
        chart.clear()
        return
    }
    const dates = rows.map((r) => r.trade_date)
    const ratio = rows.map((r) => r.ratio)
    const gNorm = rows.map((r) => r.growth_norm)
    const vNorm = rows.map((r) => r.value_norm)

    // 比值线的颜色跟随「相对起点」的方向：>1 成长占优，<1 价值占优
    const lastRatio = ratio[ratio.length - 1]
    const mainColor = lastRatio > 1 ? '#ef4444' : (lastRatio < 1 ? '#12783c' : '#909399')

    chart.setOption({
        // 右侧留白给副轴刻度
        grid: {left: 34, right: 42, top: 16, bottom: 22},
        tooltip: {
            trigger: 'axis',
            formatter: (params) => {
                const i = params[0].dataIndex
                const d = rows[i]
                return `${d.trade_date}<br/>`
                    + `比值: <b>${d.ratio.toFixed(4)}</b><br/>`
                    + `创业板指: ${d.growth_close}（${((d.growth_norm - 1) * 100).toFixed(2)}%）<br/>`
                    + `上证红利: ${d.value_close}（${((d.value_norm - 1) * 100).toFixed(2)}%）`
            }
        },
        xAxis: {
            type: 'category',
            data: dates,
            show: false
        },
        yAxis: [
            {
                // 左轴：比值（归一化后围绕 1.0 波动）。
                // ⚠️ 必须 `scale: true`（不强制含 0）—— 比值恒在 1.0 附近，
                // 从 0 起画会把整条曲线压成一条直线，涨跌完全看不出来。
                type: 'value',
                scale: true,
                splitNumber: 2,
                axisLabel: {fontSize: 9, color: '#94a3b8', formatter: (v) => v.toFixed(2)},
                splitLine: {lineStyle: {color: '#eef1f6'}}
            },
            {
                // 副轴：两条成分腿的归一化净值。
                // ⚠️ 这两条线的取值范围（0.9~1.5）比比值宽得多，若与左轴共用网格，
                // ECharts 会把两轴统一到并集范围 → 比值线被压扁、看不出形态。
                // 给副轴**显式**指定 min/max，把它和左轴彻底解耦（两条轴各自缩放）。
                type: 'value',
                min: (v) => Math.min(v.min, 1) - (Math.max(v.max, 1) - Math.min(v.min, 1)) * 0.1,
                max: (v) => Math.max(v.max, 1) + (Math.max(v.max, 1) - Math.min(v.min, 1)) * 0.1,
                splitNumber: 2,
                axisLabel: {fontSize: 9, color: '#cbd5e1', formatter: (v) => v.toFixed(2)},
                splitLine: {show: false}
            }
        ],
        series: [
            {
                name: '成长/价值',
                type: 'line',
                yAxisIndex: 0,
                data: ratio,
                smooth: true,
                showSymbol: false,
                lineStyle: {width: 1.5, color: mainColor},
                areaStyle: {
                    color: {
                        type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                        colorStops: [
                            {offset: 0, color: 'rgba(239,68,68,0.22)'},
                            {offset: 1, color: 'rgba(239,68,68,0.02)'}
                        ]
                    }
                },
                // 1.0 = 区间起点，比值在此之上为成长占优
                markLine: {
                    silent: true,
                    symbol: 'none',
                    label: {show: false},
                    lineStyle: {type: 'dashed', color: '#cbd5e1'},
                    data: [{yAxis: 1}]
                }
            },
            {
                name: '创业板指',
                type: 'line',
                yAxisIndex: 1,
                data: gNorm,
                smooth: true,
                showSymbol: false,
                lineStyle: {width: 1, color: '#ef4444', opacity: 0.45, type: 'dotted'}
            },
            {
                name: '上证红利',
                type: 'line',
                yAxisIndex: 1,
                data: vNorm,
                smooth: true,
                showSymbol: false,
                lineStyle: {width: 1, color: '#12783c', opacity: 0.45, type: 'dotted'}
            }
        ]
    })
}

// ========================
// 生命周期（F2：自动刷新）
// ========================
let tickTimer = null
let fgTimer = null
let gvTimer = null

const startTimers = () => {
    stopTimers()
    tickTimer = setInterval(fetchIndexTick, TICK_REFRESH_MS)
    fgTimer = setInterval(fetchFearGreed, FEAR_GREED_REFRESH_MS)
    gvTimer = setInterval(fetchGrowthValue, FEAR_GREED_REFRESH_MS)
}

const stopTimers = () => {
    if (tickTimer) clearInterval(tickTimer)
    if (fgTimer) clearInterval(fgTimer)
    if (gvTimer) clearInterval(gvTimer)
    tickTimer = null
    fgTimer = null
    gvTimer = null
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

    // 首屏并发拉取：四个接口互不依赖，串行等待会让首屏白屏时间翻倍。
    // 用 allSettled：任一接口挂掉不应该让另外三个也不显示。
    await Promise.allSettled([fetchIndexTick(), fetchSectors(), fetchFearGreed(), fetchGrowthValue()])
    startTimers()
})

onUnmounted(() => {
    stopTimers()
    window.removeEventListener('resize', resizeCharts)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    fgChart?.dispose()
    fgChart = null
    gvChart?.dispose()
    gvChart = null
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

        <!-- 成长 vs 价值（创业板指 ÷ 上证红利） -->
        <Card class="fear-greed-card growth-value-card">
            <template #title>
                <div class="card-title-row">
                    <span>成长 vs 价值（创业板指 ÷ 上证红利，起点归一）</span>
                    <span v-if="gvMeta" class="gv-window">
                        {{ gvMeta.start_date }} ~ {{ gvMeta.end_date }}（{{ gvMeta.trade_days }} 个交易日）
                    </span>
                </div>
            </template>
            <template #content>
                <div v-if="gvLatest" class="fear-greed-body">
                    <!-- 左：当前比值 + 区间涨跌幅 -->
                    <div class="fg-current">
                        <div class="fg-value" :style="{ color: ratioColor }">
                            {{ gvLatest.ratio.toFixed(4) }}
                        </div>
                        <div class="fg-label" :style="{ color: ratioColor }">
                            {{ gvLatest.ratio > 1 ? '成长占优' : (gvLatest.ratio < 1 ? '价值占优' : '风格均衡') }}
                        </div>
                        <div class="fg-date">{{ gvLatest.trade_date }}</div>

                        <div class="fg-scores">
                            <!-- 分量拆解：三条「相对强度」条，都按窗口首日归一化为 1.0，
                                 >1 红（跑赢）、<1 绿（跑输），与全站红涨绿跌一致。
                                 ⚠️ 条宽不能用 (norm-1) 直接当宽度：一年期成分腿的偏离多在
                                 10%~20%（ratio 只有 1%~3%），直接当百分比宽度会短到看不见。
                                 这里按「三条里最大偏离度」做相对归一，再留 12% 下限。 -->
                            <div class="fg-score">
                                <span class="score-name">成长/价值</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: gvBarWidth(gvLatest.ratio), background: ratioColor }"></span>
                                </span>
                                <span class="score-val" :style="{ color: ratioColor }">
                                    {{ gvLatest.ratio.toFixed(4) }}
                                </span>
                            </div>
                            <div class="fg-score">
                                <span class="score-name">创业板指</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: gvBarWidth(gvLatest.growth_norm), background: gvLegColor(gvLatest.growth_norm) }"></span>
                                </span>
                                <span class="score-val" :style="{ color: gvLegColor(gvLatest.growth_norm) }">
                                    {{ ((gvLatest.growth_norm - 1) * 100).toFixed(1) }}%
                                </span>
                            </div>
                            <div class="fg-score">
                                <span class="score-name">上证红利</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: gvBarWidth(gvLatest.value_norm), background: gvLegColor(gvLatest.value_norm) }"></span>
                                </span>
                                <span class="score-val" :style="{ color: gvLegColor(gvLatest.value_norm) }">
                                    {{ ((gvLatest.value_norm - 1) * 100).toFixed(1) }}%
                                </span>
                            </div>
                            <!-- 区间比值涨跌幅：>0 说明该窗口内成长跑赢价值 -->
                            <div v-for="p in gvPeriods" :key="p.days" class="fg-score">
                                <span class="score-name">近 {{ p.days }} 日</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: gvBarWidth(p.change_pct) + '%', background: p.change_pct >= 0 ? 'var(--color-up)' : 'var(--color-down)' }"></span>
                                </span>
                                <span class="score-val"
                                      :class="getPctColorClass(p.change_pct)">
                                    {{ p.change_pct == null ? '--' : (p.change_pct > 0 ? '+' : '') + p.change_pct.toFixed(1) + '%' }}
                                </span>
                            </div>
                        </div>
                    </div>
                    <!-- 右：近一年比值走势（副轴叠两条成分腿归一化净值） -->
                    <div class="fg-chart-wrap">
                        <div class="fg-chart-title">
                            近一年走势（比值上行 = 成长跑赢；点线为两条成分腿归一化涨幅）
                        </div>
                        <div ref="gvChartRef" class="fg-chart"
                             :class="{'is-loading': growth_value_loading}"></div>
                    </div>
                </div>
                <div v-else class="empty-tip">
                    {{ growth_value_loading ? '加载中…' : '暂无成长/价值比值数据' }}
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
// 成长 vs 价值（复用恐惧贪婪卡片的结构与样式）
// ========================
.growth-value-card {
    // 标题右侧的区间说明，弱化显示
    .gv-window {
        font-size: 0.8rem;
        color: #94a3b8;
        font-weight: 400;
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
