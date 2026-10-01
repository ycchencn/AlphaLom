<script setup>
/**
 * ETF 轮动分析页签。
 *
 * 数据链路：GET /etf_rotation（池内每只现拉日线 + 逐日回测），参数可调。
 *
 * ⚠️ 四条必须遵守的约定（都踩过）：
 * 1. **图表懒初始化**：图表容器在 v-if 里，首屏（还没分析出结果）ref 是 null，
 *    此时 echarts.init(null) 会在 echarts 内部抛异常并**打断整个组件的挂载链**，
 *    表现是「所有数据都不渲染」，极易误判成后端问题。必须等数据到位再 init。
 * 2. **notMerge=true**：切换参数/池成员后 series 数量会变，合并模式下残留的旧 series
 *    会继续画在图上（尤其基准被去掉后仍显示旧曲线）。
 * 3. **涨红跌绿**（A 股习惯），颜色统一取自 utils/echartsTheme。
 * 4. **持仓时间带要压缩连续段**：3 年周频调仓有 150 段，30 只标的直接渲染就是 4500 个
 *    DOM 节点。做 run-length 合并后通常只剩几十段。
 */
import {computed, nextTick, onBeforeUnmount, onMounted, ref} from 'vue';
import axios from 'axios';
import * as echarts from 'echarts';
import {COLORS, FONT, LINE, PALETTE, areaGradient, axisLabel, splitLine, tooltipBase} from '@/utils/echartsTheme';
import {useNotification} from '@/composables/useNotification';
import EtfSearchDialog from '@/components/EtfSearchDialog.vue';

const {showSuccess, showError} = useNotification();

const pool = ref([]);
const poolLimit = ref(30);
const loadingPool = ref(false);
const analyzing = ref(false);
const result = ref(null);
const errorMsg = ref('');

const modalVisible = ref(false);
const addingSymbol = ref('');
const searchDialog = ref(null);

// 参数：默认「20 日风险调整动量 / 周频调仓 / 持有 3 只 / 开绝对动量过滤」
const params = ref({
    lookback: 20,
    rebalance_days: 5,
    top_n: 3,
    abs_filter: true,
    cost: 0.0005,
    window_days: 1095,
});

const rsSymbol = ref('');

const navRef = ref(null);
const heatRef = ref(null);
const rsRef = ref(null);
let navChart = null;
let heatChart = null;
let rsChart = null;

const watchedSymbols = computed(() => pool.value.map(it => String(it.symbol)));

function nameOf(symbol) {
    const hit = pool.value.find(it => it.symbol === symbol);
    return hit?.name || symbol;
}

function pct(v, digits = 2) {
    if (v === null || v === undefined || !isFinite(v)) return '--';
    return `${(v * 100).toFixed(digits)}%`;
}

function toneOf(v) {
    if (v === null || v === undefined || !isFinite(v)) return '';
    if (v > 0) return 'is-up';
    if (v < 0) return 'is-down';
    return '';
}

// ==================== 池管理 ====================

async function loadPool() {
    loadingPool.value = true;
    try {
        const r = await axios.get('/api/v1/etf_rotation_pool');
        pool.value = Array.isArray(r.data?.items) ? r.data.items : [];
        if (r.data?.limit) poolLimit.value = r.data.limit;
    } catch (e) {
        pool.value = [];
    } finally {
        loadingPool.value = false;
    }
}

function openAdd() {
    modalVisible.value = true;
    searchDialog.value?.reset();
}

async function addToPool({symbol, name}) {
    addingSymbol.value = symbol;
    try {
        await axios.post('/api/v1/etf_rotation_pool', {symbol, name: name || null});
        showSuccess(`已加入轮动池 ${name || symbol}`);
        await loadPool();
        await runAnalysis();
    } catch (e) {
        showError(e.response?.data?.detail || '添加失败，请重试');
    } finally {
        addingSymbol.value = '';
    }
}

async function removeFromPool(symbol) {
    try {
        await axios.delete(`/api/v1/etf_rotation_pool/${encodeURIComponent(symbol)}`);
        showSuccess(`已移出轮动池 ${symbol}`);
        if (rsSymbol.value === symbol) rsSymbol.value = '';
        await loadPool();
        if (pool.value.length >= 2) await runAnalysis();
        else result.value = null;   // 不足 2 只时结果无意义，直接清空（避免展示过期曲线）
    } catch (e) {
        showError(e.response?.data?.detail || '移除失败，请重试');
    }
}

