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
import {
    COLORS, LINE, FONT,
    axisLabel, splitLine, tooltipBase, lineSeriesStyle, markLevels, areaGradient,
} from '@/utils/echartsTheme'
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
// 板块轮动分析（读库：sector_daily_stats）
// ========================
/**
 * 与上面的「申万行业涨跌排行」是**两张独立卡片、两套独立控件**：
 * 上面那张是「最新一个交易日的截面排行」，这张是「时序上的轮动」。
 * 刻意不复用同一个 sector_type —— 用户常常想看一级的排行、同时看二级的轮动，
 * 共用一个 ref 会让切一个动两处，很难理解。
 *
 * ⚠️ 数据只能读本地库（上游 `/cn/market/sector_data/{sw}` 只返回最新一个交易日，
 * 没有历史接口）。库里能回溯多久取决于日更任务 `job_update_sector_daily`
 * （mon-fri 20:35）跑了多少天，所以**请求 20 天可能只返回 5 天** ——
 * 真实样本长度一律以 `meta.trade_days` 为准，不要拿 rot_days 当样本长度。
 */
const ROT_WINDOWS = [
    {label: '近 5 日', value: 5},
    {label: '近 10 日', value: 10},
    {label: '近 20 日', value: 20},
    {label: '近 60 日', value: 60}
]
// 热力图/象限图的行数上限直接由这个控件决定（库里的 31/131/150 个板块全画出来不可读）
const ROT_TOP_N = [
    {label: '最强 10', value: 10},
    {label: '最强 20', value: 20},
    {label: '最强 30', value: 30}
]
const ROT_REFRESH_MS = 30 * 60 * 1000   // 日更数据，半小时刷一次足够

const rotation = ref(null)
const rotation_loading = ref(false)
const rot_type = ref('sw1')
const rot_days = ref(20)
const rot_top_n = ref(20)

const rotSectors = computed(() => rotation.value?.series || [])
const rotDates = computed(() => rotation.value?.dates || [])
const rotMeta = computed(() => rotation.value?.meta || null)

/**
 * 图表用的行（明细表用的是**全量** rotSectors）。
 *
 * 两层裁剪：
 *  1. 只取完整样本 —— `is_partial` 的板块没覆盖窗口内全部交易日，它的"区间累计"
 *     其实是单日涨幅（sw3 实测有 12 个板块只有 1 天），画进象限图会被误读成极端强势；
 *  2. 再截到「最强 N」—— 170 行热力图完全不可读。
 * 后端有意不做这个裁剪（明细表要全量），所以裁剪放在这里。
 */
const rotChartRows = computed(() =>
    rotSectors.value.filter((s) => !s.is_partial).slice(0, rot_top_n.value)
)

const rotMetaText = computed(() => {
    const m = rotMeta.value
    if (!m || !m.trade_days) return ''
    // 请求窗口 > 实际样本时要说清楚，否则用户会以为「近 20 日」真的看了 20 天
    const sample = m.requested_days > m.trade_days
        ? `实际样本 ${m.trade_days}/${m.requested_days} 个交易日（库里只有这些）`
        : `${m.trade_days} 个交易日`
    return `${m.start_date} ~ ${m.end_date}　${sample}　`
        + `完整样本板块 ${m.complete_count} / 全部 ${m.sector_count} 个`
})

/**
 * 排名的分母：**最新交易日的实际参与板块数**，不是 `meta.sector_count`（窗口并集）。
 * sw3 每天上游只给 150 行而并集有 170 个，用并集当分母会把"第 3/150"显示成"第 3/170"。
 */
const rotRankBase = computed(() => {
    const daily = rotation.value?.daily || []
    return daily.length ? (daily[daily.length - 1].sector_count || rotMeta.value?.sector_count) : null
})

const fetchRotation = async () => {
    rotation_loading.value = true
    try {
        const res = await axios.get('/api/v1/market/sector_rotation', {
            params: {sector_type: rot_type.value, days: rot_days.value}
        })
        rotation.value = res.data || null
    } catch (e) {
        // 接口挂了保持空态，不要留着上一个级别的图（会让人以为切了级别没反应）
        rotation.value = null
    } finally {
        rotation_loading.value = false
    }
    renderRotationCharts()
}

// 级别/窗口变了要重新取数；"最强 N"只影响两张图画几行（后端返回的是完整榜单），
// 所以只重画、不重新请求 —— 切 N 不该打一次接口。
watch([rot_type, rot_days], fetchRotation)
watch(rot_top_n, () => renderRotationCharts())

const signedPct = (v, digits = 2) => (v == null ? '--' : `${v > 0 ? '+' : ''}${Number(v).toFixed(digits)}%`)

/**
 * 懒初始化 ECharts 实例（本页三张图共用）。
 *
 * ⚠️ 两个必须处理的坑，都在本页踩过：
 *  1. 图表容器在 `v-if` 内部时，首屏数据没到 → 容器不在 DOM → ref 是 null，
 *     `echarts.init(null)` 会抛 `Cannot read properties of null (reading 'getAttribute')`，
 *     且异常发生在渲染阶段，会把整个组件挂载链打断 —— 表现是**全页数据都不渲染**，
 *     但接口一个都没发出去（极易误判成后端问题）。
 *  2. `v-if` 为 false 会把容器从文档里摘掉，但实例仍持有**已被移除的** DOM 引用，
 *     之后复用这个"孤儿实例"调 setOption，图会画在脱离文档的 canvas 上 ——
 *     表现是**左侧数值正常、右边图表空白**。
 * 所以这里既校验 null，也校验宿主容器是否还是同一个。
 */
const lazyInitChart = (el, existing) => {
    if (!el) return null
    const host = existing?.getDom?.()
    if (existing && host !== el) {
        existing.dispose()
        existing = null
    }
    if (existing) return existing
    // 容器宽高为 0 时 init 会得到 0×0 的画布，echarts 会告警且画不出来
    if (!el.clientWidth || !el.clientHeight) return null
    return echarts.init(el)
}

