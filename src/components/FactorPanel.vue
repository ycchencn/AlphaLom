<script setup>
/**
 * 个股 / ETF 技术面「专业分析」面板（因子看板 / 仪表盘 / 雷达 / 横向对比）
 *
 * 数据来源（routes/factor.py + service/factor_analysis_service.py）：
 *   GET /api/v1/factor/stock/{symbol}                 因子看板（全部技术因子 + 历史分位）
 *   GET /api/v1/factor/stock/{symbol}/dashboard       仪表盘（均线/关键位/象限/阶段/热度）
 *   GET /api/v1/factor/stock/{symbol}/radar           因子雷达
 *   GET /api/v1/factor/stock/{symbol}/industry_rank   横向对比（个股=行业内 / ETF=全站 ETF）
 *   GET /api/v1/factor/stock/{symbol}/series          因子序列（画曲线）
 *
 * 设计：本组件**自带取数**，父页面只需传 `symbol` 与 `assetType`。取数失败静默降级
 * （卡片不渲染），不让一个专业面板的失败拖垮整个详情页。
 *
 * ⚠️ ETF 与个股的差异（都会让卡片「静默变空」，不是报错）：
 *   1. 行情接口不同 → 必须传 assetType='etf'，否则仪表盘拿的是半年前的日线（见后端注释）；
 *   2. ETF 没有 `main_force_behavior_phase`（主力行为阶段）→ 该卡片本就不渲染；
 *   3. ETF 没有行业 → 横向对比改比「全站 ETF 池」，标题按响应里的 scope 自适应。
 */
import {computed, onMounted, onUnmounted, ref, watch, nextTick} from 'vue';
import axios from 'axios';
import * as echarts from 'echarts';
import {
    COLORS, LINE, FONT, axisLabel, splitLine, tooltipBase, areaGradient,
} from '@/utils/echartsTheme';

// 图表配色（沿用项目 echartsTheme 变量；缺失的语义色在此补齐）
const C = {
    up: COLORS.up,            // 红 = 涨 / 过热
    down: COLORS.down,        // 绿 = 跌 / 过冷
    neutral: COLORS.axisLabel,
    accent: '#3b82f6',        // 主数据线
    warn: '#f59e0b',
};

// 主力行为阶段配色（吸筹/洗盘/拉升/出货初/出货末）
const PHASE_COLORS = {
    0: '#c0c4cc',  // 未知
    1: '#f6c445',  // 吸筹（黄）
    2: '#f59e0b',  // 洗盘（橙）
    3: '#dc2626',  // 拉升（红）
    5: '#7c9cbf',  // 出货初期（蓝灰）
    6: '#5b8c5a',  // 出货末期（绿）
};
function phaseColor(code) {
    return PHASE_COLORS[Number(code)] || PHASE_COLORS[0];
}

const props = defineProps({
    symbol: {type: String, required: true},
    // 'stock'（默认）/ 'etf'。**ETF 必须显式传**：仪表盘的行情接口按它分流，
    // 传错不会报错，而是拿到半年前的日线，均线/关键位/ATR 全按旧价算出（静默错误）。
    assetType: {type: String, default: 'stock'},
});

// ==================== 状态 ====================
const loading = ref(false);
const board = ref(null);         // L0 因子看板
const dashboard = ref(null);     // L1 仪表盘
const radar = ref(null);         // L2 雷达
const peerRank = ref(null);      // L2 横向对比（个股=行业内 / ETF=全站 ETF）
const activeGroup = ref(null);   // 当前选中的因子分组（画曲线用）
const seriesData = ref(null);    // 选中分组的因子曲线数据

const radarRef = ref(null);
const quadRef = ref(null);
const seriesRef = ref(null);
const heatRef = ref(null);
let charts = [];

// 图表实例统一管理，卸载时销毁
function disposeAll() {
    charts.forEach((c) => c && c.dispose && c.dispose());
    charts = [];
}