// ==================== 轮动分析 ====================

async function runAnalysis() {
    if (pool.value.length < 2) {
        result.value = null;
        errorMsg.value = '';
        return;
    }
    analyzing.value = true;
    errorMsg.value = '';
    try {
        const r = await axios.get('/api/v1/etf_rotation', {
            params: {
                lookback: params.value.lookback,
                rebalance_days: params.value.rebalance_days,
                top_n: params.value.top_n,
                abs_filter: params.value.abs_filter,
                cost: params.value.cost,
                window_days: params.value.window_days,
            },
        });
        result.value = r.data;
        // 默认选中排名第一的标的画 RS 曲线
        const first = (r.data?.ranking || []).find(it => !it.missing);
        rsSymbol.value = first?.symbol || '';
        await nextTick();
        renderNav();
        renderHeatmap();
        renderRs();
    } catch (e) {
        result.value = null;
        errorMsg.value = e.response?.data?.detail || '轮动分析失败，请稍后重试';
    } finally {
        analyzing.value = false;
    }
}

function resetParams() {
    params.value = {lookback: 20, rebalance_days: 5, top_n: 3, abs_filter: true, cost: 0.0005, window_days: 1095};
    runAnalysis();
}

// ==================== 指标与排名 ====================

const kpis = computed(() => {
    const m = result.value?.metrics;
    if (!m) return [];
    return [
        {label: '总收益', value: pct(m.total_return), tone: toneOf(m.total_return)},
        {label: '年化收益', value: pct(m.annual_return), tone: toneOf(m.annual_return)},
        {label: '夏普', value: m.sharpe != null ? m.sharpe.toFixed(2) : '--', tone: toneOf(m.sharpe)},
        {label: '最大回撤', value: pct(m.max_drawdown), tone: 'is-down'},
        {label: 'Calmar', value: m.calmar != null ? m.calmar.toFixed(2) : '--', tone: toneOf(m.calmar)},
        {label: '胜率', value: pct(m.win_rate), tone: ''},
    ];
});

/**
 * 判「策略 vs 基准」的优劣。
 *
 * ⚠️ 三个指标都是**数值越大越好** —— 回撤是负数，-31% > -33% 表示策略回撤更小（更好）。
 * 所以统一用 `m - b` 的正负判优劣。这里曾经把回撤写成 `b - m`，结果「策略回撤更小」
 * 被显示成「策略更差」：负值指标最容易把方向写反，而且图上看不出异常。
 */
function verdict(delta) {
    if (!isFinite(delta)) return 'same';
    if (delta > 1e-9) return 'better';
    if (delta < -1e-9) return 'worse';
    return 'same';
}

const benchCompare = computed(() => {
    const m = result.value?.metrics;
    const b = result.value?.benchmark_metrics;
    if (!m || !b) return null;
    return [
        {label: '总收益', strategy: pct(m.total_return), bench: pct(b.total_return),
         verdict: verdict(m.total_return - b.total_return)},
        {label: '夏普', strategy: m.sharpe?.toFixed(2) ?? '--', bench: b.sharpe?.toFixed(2) ?? '--',
         verdict: verdict((m.sharpe ?? 0) - (b.sharpe ?? 0))},
        {label: '最大回撤', strategy: pct(m.max_drawdown), bench: pct(b.max_drawdown),
         verdict: verdict(m.max_drawdown - b.max_drawdown)},
    ];
});

// 排名条的宽度：以池内最大 |score| 为基准，负数也能看出相对强弱
const scoreScale = computed(() => {
    const vals = (result.value?.ranking || []).map(it => Math.abs(it.score || 0));
    return Math.max(...vals, 0.0001);
});

const ranking = computed(() => result.value?.ranking || []);

// ==================== 持仓时间带（连续段压缩） ====================

const holdingRows = computed(() => {
    const hs = result.value?.holdings || [];
    const syms = result.value?.meta?.usable || [];
    if (!hs.length || !syms.length) return [];
    return syms.map(sym => {
        const flags = hs.map(h => h.symbols.includes(sym));
        return {symbol: sym, name: nameOf(sym), segs: compress(flags)};
    });
});

function compress(flags) {
    const out = [];
    if (!flags.length) return out;
    let cur = flags[0];
    let len = 1;
    for (let i = 1; i < flags.length; i++) {
        if (flags[i] === cur) {
            len += 1;
        } else {
            out.push({held: cur, len});
            cur = flags[i];
            len = 1;
        }
    }
    out.push({held: cur, len});
    return out;
}