// ── 热力图 ──
// 涨跌幅 → 红涨绿跌的分歧色带。上下限对称（min=-maxAbs, max=+maxAbs），
// 这样 0 一定落在色带正中间（近白），不会因为数据整体偏红/偏绿而误导。
const HEAT_COLORS = ['#12783c', '#6fbf8f', '#eef2f6', '#e88989', '#c0392b']

const rotHeatRef = ref(null)
let rotHeatChart = null

// 最近的"窄容器降级"状态（只有它变了才需要重画，纯尺寸变化 resize 就够）
let rotNarrowState = null
// 全页图表共用一个 ResizeObserver 实例（见 observeCharts）
let chartResizeObserver = null

const heatColorFor = (row) => {
    // 气泡/格子里的数字要能看清：深色底用白字，浅色底用深字。
    // 阈值取色带的一半，超过就认为是"饱和色"。
    return Math.abs(row) > 0.55 ? '#ffffff' : '#1f2937'
}

const renderRotationHeat = async (maxAbs, rows) => {
    await nextTick()
    rotHeatChart = lazyInitChart(rotHeatRef.value, rotHeatChart)
    const chart = rotHeatChart
    if (!chart) return
    if (!rows.length || !rotDates.value.length) {
        chart.clear()
        return
    }
    const dates = rotDates.value
    const width = rotHeatRef.value.clientWidth
    // 极窄容器（<320px）降级：板块名占的左侧留白会吃掉大半宽度，格子只剩十几个像素，
    // 格内数字会和轴标签叠在一起糊成一团。此时退化成"纯色块矩阵"——颜色形态照样能看出
    // 轮动，具体数值交给下方的明细表与 tooltip。
    const narrow = width < 320
    rotNarrowState = narrow
    // 数据项：{value:[dateIdx, rowIdx, pct], label:{color}} —— 逐格设置字色
    const data = []
    rows.forEach((s, y) => {
        s.values.forEach((v, x) => {
            if (v == null) return
            data.push({value: [x, y, v], label: {color: heatColorFor(v / maxAbs)}})
        })
    })

    chart.setOption({
        // ⚠️ bottom 要同时容纳 x 轴日期与底部色带：留 34px 时日期和 visualMap 会重叠
        // （实测色带正好压在中间那条日期上）。64px = 日期 ~14px + 色带 ~14px + 间距。
        grid: {left: narrow ? 50 : 76, right: 12, top: 8, bottom: 64},
        tooltip: tooltipBase({
            formatter: (p) => {
                const [x, y] = p.data.value
                const s = rows[y]
                const rank = s.ranks?.[x]
                const share = s.amount_share_series?.[x]
                // 分母用**当天**实际参与排名的板块数（窗口并集会把 sw3 的分母放大）
                const total = rotation.value?.daily?.[x]?.sector_count
                return `<b>${s.sector_name}</b> · ${dates[x]}<br/>`
                    + `涨跌幅 <b>${signedPct(s.values[x])}</b>`
                    + (rank && total ? `（当日第 ${rank}/${total}）` : '') + '<br/>'
                    + `上涨 ${s.up_count ?? '--'} / 下跌 ${s.down_count ?? '--'} 家<br/>`
                    + (share != null ? `成交额占比 ${share}%<br/>` : '')
                    + (s.top_stock ? `领涨 ${s.top_stock} ${signedPct(s.top_stock_pct)}` : '')
            }
        }),
        xAxis: {
            type: 'category',
            data: dates,
            splitArea: {show: false},
            axisLabel: axisLabel({formatter: (v) => String(v).slice(5)}),
            axisTick: {show: false},
            axisLine: {lineStyle: {color: COLORS.axisLine}}
        },
        yAxis: {
            type: 'category',
            // inverse：区间最强的排最上面（数组已按累计涨幅降序）
            inverse: true,
            data: rows.map((s) => s.sector_name),
            axisLabel: narrow
                ? axisLabel({fontSize: FONT.label, color: COLORS.text, margin: 4,
                             width: 44, overflow: 'truncate'})
                : axisLabel({fontSize: FONT.label, color: COLORS.text, margin: 6}),
            axisTick: {show: false},
            axisLine: {show: false}
        },
        visualMap: {
            type: 'continuous',
            min: -maxAbs,
            max: maxAbs,
            calculable: false,
            orient: 'horizontal',
            left: 'center',
            bottom: 4,
            itemWidth: 12,
            itemHeight: 150,
            text: [`+${maxAbs}%`, `-${maxAbs}%`],
            textStyle: {fontSize: FONT.axis, color: COLORS.axisLabel},
            inRange: {color: HEAT_COLORS}
        },
        series: [{
            type: 'heatmap',
            data,
            // 格子里的数字是这张图的主要信息（否则只能靠 hover），
            // 但格子太扁（行数很多）或太窄（窄屏）时叠字反而糊，两种情况都关掉
            label: {show: !narrow && rows.length <= 24,
                    fontSize: FONT.axis,
                    formatter: (p) => p.data.value[2].toFixed(1)},
            itemStyle: {borderColor: '#fff', borderWidth: 1},
            emphasis: {itemStyle: {shadowBlur: 6, shadowColor: 'rgba(15,23,42,0.25)'}}
        }]
    })
}

// ── 强弱象限散点 ──
// x = 最新一个交易日涨跌幅（当日动量），y = 窗口累计涨幅（区间动量）。
// 四象限解读：右上「强势延续」/ 右下「超跌反弹」/ 左上「高位回落」/ 左下「持续走弱」。
const QUADRANTS = [
    {name: '强势延续', color: '#dc2626', test: (x, y) => x >= 0 && y >= 0},
    {name: '超跌反弹', color: '#f97316', test: (x, y) => x >= 0 && y < 0},
    {name: '高位回落', color: '#3b82f6', test: (x, y) => x < 0 && y >= 0},
    {name: '持续走弱', color: '#16a34a', test: (x, y) => x < 0 && y < 0}
]