// ==================== 取数 ====================
async function loadAll() {
    if (!props.symbol) return;
    loading.value = true;
    const base = `/api/v1/factor/stock/${props.symbol}`;
    const at = props.assetType;
    // ⚠️ 用 allSettled：单个接口失败（如 ETF 无行业样本导致横向对比 404）不应影响其它卡片。
    // asset_type 只传给**真的按它分流**的两个接口（dashboard / industry_rank），
    // 看板与雷达按 ticker 直接查因子表，个股 ETF 同一套口径，多传反而像是有差别。
    const [b, d, r, ir] = await Promise.allSettled([
        axios.get(base),
        axios.get(`${base}/dashboard`, {params: {asset_type: at}}),
        axios.get(`${base}/radar`),
        axios.get(`${base}/industry_rank`, {params: {asset_type: at}}),
    ]);
    board.value = b.status === 'fulfilled' ? (b.value.data?.data ?? b.value.data) : null;
    dashboard.value = d.status === 'fulfilled' ? (d.value.data?.data ?? d.value.data) : null;
    radar.value = r.status === 'fulfilled' ? (r.value.data?.data ?? r.value.data) : null;
    peerRank.value = ir.status === 'fulfilled' ? (ir.value.data?.data ?? ir.value.data) : null;
    loading.value = false;

    // 默认展开第一个分组并画曲线
    const firstGroup = board.value?.groups?.[0];
    if (firstGroup) {
        await nextTick();
        selectGroup(firstGroup);
    }
    await nextTick();
    renderRadar();
    renderQuadrant();
    renderHeat();
}

async function selectGroup(group) {
    activeGroup.value = group;
    // 取该分组内因子（最多 4 个，避免图太花）的时间序列
    const fields = (group.items || []).map((i) => i.field).slice(0, 4);
    if (!fields.length) return;
    try {
        const {data} = await axios.get(`/api/v1/factor/stock/${props.symbol}/series`, {
            params: {names: fields.join(','), lookback_days: 250},
        });
        seriesData.value = data?.data ?? data;
    } catch (e) {
        seriesData.value = null;
    }
    await nextTick();
    renderSeries();
}

// ==================== 图表 ====================
function renderSeries() {
    if (!seriesRef.value || !seriesData.value?.series) return;
    let c = echarts.getInstanceByDom(seriesRef.value);
    if (!c) { c = echarts.init(seriesRef.value); charts.push(c); }
    const seriesMap = seriesData.value.series;
    const names = Object.keys(seriesMap);
    if (!names.length) { c.clear(); return; }
    // 以第一个因子的日期为 x 轴
    const x = seriesMap[names[0]].map((p) => p.date);
    const palette = [C.accent, COLORS.up, C.warn, C.neutral];
    const series = names.map((n, i) => {
        const byDate = Object.fromEntries(seriesMap[n].map((p) => [p.date, p.value]));
        return {
            name: n,
            type: 'line',
            smooth: true,
            showSymbol: false,
            lineStyle: lineStyleOf(i),
            itemStyle: {color: palette[i % palette.length]},
            data: x.map((d) => byDate[d] ?? null),
        };
    });
    c.setOption({
        grid: {left: 48, right: 16, top: 30, bottom: 24},
        tooltip: {...tooltipBase, trigger: 'axis'},
        legend: {top: 0, textStyle: {fontSize: 11}},
        xAxis: {type: 'category', data: x, ...axisLabel, boundaryGap: false},
        yAxis: {type: 'value', ...axisLabel, splitLine},
        series,
    }, true);
    c.resize();
}

function lineStyleOf(i) {
    return {width: i === 0 ? 2 : 1.2, type: i === 0 ? 'solid' : 'solid', opacity: i === 0 ? 1 : 0.7};
}

// 雷达图：核心因子 0~100 分位
function renderRadar() {
    if (!radarRef.value || !radar.value?.axes?.length) return;
    let c = echarts.getInstanceByDom(radarRef.value);
    if (!c) { c = echarts.init(radarRef.value); charts.push(c); }
    const axes = radar.value.axes;
    c.setOption({
        tooltip: {...tooltipBase},
        radar: {
            indicator: axes.map((a) => ({name: a.name, max: 100})),
            radius: '62%',
            axisName: {fontSize: 10, color: C.neutral},
            splitLine: {lineStyle: {color: 'rgba(0,0,0,0.08)'}},
            splitArea: {areaStyle: {color: ['rgba(0,0,0,0.01)', 'rgba(0,0,0,0.03)']}},
            axisLine: {lineStyle: {color: 'rgba(0,0,0,0.1)'}},
        },
        series: [{
            type: 'radar',
            data: [{
                value: axes.map((a) => a.score ?? 0),
                name: '分位',
                lineStyle: {color: C.accent, width: 2},
                itemStyle: {color: C.accent},
                areaStyle: {color: 'rgba(214,69,69,0.15)'},
            }],
        }],
    }, true);
    c.resize();
}