const holdingSegTotal = computed(() => {
    const first = holdingRows.value[0];
    return first ? first.segs.reduce((a, s) => a + s.len, 0) : 0;
});

const holdingSummary = computed(() => {
    const hs = result.value?.holdings || [];
    if (!hs.length) return '--';
    const emptyCount = hs.filter(h => !h.symbols.length).length;
    const cur = hs[hs.length - 1];
    const curText = cur.symbols.length
        ? cur.symbols.map(s => `${nameOf(s)}(${s})`).join('、')
        : '空仓';
    return `调仓 ${hs.length} 次 · 其中空仓 ${emptyCount} 次 · 最新一期：${curText}`;
});

// ==================== 图表 ====================

function ensure(el) {
    if (!el) return null;
    return echarts.getInstanceByDom(el) || echarts.init(el);
}

function renderNav() {
    if (!navRef.value || !result.value?.series) return;
    navChart = ensure(navRef.value);
    if (!navChart) return;
    const s = result.value.series;
    const hasBench = Array.isArray(s.benchmark_equity) && s.benchmark_equity.length === s.dates.length;

    const series = [
        {
            name: '轮动策略', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
            data: s.equity, symbol: 'none', sampling: 'lttb',
            lineStyle: {width: LINE.primary, color: COLORS.up}, itemStyle: {color: COLORS.up},
        },
        {
            name: '策略回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1,
            data: s.drawdown, symbol: 'none', sampling: 'lttb',
            lineStyle: {width: LINE.secondary, color: COLORS.up}, itemStyle: {color: COLORS.up},
            areaStyle: {color: areaGradient(COLORS.up, 0.18, 0)},
        },
    ];
    if (hasBench) {
        series.splice(1, 0, {
            name: '池内等权持有', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
            data: s.benchmark_equity, symbol: 'none', sampling: 'lttb',
            lineStyle: {width: LINE.secondary, color: PALETTE[0], type: 'dashed'},
            itemStyle: {color: PALETTE[0]},
        });
    }

    navChart.setOption({
        animation: false,
        legend: {
            top: 0, left: 54, itemWidth: 14, itemHeight: 8,
            textStyle: {fontSize: FONT.legend, color: COLORS.secondary},
        },
        axisPointer: {link: [{xAxisIndex: 'all'}]},
        tooltip: tooltipBase({
            axisPointer: {type: 'cross', label: {fontSize: FONT.axis}},
            formatter: (ps) => {
                if (!ps?.length) return '';
                const i = ps[0].dataIndex;
                const lines = [`<b>${s.dates[i]}</b>`, `轮动策略净值 ${s.equity[i]?.toFixed(4) ?? '--'}`];
                if (hasBench) lines.push(`池内等权持有 ${s.benchmark_equity[i]?.toFixed(4) ?? '--'}`);
                const dd = s.drawdown[i];
                lines.push(`策略回撤 ${dd != null ? (dd * 100).toFixed(2) + '%' : '--'}`);
                return lines.join('<br/>');
            },
        }),
        // ⚠️ 回撤 grid 原来只占 18%：容器 320px 下仅 58px 要放 6 个刻度，
        // 标签会糊成一团（-5% ~ -30% 全叠在一起，截图放大才看得出来）。
        // 这里把净值压到 46%、回撤给到 20%，并让回撤轴最多只出 3 档。
        grid: [
            {left: 56, right: 16, top: 26, height: '46%'},
            {left: 56, right: 16, top: '74%', height: '20%'},
        ],
        xAxis: [
            {type: 'category', gridIndex: 0, data: s.dates, boundaryGap: false,
             axisTick: {show: false}, axisLabel: {show: false}},
            {type: 'category', gridIndex: 1, data: s.dates, boundaryGap: false,
             axisTick: {show: false}, axisLabel: axisLabel({formatter: v => String(v).slice(0, 7)})},
        ],
        yAxis: [
            {type: 'value', gridIndex: 0, scale: true, name: '净值',
             nameTextStyle: {fontSize: FONT.axis, color: COLORS.axisLabel},
             axisLabel: axisLabel(), splitLine: splitLine()},
            {type: 'value', gridIndex: 1, max: 0, name: '回撤', splitNumber: 3,
             nameTextStyle: {fontSize: FONT.axis, color: COLORS.axisLabel},
             axisLabel: axisLabel({formatter: v => `${(v * 100).toFixed(0)}%`}),
             splitLine: splitLine()},
        ],
        dataZoom: [{type: 'inside', xAxisIndex: [0, 1], zoomOnMouseWheel: true, moveOnMouseMove: true}],
        series,
    }, true);
}

