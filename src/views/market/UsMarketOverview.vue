<script setup>
/**
 * 美股大盘监控
 *
 * 数据源：GET /api/v1/index/us_cards（service/us_index_service.py → 上游
 * `databull.get_us_index_history`）。
 *
 * ⚠️ **没有实时行情**：上游美股指数只提供日线（`get_realtime(market='us')`
 * 实测 404），所以所有卡片是**最近一个交易日的收盘**，不是盘中价。
 * 页面文案里不要出现「实时」「盘中」这类词。
 *
 * ⚠️ **各指数最新交易日可能不同**（实测 VIX 比 GSPC 多一天），后端用非波动率
 * 指数的众数当「主日期」，每张卡按自己的 trade_date 显示，别在前端统一化。
 *
 * ⚠️ VIX 是波动率指数、不是价格指数：涨=市场恐慌。它和价格指数并排放在
 * 同一行卡片里时若沿用「红=涨」，VIX 上涨（恐慌）会显示成红色、看着像利好，
 * 所以卡片对 volatility 类反转了着色方向（逻辑在 `@/components/IndexCard.vue`）。
 *
 * 卡片**一行平铺、不分组**，且**与沪深大盘页共用同一个组件**
 * （`@/components/IndexCard.vue`）—— 两页的卡片视觉与算法都只有一处来源，
 * 改一处两页同时生效。本文件只负责取数与页面级布局。
 */
import {ref, computed, onMounted, onUnmounted, nextTick} from 'vue'
import ToggleSwitch from 'primevue/toggleswitch'
import axios from 'axios'
import {useToast} from 'primevue/usetoast'
import IndexCard from '@/components/IndexCard.vue'
import Card from 'primevue/card'
import * as echarts from 'echarts'
import {
    COLORS, LINE,
    axisLabel, splitLine, tooltipBase, lineSeriesStyle, markLevels, areaGradient,
} from '@/utils/echartsTheme'

// 日线数据，收盘后不变 → 刷新间隔给长（与大盘页的恐惧贪婪一致）。
const REFRESH_MS = 10 * 60 * 1000

const toast = useToast()

const loading = ref(false)
const error_msg = ref('')
const cards = ref([])
const meta = ref(null)
const auto_refresh = ref(true)
let timer = null
let avTimer = null

// 顶部的滞后提示：只在真的有指数落后于主日期时说，别天天刷「VIX 领先一天」。
const stale_hint = computed(() => {
    const codes = meta.value?.stale_codes || []
    if (!codes.length) return ''
    return `以下指数数据落后于 ${meta.value.data_date}：${codes.join('、')}`
})

const failed_hint = computed(() => {
    const failed = meta.value?.failed || []
    if (!failed.length) return ''
    return `${failed.length} 个指数取数失败：${failed.map((f) => f.code).join('、')}`
})

// ========================
// 取数
// ========================
const fetchCards = async (silent = false) => {
    if (!silent) loading.value = true
    try {
        const res = await axios.get('/api/v1/index/us_cards')
        const data = res.data
        cards.value = data?.items || []
        meta.value = data?.meta || null
        error_msg.value = ''
    } catch (e) {
        cards.value = []
        meta.value = null
        // 静默刷新失败不清空已有数据（否则定时刷新一次失败页面就白了）
        if (silent) {
            console.warn('美股指数刷新失败', e)
        } else {
            error_msg.value = e?.response?.data?.detail || '美股指数数据获取失败'
            toast.add({severity: 'error', summary: '加载失败', detail: error_msg.value, life: 4000})
        }
    } finally {
        loading.value = false
    }
}

const startTimer = () => {
    stopTimer()
    if (auto_refresh.value) {
        timer = setInterval(() => fetchCards(true), REFRESH_MS)
        // A股/美股比值是日线数据，与指数卡片同节奏刷新即可（后端缓存 30 分钟）
        avTimer = setInterval(() => fetchA500Sp500(true), REFRESH_MS)
    }
}

const stopTimer = () => {
    if (timer) {
        clearInterval(timer)
        timer = null
    }
    if (avTimer) {
        clearInterval(avTimer)
        avTimer = null
    }
}

const onRefreshToggle = () => {
    if (auto_refresh.value) {
        fetchCards(true)
        fetchA500Sp500(true)
        startTimer()
    } else {
        stopTimer()
    }
}

