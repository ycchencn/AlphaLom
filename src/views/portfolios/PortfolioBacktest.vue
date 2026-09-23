<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import axios from 'axios';
import * as echarts from 'echarts';
import { useNotification } from '@/composables/useNotification';

const { showError, showInfo } = useNotification();
const route = useRoute();

// 与后端 service/portfolio_backtest_service.py::MAX_SYMBOLS 保持一致
const MAX_SYMBOLS = 30;

// ======================== 查询条件 ========================
const selected = ref([]);            // [{ symbol, name }]，顺序即用户添加顺序
const startDate = ref(null);         // Date
const endDate = ref(null);           // Date
const initCash = ref(1000000);
const benchmark = ref('000300');
const benchmarks = ref([]);          // [{ code, name }]，来自后端，前端不再自建映射

const toIso = (d) => {
    if (!d) return '';
    const date = d instanceof Date ? d : new Date(d);
    if (Number.isNaN(date.getTime())) return '';
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};

const daysAgo = (n) => {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d;
};

// 区间快捷选项
const RANGE_PRESETS = [
    { label: '近 1 年', days: 365 },
    { label: '近 3 年', days: 365 * 3 },
    { label: '近 5 年', days: 365 * 5 },
];
const applyPreset = (days) => {
    endDate.value = new Date();
    startDate.value = daysAgo(days);
};

// ======================== 标的搜索（股票 + ETF 合并） ========================
const keyword = ref('');
const results = ref([]);             // [{ symbol, name, type }]
const searching = ref(false);
let searchTimer = null;
let searchSeq = 0;                   // 丢弃乱序返回的旧搜索（与 StockMonitor 同一套做法）

const onKeywordInput = () => {
    if (searchTimer) clearTimeout(searchTimer);
    const kw = keyword.value.trim();
    if (!kw) {
        results.value = [];
        searching.value = false;
        searchSeq++;
        return;
    }
    searchTimer = setTimeout(() => doSearch(kw), 300);
};

const pickList = (settled, type) => {
    if (settled.status !== 'fulfilled') return [];
    const data = settled.value?.data;
    return Array.isArray(data) ? data.map((i) => ({ symbol: i.symbol, name: i.name, type })) : [];
};

const doSearch = async (kw) => {
    const seq = ++searchSeq;
    searching.value = true;
    try {
        // 两个接口都返回 [{symbol, name}]；任一挂掉不影响另一个（allSettled）
        const [stockRes, etfRes] = await Promise.allSettled([
            axios.get('/api/v1/stock_search', { params: { keyword: kw, limit: 30 } }),
            axios.get('/api/v1/etf_search', { params: { keyword: kw, limit: 30 } }),
        ]);
        if (seq !== searchSeq) return;
        const seen = new Set();
        results.value = [...pickList(stockRes, 'stock'), ...pickList(etfRes, 'etf')]
            .filter((i) => i.symbol && !seen.has(i.symbol) && seen.add(i.symbol));
    } catch (e) {
        if (seq === searchSeq) results.value = [];
    } finally {
        if (seq === searchSeq) searching.value = false;
    }
};

const clearSearch = () => {
    searchTimer && clearTimeout(searchTimer);
    keyword.value = '';
    results.value = [];
    searchSeq++;
};

const addSymbol = (item) => {
    const code = String(item.symbol || '').trim();
    if (!/^\d{6}$/.test(code)) {
        showError('标的代码应为 6 位数字');
        return;
    }
    if (selected.value.some((s) => s.symbol === code)) {
        showInfo(`${code} 已在列表中`);
        clearSearch();
        return;
    }
    if (selected.value.length >= MAX_SYMBOLS) {
        showError(`一次最多回测 ${MAX_SYMBOLS} 个标的`);
        return;
    }
    selected.value.push({ symbol: code, name: item.name || code });
    clearSearch();
};

// 回车：有搜索结果就取第一条；否则把输入本身当代码（支持直接敲代码，不依赖搜索命中）
const onKeywordEnter = () => {
    clearTimeout(searchTimer);
    const kw = keyword.value.trim();
    if (/^\d{6}$/.test(kw)) {
        addSymbol({ symbol: kw, name: kw });
        return;
    }
    if (results.value.length) addSymbol(results.value[0]);
};