// 动量-波动象限（散点 + 轨迹）
function renderQuadrant() {
    if (!quadRef.value || !dashboard.value?.quadrant?.track?.length) return;
    let c = echarts.getInstanceByDom(quadRef.value);
    if (!c) { c = echarts.init(quadRef.value); charts.push(c); }
    const track = dashboard.value.quadrant.track;
    const pts = track.map((p) => [p.mom_pct, p.vol_pct]);
    const cur = pts[pts.length - 1];
    c.setOption({
        grid: {left: 44, right: 20, top: 24, bottom: 28},
        tooltip: {
            ...tooltipBase,
            formatter: (p) => `动量分位 ${p.value[0]}<br/>波动分位 ${p.value[1]}`,
        },
        xAxis: {
            type: 'value', min: 0, max: 100, name: '动量分位',
            nameLocation: 'middle', nameGap: 20, nameTextStyle: {fontSize: 10},
            ...axisLabel, splitLine,
        },
        yAxis: {
            type: 'value', min: 0, max: 100, name: '波动分位',
            nameTextStyle: {fontSize: 10}, ...axisLabel, splitLine,
        },
        series: [
            {
                type: 'line', data: pts, smooth: true, showSymbol: false,
                lineStyle: {color: 'rgba(214,69,69,0.35)', width: 1.2},
                markLine: {
                    silent: true, symbol: 'none',
                    lineStyle: {color: 'rgba(0,0,0,0.12)', type: 'dashed'},
                    data: [{xAxis: 50}, {yAxis: 50}],
                },
            },
            {
                type: 'scatter', data: [cur], symbolSize: 11,
                itemStyle: {color: COLORS.up, borderColor: '#fff', borderWidth: 1.5},
                z: 10,
            },
        ],
    }, true);
    c.resize();
}

// 超买超卖热度条
function renderHeat() {
    if (!heatRef.value || !dashboard.value?.heat) return;
    let c = echarts.getInstanceByDom(heatRef.value);
    if (!c) { c = echarts.init(heatRef.value); charts.push(c); }
    const h = dashboard.value.heat;
    c.setOption({
        grid: {left: 8, right: 8, top: 8, bottom: 8},
        series: [{
            type: 'gauge',
            startAngle: 180, endAngle: 0, min: 0, max: 100,
            radius: '100%', center: ['50%', '78%'],
            progress: {show: true, width: 12, roundCap: true,
                itemStyle: {color: heatColor(h.heat)}},
            axisLine: {lineStyle: {width: 12, color: [[1, 'rgba(0,0,0,0.06)']]}},
            pointer: {show: false},
            axisTick: {show: false}, splitLine: {show: false}, axisLabel: {show: false},
            detail: {valueAnimation: true, fontSize: 16, offsetCenter: [0, '-8%'],
                formatter: (v) => `${v}`},
            data: [{value: h.heat ?? 0}],
        }],
    }, true);
    c.resize();
}

function heatColor(v) {
    if (v == null) return C.neutral;
    if (v >= 80) return COLORS.up;      // 过热
    if (v >= 60) return C.warn;
    if (v <= 20) return COLORS.down;    // 过冷
    return C.neutral;
}

// ==================== 展示辅助 ====================
// 分位条颜色：越高越红（A 股习惯），越低越绿
function pctColor(pct, lowerIsBetter) {
    if (pct == null) return C.neutral;
    const v = lowerIsBetter ? 100 - pct : pct;
    if (v >= 80) return COLORS.up;
    if (v >= 60) return C.warn;
    if (v <= 20) return COLORS.down;
    return C.neutral;
}

// 「优于同业」：反向因子（波动越低越好）要把分位翻过来读
function betterPct(row) {
    const p = Number(row.percentile ?? 0);
    return row.lower_is_better ? 100 - p : p;
}