// 手动刷新：后端缓存 30 分钟，用 bust 参数强制回源。
// ⚠️ 必须走**已声明**的参数名 `bust`：cache key 由
// md5(module:qualname:args:kwargs) 生成，只有声明过的 query 参数才进 key；
// 写成 `?_=<ts>`（未声明）会被 FastAPI 直接忽略 → 照样命中旧缓存，
// 点「刷新」看起来毫无反应。
const manualRefresh = async () => {
    await axios.get('/api/v1/index/us_cards', {params: {bust: Date.now()}}).then((res) => {
        cards.value = res.data?.items || []
        meta.value = res.data?.meta || null
    }).catch((e) => {
        toast.add({severity: 'error', summary: '刷新失败', detail: '上游接口暂时不可用', life: 4000})
    })
    // 比值图同样用 bust 绕过缓存（non-silent，失败会提示）
    await fetchA500Sp500(false, true)
}

// ========================
// A股 vs 美股（中证A500 ÷ 标普500 比值走势）
// ========================
/**
 * A股 vs 美股 = 中证A500(000510) ÷ 标普500(GSPC)
 *
 * 比值**上行 = A股跑赢美股**，下行 = 美股跑赢 A股。比值本身没有绝对高低含义，
 * 所以后端返回的是「以区间首日归一为 1.0」的净值，同时给出两条成分腿的
 * 归一化净值 —— 只看比值看不到「是中证A500涨出来的还是标普500跌出来的」，
 * 副轴叠两条线就能一眼分辨。
 *
 * ⚠️ 中证A500 用的是 000510（不是官方 CSI 代码 931337，上游对 931 段无 K 线），
 * 详见 service/a500_sp500_service.py 顶部说明。结构完全复用沪深大盘页
 * 「成长 vs 价值」卡片的界面与逻辑。
 */
const A500_SP500_DAYS = 250   // ≈ 一年交易日

const a500_sp500 = ref(null)
const a500_sp500_loading = ref(false)

const avLatest = computed(() => a500_sp500.value?.points?.slice(-1)[0] || null)
const avMeta = computed(() => a500_sp500.value?.meta || null)
const avPeriods = computed(() => a500_sp500.value?.periods || [])

// 比值涨 → A股占优（红）；跌 → 美股占优（绿）。与全站红涨绿跌一致。
const avRatioColor = computed(() => {
    const v = avLatest.value?.ratio
    if (v == null) return '#909399'
    if (v > 1) return 'var(--color-up)'
    if (v < 1) return 'var(--color-down)'
    return 'var(--color-flat)'
})

const avChartRef = ref(null)
let avChart = null
let avResizeObserver = null

/**
 * 相对强度（归一化净值或比值）→ 迷你条宽度（%）。
 * 与沪深大盘页「成长 vs 价值」同一条约定：按三者里最大偏离度做相对归一，留 12% 下限。
 */
const avBarWidth = (norm) => {
    if (norm == null) return 0
    const devs = [avLatest.value?.ratio, avLatest.value?.a500_norm, avLatest.value?.sp500_norm]
        .filter((v) => v != null)
        .map((v) => Math.abs(Number(v) - 1))
    const maxDev = Math.max(...devs, 1e-9)
    return Math.max(12, Math.round((Math.abs(Number(norm) - 1) / maxDev) * 100))
}

// 成分腿颜色：>1 表示该腿跑赢（红），<1 表示跑输（绿）
const avLegColor = (norm) => {
    if (norm == null) return '#909399'
    if (norm > 1) return 'var(--color-up)'
    if (norm < 1) return 'var(--color-down)'
    return 'var(--color-flat)'
}

const getPctColorClass = (value) => {
    if (value > 0) return 'text-up'
    if (value < 0) return 'text-down'
    return 'text-flat'
}

// 容器在 v-if 内，数据到位后 DOM 才存在，必须懒初始化；用 ResizeObserver 跟随尺寸
// （不挂 window.resize：盯盘页开一天会产生上万次无意义 resize）。
const ensureAvChart = () => {
    if (typeof ResizeObserver !== 'undefined' && !avResizeObserver) {
        avResizeObserver = new ResizeObserver(() => { avChart?.resize() })
    }
    if (avChart || !avChartRef.value) return avChart
    if (!avChartRef.value.clientWidth || !avChartRef.value.clientHeight) return null
    avChart = echarts.init(avChartRef.value)
    if (avChartRef.value) avResizeObserver?.observe(avChartRef.value)
    return avChart
}