const removeSymbol = (symbol) => {
    selected.value = selected.value.filter((s) => s.symbol !== symbol);
};

const nameOf = (symbol) => selected.value.find((s) => s.symbol === symbol)?.name || symbol;

// ======================== 回测 ========================
const loading = ref(false);
const result = ref(null);

const runBacktest = async () => {
    if (!selected.value.length) {
        showError('请至少选择一个标的');
        return;
    }
    clearSearch();
    loading.value = true;
    try {
        const { data } = await axios.get('/api/v1/portfolio_backtest', {
            params: {
                symbols: selected.value.map((s) => s.symbol).join(','),
                start_date: toIso(startDate.value),
                end_date: toIso(endDate.value),
                init_cash: Number(initCash.value) || 1000000,
                benchmark: benchmark.value || '',
            },
        });
        result.value = data;
        await nextTick();
        renderChart();
        syncQuery();
    } catch (e) {
        result.value = null;
        await nextTick();
        renderChart();
        // 后端 400 的 detail 是可直接展示的中文原因
        showError(e?.response?.data?.detail || e?.response?.data?.msg || '回测失败，请稍后重试');
    } finally {
        loading.value = false;
    }
};

// 把当前条件写进 URL，方便把一次回测结果直接分享/收藏
const syncQuery = () => {
    if (!result.value) return;
    const q = {
        symbols: selected.value.map((s) => s.symbol).join(','),
        start_date: toIso(startDate.value),
        end_date: toIso(endDate.value),
        init_cash: String(initCash.value ?? ''),
        benchmark: benchmark.value || '',
    };
    window.history.replaceState(null, '', '#' + route.path + '?' + new URLSearchParams(q).toString());
};

// ======================== 图表 ========================
const chartRef = ref(null);
let chart = null;

/**
 * 懒初始化 ECharts。
 * ⚠️ 图表容器在 v-if 内，首屏（还没回测过）它根本不在 DOM 里，ref 是 null。
 * 此时 echarts.init(null) 会在 echarts 内部抛异常并打断整个组件的挂载链
 * —— 表现是「所有数据都不渲染」，极易误判成后端问题。所以必须等数据到位再 init。
 */
const ensureChart = () => {
    if (chart || !chartRef.value) return chart;
    chart = echarts.init(chartRef.value);
    return chart;
};