function fmtValue(field, value) {
    if (value == null) return '—';
    const v = Number(value);
    if (!Number.isFinite(v)) return '—';
    // 比率类显示成百分比
    if (/^(mom|bias|vol|mom_risk_adj)/.test(field)) return `${(v * 100).toFixed(2)}%`;
    if (field === 'rsi_14') return v.toFixed(2);
    if (field === 'closing_strength') return v.toFixed(3);
    if (field === '52week_position') return v.toFixed(1);
    if (field === 'atr_14') return v.toFixed(3);
    if (field === 'atr_14_annualized') return v.toFixed(2);
    if (/^turnover/.test(field)) return v >= 1e8 ? (v / 1e8).toFixed(2) + '亿' : (v / 1e4).toFixed(1) + '万';
    return v.toFixed(3);
}

const maState = computed(() => dashboard.value?.ma_status || null);
const levels = computed(() => dashboard.value?.key_levels || null);
const phase = computed(() => dashboard.value?.phase_series || null);
const range52 = computed(() => board.value?.range_52week || null);

// 横向对比卡片：标题与脚注按后端返回的 scope 走，前端不再自己判「什么类型写什么文案」。
const peerTitle = computed(() => {
    const ir = peerRank.value;
    if (!ir) return '';
    // 兼容旧响应（无 scope 字段时按行业处理）
    const label = ir.peer_label ?? ir.industry ?? '';
    return (ir.scope === 'etf' ? '同类排名' : '行业内排名') + (label ? ` · ${label}` : '');
});
const peerNote = computed(() => (peerRank.value?.scope === 'etf'
    ? '同类样本来自监控清单与轮动池中的全部 ETF，样本较少时仅供参考。'
    : '同业样本来自监控池中同行业标的，样本较少时仅供参考。'));

// 因子历史过短时（新纳入日更的标的常常只落了一两天），历史分位没有参考价值，
// 显式提示而不是让用户对着一堆「100% / 0%」猜。阈值取 5 个交易日。
const historyShort = computed(() => {
    const n = board.value?.history_days;
    return typeof n === 'number' && n > 0 && n < 5;
});

const MA_STATE_STYLE = {
    bull: {text: '多头排列', color: '#d64545'},
    bear: {text: '空头排列', color: '#1f9d55'},
    mixed: {text: '均线纠缠', color: '#8a8a8a'},
};

function onResize() {
    charts.forEach((c) => c && c.resize && c.resize());
}

onMounted(() => {
    loadAll();
    window.addEventListener('resize', onResize);
});
onUnmounted(() => {
    window.removeEventListener('resize', onResize);
    disposeAll();
});
// symbol 或 assetType 变化都要重取：同一代码在个股/ETF 下走的是不同行情接口。
watch(() => [props.symbol, props.assetType], () => { disposeAll(); loadAll(); });
</script>