function renderHeatmap() {
    if (!heatRef.value || !result.value?.heatmap) return;
    heatChart = ensure(heatRef.value);
    if (!heatChart) return;
    const hm = result.value.heatmap;
    if (!hm.symbols?.length || !hm.dates?.length) return;

    // ECharts heatmap 需要 [xIndex, yIndex, value] 的扁平数组
    const data = [];
    hm.values.forEach((row, y) => {
        row.forEach((v, x) => {
            if (v !== null && v !== undefined) data.push([x, y, v]);
        });
    });
    const clamp = hm.clamp || 3;

    heatChart.setOption({
        animation: false,
        tooltip: tooltipBase({
            trigger: 'item',
            formatter: (p) => {
                const sym = hm.symbols[p.value[1]];
                const name = hm.names?.[p.value[1]] || sym;
                return `<b>${hm.dates[p.value[0]]}</b><br/>${name}（${sym}）<br/>风险调整动量 ${p.value[2].toFixed(3)}`;
            },
        }),
        grid: {left: 80, right: 16, top: 8, bottom: 56},
        xAxis: {
            type: 'category', data: hm.dates, splitArea: {show: false},
            axisTick: {show: false},
            axisLabel: axisLabel({formatter: v => String(v).slice(0, 7), interval: 'auto'}),
        },
        yAxis: {
            // ⚠️ y 轴只放**代码**，不放名称：中文名最长有 15 字（如「华泰柏瑞沪深300ETF」），
            // 9px 字号也要 135px，会把热力图区域挤没。名称在右侧排名表和 tooltip 里都有。
            type: 'category', data: hm.symbols,
            // 不写 inverse 时 category 轴自下而上排，第 1 只落最底，与右侧排名表顺序相反
            inverse: true,
            splitArea: {show: false},
            axisTick: {show: false},
            axisLabel: axisLabel({color: COLORS.secondary}),
        },
        visualMap: {
            min: -clamp, max: clamp, calculable: true, orient: 'horizontal',
            left: 'center', bottom: 0, itemWidth: 10, itemHeight: 70,
            textStyle: {fontSize: FONT.axis, color: COLORS.axisLabel},
            // 涨红跌绿：动量强 = 红，弱/负 = 绿
            inRange: {color: ['#16a34a', '#f1f5f9', '#dc2626']},
        },
        series: [{
            type: 'heatmap', data,
            emphasis: {itemStyle: {borderColor: COLORS.text, borderWidth: 0.5}},
            itemStyle: {borderColor: '#fff', borderWidth: 0.5},
        }],
    }, true);
}

async function renderRs() {
    if (!rsRef.value || !result.value?.series) return;
    rsChart = ensure(rsRef.value);
    if (!rsChart) return;
    const sym = rsSymbol.value;
    if (!sym) {
        rsChart.clear();
        return;
    }
    const s = result.value.series;
    const benchMap = new Map();
    s.dates.forEach((d, i) => benchMap.set(d, s.benchmark_equity[i]));

    // 复用已有的 /etf_history（自带 1 小时缓存），不再为此单开接口
    let hist = [];
    try {
        const r = await axios.get(`/api/v1/etf_history/${encodeURIComponent(sym)}`, {
            params: {period: 'd', start_date: s.dates[0], end_date: s.dates[s.dates.length - 1]},
        });
        hist = Array.isArray(r.data) ? r.data : [];
    } catch (e) {
        hist = [];
    }

    const dates = [];
    const rs = [];
    let base = null;
    hist.forEach(h => {
        const b = benchMap.get(h.date);
        if (!b || !h.close || !isFinite(h.close) || !isFinite(b) || b <= 0) return;
        const v = h.close / b;
        if (base === null) base = v;
        dates.push(h.date);
        rs.push(Number((v / base).toFixed(4)));   // 归一化到起点 1.0，只看相对强弱
    });

    if (!dates.length) {
        rsChart.clear();
        return;
    }

    rsChart.setOption({
        animation: false,
        tooltip: tooltipBase({
            formatter: (ps) => {
                if (!ps?.length) return '';
                const p = ps[0];
                const rel = (p.value - 1) * 100;
                return `<b>${p.name}</b><br/>${nameOf(sym)}（${sym}）相对强弱 ${p.value.toFixed(4)}`
                    + `<br/><span style="color:${rel >= 0 ? COLORS.up : COLORS.down}">相对基准 ${rel >= 0 ? '+' : ''}${rel.toFixed(2)}%</span>`;
            },
        }),
        grid: {left: 50, right: 16, top: 16, bottom: 28},
        xAxis: {
            type: 'category', data: dates, boundaryGap: false,
            axisTick: {show: false},
            axisLabel: axisLabel({formatter: v => String(v).slice(0, 7)}),
        },
        yAxis: {
            type: 'value', scale: true, name: '相对强弱',
            nameTextStyle: {fontSize: FONT.axis, color: COLORS.axisLabel},
            axisLabel: axisLabel({formatter: v => v.toFixed(2)}),
            splitLine: splitLine(),
        },
        series: [{
            name: '相对强弱', type: 'line', data: rs, symbol: 'none', sampling: 'lttb',
            lineStyle: {width: LINE.primary, color: PALETTE[1]}, itemStyle: {color: PALETTE[1]},
            areaStyle: {color: areaGradient(PALETTE[1], 0.14, 0)},
            markLine: {
                silent: true, symbol: 'none',
                lineStyle: {color: COLORS.guideStrong, width: LINE.guide, type: 'dashed'},
                label: {show: false},
                data: [{yAxis: 1}],   // 1.0 = 与基准同步
            },
        }],
    }, true);
}