// 标签层（独立 scatter series）的锚点常量：
//   气泡符号尺寸 / 文字与符号的水平间距 —— 'right' 标签自带 SYM/2 + DIST 的固定偏移，
//   所以锚点要反向减回去，文字左边缘才能精确落在算好的位置。
const QUAD_SYM = 4
const QUAD_DIST = 2
const QUAD_RIGHT_OFF = QUAD_SYM / 2 + QUAD_DIST
const QUAD_GAP = 5                                  // 标签边缘离气泡的水平间距

// 只给「最有信息量」的点打名字：区间两端各 5 个 + 成交额占比前 3 ——
// 全部打名字会糊成一片（20 个点大多挤在 0 附近）。
// 极窄容器里连这几个名字也放不下（点本身就挤），一律不打，交给 tooltip。
const quadNamedSet = (pts) => new Set(rotNarrowState ? [] : [
    ...pts.slice(0, 5).map((s) => s.sector_name),
    ...pts.slice(-5).map((s) => s.sector_name),
    ...[...pts].sort((a, b) => (b.amount_share_latest ?? 0) - (a.amount_share_latest ?? 0))
        .slice(0, 3).map((s) => s.sector_name)
])

// 象限图标签的像素级避让，返回 [[xData, yData, 0, name]]。
// 为什么不用 ECharts 内置的 labelLayout：
//   · hideOverlap = true   → 标签重叠时**直接隐藏**（实测 11 个该打标签的板块只剩 9 个，
//     用户报的"有些文字不显示"就是它）；
//   · moveOverlap = 'shiftY' → 在 scatter 上几乎不动，只错开几像素。
// ⚠️ 坐标一律问 chart 要（convertToPixel/convertFromPixel），**不许按 grid 配置自己推算**：
//    `grid.left: 40` 只是"下限"——轴名/刻度文字过宽时 ECharts 会把绘图区往里推，
//    实测 left:40 时真实绘图区左边界是 53（刻度变成 "-1000" 时到 68，去掉轴名才回到 40）。
//    按 grid.left 算会让标签整体偏移，靠左边界的那条（"纺织服饰"）锚点落到 53 之外，
//    被 series 的 clip 整个裁掉 —— 看着就是"这条标签没画"。
const layoutQuadLabels = (chart, pts, named) => {
    const gridComp = chart.getModel().getComponent('grid')
    const cs = gridComp && gridComp.coordinateSystem
    if (!cs) return []
    const rect = cs.getRect()
    const right = rect.x + rect.width
    const bottom = rect.y + rect.height
    const toPx = (v) => chart.convertToPixel({xAxisIndex: 0}, v)
    const toPy = (v) => chart.convertToPixel({yAxisIndex: 0}, v)
    const LH = FONT.label + 8                           // 标签行距（留足呼吸位，否则两行字挨着像叠字）
    const labelW = (n) => n.length * FONT.label + 2     // 中文按 1 字宽 ≈ 字号估
    const radiusOf = (s) => (5 + Math.min(20, Math.sqrt(s.amount_share_latest ?? 0) * 4.2)) / 2
    const midPx = rect.x + rect.width / 2

    // 气泡包围盒：标签不能压在气泡上（否则字糊在色块上读不出来）
    const bubbleBoxes = pts.map((s) => {
        const cx = toPx(s.latest_pct)
        const cy = toPy(s.cum_pct)
        const r = radiusOf(s)
        return {x0: cx - r, x1: cx + r, top: cy - r, bottom: cy + r}
    })

    const anchors = []
    const placed = []
    const rows = []
    pts.filter((s) => named.has(s.sector_name))
        .sort((a, b) => toPy(a.cum_pct) - toPy(b.cum_pct))
        .forEach((s) => {
            const cx = toPx(s.latest_pct)
            const cy = toPy(s.cum_pct)
            const r = radiusOf(s)
            const w = labelW(s.sector_name)
            // 两个候选边：靠左的点默认挂右边、靠右的挂左边（都往图中间靠，避免撞出画布）；
            // 再夹回绘图区内 —— 越界的标签会被 series 的 clip 吃掉
            const cand = (toRight) => {
                const raw = toRight ? cx + r + QUAD_GAP : cx - r - QUAD_GAP - w
                const left = Math.max(rect.x, Math.min(raw, right - w))
                return {toRight, left, x0: left, x1: left + w}
            }
            const pref = cand(cx <= midPx)
            const alt = cand(cx > midPx)
            // 从气泡中线的位置出发，朝 dir（+1 下 / -1 上）推进，只跟**真正相交**的
            // 障碍（已放置标签、气泡）消解；不相交就不动，否则会被远处同列的障碍一路顶跑。
            const push = (c, dir) => {
                let t = cy - LH / 2
                for (let g = 0; g < 50; g++) {
                    let next = t
                    const eat = (b) => {
                        if (c.x1 <= b.x0 || c.x0 >= b.x1) return
                        if (t >= b.bottom || t + LH <= b.top) return
                        next = dir > 0 ? Math.max(next, b.bottom) : Math.min(next, b.top - LH)
                    }
                    placed.forEach(eat)
                    // 气泡两侧各让 2px，免得文字贴在色块边上
                    bubbleBoxes.forEach((q) => eat({x0: q.x0, x1: q.x1, top: q.top - 2, bottom: q.bottom + 2}))
                    if (Math.abs(next - t) < 0.01) break
                    t = next
                }
                return {top: t, off: Math.abs(t + LH / 2 - cy)}
            }
            // 左右两边 × 上下两个方向共四种排法，取**离气泡最近**的那种
            // （只往下推过的话，'食品饮料' 会被顶到气泡下方 46px，跟气泡失去对应关系）；
            // 位移相同则优先首选边、再优先向下（向下更符合阅读顺序）。
            const best = (c) => {
                const down = push(c, 1)
                const up = push(c, -1)
                return up.off < down.off ? {c, top: up.top, off: up.off}
                    : {c, top: down.top, off: down.off}
            }
            const a = best(pref)
            const b = best(alt)
            // 换边要有明显收益（6px 死区），否则标签会在两条边之间无谓跳动
            const chosen = b.off + 6 < a.off ? b : a
            const top = Math.max(rect.y, Math.min(chosen.top, bottom - LH))
            placed.push({x0: chosen.c.x0, x1: chosen.c.x1, top, bottom: top + LH})
            rows.push({left: chosen.c.left, top, name: s.sector_name})
        })
    // 整体越过绘图区下沿 → 统一上抬（保持相对间距）
    const spill = rows.length
        ? Math.max(0, Math.max(...rows.map((t) => t.top + LH)) - bottom) : 0
    rows.forEach((t) => {
        const anchorPy = t.top - spill + LH / 2            // 期望的标签垂直居中线
        const anchorPx = t.left - QUAD_RIGHT_OFF           // 补偿 'right' 的固定偏移
        anchors.push([
            chart.convertFromPixel({xAxisIndex: 0}, anchorPx),
            chart.convertFromPixel({yAxisIndex: 0}, anchorPy),
            0, t.name
        ])
    })
    return anchors
}