<template>
    <div class="fp-wrap">
        <div v-if="loading" class="fp-loading">
            <i class="pi pi-spin pi-spinner"></i> 专业因子分析加载中...
        </div>

        <template v-else>
            <!-- ============ L1 · 技术面仪表盘 ============ -->
            <div v-if="dashboard" class="fp-block">
                <div class="fp-title"><i class="pi pi-compass text-blue-500"></i> 技术面仪表盘</div>

                <div class="fp-cards">
                    <!-- 均线排列：整行通栏（内容以状态标签 + 均线偏离小标签为主，横向铺开更易读） -->
                    <div class="fp-card fp-card-full" v-if="maState">
                        <div class="fp-card-h">均线排列</div>
                        <div class="fp-card-body-row">
                            <div class="fp-ma-state"
                                 :style="{color: (MA_STATE_STYLE[maState.state]||{}).color}">
                                {{ (MA_STATE_STYLE[maState.state]||{}).text }}
                                <span v-if="maState.bull_days > 0" class="fp-ma-days">
                                    (多头已 {{ maState.bull_days }} 日)
                                </span>
                            </div>
                            <div class="fp-ma-list">
                                <span v-for="(v, k) in maState.bias_pct" :key="k"
                                      class="fp-ma-item"
                                      :style="{color: Number(v) >= 0 ? '#d64545' : '#1f9d55'}">
                                    MA{{ k }} {{ Number(v) >= 0 ? '+' : '' }}{{ v }}%
                                </span>
                            </div>
                        </div>
                    </div>

                    <!-- 超买超卖热度 + 关键位：同一行左右并排 -->
                    <div class="fp-card" v-if="dashboard.heat">
                        <div class="fp-card-h">超买超卖热度</div>
                        <div ref="heatRef" class="fp-heat-chart"></div>
                        <div class="fp-heat-meta">
                            <span>RSI {{ dashboard.heat.rsi }}</span>
                            <span class="fp-tag" :style="{color: heatColor(dashboard.heat.heat)}">
                                {{ dashboard.heat.tag }}
                            </span>
                        </div>
                    </div>

                    <div class="fp-card" v-if="levels">
                        <div class="fp-card-h">关键位与动态止损（ATR 模型）</div>
                        <div class="fp-levels">
                            <div class="fp-lv">
                                <span class="fp-lv-k">当前价</span>
                                <span class="fp-lv-v">{{ levels.close }}</span>
                            </div>
                            <div class="fp-lv">
                                <span class="fp-lv-k">52周高</span>
                                <span class="fp-lv-v up">{{ levels.high_52w }}</span>
                            </div>
                            <div class="fp-lv">
                                <span class="fp-lv-k">52周低</span>
                                <span class="fp-lv-v down">{{ levels.low_52w }}</span>
                            </div>
                            <div class="fp-lv" v-if="levels.dense_zone">
                                <span class="fp-lv-k">成交密集区</span>
                                <span class="fp-lv-v">{{ levels.dense_zone[0] }} ~ {{ levels.dense_zone[1] }}</span>
                            </div>
                            <div class="fp-lv" v-if="levels.atr14">
                                <span class="fp-lv-k">ATR(14)</span>
                                <span class="fp-lv-v">{{ levels.atr14 }}</span>
                            </div>
                            <div class="fp-lv" v-if="levels.stop_loss_2atr">
                                <span class="fp-lv-k">止损参考 (2×ATR)</span>
                                <span class="fp-lv-v down">{{ levels.stop_loss_2atr }}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 动量-波动象限 + 主力阶段 -->
                <div class="fp-row2">
                    <div class="fp-card">
                        <div class="fp-card-h">动量 - 波动象限（近 60 日轨迹）</div>
                        <div ref="quadRef" class="fp-quad-chart"></div>
                        <div class="fp-quad-hint">
                            右上=强势低波(佳) · 左上=强势高波 · 右下=弱势低波 · 左下=弱势高波(险)
                        </div>
                    </div>
                    <div class="fp-card" v-if="phase && phase.segments.length">
                        <div class="fp-card-h">主力行为阶段（近 250 日）</div>
                        <div class="fp-phase-bar">
                            <span v-for="(seg, i) in phase.segments" :key="i"
                                  class="fp-phase-seg"
                                  :style="{flex: seg.days, background: phaseColor(seg.code)}"
                                  :title="`${seg.label} ${seg.start} ~ ${seg.end} (${seg.days}日)`"></span>
                        </div>
                        <div class="fp-phase-cur" v-if="phase.current">
                            当前：<b :style="{color: phaseColor(phase.current.code)}">{{ phase.current.label }}</b>
                            ，已持续 {{ phase.current.days }} 个交易日
                        </div>
                        <div class="fp-phase-legend">
                            <span v-for="(label, code) in phase.name_map" :key="code" class="fp-pl-item">
                                <i :style="{background: phaseColor(Number(code))}"></i>{{ label }}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- ============ L0 · 因子看板 ============ -->
            <div v-if="board && board.groups.length" class="fp-block">
                <div class="fp-title"><i class="pi pi-th-large text-blue-500"></i> 因子看板
                    <span class="fp-sub">共 {{ board.groups.reduce((s, g) => s + g.items.length, 0) }} 个技术因子 ·
                        截至 {{ board.asof }}</span>
                </div>

                <!-- 历史分位要有足够样本才有意义：新纳入日更的标的往往只落了一两天，
                     此时「历史分位」是 1 个点里的 100%，看着正常其实无效。 -->
                <div class="fp-note" v-if="historyShort">
                    <i class="pi pi-info-circle"></i>
                    该标的的因子历史仅 {{ board.history_days }} 个交易日，历史分位与因子走势曲线的参考价值有限
                    （因子按日累积，新纳入监控的标的从纳入日起逐日补齐）。
                </div>

                <div class="fp-groups">
                    <div v-for="g in board.groups" :key="g.key"
                         class="fp-group" :class="{active: activeGroup && activeGroup.key === g.key}"
                         @click="selectGroup(g)">
                        <div class="fp-group-h">
                            <span>{{ g.label }}</span>
                            <span class="fp-group-n">{{ g.items.length }}</span>
                        </div>
                        <div class="fp-group-desc">{{ g.desc }}</div>
                        <div class="fp-factor-list">
                            <div v-for="it in g.items" :key="it.field" class="fp-factor">
                                <div class="fp-factor-top">
                                    <span class="fp-factor-name" :title="it.description">{{ it.name }}</span>
                                    <span class="fp-factor-val">{{ fmtValue(it.field, it.value) }}</span>
                                </div>
                                <div class="fp-pct-track">
                                    <div class="fp-pct-fill"
                                         :style="{width: Math.min(100, it.percentile ?? 0) + '%',
                                                  background: pctColor(it.percentile, it.lower_is_better)}"></div>
                                </div>
                                <div class="fp-factor-pct">
                                    历史分位 {{ it.percentile == null ? '—' : it.percentile }}%
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 52周区间条 -->
                <div v-if="range52" class="fp-range">
                    <span class="fp-range-k">52周区间位置</span>
                    <div class="fp-range-bar">
                        <div class="fp-range-fill"
                             :style="{width: Math.min(100, range52.position ?? 0) + '%'}"></div>
                        <span class="fp-range-mark"
                              :style="{left: Math.min(100, range52.position ?? 0) + '%'}"></span>
                    </div>
                    <span class="fp-range-v">
                        {{ range52.low }} ~ {{ range52.high }}
                        <b>（{{ Number(range52.position).toFixed(1) }}%）</b>
                    </span>
                </div>

                <!-- 选中分组的因子曲线 -->
                <div class="fp-series">
                    <div class="fp-series-h">
                        因子走势（近 250 日）：
                        <b>{{ activeGroup ? activeGroup.label : '' }}</b>
                    </div>
                    <div ref="seriesRef" class="fp-series-chart"></div>
                </div>
            </div>

            <!-- ============ L2 · 雷达 + 横向对比（个股=行业 / ETF=全站 ETF） ============ -->
            <div class="fp-block" v-if="radar || peerRank">
                <div class="fp-title"><i class="pi pi-chart-pie text-blue-500"></i> 因子雷达与横向对比</div>
                <div class="fp-row2">
                    <div class="fp-card" v-if="radar && radar.axes.length">
                        <div class="fp-card-h">核心因子雷达（0~100 分位，反向因子已翻转）</div>
                        <div ref="radarRef" class="fp-radar-chart"></div>
                    </div>
                    <div class="fp-card" v-if="peerRank && peerRank.rows.length">
                        <div class="fp-card-h">
                            {{ peerTitle }}
                            <span class="fp-sub">（样本 {{ peerRank.peer_count }} 只）</span>
                        </div>
                        <div class="fp-rank-list">
                            <div v-for="r in peerRank.rows" :key="r.field" class="fp-rank-row">
                                <span class="fp-rank-name">{{ r.name }}</span>
                                <span class="fp-rank-val">{{ fmtValue(r.field, r.value) }}</span>
                                <span class="fp-rank-pct"
                                      :style="{color: betterPct(r) >= 70 ? '#d64545' : (betterPct(r) <= 30 ? '#1f9d55' : '#8a8a8a')}">
                                    优于同类 {{ betterPct(r).toFixed(0) }}%
                                </span>
                            </div>
                        </div>
                        <div class="fp-sub" style="margin-top:8px">
                            {{ peerNote }}
                        </div>
                    </div>
                </div>
            </div>

            <div v-if="!loading && !board && !dashboard" class="fp-empty">
                暂无因子数据（该标的可能未纳入因子计算，或因子任务尚未运行）
            </div>
        </template>
    </div>