function resizeAll() {
    navChart?.resize();
    heatChart?.resize();
    rsChart?.resize();
}

function pickRs(symbol) {
    if (rsSymbol.value === symbol) return;
    rsSymbol.value = symbol;
    renderRs();
}

onMounted(async () => {
    window.addEventListener('resize', resizeAll);
    await loadPool();
    if (pool.value.length >= 2) await runAnalysis();
});

onBeforeUnmount(() => {
    window.removeEventListener('resize', resizeAll);
    navChart?.dispose();
    heatChart?.dispose();
    rsChart?.dispose();
    navChart = heatChart = rsChart = null;
});
</script>

<template>
    <div class="card etf-rotation">
        <EtfSearchDialog
            ref="searchDialog"
            v-model:visible="modalVisible"
            title="加入轮动池"
            :watched="watchedSymbols"
            :adding="addingSymbol"
            hint="输入 ETF 代码或名称，加入参与轮动分析的标的池"
            fallback-hint="未搜到？可直接用代码（如 512480）加入"
            @submit="addToPool"
        />

        <!-- 轮动池 -->
        <div class="rot-block">
            <div class="rot-head">
                <span class="rot-head__title">轮动池</span>
                <span class="rot-head__meta">已选 {{ pool.length }} / {{ poolLimit }}</span>
                <div class="rot-head__actions">
                    <Button
                        icon="pi pi-plus" label="添加 ETF" size="small"
                        :disabled="pool.length >= poolLimit"
                        @click="openAdd"
                    />
                    <Button
                        icon="pi pi-refresh" label="重新分析" size="small"
                        severity="secondary" outlined
                        :loading="analyzing"
                        :disabled="pool.length < 2"
                        @click="runAnalysis"
                    />
                </div>
            </div>

            <div v-if="loadingPool" class="rot-hint">加载中…</div>
            <div v-else-if="!pool.length" class="rot-hint">
                轮动池是空的。添加 2 只以上 ETF 即可开始轮动分析（池成员与「监控列表」相互独立）。
            </div>
            <div v-else class="rot-chips">
                <span v-for="it in pool" :key="it.symbol" class="rot-chip">
                    <span class="rot-chip__code">{{ it.symbol }}</span>
                    <span class="rot-chip__name">{{ it.name || '—' }}</span>
                    <button type="button" class="rot-chip__x" title="移出轮动池" @click="removeFromPool(it.symbol)">
                        <i class="pi pi-times"/>
                    </button>
                </span>
            </div>
        </div>

        <!-- 参数 -->
        <div class="rot-block rot-params">
            <label class="rot-field">
                <span>动量窗口</span>
                <input type="number" min="5" max="250" step="1" v-model.number="params.lookback">
                <em>交易日</em>
            </label>
            <label class="rot-field">
                <span>调仓周期</span>
                <input type="number" min="1" max="60" step="1" v-model.number="params.rebalance_days">
                <em>交易日（5≈周频）</em>
            </label>
            <label class="rot-field">
                <span>持有只数</span>
                <input type="number" min="1" max="30" step="1" v-model.number="params.top_n">
                <em>TopN</em>
            </label>
            <label class="rot-field">
                <span>单边费率</span>
                <input type="number" min="0" max="0.01" step="0.0001" v-model.number="params.cost">
                <em>如 0.0005</em>
            </label>
            <label class="rot-field">
                <span>回测区间</span>
                <select v-model.number="params.window_days">
                    <option :value="365">近 1 年</option>
                    <option :value="730">近 2 年</option>
                    <option :value="1095">近 3 年</option>
                    <option :value="1825">近 5 年</option>
                </select>
            </label>
            <label class="rot-field rot-field--check">
                <input type="checkbox" v-model="params.abs_filter">
                <span>绝对动量过滤（动量转负则空仓）</span>
            </label>
            <div class="rot-params__actions">
                <Button icon="pi pi-play" label="重新计算" size="small" :loading="analyzing"
                        :disabled="pool.length < 2" @click="runAnalysis"/>
                <Button label="重置默认" size="small" text severity="secondary" @click="resetParams"/>
            </div>
        </div>

        <!-- 结果 -->
        <div v-if="analyzing && !result" class="rot-hint rot-hint--loading">
            正在拉取 {{ pool.length }} 只 ETF 的日线并计算…
        </div>
        <div v-else-if="errorMsg" class="rot-error">{{ errorMsg }}</div>
        <div v-else-if="!result" class="rot-hint">
            添加 2 只以上 ETF 后会自动开始分析。
        </div>

        <template v-else>
            <div class="rot-meta">
                {{ result.meta.strategy_label }} ·
                {{ result.meta.start_date }} ~ {{ result.meta.end_date }} ·
                {{ result.meta.usable.length }} 只候选 ·
                对比「{{ result.meta.benchmark_name }}」
            </div>

            <div class="rot-kpis">
                <div v-for="k in kpis" :key="k.label" class="rot-kpi">
                    <div class="rot-kpi__label">{{ k.label }}</div>
                    <div class="rot-kpi__value" :class="k.tone">{{ k.value }}</div>
                </div>
            </div>

            <div v-if="benchCompare" class="rot-bench">
                <div class="rot-bench__title">对比池内等权持有</div>
                <div class="rot-bench__row" v-for="b in benchCompare" :key="b.label">
                    <span class="rot-bench__label">{{ b.label }}</span>
                    <span class="rot-bench__val">策略 {{ b.strategy }}</span>
                    <span class="rot-bench__val rot-bench__val--bench">基准 {{ b.bench }}</span>
                    <span class="rot-bench__diff" :class="b.verdict">
                        {{ b.verdict === 'better' ? '策略更好' : (b.verdict === 'worse' ? '策略更差' : '持平') }}
                    </span>
                </div>
            </div>

            <!-- 净值与回撤 -->
            <div class="rot-section">
                <div class="rot-section__title">轮动净值与回撤</div>
                <div ref="navRef" class="rot-chart rot-chart--nav"></div>
            </div>

            <div class="rot-grid2">
                <!-- 当前排名 -->
                <div class="rot-section">
                    <div class="rot-section__title">当前排名 · 风险调整动量</div>
                    <div class="rot-rank">
                        <div
                            v-for="it in ranking"
                            :key="it.symbol"
                            class="rot-rank__row"
                            :class="{ 'is-held': it.held, 'is-active': it.symbol === rsSymbol, 'is-missing': it.missing }"
                            @click="!it.missing && pickRs(it.symbol)"
                        >
                            <span class="rot-rank__no">{{ it.rank ?? '—' }}</span>
                            <span class="rot-rank__name" :title="`${it.name} ${it.symbol}`">
                                <span class="rot-rank__code">{{ it.symbol }}</span>
                                <span class="rot-rank__text">{{ it.name }}</span>
                            </span>
                            <span class="rot-rank__bar">
                                <span
                                    class="rot-rank__bar-fill"
                                    :class="(it.score ?? 0) >= 0 ? 'is-up' : 'is-down'"
                                    :style="{ width: `${Math.min(100, Math.abs(it.score || 0) / scoreScale * 100)}%` }"
                                />
                            </span>
                            <span class="rot-rank__val">{{ it.score != null ? it.score.toFixed(3) : '数据不足' }}</span>
                            <span class="rot-rank__mom" :class="toneOf(it.mom)">
                                {{ it.mom != null ? pct(it.mom) : '--' }}
                            </span>
                        </div>
                    </div>
                    <div class="rot-legend">点击任意一行查看它相对基准的强弱曲线</div>
                </div>

                <!-- RS -->
                <div class="rot-section">
                    <div class="rot-section__title">
                        相对强弱 RS · {{ rsSymbol ? `${nameOf(rsSymbol)}（${rsSymbol}）` : '未选择' }}
                    </div>
                    <div ref="rsRef" class="rot-chart rot-chart--rs"></div>
                    <div class="rot-legend">曲线 = 该 ETF 价格 ÷ 池内等权基准净值，起点归一到 1.00；在 1.00 之上表示持续跑赢池子平均</div>
                </div>
            </div>

            <!-- 热力图 -->
            <div class="rot-section">
                <div class="rot-section__title">动量热力图（月度采样 · 红强绿弱）</div>
                <div ref="heatRef" class="rot-chart rot-chart--heat"></div>
            </div>

            <!-- 持仓演变 -->
            <div class="rot-section">
                <div class="rot-section__title">持仓演变</div>
                <div class="rot-legend rot-legend--top">{{ holdingSummary }}</div>
                <div class="rot-hold">
                    <div v-for="row in holdingRows" :key="row.symbol" class="rot-hold__row">
                        <span class="rot-hold__name" :title="`${row.name} ${row.symbol}`">{{ row.symbol }}</span>
                        <span class="rot-hold__track">
                            <span
                                v-for="(seg, i) in row.segs"
                                :key="i"
                                class="rot-hold__seg"
                                :class="{ 'is-held': seg.held }"
                                :style="{ flexGrow: seg.len }"
                                :title="seg.held ? '持有' : '未持有'"
                            />
                        </span>
                    </div>
                </div>
                <div class="rot-legend">实色 = 持有期，浅色 = 未持有 / 空仓</div>
            </div>

            <div v-if="result.warnings?.length" class="rot-warnings">
                <div v-for="(w, i) in result.warnings" :key="i" class="rot-warning">
                    <i class="pi pi-info-circle"/> {{ w }}
                </div>
            </div>
        </template>
    </div>