const rotQuadRef = ref(null)
let rotQuadChart = null

const renderRotationQuad = async (rows) => {
    await nextTick()
    rotQuadChart = lazyInitChart(rotQuadRef.value, rotQuadChart)
    const chart = rotQuadChart
    if (!chart) return
    // rows 已经是"完整样本 + 最强 N"（见 rotChartRows），这里再兜一层空值保护
    const pts = rows.filter((s) => s.latest_pct != null && s.cum_pct != null)
    if (!pts.length) {
        chart.clear()
        return
    }

    const xs = pts.map((s) => s.latest_pct)
    const ys = pts.map((s) => s.cum_pct)
    // 显式给坐标轴范围，markArea 的象限底纹才能精确落在 0 轴上
    const xPad = Math.max(0.3, (Math.max(...xs) - Math.min(...xs)) * 0.18)
    const yPad = Math.max(0.5, (Math.max(...ys) - Math.min(...ys)) * 0.18)
    const xMin = Math.min(...xs, 0) - xPad
    const xMax = Math.max(...xs, 0) + xPad
    const yMin = Math.min(...ys, 0) - yPad
    const yMax = Math.max(...ys, 0) + yPad

    const named = quadNamedSet(pts)

    // 标签层：只画文字，位置由 layoutQuadLabels 算好。
    // ⚠️ 必须留一个 symbol：symbol:'none' 或 symbolSize:0 会让 ECharts 把整个元素跳过，
    //    label 一起没；所以留 4px 的符号、填成透明色（看不见但仍参与布局）。
    //    position 只能用 'right' 这类合法值 —— 'inside'/'center' 对 scatter 不渲染。
    // ⚠️ data 第 3 维必须是**数值**（这里用 0）：放字符串会让该点解析失败、整点被丢弃。
    const labelSeries = (data) => ({
        type: 'scatter',
        name: '__labels',
        silent: true,
        z: 10,
        clip: false,
        symbolSize: QUAD_SYM,
        itemStyle: {color: 'transparent'},
        data,
        tooltip: {show: false},
        label: {
            show: true,
            position: 'right',
            distance: QUAD_DIST,
            fontSize: FONT.label,
            color: COLORS.text,
            formatter: (p) => p.data[3]
        }
    })

    const bubbleSeries = {
        type: 'scatter',
        // [当日涨跌, 区间累计, 占比, 原始对象]
        data: pts.map((s) => [s.latest_pct, s.cum_pct, s.amount_share_latest ?? 0, s]),
        // 气泡大小 = 成交额占比（用 sqrt 压缩，否则电子 25% 会把别的点压成米粒）
        symbolSize: (d) => 5 + Math.min(20, Math.sqrt(d[2] ?? 0) * 4.2),
        itemStyle: {
            opacity: 0.85,
            borderColor: '#fff',
            borderWidth: 1,
            color: (p) => {
                const [x, y] = p.data
                return (QUADRANTS.find((q) => q.test(x, y)) || QUADRANTS[3]).color
            }
        },
        // 气泡本身不带标签 —— 文字全部由独立标签 series 画（见 layoutQuadLabels）
        label: {show: false},
        // 四象限底纹 + 名称
        markArea: {
            silent: true,
            itemStyle: {opacity: 0.05},
            label: {fontSize: FONT.label, color: COLORS.axisLabel, position: 'insideTopLeft', distance: 8},
            data: [
                [{name: '高位回落', xAxis: xMin, yAxis: 0, itemStyle: {color: '#3b82f6'}}, {xAxis: 0, yAxis: yMax}],
                [{name: '强势延续', xAxis: 0, yAxis: 0, itemStyle: {color: '#dc2626'}}, {xAxis: xMax, yAxis: yMax}],
                [{name: '持续走弱', xAxis: xMin, yAxis: yMin, itemStyle: {color: '#16a34a'}}, {xAxis: 0, yAxis: 0}],
                [{name: '超跌反弹', xAxis: 0, yAxis: yMin, itemStyle: {color: '#f97316'}}, {xAxis: xMax, yAxis: 0}]
            ]
        },
        markLine: markLevels([0], {color: COLORS.guideStrong})
    }

    const frameOpt = {
        grid: {left: 40, right: 24, top: 14, bottom: 34},
        tooltip: tooltipBase({
            formatter: (p) => {
                const s = p.data[3]
                return `<b>${s.sector_name}</b><br/>`
                    + `最新一日 ${signedPct(s.latest_pct)}（第 ${s.latest_rank}/${rotRankBase.value ?? '--'}）<br/>`
                    + `区间累计 ${signedPct(s.cum_pct)}（日均 ${signedPct(s.avg_pct)}）<br/>`
                    + `跑赢中位 ${s.beat_days}/${s.trade_days} 日`
                    + (s.streak ? `，当前连续 ${s.streak} 日` : '') + '<br/>'
                    + `成交额占比 ${s.amount_share_latest ?? '--'}%`
            }
        }),
        xAxis: {
            type: 'value', min: xMin, max: xMax,
            name: '最新一日', nameLocation: 'middle', nameGap: 22,
            nameTextStyle: {fontSize: FONT.axis, color: COLORS.axisLabel},
            axisLabel: axisLabel({formatter: (v) => v.toFixed(1)}),
            splitLine: splitLine(),
            axisLine: {show: false}
        },
        yAxis: {
            type: 'value', min: yMin, max: yMax,
            name: '区间累计', nameLocation: 'middle', nameGap: 30,
            nameTextStyle: {fontSize: FONT.axis, color: COLORS.axisLabel},
            axisLabel: axisLabel({formatter: (v) => v.toFixed(1)}),
            splitLine: splitLine(),
            axisLine: {show: false}
        },
    }

    // ① 先只落「气泡 + 坐标轴」：让 ECharts 按自己的规则把真实绘图区几何定下来
    chart.setOption({...frameOpt, series: [bubbleSeries, labelSeries([])]})
    // ② 再按真实几何排标签（grid.left ≠ 绘图区左边界，见 layoutQuadLabels 注释）
    chart.setOption({series: [bubbleSeries, labelSeries(layoutQuadLabels(chart, pts, named))]})
}