const renderChart = async () => {
    await nextTick();
    const c = ensureChart();
    if (!c) return;
    const s = result.value?.series;
    if (!s || !s.dates?.length) {
        c.clear();
        return;
    }

    const hasBench = Array.isArray(s.benchmark_equity)
        && s.benchmark_equity.length === s.dates.length
        && s.benchmark_equity.length > 0;

    const series = [
        {
            name: '组合净值', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
            data: s.equity, symbol: 'none', sampling: 'lttb',
            lineStyle: { width: 1.6, color: '#ef4444' }, itemStyle: { color: '#ef4444' },
        },
        {
            name: '组合回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1,
            data: s.drawdown, symbol: 'none', sampling: 'lttb',
            lineStyle: { width: 1, color: '#ef4444' }, itemStyle: { color: '#ef4444' },
            areaStyle: { opacity: 0.18, color: '#ef4444' },
        },
    ];
    if (hasBench) {
        series.splice(1, 0, {
            name: '基准净值', type: 'line', xAxisIndex: 0, yAxisIndex: 0,
            data: s.benchmark_equity, symbol: 'none', sampling: 'lttb',
            lineStyle: { width: 1.4, color: '#3b82f6' }, itemStyle: { color: '#3b82f6' },
        });
        series.push({
            name: '基准回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1,
            data: s.benchmark_drawdown, symbol: 'none', sampling: 'lttb',
            lineStyle: { width: 1, color: '#3b82f6', type: 'dashed' }, itemStyle: { color: '#3b82f6' },
            areaStyle: { opacity: 0.08, color: '#3b82f6' },
        });
    }

    c.setOption({
        animation: false,
        legend: { top: 0, left: 54, itemWidth: 14, itemHeight: 8, textStyle: { fontSize: 9, color: '#64748b' } },
        // 两个 grid 共用一条竖线光标，鼠标在净值图上移动时回撤图同步跟随
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross', label: { fontSize: 9 } },
            textStyle: { fontSize: 10 },
            formatter: (params) => {
                if (!params?.length) return '';
                const i = params[0].dataIndex;
                const lines = [`<b>${s.dates[i]}</b>`, `组合净值 ${s.equity[i].toFixed(4)}`];
                if (hasBench) lines.push(`基准净值 ${s.benchmark_equity[i].toFixed(4)}`);
                lines.push(`组合回撤 <span style="color:#ef4444">${(s.drawdown[i] * 100).toFixed(2)}%</span>`);
                if (hasBench) lines.push(`基准回撤 <span style="color:#3b82f6">${(s.benchmark_drawdown[i] * 100).toFixed(2)}%</span>`);
                return lines.join('<br/>');
            },
        },
        grid: [
            { left: 56, right: 16, top: 26, height: '46%' },
            { left: 56, right: 16, top: '74%', height: '18%' },
        ],
        xAxis: [
            {
                type: 'category', gridIndex: 0, data: s.dates, boundaryGap: false,
                axisTick: { show: false }, axisLabel: { show: false },
            },
            {
                type: 'category', gridIndex: 1, data: s.dates, boundaryGap: false,
                axisTick: { show: false },
                axisLabel: { fontSize: 9, color: '#94a3b8', formatter: (v) => String(v).slice(0, 7) },
            },
        ],
        yAxis: [
            {
                type: 'value', gridIndex: 0, scale: true, name: '净值',
                nameTextStyle: { fontSize: 9, color: '#94a3b8' },
                axisLabel: { fontSize: 9, color: '#94a3b8' },
                splitLine: { lineStyle: { color: '#eef1f6' } },
            },
            {
                type: 'value', gridIndex: 1, max: 0, name: '回撤',
                nameTextStyle: { fontSize: 9, color: '#94a3b8' },
                axisLabel: { fontSize: 9, color: '#94a3b8', formatter: (v) => `${(v * 100).toFixed(0)}%` },
                splitLine: { lineStyle: { color: '#eef1f6' } },
            },
        ],
        dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], zoomOnMouseWheel: true, moveOnMouseMove: true }],
        series,
    // ⚠️ notMerge=true：切换标的数/是否带基准时 series 数量会变，
    // 合并模式下残留的旧 series 会继续画在图上（尤其是基准被去掉后仍显示灰色曲线）
    }, true);
};

const resizeChart = () => chart?.resize();

// ======================== 展示辅助 ========================
const pct = (v, digits = 2) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`);
const pctAbs = (v, digits = 2) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`);
// 红涨绿跌（A 股习惯）
const toneClass = (v) => (v > 0 ? 'text-red-600' : v < 0 ? 'text-green-600' : 'text-gray-500');

const excessReturn = computed(() => {
    const m = result.value?.metrics;
    const b = result.value?.benchmark_metrics;
    if (!m || !b) return null;
    return m.total_return - b.total_return;
});

const metricCards = computed(() => {
    const m = result.value?.metrics;
    if (!m) return [];
    return [
        { label: '区间收益', value: pct(m.total_return), cls: toneClass(m.total_return) },
        { label: '年化收益', value: pct(m.annual_return), cls: toneClass(m.annual_return) },
        { label: '最大回撤', value: pctAbs(m.max_drawdown), cls: 'text-green-600' },
        { label: '年化波动率', value: pctAbs(m.volatility), cls: 'text-gray-700' },
        { label: '夏普比率', value: m.sharpe.toFixed(2), cls: m.sharpe > 0 ? 'text-red-600' : 'text-green-600' },
        { label: '卡玛比率', value: m.calmar.toFixed(2), cls: m.calmar > 0 ? 'text-red-600' : 'text-green-600' },
    ];
});