const disconnectAvChart = () => {
    avResizeObserver?.disconnect()
    avResizeObserver = null
}

const fetchA500Sp500 = async (silent = false, bust = false) => {
    if (!silent) a500_sp500_loading.value = true
    try {
        const params = {days: A500_SP500_DAYS}
        if (bust) params.bust = Date.now()
        const res = await axios.get('/api/v1/market/a500_sp500', {params})
        a500_sp500.value = res.data || null
        renderA500Sp500Chart()
    } catch (e) {
        // 静默刷新失败不清空已有数据
        if (!silent) {
            a500_sp500.value = null
            toast.add({severity: 'error', summary: '加载失败', detail: 'A股/美股比值数据获取失败', life: 4000})
        }
    } finally {
        a500_sp500_loading.value = false
    }
}

const renderA500Sp500Chart = async () => {
    await nextTick()
    const chart = ensureAvChart()
    if (!chart) return

    const rows = a500_sp500.value?.points || []
    if (!rows.length) {
        chart.clear()
        return
    }
    const dates = rows.map((r) => r.trade_date)
    const ratio = rows.map((r) => r.ratio)
    const aNorm = rows.map((r) => r.a500_norm)
    const sNorm = rows.map((r) => r.sp500_norm)

    // 比值线颜色跟随「相对起点」方向：>1 A股占优，<1 美股占优
    const lastRatio = ratio[ratio.length - 1]
    const mainColor = lastRatio > 1 ? '#ef4444' : (lastRatio < 1 ? '#12783c' : '#909399')

    chart.setOption({
        grid: {left: 34, right: 42, top: 16, bottom: 22},
        tooltip: tooltipBase({
            formatter: (params) => {
                const i = params[0].dataIndex
                const d = rows[i]
                return `${d.trade_date}<br/>`
                    + `比值: <b>${d.ratio.toFixed(4)}</b><br/>`
                    + `中证A500: ${d.a500_close}（${((d.a500_norm - 1) * 100).toFixed(2)}%）<br/>`
                    + `标普500: ${d.sp500_close}（${((d.sp500_norm - 1) * 100).toFixed(2)}%）`
            }
        }),
        xAxis: {
            type: 'category',
            data: dates,
            show: false
        },
        yAxis: [
            {
                type: 'value',
                scale: true,
                splitNumber: 2,
                axisLabel: axisLabel({formatter: (v) => v.toFixed(2)}),
                splitLine: splitLine()
            },
            {
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
                name: 'A股/美股',
                type: 'line',
                yAxisIndex: 0,
                data: ratio,
                smooth: true,
                showSymbol: false,
                ...lineSeriesStyle({color: mainColor, shadow: false}),
                areaStyle: {
                    color: areaGradient(mainColor, 0.22, 0.02)
                },
                // 1.0 = 区间起点，比值在此之上为 A股占优
                markLine: markLevels([1], {color: COLORS.guideStrong})
            },
            {
                name: '中证A500',
                type: 'line',
                yAxisIndex: 1,
                data: aNorm,
                smooth: true,
                showSymbol: false,
                ...lineSeriesStyle({color: '#ef4444', width: LINE.secondary, type: 'dotted', opacity: 0.45, shadow: false})
            },
            {
                name: '标普500',
                type: 'line',
                yAxisIndex: 1,
                data: sNorm,
                smooth: true,
                showSymbol: false,
                ...lineSeriesStyle({color: '#12783c', width: LINE.secondary, type: 'dotted', opacity: 0.45, shadow: false})
            }
        ]
    })
}

onMounted(async () => {
    await fetchCards()
    await fetchA500Sp500()
    startTimer()
})

onUnmounted(() => {
    stopTimer()
    disconnectAvChart()
    avChart?.dispose()
    avChart = null
})
</script>