</template>

<style scoped lang="scss">
.etf-rotation {
    /* ⚠️ 必须给根容器 min-width:0：内部有很多长中文 + 弹性布局，
       缺少它时子元素的 min-content 宽度会把卡片撑出横向滚动条。 */
    min-width: 0;
}

.rot-block {
    border: 1px solid #eef1f6;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 12px;
    min-width: 0;
}

.rot-head {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;

    &__title {
        font-size: 13px;
        font-weight: 500;
        color: #1f2937;
    }

    &__meta {
        font-size: 12px;
        color: #94a3b8;
    }

    &__actions {
        margin-left: auto;
        display: flex;
        gap: 8px;
    }
}

.rot-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
    min-width: 0;
}

.rot-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    padding: 4px 6px 4px 10px;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    background: #f8fafc;
    font-size: 12px;
    min-width: 0;

    &__code {
        font-weight: 500;
        color: #1f2937;
    }

    &__name {
        color: #64748b;
        max-width: 140px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    &__x {
        border: none;
        background: transparent;
        color: #94a3b8;
        cursor: pointer;
        padding: 0 2px;
        line-height: 1;

        &:hover {
            color: #dc2626;
        }

        i {
            font-size: 11px;
        }
    }
}

.rot-hint {
    margin-top: 10px;
    font-size: 12px;
    color: #94a3b8;

    &--loading {
        padding: 24px 0;
        text-align: center;
    }
}