const renderRotationCharts = async () => {
    // 两张图都只用 rotChartRows（完整样本 + 最强 N），明细表才用全量
    const rows = rotChartRows.value
    if (!rows.length) {
        rotHeatChart?.clear()
        rotQuadChart?.clear()
        return
    }
    // 容器在 `v-if="rotMeta.trade_days"` 里 —— 第一次拿到数据时 DOM 还不存在，
    // 必须等这一拍渲染完再 observe/init（fetchRotation 里不 await，允许悬挂）
    await nextTick()
    observeCharts()
    // 色带上限取所有格子里绝对值最大者（保底 1%，避免全都在 0 附近时颜色被放大成极端）
    const maxAbs = Math.max(1, Math.ceil(Math.max(...rows.flatMap((s) => s.values.filter((v) => v != null).map(Math.abs))) * 10) / 10)
    renderRotationHeat(maxAbs, rows)
    renderRotationQuad(rows)
}

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
    observeCharts()
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
        tooltip: tooltipBase({
            formatter: (params) => {
                const p = params[0]
                const d = rows[p.dataIndex]
                return `${d.trade_date}<br/>综合: <b>${d.fear_greed}</b>（${fearGreedLabel(d.fear_greed)}）`
                    + `<br/>波动分: ${d.vol_score ?? '--'}<br/>动量分: ${d.mom_score ?? '--'}`
            }
        }),
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
            axisLabel: axisLabel(),
            splitLine: splitLine()
        },
        series: [{
            type: 'line',
            data: rows.map((r) => r.fear_greed),
            smooth: true,
            showSymbol: false,
            ...lineSeriesStyle({color: '#ef4444', shadow: false}),
            areaStyle: {
                color: areaGradient('#ef4444', 0.28, 0.02)
            },
            // 50 为多空分界参考线
            markLine: markLevels([50, 25, 75], {color: COLORS.guideStrong})
        }]
    })
}

/**
 * 全页图表的尺寸跟随：**只用 ResizeObserver，不用 `window.resize`**。
 *
 * ⚠️ 踩过的坑（1420→430→1440 走一遍必现）：
 *  `window.resize` 回调**早于最终布局生效**。本页两侧都有会改变内容宽度的东西
 *  （≤1200px 的媒体查询把两列栅格改一列、窄屏时侧栏让位），resize 那一刻量到的
 *  还是过渡中的宽度 —— 实测切回 1440 后容器已经是 840px，ECharts 内部却写死了
 *  1044px。更糟的是 ECharts 的根 div 是**带显式 px 宽度**的普通块元素，
 *  而 `.fg-chart` 的 `overflow-x` 默认 `visible` → 多出的 200px 直接漏到盒外，
 *  把 `documentElement.scrollWidth` 撑到 1581，页面凭空多出一条横向滚动条。
 *  ResizeObserver 在元素尺寸真正变化后回调，量到的才是最终宽度；
 *  再配 CSS 的 `overflow-x: clip`（见样式里 .fg-chart / .rot-chart）兜底，
 *  就算哪次量歪了也只是裁掉，不会污染页面级滚动。
 *
 * 轮动图另有一条：容器窄到 <320px 时格内数字要关掉、轴留白要收窄，
 * 这类配置**只能靠重画生效**（纯 resize 只改画布尺寸），所以降级状态翻转时
 * 走 renderRotationCharts 重画。
 */
const observeCharts = () => {
    if (typeof ResizeObserver === 'undefined') return
    if (!chartResizeObserver) {
        chartResizeObserver = new ResizeObserver(() => {
            const charts = [fgChart, gvChart, rotHeatChart, rotQuadChart]
            if (!charts.some(Boolean)) return
            const narrow = (rotHeatRef.value?.clientWidth ?? 0) < 320
            if (rotHeatChart && narrow !== rotNarrowState) {
                renderRotationCharts()
                return
            }
            charts.forEach((c) => c?.resize())
        })
    }
    // 四个容器都在 v-if 里，早期调用时 ref 还是 null → **每次都尝试 observe**
    // （重复 observe 同一元素是幂等的；只 observe 一次会永久漏掉后来出现的容器）
    ;[fgChartRef, gvChartRef, rotHeatRef, rotQuadRef].forEach((r) => {
        if (r.value) chartResizeObserver.observe(r.value)
    })
}

