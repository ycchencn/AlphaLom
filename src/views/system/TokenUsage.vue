<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue';
import axios from 'axios';
import * as echarts from 'echarts';
import Card from 'primevue/card';

const summary = ref(null);
const loadingSummary = ref(false);
const records = ref([]);
const loadingRecords = ref(false);
const totalRecords = ref(0);
const currentPage = ref(1);
const pageSize = ref(20);

const dateRange = ref(null);
const filterModel = ref(null);
const filterScene = ref(null);
const modelOptions = ref([]);
const sceneOptions = ref([]);

const expandedRows = ref({});

const fmt = (n) => (n == null ? 0 : n);

const fmtDate = (d) => {
    const dt = new Date(d);
    return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0');
};

const buildParams = () => {
    const p = {};
    if (filterModel.value) p.model = filterModel.value;
    if (filterScene.value) p.scene = filterScene.value;
    if (dateRange.value && dateRange.value[0]) p.start_date = fmtDate(dateRange.value[0]);
    if (dateRange.value && dateRange.value[1]) p.end_date = fmtDate(dateRange.value[1]);
    return p;
};

const loadSummary = async () => {
    loadingSummary.value = true;
    try {
        const r = await axios.get('/api/v1/token_usage/summary', { params: buildParams() });
        if (r.data.code === 200) {
            summary.value = r.data.data;
            modelOptions.value = (summary.value.by_model || []).map((m) => ({ label: m.model, value: m.model }));
            sceneOptions.value = (summary.value.by_scene || []).map((s) => ({ label: s.scene, value: s.scene }));
            await renderCharts();
        }
    } catch (e) {
        console.error('加载统计失败', e);
    } finally {
        loadingSummary.value = false;
    }
};

const loadRecords = async () => {
    loadingRecords.value = true;
    try {
        const params = { page: currentPage.value, page_size: pageSize.value, ...buildParams() };
        const r = await axios.get('/api/v1/token_usage/records', { params });
        if (r.data.code === 200) {
            records.value = r.data.data.records;
            totalRecords.value = r.data.data.total;
        }
    } catch (e) {
        console.error('加载明细失败', e);
    } finally {
        loadingRecords.value = false;
    }
};

const onPage = (e) => {
    currentPage.value = e.page + 1;
    loadRecords();
};

const onFilter = () => {
    currentPage.value = 1;
    loadSummary();
    loadRecords();
};

const onReset = () => {
    filterModel.value = null;
    filterScene.value = null;
    dateRange.value = null;
    currentPage.value = 1;
    loadSummary();
    loadRecords();
};

/* ---------------- echarts ---------------- */
const PIE_PALETTE = [
    '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899',
    '#14b8a6', '#ef4444', '#6366f1', '#f97316', '#0ea5e9',
    '#a855f7', '#22c55e'
];

const trendChartRef = ref(null);
const modelPieRef = ref(null);
const scenePieRef = ref(null);
let trendChart = null;
let modelPie = null;
let scenePie = null;

// 容器可能在 v-if 内 → init 必须等数据到位；宿主 DOM 被替换/摘除时要 dispose 重建。
const ensureChart = (chart, refEl) => {
    const host = chart && chart.getDom && chart.getDom();
    if (chart && host !== refEl.value) {
        if (host && !document.contains(host)) { chart.dispose(); chart = null; }
        else if (!host) { chart = null; }
    }
    if (!chart) {
        if (!refEl.value) return null;
        if (!refEl.value.clientWidth || !refEl.value.clientHeight) return null;
        chart = echarts.init(refEl.value);
    }
    return chart;
};

const renderTrend = async () => {
    await nextTick();
    trendChart = ensureChart(trendChart, trendChartRef);
    if (!trendChart) return;

    const daily = (summary.value && summary.value.daily) || [];
    if (!daily.length) { trendChart.clear(); return; }

    const dates = daily.map((d) => d.date);
    const input = daily.map((d) => d.prompt_tokens || 0);
    const output = daily.map((d) => d.completion_tokens || 0);
    const calls = daily.map((d) => d.calls || 0);

    trendChart.setOption({
        color: ['#3b82f6', '#10b981', '#f59e0b'],
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: ['输入 Token', '输出 Token', '调用次数'], bottom: 0, textStyle: { fontSize: 11, color: '#64748b' } },
        grid: { left: 56, right: 56, top: 24, bottom: 44 },
        xAxis: {
            type: 'category', boundaryGap: false, data: dates,
            axisLine: { lineStyle: { color: '#e2e8f0' } },
            axisLabel: { color: '#64748b', fontSize: 11 }
        },
        yAxis: [
            {
                type: 'value', name: 'Token',
                axisLabel: { color: '#64748b', fontSize: 11 },
                splitLine: { lineStyle: { color: '#f1f5f9' } }
            },
            {
                type: 'value', name: '次数',
                axisLabel: { color: '#64748b', fontSize: 11 },
                splitLine: { show: false }
            }
        ],
        series: [
            {
                name: '输入 Token', type: 'line', stack: 'usage', symbol: 'none',
                lineStyle: { width: 0 }, itemStyle: { color: '#3b82f6' },
                areaStyle: { color: 'rgba(59,130,246,0.35)' }, data: input
            },
            {
                name: '输出 Token', type: 'line', stack: 'usage', symbol: 'none',
                lineStyle: { width: 0 }, itemStyle: { color: '#10b981' },
                areaStyle: { color: 'rgba(16,185,129,0.35)' }, data: output
            },
            {
                name: '调用次数', type: 'line', yAxisIndex: 1, symbol: 'circle', symbolSize: 4,
                itemStyle: { color: '#f59e0b' }, lineStyle: { color: '#f59e0b' }, data: calls
            }
        ]
    });
};