<template>
    <div class="dashboard-container">
        <!-- 顶部标题栏 -->
        <div class="header">
            <div class="title-block">
                <h1 class="title">美股大盘监控</h1>
                <div class="subtitle">
                    数据时间 {{ meta?.data_date || '--' }}（{{ meta?.trade_timezone || 'America/New_York' }} 收盘）
                </div>
            </div>
            <div class="header-right">
                <label class="auto-refresh">
                    <ToggleSwitch v-model="auto_refresh" @change="onRefreshToggle" />
                    <span>{{ auto_refresh ? '自动刷新 10min' : '已暂停' }}</span>
                </label>
                <button class="refresh-btn" :disabled="loading" @click="manualRefresh">
                    <i class="pi pi-refresh" :class="{spin: loading}"></i>
                    <span>刷新</span>
                </button>
            </div>
        </div>

        <!-- 异常提示：仅在有值时出现（取数失败 / 指数数据滞后）。
             原先这里还有一条常驻「口径说明」提示条，按用户要求去掉了 ——
             它每次都在、看一次就够，属于噪音；而这两个提示只在**真的出问题**时
             才出现，是会「说话」的，不能跟着一起删。 -->
        <div v-if="error_msg || stale_hint || failed_hint" class="error-box">
            <div v-if="error_msg">{{ error_msg }}</div>
            <div v-if="stale_hint">{{ stale_hint }}</div>
            <div v-if="failed_hint">{{ failed_hint }}</div>
        </div>

        <!-- A股 vs 美股（中证A500 ÷ 标普500，起点归一）；复用沪深大盘页「成长 vs 价值」卡片结构 -->
        <Card class="fear-greed-card a500-sp500-card">
            <template #title>
                <div class="card-title-row">
                    <span>A股 vs 美股（中证A500 ÷ 标普500，起点归一）</span>
                    <span v-if="avMeta" class="av-window">
                        {{ avMeta.start_date }} ~ {{ avMeta.end_date }}（{{ avMeta.trade_days }} 个交易日）
                    </span>
                </div>
            </template>
            <template #content>
                <div v-if="avLatest" class="fear-greed-body">
                    <!-- 左：当前比值 + 区间涨跌幅 -->
                    <div class="fg-current">
                        <div class="fg-value" :style="{ color: avRatioColor }">
                            {{ avLatest.ratio.toFixed(4) }}
                        </div>
                        <div class="fg-label" :style="{ color: avRatioColor }">
                            {{ avLatest.ratio > 1 ? 'A股占优' : (avLatest.ratio < 1 ? '美股占优' : '相对均衡') }}
                        </div>
                        <div class="fg-date">{{ avLatest.trade_date }}</div>

                        <div class="fg-scores">
                            <!-- 分量拆解：三条「相对强度」条，都按窗口首日归一化为 1.0，
                                 >1 红（跑赢）、<1 绿（跑输），与全站红涨绿跌一致。
                                 条宽按「三条里最大偏离度」做相对归一，再留 12% 下限。 -->
                            <div class="fg-score">
                                <span class="score-name">A股/美股</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: avBarWidth(avLatest.ratio), background: avRatioColor }"></span>
                                </span>
                                <span class="score-val" :style="{ color: avRatioColor }">
                                    {{ avLatest.ratio.toFixed(4) }}
                                </span>
                            </div>
                            <div class="fg-score">
                                <span class="score-name">中证A500</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: avBarWidth(avLatest.a500_norm), background: avLegColor(avLatest.a500_norm) }"></span>
                                </span>
                                <span class="score-val" :style="{ color: avLegColor(avLatest.a500_norm) }">
                                    {{ ((avLatest.a500_norm - 1) * 100).toFixed(1) }}%
                                </span>
                            </div>
                            <div class="fg-score">
                                <span class="score-name">标普500</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: avBarWidth(avLatest.sp500_norm), background: avLegColor(avLatest.sp500_norm) }"></span>
                                </span>
                                <span class="score-val" :style="{ color: avLegColor(avLatest.sp500_norm) }">
                                    {{ ((avLatest.sp500_norm - 1) * 100).toFixed(1) }}%
                                </span>
                            </div>
                            <!-- 区间比值涨跌幅：>0 说明该窗口内 A股跑赢美股 -->
                            <div v-for="p in avPeriods" :key="p.days" class="fg-score">
                                <span class="score-name">近 {{ p.days }} 日</span>
                                <span class="score-track">
                                    <span class="score-fill"
                                          :style="{ width: avBarWidth(p.change_pct) + '%', background: p.change_pct >= 0 ? 'var(--color-up)' : 'var(--color-down)' }"></span>
                                </span>
                                <span class="score-val"
                                      :class="getPctColorClass(p.change_pct)">
                                    {{ p.change_pct == null ? '--' : (p.change_pct > 0 ? '+' : '') + p.change_pct.toFixed(1) + '%' }}
                                </span>
                            </div>
                        </div>
                    </div>
                    <!-- 右：近一年比值走势（副轴叠两条成分指数归一化净值） -->
                    <div class="fg-chart-wrap">
                        <div class="fg-chart-title">
                            近一年走势（比值上行 = A股跑赢；点线为两条成分指数归一化涨幅）
                        </div>
                        <div ref="avChartRef" class="fg-chart"
                             :class="{'is-loading': a500_sp500_loading}"></div>
                    </div>
                </div>
                <div v-else class="empty-tip">
                    {{ a500_sp500_loading ? '加载中…' : '暂无 A股/美股比值数据' }}
                </div>
            </template>
        </Card>

        <!-- 指数卡片：一行平铺，不分组（与沪深大盘页一致，共用 IndexCard 组件） -->
        <div class="indices-row">
            <IndexCard
                v-for="item in cards"
                :key="item.code"
                :item="item"
                :tag-text="item.is_volatility ? '恐慌指数' : ''"
            />
        </div>

        <div v-if="!loading && !cards.length" class="empty-tip">暂无美股指数数据</div>

    </div>