const benchmarkCards = computed(() => {
    const b = result.value?.benchmark_metrics;
    const name = result.value?.meta?.benchmark_name;
    if (!b) return [];
    return [
        { label: `${name} 区间收益`, value: pct(b.total_return), cls: toneClass(b.total_return) },
        { label: `${name} 最大回撤`, value: pctAbs(b.max_drawdown), cls: 'text-green-600' },
        { label: '超额收益', value: excessReturn.value == null ? '—' : pct(excessReturn.value), cls: toneClass(excessReturn.value ?? 0) },
    ];
});

const holdingRows = computed(() => {
    const rows = result.value?.holdings || [];
    return rows.map((h) => ({ ...h, name: nameOf(h.symbol) }));
});

const drawdownRange = computed(() => {
    const m = result.value?.metrics;
    if (!m?.max_drawdown_start) return '';
    const rec = m.max_drawdown_recovery ? `，${m.max_drawdown_recovery} 修复` : '，尚未修复';
    return `${m.max_drawdown_start} → ${m.max_drawdown_end}${rec}`;
});

// ======================== 生命周期 ========================
const loadBenchmarks = async () => {
    try {
        const { data } = await axios.get('/api/v1/portfolio_backtest_benchmarks');
        benchmarks.value = Array.isArray(data) ? data : [];
        if (benchmarks.value.length && !benchmarks.value.some((b) => b.code === benchmark.value)) {
            benchmark.value = benchmarks.value[0].code;
        }
    } catch (e) {
        // 拉不到就不给下拉选项，但保留默认值，回测本身仍可用
        benchmarks.value = [];
    }
};

// URL 带 symbols 进来时直接还原一次回测（分享链接/收藏）
const restoreFromQuery = async () => {
    const q = route.query || {};
    const syms = String(q.symbols || '').split(',').map((s) => s.trim()).filter(Boolean);
    if (!syms.length) return;

    selected.value = syms.map((s) => ({ symbol: s, name: s }));
    if (q.start_date) startDate.value = new Date(String(q.start_date));
    if (q.end_date) endDate.value = new Date(String(q.end_date));
    if (q.init_cash) initCash.value = Number(q.init_cash);
    if (q.benchmark) benchmark.value = String(q.benchmark);

    await runBacktest();
    await resolveMissingNames();
};

// URL 里的标的没有名字（只有代码）时补一次名称，纯展示用，失败不影响结果
const resolveMissingNames = async () => {
    const targets = selected.value.filter((s) => s.name === s.symbol);
    if (!targets.length) return;
    await Promise.allSettled(targets.map(async (t) => {
        try {
            const [s1, s2] = await Promise.allSettled([
                axios.get('/api/v1/stock_search', { params: { keyword: t.symbol, limit: 10 } }),
                axios.get('/api/v1/etf_search', { params: { keyword: t.symbol, limit: 10 } }),
            ]);
            const all = [...pickList(s1, 'stock'), ...pickList(s2, 'etf')];
            const hit = all.find((i) => i.symbol === t.symbol);
            if (hit?.name) t.name = hit.name;
        } catch (e) {
            // 忽略：保持显示代码
        }
    }));
};

onMounted(async () => {
    window.addEventListener('resize', resizeChart);
    applyPreset(365);
    await loadBenchmarks();
    await restoreFromQuery();
});

onBeforeUnmount(() => {
    window.removeEventListener('resize', resizeChart);
    chart?.dispose();
    chart = null;
});
</script>