.rot-error {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 6px;
    background: #fef2f2;
    color: #b91c1c;
    font-size: 12px;
}

/* 参数面板 */
.rot-params {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px;

    &__actions {
        margin-left: auto;
        display: flex;
        gap: 8px;
    }
}

.rot-field {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: #475569;
    min-width: 0;

    > span {
        white-space: nowrap;
    }

    input[type='number'],
    select {
        width: 74px;
        padding: 3px 6px;
        border: 1px solid #e2e8f0;
        border-radius: 4px;
        font-size: 12px;
        color: #1f2937;
        background: #fff;
    }

    select {
        width: 92px;
    }

    em {
        font-style: normal;
        color: #94a3b8;
        white-space: nowrap;
    }

    &--check {
        cursor: pointer;

        input {
            margin: 0;
        }
    }
}

/* 结果区 */
.rot-meta {
    font-size: 12px;
    color: #64748b;
    margin-bottom: 12px;
    overflow-wrap: anywhere;
}

.rot-kpis {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
    gap: 10px;
    margin-bottom: 12px;
}

.rot-kpi {
    background: #f8fafc;
    border-radius: 8px;
    padding: 10px 12px;

    &__label {
        font-size: 12px;
        color: #94a3b8;
    }

    &__value {
        font-size: 16px;
        font-weight: 500;
        color: #1f2937;
        margin-top: 2px;
    }
}