</template>

<style scoped>
/* 防横向溢出：本面板内所有文本元素一律不允许把父容器撑宽。
   起因：`.fp-group-desc` / `.fp-card-h` 这类长中文串在窄卡片里可能没有换行机会，
   scrollWidth 会略大于 clientWidth，而 overflow-x 默认 visible
   会让多出的几个像素"画"到卡片外面 —— 右列卡片尤其容易把整页顶出横向滚动条。
   这里统一加 min-width:0 + overflow-wrap + overflow:hidden，
   三管齐下：能换行就换行，换不了就裁掉，绝不把父容器顶宽。 */
.fp-wrap { margin-top: 1.25rem; overflow-x: clip; }
.fp-block, .fp-card, .fp-group, .fp-series, .fp-range, .fp-row2, .fp-cards, .fp-groups { min-width: 0; }
.fp-title, .fp-sub, .fp-card-h, .fp-group-h, .fp-group-desc,
.fp-factor, .fp-factor-top, .fp-factor-name, .fp-factor-val, .fp-factor-pct,
.fp-ma-state, .fp-ma-list, .fp-ma-item, .fp-lv, .fp-lv-k, .fp-lv-v,
.fp-range-k, .fp-range-v, .fp-phase-cur, .fp-phase-legend, .fp-pl-item,
.fp-rank-row, .fp-rank-name, .fp-rank-val, .fp-rank-pct, .fp-note {
    min-width: 0;
    overflow-wrap: anywhere;
    overflow: hidden;
}
.fp-loading { padding: 1rem 0; color: #8a8a8a; font-size: 13px; }
.fp-empty { padding: 1.5rem 0; color: #8a8a8a; font-size: 13px; text-align: center; }
/* 提示条（因子历史不足等）：淡底 + 左侧图标，窄屏不撑宽（已并入上方防溢出选择器） */
.fp-note {
    display: flex; align-items: baseline; gap: 6px;
    font-size: 12px; color: #8a6d3b;
    background: #fdf6e3; border: 0.5px solid #f0e0b8;
    border-radius: 8px; padding: 8px 10px; margin: 6px 0 10px;
}
.fp-block { margin-bottom: 1.5rem; }
.fp-title { font-size: 15px; font-weight: 500; margin-bottom: 4px; display: flex; align-items: baseline; gap: 8px; }
.fp-sub { font-size: 11px; font-weight: 400; color: #9a9a9a; }

/* 仪表盘卡片：两列布局。
   第 1 行「均线排列」通栏（.fp-card-full），第 2 行「超买超卖热度 | 关键位与动态止损」并排。 */
.fp-cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 10px; }
.fp-card { background: #fff; border: 0.5px solid rgba(0,0,0,0.1); border-radius: 12px; padding: 12px 14px; }
.fp-card-full { grid-column: 1 / -1; }
/* 均线排列通栏后，状态标签与均线偏离标签改为同一行排布，避免整行只有一小块内容 */
.fp-card-body-row { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 18px; }
.fp-card-h { font-size: 12px; color: #6b6b6b; margin-bottom: 8px; }

/* 通栏卡里与均线标签同排（.fp-card-body-row），故不需要单独的 margin-bottom */
.fp-ma-state { font-size: 18px; font-weight: 500; }
.fp-ma-days { font-size: 12px; font-weight: 400; color: #8a8a8a; }
.fp-ma-list { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; }
/* 均线偏离标签：允许换行（标签本身很短，换行比裁掉更友好） */
.fp-ma-item { white-space: normal; }

.fp-heat-chart { width: 100%; height: 92px; }
.fp-heat-meta { display: flex; justify-content: center; gap: 10px; font-size: 11px; color: #6b6b6b; margin-top: -6px; }
.fp-tag { font-weight: 500; }

/* 关键位现在只占半行宽，列宽随之自适应：足够宽时 3 列，变窄自动降到 2 列 */
.fp-levels { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px 14px; }
.fp-lv { display: flex; flex-direction: column; }
.fp-lv-k { font-size: 11px; color: #9a9a9a; }
.fp-lv-v { font-size: 14px; font-weight: 500; }
.fp-lv-v.up { color: #d64545; }
.fp-lv-v.down { color: #1f9d55; }

.fp-row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
/* 两列行里只剩一张卡时让它铺满整行。
   ⚠️ 真实场景有两个：ETF 没有 `main_force_behavior_phase` 因子 → 「主力行为阶段」不渲染，
   于是「动量-波动象限」右侧空掉半行；标的没有同行业样本时「行业内排名」不渲染，
   雷达图同理。用 :only-child 一次覆盖，比在模板里给每个卡片各挂一个条件类更不容易漏。
   注意 :only-child 只看**元素**子节点，两处 .fp-row2 里除卡片外没有别的元素，成立。 */
.fp-row2 > .fp-card:only-child { grid-column: 1 / -1; }
.fp-quad-chart { width: 100%; height: 200px; }
.fp-quad-hint { font-size: 10px; color: #a0a0a0; margin-top: 4px; }

.fp-phase-bar { display: flex; height: 18px; border-radius: 4px; overflow: hidden; margin-bottom: 8px; }
.fp-phase-seg { min-width: 2px; }
.fp-phase-cur { font-size: 12px; color: #4a4a4a; margin-bottom: 8px; }
.fp-phase-legend { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 10px; color: #8a8a8a; }
.fp-pl-item { display: inline-flex; align-items: center; gap: 4px; }
.fp-pl-item i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }

.fp-groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-top: 10px; }
.fp-group { background: #fff; border: 0.5px solid rgba(0,0,0,0.1); border-radius: 12px; padding: 12px 14px; cursor: pointer; transition: border-color .15s, box-shadow .15s; }
.fp-group:hover { border-color: rgba(0,0,0,0.25); }
.fp-group.active { border-color: #d64545; box-shadow: 0 0 0 1px rgba(214,69,69,0.25); }
.fp-group-h { display: flex; justify-content: space-between; font-size: 13px; font-weight: 500; gap: 6px; }
.fp-group-h > span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fp-group-n { color: #b0b0b0; font-weight: 400; flex: 0 0 auto; }
/* 描述文案最长可达「单位风险下的趋势质量（去波动后的动量）」这类 18+ 字中文串，
   窄卡片里既放不下又会把卡片顶宽 —— 按 2 行截断，末行省略号。 */
.fp-group-desc {
    font-size: 10px; color: #9a9a9a; margin: 2px 0 10px;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    overflow: hidden; line-height: 1.4;
}
.fp-factor-list { display: flex; flex-direction: column; gap: 9px; }
.fp-factor-top { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 3px; }
.fp-factor-name { color: #4a4a4a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fp-factor-val { font-weight: 500; font-variant-numeric: tabular-nums; }
.fp-pct-track { height: 5px; border-radius: 3px; background: #f0f0f0; overflow: hidden; }
.fp-pct-fill { height: 100%; border-radius: 3px; transition: width .3s; }
.fp-factor-pct { font-size: 10px; color: #b0b0b0; margin-top: 2px; }

.fp-range { display: flex; align-items: center; gap: 12px; margin-top: 14px; font-size: 12px; flex-wrap: wrap; }
.fp-range-k { color: #6b6b6b; }
.fp-range-bar { position: relative; flex: 1 1 120px; min-width: 100px; height: 8px; border-radius: 4px; background: linear-gradient(90deg, #cfe8d5, #f0e2cf, #f3cfcf); }
.fp-range-fill { height: 100%; border-radius: 4px; background: rgba(0,0,0,0.06); }
.fp-range-mark { position: absolute; top: -3px; width: 2px; height: 14px; background: #333; border-radius: 1px; transform: translateX(-1px); }
.fp-range-v { color: #6b6b6b; }
.fp-range-v b { color: #333; }

.fp-series { margin-top: 14px; }
.fp-series-h { font-size: 12px; color: #6b6b6b; margin-bottom: 6px; }
.fp-series-chart { width: 100%; height: 220px; }

.fp-radar-chart { width: 100%; height: 260px; }
.fp-rank-list { display: flex; flex-direction: column; gap: 8px; }
.fp-rank-row { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; align-items: center; font-size: 12px; border-bottom: 0.5px solid rgba(0,0,0,0.05); padding-bottom: 6px; }
.fp-rank-name { color: #4a4a4a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fp-rank-val { font-variant-numeric: tabular-nums; color: #333; }
.fp-rank-pct { font-weight: 500; min-width: 52px; text-align: right; }
</style>