<template>
    <Toast />

    <div class="backtest-page">
        <!-- 查询条件 -->
        <Card class="cond-card">
            <template #title>
                <div class="cond-title">
                    <span>组合回测</span>
                    <Tag value="等权买入持有" severity="secondary" />
                </div>
            </template>
            <template #content>
                <div class="cond-grid">
                    <!-- 标的选择：占满整行 —— chips 会换行，给窄列会把条件区顶得很高 -->
                    <div class="cond-item span-all">
                        <label class="cond-label">
                            回测标的（股票 / ETF，最多 {{ MAX_SYMBOLS }} 个）
                        </label>
                        <div class="picker">
                            <div class="picker-chips" v-if="selected.length">
                                <span v-for="s in selected" :key="s.symbol" class="chip">
                                    <span class="chip-name">{{ s.name }}</span>
                                    <span class="chip-code">{{ s.symbol }}</span>
                                    <i class="pi pi-times chip-x" @click="removeSymbol(s.symbol)"></i>
                                </span>
                            </div>
                            <div class="picker-input-row">
                                <InputText
                                    v-model="keyword"
                                    class="w-full"
                                    placeholder="输入代码或名称搜索，回车添加（如 600519 / 沪深300）"
                                    @input="onKeywordInput"
                                    @keyup.enter="onKeywordEnter"
                                />
                                <Button
                                    v-if="selected.length"
                                    label="清空"
                                    size="small"
                                    severity="secondary"
                                    text
                                    class="whitespace-nowrap"
                                    @click="selected = []"
                                />
                            </div>

                            <!-- 搜索建议 -->
                            <div v-if="keyword.trim()" class="picker-panel">
                                <div v-if="searching" class="picker-tip">搜索中…</div>
                                <template v-else-if="results.length">
                                    <div
                                        v-for="item in results"
                                        :key="item.symbol"
                                        class="picker-option"
                                        @click="addSymbol(item)"
                                    >
                                        <span class="opt-name">{{ item.name }}</span>
                                        <span class="opt-code">{{ item.symbol }}</span>
                                        <Tag :value="item.type === 'etf' ? 'ETF' : '股票'" severity="secondary" class="opt-tag" />
                                    </div>
                                </template>
                                <div v-else class="picker-tip">
                                    没有匹配结果
                                    <span v-if="/^\d{6}$/.test(keyword.trim())">，按回车直接把 {{ keyword.trim() }} 加入</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 区间 -->
                    <div class="cond-item">
                        <label class="cond-label">回测区间</label>
                        <div class="range-row">
                            <DatePicker v-model="startDate" dateFormat="yy-mm-dd" showIcon placeholder="开始日期" class="range-input" />
                            <span class="range-sep">~</span>
                            <DatePicker v-model="endDate" dateFormat="yy-mm-dd" showIcon placeholder="结束日期" class="range-input" />
                        </div>
                        <div class="preset-row">
                            <Button
                                v-for="p in RANGE_PRESETS"
                                :key="p.label"
                                :label="p.label"
                                size="small"
                                severity="secondary"
                                text
                                @click="applyPreset(p.days)"
                            />
                        </div>
                    </div>

                    <!-- 初始资金 -->
                    <div class="cond-item">
                        <label class="cond-label">初始资金</label>
                        <InputNumber v-model="initCash" mode="currency" currency="CNY" locale="zh-CN" :min="0" class="w-full" />
                    </div>

                    <!-- 基准 -->
                    <div class="cond-item">
                        <label class="cond-label">对比基准</label>
                        <Dropdown
                            v-model="benchmark"
                            :options="benchmarks"
                            optionLabel="name"
                            optionValue="code"
                            placeholder="不对比基准"
                            showClear
                            class="w-full"
                        />
                    </div>
                </div>

                <div class="cond-actions">
                    <span class="cond-hint">
                        等权买入持有：起投日按 1/N 一次性建仓，区间内不调仓；行情为不复权价。
                    </span>
                    <Button label="开始回测" icon="pi pi-play" :loading="loading" class="whitespace-nowrap" @click="runBacktest" />
                </div>
            </template>
        </Card>

        <!-- 空状态 -->
        <div v-if="!result && !loading" class="empty-state">
            <i class="pi pi-chart-line empty-icon"></i>
            <div class="empty-title">选择标的与区间后开始回测</div>
            <div class="empty-sub">支持 1~{{ MAX_SYMBOLS }} 只股票 / ETF，输出组合净值、回撤曲线与绩效指标</div>
        </div>

        <template v-if="result">
            <!-- 提示 -->
            <Message v-for="(w, i) in result.warnings" :key="'w' + i" severity="warn" :closable="false" class="warn-msg">
                {{ w }}
            </Message>
            <Message v-if="result.skipped.length" severity="error" :closable="false" class="warn-msg">
                以下标的没有取到行情，已从组合中剔除：
                {{ result.skipped.map((s) => `${s.symbol}（${s.reason}）`).join('、') }}
            </Message>

            <!-- 指标卡 -->
            <div class="metric-row">
                <div v-for="c in metricCards" :key="c.label" class="metric-card">
                    <div class="metric-label">{{ c.label }}</div>
                    <div class="metric-value" :class="c.cls">{{ c.value }}</div>
                </div>
            </div>

            <!-- 基准对比 -->
            <div v-if="benchmarkCards.length" class="metric-row bench-row">
                <div v-for="c in benchmarkCards" :key="c.label" class="metric-card bench-card">
                    <div class="metric-label">{{ c.label }}</div>
                    <div class="metric-value" :class="c.cls">{{ c.value }}</div>
                </div>
            </div>

            <!-- 净值 / 回撤 -->
            <Card class="chart-card">
                <template #title>
                    <div class="chart-title-row">
                        <span>组合净值与回撤</span>
                        <span class="chart-sub">
                            {{ result.meta.start_date }} ~ {{ result.meta.end_date }}
                            （{{ result.metrics.trading_days }} 个交易日）
                        </span>
                    </div>
                </template>
                <template #content>
                    <div ref="chartRef" class="equity-chart"></div>
                    <div class="chart-foot">
                        <span>最大回撤区间：{{ drawdownRange }}</span>
                        <span>滚轮缩放 / 拖动平移</span>
                    </div>
                </template>
            </Card>

            <!-- 持仓明细 -->
            <Card class="table-card">
                <template #title>
                    <div class="chart-title-row">
                        <span>成分明细（等权）</span>
                        <span class="chart-sub">
                            单只权重 {{ (result.meta.weight_per_symbol * 100).toFixed(2) }}%，
                            贡献 = 权重 × 区间收益，各项之和恰好等于组合区间收益
                        </span>
                    </div>
                </template>
                <template #content>
                    <DataTable :value="holdingRows" dataKey="symbol" size="small" showGridlines style="font-size: 11px">
                        <Column field="symbol" header="代码" style="width: 7rem" />
                        <Column field="name" header="名称" />
                        <Column header="类型" style="width: 5rem">
                            <template #body="{ data }">
                                <Tag :value="data.asset_type === 'etf' ? 'ETF' : '股票'" severity="secondary" />
                            </template>
                        </Column>
                        <Column header="权重" style="width: 6rem">
                            <template #body="{ data }">{{ (data.weight * 100).toFixed(2) }}%</template>
                        </Column>
                        <Column header="区间收益" style="width: 8rem">
                            <template #body="{ data }">
                                <span :class="toneClass(data.total_return)">{{ pct(data.total_return) }}</span>
                            </template>
                        </Column>
                        <Column header="收益贡献" style="width: 8rem">
                            <template #body="{ data }">
                                <span :class="toneClass(data.contribution)">{{ pct(data.contribution) }}</span>
                            </template>
                        </Column>
                    </DataTable>
                </template>
            </Card>
        </template>
    </div>
