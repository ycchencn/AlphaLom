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
import Button from 'primevue/button';
import Dialog from 'primevue/dialog';
import SelectButton from 'primevue/selectbutton';
import {useNotification} from '@/composables/useNotification';
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
    // 渲染哪些区块（个股详情页按 tab 拆分后传入）：
    //   'all'（默认）—— 仪表盘 + 因子看板 + 雷达/横向对比（ETF 详情页用，行为不变）；
    //   'dashboard'  —— 只渲染「技术面仪表盘」，只请求 dashboard 一个接口（技术面分析 tab）；
    //   'factors'    —— 只渲染「因子看板 + 因子雷达与横向对比」，只请求对应接口（因子分析 tab）。
    // ⚠️ 两个模式各挂一个实例时，请求互不重叠（dashboard 1 个 / factors 3 个），
    //    合起来正好是原来一个实例的 4 个接口，不会多打。
    mode: {type: String, default: 'all'},
    // 宿主容器是否可见（由父页 tab 切换驱动）。⚠️ 容器在 v-show 里时，非激活状态
    // display:none、clientWidth=0，此时 echarts.init 会得到 0x0 画布（图是空的）。
    // 父页在 tab 变可见时把 active 置 true，这里重绘一次图表；默认 true 兼容旧用法。
    active: {type: Boolean, default: true},
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

// ==================== 一键重算因子 ====================
// 后端只保证「已入队」（队列 prefetch=1 串行，单只 full 重算约 1 分钟），
// 完成后要靠轮询 recalc_status 让看板自动刷新 —— 否则用户点完还是看到旧值。
// ⚠️ 轮询定时器必须在 unmount / 换标的时清掉，否则会在离开页面后继续打接口。
const recalcVisible = ref(false);
const recalcSubmitting = ref(false);
const recalcFull = ref(false);
const recalcRunning = ref(false);
const recalcStatus = ref(null);
let pollTimer = null;
const POLL_INTERVAL_MS = 5000;
// 轮询上限：约 6 分钟。full 重算实测 ~1 分钟，队列积压时才可能更久；
// 到点仍未完成就停止轮询并提示「可稍后刷新」，不要无限打接口。
const POLL_MAX_TIMES = 72;

const {showSuccess, showInfo, showError} = useNotification();

const recalcTarget = computed(() => `${props.symbol}（${props.assetType === 'etf' ? 'ETF' : '个股'}）`);

// 重算范围选项。默认选「只算最新一天」——它是幂等且不改历史的操作，
// 用户点「重算」的直觉预期也是「刷新一下数值」；整段重写会清空历史，属高风险，
// 放在需要主动切换的第二项而不是默认项上。
const recalcScopeOptions = [
    { label: '仅最新交易日', value: false },
    { label: '整段重写（3年）', value: true },
];

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

async function fetchRecalcStatus() {
    try {
        const {data} = await axios.get(`/api/v1/factor/stock/${props.symbol}/recalc_status`);
        return data?.data ?? data;
    } catch (e) {
        return null;
    }
}

function startPolling() {
    stopPolling();
    let times = 0;
    pollTimer = setInterval(async () => {
        times += 1;
        const st = await fetchRecalcStatus();
        if (st) recalcStatus.value = st;
        // 完成判定由后端给出（库里的 update_time 是否晚于入队时刻）
        if (st?.done) {
            stopPolling();
            recalcRunning.value = false;
            showSuccess('因子重算完成，已刷新看板');
            await loadAll();
            return;
        }
        if (times >= POLL_MAX_TIMES) {
            stopPolling();
            recalcRunning.value = false;
            showInfo('重算仍在后台进行，稍后手动刷新本页即可看到结果');
        }
    }, POLL_INTERVAL_MS);
}

async function submitRecalc() {
    if (recalcSubmitting.value) return;
    recalcSubmitting.value = true;
    try {
        await axios.put(`/api/v1/factor/stock/${props.symbol}/recalc`, {
            asset_type: props.assetType,
            full: recalcFull.value,
        });
        recalcVisible.value = false;
        recalcRunning.value = true;
        showInfo(recalcFull.value ? '已提交整段重算（约 1 分钟）' : '已提交重算最新交易日');
        startPolling();
    } catch (e) {
        const status = e?.response?.status;
        // 429 = 冷却期内重复触发（后端已用 Redis NX 做互斥），把等待秒数如实回显
        if (status === 429) {
            showError(e?.response?.data?.detail || '触发过于频繁，请稍后再试');
        } else if (e?.isSpaFallback) {
            showError('后端尚未部署该接口，请重启后端服务');
        } else {
            showError(e?.response?.data?.detail || '重算任务提交失败，请重试');
        }
    } finally {
        recalcSubmitting.value = false;
    }
}