.is-up {
    color: #dc2626 !important;
}

.is-down {
    color: #16a34a !important;
}

.rot-bench {
    border: 1px solid #eef1f6;
    border-radius: 8px;
    padding: 10px 16px;
    margin-bottom: 12px;

    &__title {
        font-size: 12px;
        color: #94a3b8;
        margin-bottom: 6px;
    }

    &__row {
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 12px;
        padding: 3px 0;
        flex-wrap: wrap;
    }

    &__label {
        width: 64px;
        color: #475569;
        flex-shrink: 0;
    }

    &__val {
        color: #1f2937;

        &--bench {
            color: #94a3b8;
        }
    }

    &__diff {
        margin-left: auto;
        color: #94a3b8;
        font-size: 12px;

        /* 优劣着色沿用全站色义：红 = 占优，绿 = 落后 */
        &.better {
            color: #dc2626;
        }

        &.worse {
            color: #16a34a;
        }
    }
}

.rot-section {
    margin-bottom: 16px;
    min-width: 0;

    &__title {
        font-size: 13px;
        font-weight: 500;
        color: #1f2937;
        margin-bottom: 8px;
    }
}

.rot-grid2 {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 16px;
    min-width: 0;
}

.rot-chart {
    width: 100%;
    min-width: 0;

    &--nav {
        height: 320px;
    }

    &--rs {
        height: 240px;
    }

    &--heat {
        height: 260px;
    }
}

/* 排名 */
.rot-rank {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;

    &__row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 5px 6px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 12px;
        min-width: 0;

        &:hover {
            background: #f8fafc;
        }

        &.is-active {
            background: #eff6ff;
        }

        &.is-held .rot-rank__code::after {
            content: '持';
            margin-left: 4px;
            padding: 0 3px;
            border-radius: 3px;
            background: #dc2626;
            color: #fff;
            font-size: 10px;
        }

        &.is-missing {
            cursor: default;
            opacity: 0.55;
        }
    }

    &__no {
        width: 18px;
        text-align: right;
        color: #94a3b8;
        flex-shrink: 0;
    }

    &__name {
        /* 160px ≈ 13 个中文字符（含数字更宽裕）。原先 128px 时「半导体ETF国泰」这类
           名字会被截成「半导体ETF国…」，两只同指数不同公司的 ETF 就分不出来了。 */
        width: 160px;
        display: inline-flex;
        gap: 6px;
        align-items: baseline;
        min-width: 0;
        flex-shrink: 0;
    }

    &__code {
        font-weight: 500;
        color: #1f2937;
        flex-shrink: 0;
    }

    &__text {
        color: #94a3b8;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    &__bar {
        flex: 1;
        min-width: 40px;
        height: 8px;
        border-radius: 4px;
        background: #f1f5f9;
        overflow: hidden;
        display: block;
    }

    &__bar-fill {
        display: block;
        height: 100%;
        border-radius: 4px;
        background: currentColor;
    }

    &__val {
        width: 56px;
        text-align: right;
        font-weight: 500;
        color: #1f2937;
        flex-shrink: 0;
    }

    &__mom {
        width: 58px;
        text-align: right;
        flex-shrink: 0;
    }
}

.rot-legend {
    font-size: 11px;
    color: #94a3b8;
    margin-top: 6px;
    overflow-wrap: anywhere;

    &--top {
        margin-top: 0;
        margin-bottom: 8px;
    }
}

/* 持仓时间带 */
.rot-hold {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;

    &__row {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
    }

    &__name {
        width: 64px;
        font-size: 12px;
        color: #475569;
        flex-shrink: 0;
    }

    &__track {
        flex: 1;
        display: flex;
        gap: 1px;
        min-width: 0;
    }

    &__seg {
        height: 14px;
        border-radius: 2px;
        background: #f1f5f9;
        flex-basis: 0;

        &.is-held {
            background: #dc2626;
        }
    }
}

.rot-warnings {
    margin-top: 4px;
}

.rot-warning {
    font-size: 11px;
    color: #94a3b8;
    line-height: 1.8;

    i {
        font-size: 11px;
    }
}
</style>