</template>

<style scoped lang="scss">
.backtest-page {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 0.25rem;
}

/* ---------- 条件区 ---------- */
.cond-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.cond-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.75rem 1rem;
}

.cond-item {
    display: flex;
    flex-direction: column;
    min-width: 0;
}

/* 标的行占满所有列。用 `1 / -1` 而不是 `span 3`：
   栅格在窄屏会降到 2 列 / 1 列，写死 span 数会溢出到不存在的列上 */
.span-all {
    grid-column: 1 / -1;
}

.cond-label {
    font-size: 1rem; /* 12px（根字号 12px） */
    color: #64748b;
    margin-bottom: 0.25rem;
}

.range-row {
    display: flex;
    align-items: center;
    gap: 0.35rem;
}

.range-input {
    flex: 1 1 0;
    min-width: 0;
}

.range-sep {
    color: #94a3b8;
}

.preset-row {
    display: flex;
    gap: 0.15rem;
    margin-top: 0.15rem;
}

.cond-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    margin-top: 0.75rem;
    padding-top: 0.6rem;
    border-top: 1px solid #f1f5f9;
}

.cond-hint {
    font-size: 1rem;
    color: #94a3b8;
}

/* ---------- 标的搜索 ---------- */
.picker {
    position: relative;
}

.picker-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    margin-bottom: 0.35rem;
}

.chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.1rem 0.4rem;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 0.25rem;
    font-size: 1rem;
    color: #334155;
}

.chip-code {
    color: #94a3b8;
    font-size: 0.9rem;
}

.chip-x {
    cursor: pointer;
    font-size: 0.9rem;
    color: #94a3b8;
}

.chip-x:hover {
    color: #ef4444;
}

.picker-input-row {
    display: flex;
    align-items: center;
    gap: 0.35rem;
}

/* 搜索建议面板：普通绝对定位浮层，避免再引一个组件 */
.picker-panel {
    position: absolute;
    z-index: 30;
    left: 0;
    right: 0;
    top: 100%;
    max-height: 15rem;
    /* 标的行现在是整行宽，建议面板跟着整行铺开会有上几百 px 的空行，
       限到一个下拉框该有的宽度 */
    max-width: 34rem;
    overflow-y: auto;
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 0.25rem;
    box-shadow: 0 6px 16px rgba(15, 23, 42, 0.08);
}

.picker-option {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0.5rem;
    cursor: pointer;
    font-size: 1rem;
}

.picker-option:hover {
    background: #f8fafc;
}

.opt-name {
    flex: 1 1 auto;
    color: #1e293b;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.opt-code {
    color: #94a3b8;
}

.opt-tag {
    flex: 0 0 auto;
    font-size: 0.9rem;
}

.picker-tip {
    padding: 0.5rem;
    font-size: 1rem;
    color: #94a3b8;
}

/* ---------- 空状态 ---------- */
.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 4rem 1rem;
    background: #fff;
    border: 1px dashed #e2e8f0;
    border-radius: 0.375rem;
    color: #94a3b8;
}

.empty-icon {
    font-size: 2rem;
    color: #cbd5e1;
}

.empty-title {
    font-size: 1.25rem; /* 15px */
    color: #64748b;
}

.empty-sub {
    font-size: 1rem;
}

/* ---------- 提示 ---------- */
.warn-msg {
    font-size: 1rem;
}

/* ---------- 指标卡 ---------- */
.metric-row {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 0.6rem;
}

.bench-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
}

.metric-card {
    background: #fff;
    border: 1px solid #eef1f6;
    border-radius: 0.375rem;
    padding: 0.55rem 0.7rem;
}

.bench-card {
    background: #f8fafc;
}

.metric-label {
    font-size: 1rem;
    color: #94a3b8;
    margin-bottom: 0.2rem;
}

.metric-value {
    font-size: 1.25rem; /* 15px —— 与项目其它指标卡一致 */
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}

/* ---------- 图表 ---------- */
.chart-title-row {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    flex-wrap: wrap;
}

.chart-sub {
    font-size: 1rem;
    color: #94a3b8;
    font-weight: 400;
}

.equity-chart {
    width: 100%;
    height: 24rem;
}

.chart-foot {
    display: flex;
    justify-content: space-between;
    font-size: 1rem;
    color: #94a3b8;
    margin-top: 0.35rem;
}

/* 窄屏收敛成两列 / 一列，避免 3 列网格在小屏被挤爆 */
@media (max-width: 1200px) {
    .cond-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .metric-row {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
}

@media (max-width: 768px) {
    .cond-grid {
        grid-template-columns: minmax(0, 1fr);
    }

    /* 窄屏下条件区变单列，提示文字会挤掉按钮，改为上下排布 */
    .cond-actions {
        flex-direction: column;
        align-items: stretch;
    }
}
</style>