</template>

<style scoped lang="scss">
.dashboard-container {
    /* 页面外边距对齐全站约定：横向 2rem（=24px），与 .card 内容左边缘一致（204）。
       与 MarketOverview.vue 保持相同。 */
    padding: 2rem;
    background: #f5f7fb;
    min-height: 100vh;
}

/* ========================
   A股 vs 美股（复用沪深大盘页「成长 vs 价值」恐惧贪婪卡片的结构与样式）
   ======================== */
.fear-greed-card {
    margin-bottom: 1.5rem;
    background: #fff;

    .card-title-row {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 0.5rem;
        flex-wrap: wrap;
    }

    // 标题右侧的区间说明，弱化显示
    .av-window {
        font-size: 0.8rem;
        color: #94a3b8;
        font-weight: 400;
    }
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
            // 与沪深大盘页同一条约定：挡住 ECharts 根 div 的显式宽度漏到页面级滚动
            overflow-x: clip;

            &.is-loading {
                opacity: 0.45;
            }
        }
    }
}

// 颜色工具类（--color-up/down/flat 定义在全局 :root）
.text-up {
    color: var(--color-up);
}

.text-down {
    color: var(--color-down);
}

.text-flat {
    color: var(--color-flat);
}


.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
    flex-wrap: wrap;
    gap: 0.75rem;

    .title-block {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .title {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1e293b;
        margin: 0;
    }

    .subtitle {
        font-size: 0.85rem;
        color: #64748b;
    }

    .header-right {
        display: flex;
        align-items: center;
        gap: 1rem;
        flex-wrap: wrap;
    }
}

.auto-refresh {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    color: #475569;
    font-size: 0.9rem;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
}

.refresh-btn {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.45rem 0.8rem;
    font-size: 0.85rem;
    color: #475569;
    background: #fff;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    cursor: pointer;
    white-space: nowrap;

    &:hover:not(:disabled) {
        border-color: var(--primary-color);
        color: var(--primary-color);
    }

    &:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .spin {
        animation: us-spin 1s linear infinite;
    }
}

@keyframes us-spin {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}

/* 异常提示条（取数失败 / 数据滞后）。原先还有一个常驻的蓝色「口径说明」提示条，
   按用户要求去掉了（每次都在、看一次就够），样式一并清掉。 */
.error-box {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.75rem 1rem;
    margin-bottom: 1.25rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 8px;
    color: #b91c1c;
    font-size: 0.9rem;
}

/* 指数卡片行：flex-wrap + flex:1 1（与沪深大盘页 `.indices-row` 同一套）。
   ⚠️ 别用 grid：11 张卡除以 4 列是 4+4+3，grid 下最后一行会缺一格、右侧留空。
   flex 让每行的卡片自动拉伸填满整行，最后一行 3 张照样铺满。 */
.indices-row {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 1.5rem;
}

/* 卡片自身样式在 IndexCard.vue 里（两页共用）。这里只管行布局：
   flex-wrap + flex:1 1 让每行卡片自动拉伸铺满 —— 11 张卡 4+4+3，最后一行不空一格。
   ⚠️ 别用 grid：11/4 除不尽，最后一行会缺格。 */
.index-card {
    flex: 1 1 calc(25% - 0.75rem);
    min-width: 240px;
}

.empty-tip {
    padding: 2rem;
    text-align: center;
    color: #94a3b8;
}
</style>