const disconnectCharts = () => {
    chartResizeObserver?.disconnect()
    chartResizeObserver = null
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
    observeCharts()
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
        tooltip: tooltipBase({
            formatter: (params) => {
                const i = params[0].dataIndex
                const d = rows[i]
                return `${d.trade_date}<br/>`
                    + `比值: <b>${d.ratio.toFixed(4)}</b><br/>`
                    + `创业板指: ${d.growth_close}（${((d.growth_norm - 1) * 100).toFixed(2)}%）<br/>`
                    + `上证红利: ${d.value_close}（${((d.value_norm - 1) * 100).toFixed(2)}%）`
            }
        }),
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
                axisLabel: axisLabel({formatter: (v) => v.toFixed(2)}),
                splitLine: splitLine()
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
                axisLabel: axisLabel({color: COLORS.axisLabelThin, formatter: (v) => v.toFixed(2)}),
                splitLine: splitLine({show: false})
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
                ...lineSeriesStyle({color: mainColor, shadow: false}),
                areaStyle: {
                    color: areaGradient(mainColor, 0.22, 0.02)
                },
                // 1.0 = 区间起点，比值在此之上为成长占优
                markLine: markLevels([1], {color: COLORS.guideStrong})
            },
            {
                name: '创业板指',
                type: 'line',
                yAxisIndex: 1,
                data: gNorm,
                smooth: true,
                showSymbol: false,
                ...lineSeriesStyle({color: '#ef4444', width: LINE.secondary, type: 'dotted', opacity: 0.45, shadow: false})
            },
            {
                name: '上证红利',
                type: 'line',
                yAxisIndex: 1,
                data: vNorm,
                smooth: true,
                showSymbol: false,
                ...lineSeriesStyle({color: '#12783c', width: LINE.secondary, type: 'dotted', opacity: 0.45, shadow: false})
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
let rotTimer = null

const startTimers = () => {
    stopTimers()
    tickTimer = setInterval(fetchIndexTick, TICK_REFRESH_MS)
    fgTimer = setInterval(fetchFearGreed, FEAR_GREED_REFRESH_MS)
    gvTimer = setInterval(fetchGrowthValue, FEAR_GREED_REFRESH_MS)
    // 板块轮动是日更数据（job_update_sector_daily mon-fri 20:35），涨了也不会盘中变化
    rotTimer = setInterval(fetchRotation, ROT_REFRESH_MS)
}

const stopTimers = () => {
    if (tickTimer) clearInterval(tickTimer)
    if (fgTimer) clearInterval(fgTimer)
    if (gvTimer) clearInterval(gvTimer)
    if (rotTimer) clearInterval(rotTimer)
    tickTimer = null
    fgTimer = null
    gvTimer = null
    rotTimer = null
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
    // 图表尺寸跟随也不挂 window.resize —— 改用 observeCharts 的 ResizeObserver，原因见其注释。
    document.addEventListener('visibilitychange', onVisibilityChange)

    // 首屏并发拉取：五个接口互不依赖，串行等待会让首屏白屏时间翻倍。
    // 用 allSettled：任一接口挂掉不应该让另外几个也不显示。
    await Promise.allSettled([
        fetchIndexTick(), fetchSectors(), fetchFearGreed(), fetchGrowthValue(), fetchRotation()
    ])
    startTimers()
})