const renderModelPie = async () => {
    await nextTick();
    modelPie = ensureChart(modelPie, modelPieRef);
    if (!modelPie) return;

    const byModel = (summary.value && summary.value.by_model) || [];
    if (!byModel.length) { modelPie.clear(); return; }
    const total = byModel.reduce((s, m) => s + (m.total_tokens || 0), 0);

    modelPie.setOption({
        color: PIE_PALETTE,
        tooltip: {
            trigger: 'item',
            formatter: (p) => {
                const pct = total ? (p.value / total * 100).toFixed(2) : 0;
                const m = byModel.find((x) => x.model === p.name);
                return `<div style="font-size:12px"><b>${p.name}</b><br/>`
                    + `Token：${p.value.toLocaleString()}<br/>`
                    + `占比：<b>${pct}%</b><br/>`
                    + `调用：${m ? m.calls : 0} 次</div>`;
            }
        },
        legend: { type: 'scroll', bottom: 0, left: 'center', textStyle: { fontSize: 11, color: '#64748b' } },
        series: [{
            name: '按模型', type: 'pie', radius: ['40%', '65%'], center: ['50%', '45%'],
            avoidLabelOverlap: true, itemStyle: { borderColor: '#fff', borderWidth: 2 },
            label: { show: false }, labelLine: { show: false },
            emphasis: { label: { show: false }, itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' } },
            data: byModel.map((m) => ({ name: m.model, value: m.total_tokens || 0 }))
        }]
    });
};

const renderScenePie = async () => {
    await nextTick();
    scenePie = ensureChart(scenePie, scenePieRef);
    if (!scenePie) return;

    const byScene = (summary.value && summary.value.by_scene) || [];
    if (!byScene.length) { scenePie.clear(); return; }
    const total = byScene.reduce((s, m) => s + (m.total_tokens || 0), 0);

    scenePie.setOption({
        color: PIE_PALETTE,
        tooltip: {
            trigger: 'item',
            formatter: (p) => {
                const pct = total ? (p.value / total * 100).toFixed(2) : 0;
                const s = byScene.find((x) => x.scene === p.name);
                return `<div style="font-size:12px"><b>${p.name}</b><br/>`
                    + `Token：${p.value.toLocaleString()}<br/>`
                    + `占比：<b>${pct}%</b><br/>`
                    + `调用：${s ? s.calls : 0} 次</div>`;
            }
        },
        legend: { type: 'scroll', bottom: 0, left: 'center', textStyle: { fontSize: 11, color: '#64748b' } },
        series: [{
            name: '按场景', type: 'pie', radius: ['40%', '65%'], center: ['50%', '45%'],
            avoidLabelOverlap: true, itemStyle: { borderColor: '#fff', borderWidth: 2 },
            label: { show: false }, labelLine: { show: false },
            emphasis: { label: { show: false }, itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' } },
            data: byScene.map((s) => ({ name: s.scene, value: s.total_tokens || 0 }))
        }]
    });
};

const renderCharts = async () => {
    await renderTrend();
    await renderModelPie();
    await renderScenePie();
};

const resizeCharts = () => {
    trendChart?.resize();
    modelPie?.resize();
    scenePie?.resize();
};

onMounted(() => {
    loadSummary();
    loadRecords();
    window.addEventListener('resize', resizeCharts);
});

onUnmounted(() => {
    window.removeEventListener('resize', resizeCharts);
    trendChart?.dispose();
    modelPie?.dispose();
    scenePie?.dispose();
});
</script>

<template>
    <div class="card mt-5">
        <div class="font-semibold text-xl mb-4">Token 使用量统计</div>

        <!-- 汇总卡片 -->
        <div class="summary-row">
            <Card class="stat-card">
                <template #content>
                    <div class="card-content">
                        <div class="stat-label">总调用次数</div>
                        <div class="stat-value">{{ fmt(summary?.total_calls) }}</div>
                    </div>
                </template>
            </Card>
            <Card class="stat-card">
                <template #content>
                    <div class="card-content">
                        <div class="stat-label">总 Token</div>
                        <div class="stat-value">{{ fmt(summary?.total_tokens) }}</div>
                    </div>
                </template>
            </Card>
            <Card class="stat-card">
                <template #content>
                    <div class="card-content">
                        <div class="stat-label">输入 Token</div>
                        <div class="stat-value">{{ fmt(summary?.total_prompt_tokens) }}</div>
                    </div>
                </template>
            </Card>
            <Card class="stat-card">
                <template #content>
                    <div class="card-content">
                        <div class="stat-label">输出 Token</div>
                        <div class="stat-value">{{ fmt(summary?.total_completion_tokens) }}</div>
                    </div>
                </template>
            </Card>
        </div>

        <!-- 筛选 -->
        <div class="mb-4 flex flex-wrap gap-2 align-items-center">
            <Dropdown v-model="filterModel" :options="modelOptions" optionLabel="label" optionValue="value" placeholder="模型" showClear />
            <Dropdown v-model="filterScene" :options="sceneOptions" optionLabel="label" optionValue="value" placeholder="场景" showClear />
            <Calendar v-model="dateRange" selectionMode="range" :manualInput="false" dateFormat="yy-mm-dd" placeholder="时间范围" />
            <Button label="筛选" icon="pi pi-filter" @click="onFilter" size="small" />
            <Button label="重置" icon="pi pi-filter-slash" @click="onReset" outlined size="small" />
        </div>

        <!-- 每日用量走势面积图 -->
        <div class="font-semibold mb-2">每日用量走势</div>
        <div ref="trendChartRef" style="height: 320px" class="mb-2"></div>
        <DataTable :value="summary?.daily || []" stripedRows showGridlines class="mb-4" style="font-size: 11px">
            <Column field="date" header="日期" />
            <Column field="calls" header="调用次数" />
            <Column field="prompt_tokens" header="输入 Token" />
            <Column field="completion_tokens" header="输出 Token" />
            <Column field="total_tokens" header="总计 Token" />
            <template #empty>暂无数据</template>
        </DataTable>

        <!-- 按模型 / 按场景 饼图 -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-2">
            <div>
                <div class="font-semibold mb-2">按模型（Token 占比）</div>
                <div ref="modelPieRef" style="height: 300px"></div>
                <DataTable :value="summary?.by_model || []" stripedRows showGridlines class="mt-2" style="font-size: 11px">
                    <Column field="model" header="模型" />
                    <Column field="calls" header="调用次数" />
                    <Column field="prompt_tokens" header="输入 Token" />
                    <Column field="completion_tokens" header="输出 Token" />
                    <Column field="total_tokens" header="总计 Token" />
                    <template #empty>暂无数据</template>
                </DataTable>
            </div>
            <div>
                <div class="font-semibold mb-2">按场景（Token 占比）</div>
                <div ref="scenePieRef" style="height: 300px"></div>
                <DataTable :value="summary?.by_scene || []" stripedRows showGridlines class="mt-2" style="font-size: 11px">
                    <Column field="scene" header="场景" />
                    <Column field="calls" header="调用次数" />
                    <Column field="total_tokens" header="总计 Token" />
                    <template #empty>暂无数据</template>
                </DataTable>
            </div>
        </div>

        <!-- 调用明细 -->
        <div class="font-semibold mb-2">调用明细</div>
        <DataTable
            :value="records" :loading="loadingRecords" lazy paginator :rows="pageSize"
            :totalRecords="totalRecords" @page="onPage"
            :rowsPerPageOptions="[20, 50, 100]" stripedRows showGridlines
            v-model:expandedRows="expandedRows" dataKey="id" style="font-size: 11px">
            <Column expander style="width: 2rem" />
            <Column field="created_at" header="时间" />
            <Column field="user_id" header="用户ID" />
            <Column field="scene" header="场景" />
            <Column field="platform" header="平台" />
            <Column field="model" header="模型" />
            <Column field="prompt_tokens" header="输入" />
            <Column field="completion_tokens" header="输出" />
            <Column field="total_tokens" header="总计" />
            <template #expansion="slotProps">
                <div class="p-3">
                    <div class="font-semibold mb-1">输入</div>
                    <pre class="whitespace-pre-wrap text-sm" style="max-height: 300px; overflow: auto">{{ slotProps.data.input_text }}</pre>
                    <div class="font-semibold mt-3 mb-1">输出</div>
                    <pre class="whitespace-pre-wrap text-sm" style="max-height: 300px; overflow: auto">{{ slotProps.data.output_text }}</pre>
                </div>
            </template>
            <template #empty>暂无数据</template>
        </DataTable>
    </div>
</template>

<style scoped lang="scss">
// 汇总卡片行（与沪深大盘监控 MarketOverview 的指数卡片对齐）
.summary-row {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 1.5rem;

    .stat-card {
        flex: 1 1 calc(25% - 1rem);
        min-width: 160px;
        transition: all 0.2s ease;

        &:hover {
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }
    }
}

// 让卡片内容撑满高度、垂直居中
.stat-card :deep(.p-card-body),
.stat-card :deep(.p-card-content) {
    height: 100%;
}

.card-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0.25rem 0;

    .stat-label {
        font-size: 0.9rem;
        color: #64748b;
        font-weight: 600;
        white-space: nowrap;
    }

    .stat-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0f172a;
        margin-top: 0.4rem;
        line-height: 1;
        font-variant-numeric: tabular-nums;
    }
}

:deep(.p-datatable .p-datatable-thead > tr > th) {
    background-color: var(--surface-50);
}
pre {
    white-space: pre-wrap;
    word-break: break-word;
}
</style>