// 页面加载时先探一次：若上一次重算还没跑完，按钮要显示「计算中」而不是「可点」。
// ⚠️ 只在渲染因子看板的实例上探（dashboard 实例不显示按钮，探了纯属白打接口）。
async function checkRecalcState() {
    if (!wantsFactors.value) return;
    const st = await fetchRecalcStatus();
    if (!st) return;
    recalcStatus.value = st;
    if (st.dispatched_at && !st.done) {
        recalcRunning.value = true;
        startPolling();
    }
}

function openRecalc() {
    recalcVisible.value = true;
}

// 图表实例统一管理，卸载时销毁
function disposeAll() {
    charts.forEach((c) => c && c.dispose && c.dispose());
    charts = [];
}

// ==================== 取数 ====================
// mode 控制只取本区块需要的接口，避免两个 tab 各挂一个实例时重复请求：
//   dashboard 模式只需 dashboard；factors 模式只需 board / radar / industry_rank。
async function loadAll() {
    if (!props.symbol) return;
    loading.value = true;
    const base = `/api/v1/factor/stock/${props.symbol}`;
    const at = props.assetType;
    const wantsDashboard = props.mode !== 'factors';
    const wantsFactors = props.mode !== 'dashboard';
    // ⚠️ 用 allSettled：单个接口失败（如 ETF 无行业样本导致横向对比 404）不应影响其它卡片。
    // asset_type 只传给**真的按它分流**的两个接口（dashboard / industry_rank），
    // 看板与雷达按 ticker 直接查因子表，个股 ETF 同一套口径，多传反而像是有差别。
    const [b, d, r, ir] = await Promise.allSettled([
        wantsFactors ? axios.get(base) : Promise.resolve(null),
        wantsDashboard ? axios.get(`${base}/dashboard`, {params: {asset_type: at}}) : Promise.resolve(null),
        wantsFactors ? axios.get(`${base}/radar`) : Promise.resolve(null),
        wantsFactors ? axios.get(`${base}/industry_rank`, {params: {asset_type: at}}) : Promise.resolve(null),
    ]);
    board.value = b.status === 'fulfilled' ? (b.value?.data?.data ?? b.value?.data) : null;
    dashboard.value = d.status === 'fulfilled' ? (d.value?.data?.data ?? d.value?.data) : null;
    radar.value = r.status === 'fulfilled' ? (r.value?.data?.data ?? r.value?.data) : null;
    peerRank.value = ir.status === 'fulfilled' ? (ir.value?.data?.data ?? ir.value?.data) : null;
    loading.value = false;

    // 默认展开第一个分组并画曲线（仅 factors 模式有看板数据）
    const firstGroup = board.value?.groups?.[0];
    if (firstGroup) {
        await nextTick();
        selectGroup(firstGroup);
    }
    // ⚠️ 容器在 v-show 里且当前非激活时（display:none、clientWidth=0），
    // echarts.init 会得到 0x0 画布并告警（表现为「图是空的」）。此时**跳过渲染**，
    // 数据已取好，等父页把 active 置 true（切到本 tab）时由 active watch 统一重绘。
    if (!props.active) return;
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
    // 容器非激活时跳过渲染（0x0 画布问题，见 loadAll 注释），由 active watch 重绘
    if (!props.active) return;
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
    // ETF 市盈率：估值倍数，2 位小数足够
    if (field === 'etf_pe_ttm') return v.toFixed(2);
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

/** 本实例是否渲染因子看板区块（与 loadAll 里请求哪些接口的口径保持一致）。 */
const wantsFactors = computed(() => props.mode !== 'dashboard');

/**
 * 52 周区间位置（位置条用）。
 *
 * ⚠️ 数据来源是**仪表盘的 key_levels**，不是因子看板的 range_52week：
 *    位置条的宿主已从「因子分析 tab」搬到「技术面分析 tab」，而后者只挂
 *    mode='dashboard' 的实例、只请求 dashboard 一个接口，根本不取 board ——
 *    继续读 board.range_52week 的话，条子在任何情况下都渲染不出来。
 *    换成 key_levels 还有个额外好处：条上的最高/最低与紧邻的「关键位与动态止损」
 *    卡片里的 52周高/52周低**同源同值**（同一份日线 df 算出来的），不会出现
 *    「上面写 12.30、下面条上写 12.10」这种自相矛盾。
 *
 * 位置 = (现价 - 52周最低) / (52周最高 - 52周最低) × 100。
 * 在这里一次钳到 0~100 并按 1 位小数定稿：原来模板里只在 width 上 Math.min(100)、
 * 文案却打原值，越界时条子与百分比会互相打架（除权、异常行情下确实会越界）。
 * 高 == 低（区间退化成一个点，如刚上市/长期停牌）时位置没有意义 → 返回 null，
 * 整张卡不渲染，而不是画一条永远指在 0% 的假条。
 */
const range52 = computed(() => {
    const lv = levels.value;
    if (!lv) return null;
    const low = Number(lv.low_52w);
    const high = Number(lv.high_52w);
    const close = Number(lv.close);
    if (![low, high, close].every(Number.isFinite) || high <= low) return null;
    const pct = Math.min(100, Math.max(0, ((close - low) / (high - low)) * 100));
    return {low, high, close, position: Math.round(pct * 10) / 10};
});

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
    checkRecalcState();
    window.addEventListener('resize', onResize);
});
onUnmounted(() => {
    window.removeEventListener('resize', onResize);
    // ⚠️ 轮询必须随组件一起停：否则在详情页之间来回切换时会留下一串后台定时器，
    // 持续打 recalc_status 且回调里 loadAll() 会把**别的标的**的数据写进当前组件。
    stopPolling();
    recalcRunning.value = false;
    disposeAll();
});
// symbol 或 assetType 变化都要重取：同一代码在个股/ETF 下走的是不同行情接口。
watch(() => [props.symbol, props.assetType], () => {
    // 换标的 = 上一个标的的「重算中」状态与轮询都不再适用
    stopPolling();
    recalcRunning.value = false;
    recalcStatus.value = null;
    disposeAll();
    loadAll();
    checkRecalcState();
});
// 容器从隐藏（v-show 非激活）变可见时，之前 0x0 画布上的图要重画：
// 数据早已取好（组件常驻），只差尺寸到位。重走渲染函数即可（内部会 getInstanceByDom + setOption + resize）。
watch(() => props.active, (v) => {
    if (!v) return;
    nextTick(() => {
        renderRadar();
        renderQuadrant();
        renderHeat();
        renderSeries();
    });
});
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

                    <!-- 52周区间位置：整行通栏，紧跟在「均线排列」下方 —— 两者合起来回答
                         「现价处在什么位置」（均线说的是相对均线，区间条说的是相对近一年高低点）。
                         最高/最低与下面「关键位与动态止损」卡片里的 52周高低同源同值。 -->
                    <div class="fp-card fp-card-full" v-if="range52">
                        <div class="fp-card-h">52周区间位置 <b>现价位于 {{ range52.position.toFixed(1) }}%</b></div>
                        <div class="fp-range">
                            <div class="fp-range-bar">
                                <div class="fp-range-fill"
                                     :style="{width: range52.position + '%'}"></div>
                                <span class="fp-range-mark"
                                      :style="{left: range52.position + '%'}"></span>
                            </div>
                            <span class="fp-range-v">
                                最低 {{ range52.low }} ~ 最高 {{ range52.high }}
                            </span>
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
                    <span class="fp-sub">共 {{ board.groups.reduce((s, g) => s + g.items.length, 0) }} 个因子 ·
                        截至 {{ board.asof }}</span>
                    <!-- ⚠️ 只挂在「因子看板」这一块（mode='factors' / 'all'），不挂到
                         mode='dashboard' 的实例上：那是技术面分析 tab，不需要重算入口。
                         两个实例同时挂着时按钮只出现一次，不会让用户以为是两个功能。 -->
                    <Button size="small" severity="secondary" outlined class="fp-recalc-btn"
                            :loading="recalcRunning" :disabled="recalcRunning"
                            icon="pi pi-refresh" label="重算因子" @click="openRecalc"/>
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

                <!-- 选中分组的因子曲线 -->
                <div class="fp-series">
                    <div class="fp-series-h">
                        因子走势（近 250 日）：
                        <b>{{ activeGroup ? activeGroup.label : '' }}</b>
                    </div>
                    <div ref="seriesRef" class="fp-series-chart"></div>
                </div>
            </div>

            <!-- 因子尚未入库（新入池标的）时上面的看板块整块不渲染，这里补一个空态 + 重算入口。
                 没有它，用户看到的只是一句「暂无因子数据」，不知道自己能重算。
                 ⚠️ 必须与看板块**同级**：放进看板块内部会变成它的子节点，
                 v-else 挂在别的元素后 Vue 编译期直接报错。 -->
            <div v-else-if="wantsFactors" class="fp-block">
                <div class="fp-title"><i class="pi pi-th-large text-blue-500"></i> 因子看板</div>
                <div class="fp-note fp-note-empty">
                    <i class="pi pi-info-circle"></i>
                    该标的暂无因子数据（可能未纳入因子计算，或因子任务尚未运行），可手动触发一次重算。
                    <Button size="small" severity="secondary" outlined class="fp-recalc-btn"
                            :loading="recalcRunning" :disabled="recalcRunning"
                            icon="pi pi-refresh" label="一键重算" @click="openRecalc"/>
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

            <!-- ⚠️ 因子模式（wantsFactors）下「空」已经由上面的「因子看板空态块」表达了，
                 这里只在 dashboard 模式（技术面 tab、无看板区块）兜底，否则两条文案会同时出现。 -->
            <div v-if="!loading && !board && !dashboard && !wantsFactors" class="fp-empty">
                暂无因子数据（该标的可能未纳入因子计算，或因子任务尚未运行）
            </div>
        </template>

        <!-- 一键重算确认框。full 模式会先清空该标的的全部历史因子再整段重写，
             这是有风险的操作（行情取不到时会把已有数据清空），所以必须显式确认。 -->
        <Dialog v-model:visible="recalcVisible" modal header="重算因子"
                :style="{ width: '30rem' }">
            <div class="flex flex-col gap-3">
                <div>
                    将重新计算 <b>{{ recalcTarget }}</b> 的全部技术因子。
                    当前已积累 <b>{{ recalcStatus?.history_days ?? 0 }}</b> 个交易日
                    的因子历史。
                </div>
                <div class="flex flex-col gap-1">
                    <label class="text-sm font-medium">重算范围</label>
                    <SelectButton v-model="recalcFull" :options="recalcScopeOptions"
                                 optionLabel="label" optionValue="value" :allowEmpty="false"/>
                </div>
                <div class="del-warn">
                    <template v-if="recalcFull">
                        ⚠️ 整段重算会<b>先删除该标的已有的全部因子历史</b>，再按近 3 年行情重写
                        （约 1 分钟）。若上游行情取不到，历史会被清空且不恢复。
                    </template>
                    <template v-else>
                        仅重算<b>最新一个交易日</b>，已落库的历史不动（约几秒）。
                        适合行情刚更新、想刷新当天数值。
                    </template>
                </div>
                <div class="text-xs text-gray-500">
                    任务提交后进入后台队列串行执行，完成后本页会自动刷新；同一标的 5 分钟内只能触发一次。
                </div>
            </div>
            <template #footer>
                <div class="flex justify-end gap-2">
                    <Button label="取消" severity="secondary" text
                            :disabled="recalcSubmitting" @click="recalcVisible = false"/>
                    <Button :label="recalcFull ? '确认整段重算' : '确认重算'"
                            :icon="recalcFull ? 'pi pi-exclamation-triangle' : 'pi pi-refresh'"
                            :severity="recalcFull ? 'danger' : 'primary'"
                            :loading="recalcSubmitting" @click="submitRecalc"/>
                </div>
            </template>
        </Dialog>
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
.fp-range-v, .fp-phase-cur, .fp-phase-legend, .fp-pl-item,
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
/* 重算按钮推到标题行最右。⚠️ 用 margin-left:auto 而不是给 .fp-title 加 justify-content:
   .fp-title 还被另外两个区块（仪表盘 / 雷达）复用，push 到右边会改变它们的排版。 */
.fp-recalc-btn { margin-left: auto; flex: 0 0 auto; }
/* 因子看板空态块：复用 .fp-note 的淡底样式，按钮与文字同一行靠 flex 撑开 */
.fp-note-empty { align-items: center; }
.fp-note-empty .fp-recalc-btn { margin-left: auto; }
/* 重算确认框里的高风险提示条（与 UserManage / ApiKeyManage / PortfolioView 的 .del-warn 同款） */
.del-warn {
    background: var(--red-50, #fef2f2);
    border-left: 3px solid var(--red-500, #ef4444);
    padding: 0.6rem 0.75rem;
    font-size: 0.9rem;
    line-height: 1.5;
}
.fp-sub { font-size: 11px; font-weight: 400; color: #9a9a9a; }

/* 仪表盘卡片：两列布局。
   第 1 行「均线排列」通栏、第 2 行「52 周区间位置」通栏（都是 .fp-card-full），
   第 3 行「超买超卖热度 | 关键位与动态止损」并排。 */
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

.fp-range { display: flex; align-items: center; gap: 12px; font-size: 12px; flex-wrap: wrap; }
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