onUnmounted(() => {
    stopTimers()
    document.removeEventListener('visibilitychange', onVisibilityChange)
    disconnectCharts()
    fgChart?.dispose()
    fgChart = null
    gvChart?.dispose()
    gvChart = null
    rotHeatChart?.dispose()
    rotHeatChart = null
    rotQuadChart?.dispose()
    rotQuadChart = null
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

        <!-- 板块轮动分析（读库 sector_daily_stats，样本长度见 meta.trade_days） -->
        <Card class="chart-card rotation-card mt-5">
            <template #title>
                <div class="card-title-row">
                    <span>板块轮动分析</span>
                    <div class="rot-controls">
                        <SelectButton
                            v-model="rot_type"
                            :options="SECTOR_TYPES"
                            optionLabel="label"
                            optionValue="value"
                            :allowEmpty="false"
                            size="small"
                        />
                        <SelectButton
                            v-model="rot_days"
                            :options="ROT_WINDOWS"
                            optionLabel="label"
                            optionValue="value"
                            :allowEmpty="false"
                            size="small"
                        />
                        <SelectButton
                            v-model="rot_top_n"
                            :options="ROT_TOP_N"
                            optionLabel="label"
                            optionValue="value"
                            :allowEmpty="false"
                            size="small"
                        />
                    </div>
                </div>
            </template>
            <template #content>
                <div v-if="rotMeta && rotMeta.trade_days" class="rot-body" :class="{'is-loading': rotation_loading}">
                    <!-- 样本口径：请求 20 天只有 5 天时必须说清楚，否则会被当成"近 20 日" -->
                    <div class="rot-meta">
                        <span class="rot-meta-text">{{ rotMetaText }}</span>
                        <span v-if="rotMeta.sample_hint" class="rot-hint">{{ rotMeta.sample_hint }}</span>
                        <span v-if="rotMeta.partial_hint" class="rot-hint">{{ rotMeta.partial_hint }}</span>
                    </div>

                    <!-- 每日市场宽度（板块层面） -->
                    <div class="rot-section-title">
                        每日市场宽度（板块层面，涨跌板块家数 / 中位涨跌幅 / 分化度）
                    </div>
                    <div class="rot-days">
                        <div v-for="d in rotation.daily" :key="d.trade_date" class="rot-day">
                            <div class="rd-date">
                                {{ d.trade_date.slice(5) }}
                                <span class="rd-amt">{{ (Number(d.amount_total) / 10000).toFixed(2) }} 万亿</span>
                            </div>
                            <div class="rd-mid">
                                中位 <b :class="getPctColorClass(d.median_pct)">{{ signedPct(d.median_pct) }}</b>
                                <span class="rd-disp">分化 {{ Number(d.dispersion ?? 0).toFixed(2) }}</span>
                            </div>
                            <div class="rd-breadth">
                                <span class="text-up">{{ d.up_sector_count }}</span> 涨 /
                                <span class="text-down">{{ d.down_sector_count }}</span> 跌
                                <span class="rd-ratio">涨跌家数比 {{ Number(d.adv_ratio ?? 0).toFixed(2) }}</span>
                            </div>
                            <div class="rd-leader">
                                最强 <span class="rd-name">{{ d.strongest?.sector_name || '--' }}</span>
                                <b :class="getPctColorClass(d.strongest?.change_pct)">
                                    {{ signedPct(d.strongest?.change_pct) }}
                                </b>
                            </div>
                            <div class="rd-leader">
                                最弱 <span class="rd-name">{{ d.weakest?.sector_name || '--' }}</span>
                                <b :class="getPctColorClass(d.weakest?.change_pct)">
                                    {{ signedPct(d.weakest?.change_pct) }}
                                </b>
                            </div>
                        </div>
                    </div>

                    <!-- 热力图 + 强弱象限 -->
                    <div class="rot-charts">
                        <div class="rot-chart-box">
                            <div class="rot-chart-title">
                                轮动热力图（按区间累计涨幅排序，红涨绿跌；格内为当日涨跌幅 %）
                            </div>
                            <div ref="rotHeatRef" class="rot-chart rot-heat"
                                 :class="{'is-loading': rotation_loading}"></div>
                        </div>
                        <div class="rot-chart-box">
                            <div class="rot-chart-title">
                                强弱象限（气泡大小 = 最新日成交额占比）
                            </div>
                            <div ref="rotQuadRef" class="rot-chart rot-quad"
                                 :class="{'is-loading': rotation_loading}"></div>
                            <div class="rot-legend">
                                <span v-for="q in QUADRANTS" :key="q.name" class="rot-legend-item">
                                    <i class="rot-dot" :style="{background: q.color}"></i>{{ q.name }}
                                </span>
                            </div>
                        </div>
                    </div>

                    <!-- 轮动明细 -->
                    <div class="rot-section-title">
                        轮动明细（按区间累计涨幅降序，样本不完整的板块沉底并标注「样本 n/N」）
                    </div>
                    <DataTable
                        :value="rotation.series"
                        :loading="rotation_loading"
                        stripedRows
                        size="small"
                        class="rot-table"
                        :sortField="'sort_cum'"
                        :sortOrder="-1"
                        sortMode="single"
                        removableSort
                        :rowHover="true"
                        scrollable
                        scrollHeight="420px"
                    >
                        <Column field="sector_name" header="板块" :filter="true" filterPlaceholder="搜索板块"
                                style="min-width: 128px">
                            <template #body="{ data }">
                                {{ data.sector_name }}
                                <!-- 样本不满窗口 → 明确标出来，"区间累计"对它是单日涨幅 -->
                                <span v-if="data.is_partial" class="rot-partial"
                                      :title="`该板块只覆盖 ${data.sample_days}/${rotMeta.trade_days} 个交易日`">
                                    样本 {{ data.sample_days }}/{{ rotMeta.trade_days }}
                                </span>
                            </template>
                        </Column>
                        <!-- ⚠️ 排序字段用 sort_cum 而不是 cum_pct：样本不完整的板块
                             cum_pct 其实只是单日涨幅，直接按它排会被顶到最前面（实测
                             sw3 的「视频媒体 +6.06%」只有 1 天数据）。sort_cum 把它们
                             压到地板之下，展示的仍是真实 cum_pct。 -->
                        <Column field="sort_cum" header="区间累计" sortable style="min-width: 88px">
                            <template #body="{ data }">
                                <b :class="getPctColorClass(data.cum_pct)">{{ signedPct(data.cum_pct) }}</b>
                            </template>
                        </Column>
                        <Column field="latest_pct" header="最新日" sortable style="min-width: 80px">
                            <template #body="{ data }">
                                <span :class="getPctColorClass(data.latest_pct)">{{ signedPct(data.latest_pct) }}</span>
                            </template>
                        </Column>
                        <Column field="win_days" header="上涨天数" sortable style="min-width: 84px">
                            <template #body="{ data }">
                                <span class="text-up">{{ data.win_days }}</span>
                                <span class="text-muted"> / {{ data.sample_days }}</span>
                            </template>
                        </Column>
                        <Column field="beat_days" header="跑赢中位" sortable style="min-width: 84px">
                            <template #body="{ data }">
                                {{ data.beat_days }}<span class="text-muted"> / {{ data.sample_days }}</span>
                            </template>
                        </Column>
                        <Column field="streak" header="连续跑赢" sortable style="min-width: 84px">
                            <template #body="{ data }">
                                <span v-if="data.streak" class="rot-streak">{{ data.streak }} 日</span>
                                <span v-else class="text-muted">—</span>
                            </template>
                        </Column>
                        <Column field="latest_rank" header="最新排名" sortable style="min-width: 84px">
                            <template #body="{ data }">
                                {{ data.latest_rank ?? '--' }}
                                <span class="text-muted">/{{ rotRankBase ?? '--' }}</span>
                            </template>
                        </Column>
                        <Column field="rank_change" header="排名变化" sortable style="min-width: 84px">
                            <template #body="{ data }">
                                <!-- rank_change > 0 = 排名数字变小 = 名次上升 -->
                                <span v-if="data.rank_change > 0" class="text-up">▲{{ data.rank_change }}</span>
                                <span v-else-if="data.rank_change < 0" class="text-down">▼{{ -data.rank_change }}</span>
                                <span v-else class="text-muted">—</span>
                            </template>
                        </Column>
                        <Column field="amount_share_latest" header="成交额占比" sortable style="min-width: 104px">
                            <template #body="{ data }">
                                {{ data.amount_share_latest == null ? '--' : data.amount_share_latest + '%' }}
                                <div v-if="data.amount_share_change != null" class="rot-share-chg"
                                     :class="getPctColorClass(data.amount_share_change)">
                                    {{ data.amount_share_change > 0 ? '+' : '' }}{{ Number(data.amount_share_change).toFixed(2) }}pp
                                </div>
                            </template>
                        </Column>
                        <Column header="领涨股" style="min-width: 130px">
                            <template #body="{ data }">
                                <span v-if="data.top_stock" class="text-up">
                                    {{ data.top_stock }}
                                    <span class="text-xxs">({{ Number(data.top_stock_pct ?? 0).toFixed(2) }}%)</span>
                                </span>
                                <span v-else class="text-muted">--</span>
                            </template>
                        </Column>
                        <template #empty>
                            <div class="empty-tip">暂无轮动数据</div>
                        </template>
                    </DataTable>
                </div>
                <div v-else class="empty-tip">
                    {{ rotation_loading ? '加载中…' : '暂无板块历史数据（日更任务 job_update_sector_daily 每天 20:35 落库，需累积几天才能算轮动）' }}
                </div>
            </template>
        </Card>

    </div>
</template>

<style scoped lang="scss">

.dashboard-container {
    /* 页面外边距对齐全站约定：横向 2rem（=24px），与 .card 页内容左边缘一致（204）。
       原先是四边 1.5rem，横向比别人少 6px，看起来「缩了一点」。 */
    padding: 2rem;
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
            // ECharts 的根 div 是**带显式 px 宽度**的普通块元素（不是 absolute），
            // 一旦实例尺寸没跟上容器（窗口缩放过程中量歪），多出的宽度在
            // overflow-x: visible 下会"画"到盒外并撑开页面级滚动条 —— 实测把
            // scrollWidth 从 1440 撑到 1581。这里裁掉，最坏情况只是图被裁一点。
            overflow-x: clip;

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

.text-muted {
    color: #94a3b8;
}

// ========================
// 板块轮动分析
// ========================
.rotation-card {
    margin-bottom: 1.5rem;
}

.rot-controls {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.rot-body {
    transition: opacity 0.2s ease;

    &.is-loading {
        opacity: 0.5;
    }
}

// 样本口径 + 短样本提示
.rot-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.9rem;
    font-size: 0.9rem;

    .rot-meta-text {
        color: #64748b;
    }

    // ⚠️ 长中文文案必须给 min-width: 0 + 允许换行：否则 flex 子项的最小内容宽度
    // 会把整行撑开（overflow-x 默认 visible 时表现为卡片多出横向滚动条）
    .rot-hint {
        min-width: 0;
        padding: 0.2rem 0.6rem;
        border-radius: 4px;
        background: #fef6e0;
        border: 1px solid #f5dfa6;
        color: #8a6100;
        overflow-wrap: anywhere;
    }
}

.rot-section-title {
    font-size: 0.9rem;
    color: #94a3b8;
    margin: 1rem 0 0.5rem;
}

// 每日市场宽度
.rot-days {
    display: flex;
    gap: 0.6rem;
    // 数据攒到几十天时横向滚动，不要把它挤扁
    overflow-x: auto;
    padding-bottom: 0.3rem;

    .rot-day {
        flex: 0 0 auto;
        min-width: 168px;
        padding: 0.55rem 0.7rem;
        border: 1px solid var(--border-color);
        border-radius: 6px;
        background: #fbfcfe;
        font-size: 0.85rem;
        line-height: 1.7;
        color: #475569;

        .rd-date {
            font-weight: 600;
            color: #1e293b;

            .rd-amt {
                margin-left: 0.4rem;
                font-weight: 400;
                color: #94a3b8;
                font-size: 0.9em;
            }
        }

        .rd-mid .rd-disp {
            margin-left: 0.5rem;
            color: #94a3b8;
            font-size: 0.9em;
        }

        .rd-breadth .rd-ratio {
            margin-left: 0.5rem;
            color: #94a3b8;
            font-size: 0.9em;
        }

        .rd-leader {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;

            .rd-name {
                color: #1e293b;
                font-weight: 600;
            }

            // ⚠️ Vue 模板默认 whitespace: 'condense' —— 元素之间只含换行的空白会被删掉，
            // 所以「电子」和「+0.80%」会贴在一起，得用 CSS 补间距
            b {
                margin-left: 0.15rem;
            }
        }
    }
}

// 两张图：热力图为宽图、象限为方图
.rot-charts {
    display: grid;
    grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr);
    gap: 1.2rem;
    margin-top: 0.4rem;

    .rot-chart-box {
        min-width: 0;
        display: flex;
        flex-direction: column;

        .rot-chart-title {
            font-size: 0.85rem;
            color: #94a3b8;
            margin-bottom: 0.3rem;
        }

        .rot-chart {
            width: 100%;
            transition: opacity 0.2s ease;
            // 同 .fg-chart：挡住 ECharts 根 div 的显式宽度漏到页面级滚动
            overflow-x: clip;
        }

        .rot-heat {
            height: 440px;
        }

        .rot-quad {
            height: 400px;
        }
    }
}

// 象限配色说明（用 HTML 图例而不是 ECharts legend：四象限是"底纹"不是 series）
.rot-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.8rem;
    justify-content: center;
    font-size: 0.85rem;
    color: #64748b;
    margin-top: 0.2rem;

    .rot-legend-item {
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
    }

    .rot-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
    }
}

// 轮动明细表（与上方的申万排行表同款，只是列更多）
.rot-table {
    td, th {
        padding: 0.4rem 0.5rem;
        font-size: 0.9rem;
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

    // "连续跑赢"是这张表里最像"当前主线"的字段，给个轻量高亮
    .rot-streak {
        color: #b45309;
        font-weight: 600;
    }

    // 样本不满窗口的板块标记
    .rot-partial {
        margin-left: 0.3rem;
        padding: 0 0.3rem;
        border-radius: 3px;
        background: #eef2f6;
        color: #94a3b8;
        font-size: 0.9em;
        white-space: nowrap;
        cursor: help;
    }

    .rot-share-chg {
        font-size: 0.9em;
    }
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

    // 两张轮动图并排会让每张都太窄（热力图还要放板块名），窄屏改为上下堆叠
    .rot-charts {
        grid-template-columns: minmax(0, 1fr);
    }
}

@media (max-width: 768px) {
    .indices-row .index-card {
        flex: 1 1 calc(50% - 1rem);
    }
}

</style>
