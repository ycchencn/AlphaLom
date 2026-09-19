<script setup>

import {ref, computed, onMounted, onUnmounted, nextTick} from 'vue';
import {useRoute, useRouter} from 'vue-router';
import axios from 'axios';
import {init, dispose} from 'klinecharts';
import {chartConfigs} from '@/utils/constants.js';
import Card from 'primevue/card';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Button from 'primevue/button';
import ProgressSpinner from 'primevue/progressspinner';
import SelectButton from 'primevue/selectbutton';
import PriceRange52Week from '@/components/PriceRange52Week.vue';
import {formatCurrency, formatPercentage, formatStockTradeAmount} from '@/utils/function.js';
import {useNotification} from '@/composables/useNotification';

const route = useRoute();
const router = useRouter();
const {showError} = useNotification();

const symbol = route.params.symbol;

const detail = ref(null);
const loading = ref(true);
const error = ref(null);

const history = ref([]);
const historyLoading = ref(false);
const period = ref('1Y');
const periodOptions = [
    {label: '1月', value: '1M'},
    {label: '3月', value: '3M'},
    {label: '6月', value: '6M'},
    {label: '1年', value: '1Y'},
    {label: '3年', value: '3Y'},
];
const periodDays = {'1M': 30, '3M': 90, '6M': 180, '1Y': 365, '3Y': 1095};

const composition = ref([]);
const compositionLoading = ref(false);

// ETF 基本资料（get_etf_info：交易所/净值/申赎单位/类型/申赎开关/交易日等）
const etfInfo = ref({});
// 后端 type 字段为数字代码，databull 文档未给出权威映射，这里仅作友好呈现参考，
// 若与上游不一致以原始代码展示为主。
const ETF_TYPE_MAP = {
    0: '股票型ETF', 1: '债券型ETF', 2: '货币型ETF',
    3: '商品型ETF', 4: '跨境/海外ETF', 5: '其他',
};
const infoRows = computed(() => {
    const d = etfInfo.value || {};
    const rows = [];
    const push = (label, value) => {
        if (value !== undefined && value !== null && value !== '') rows.push({label, value});
    };
    push('交易所', d.etf_exch_id);
    push('单位净值', d.nav != null ? formatCurrency(d.nav) : null);
    push('每申赎单位净值', d.nav_per_cu != null ? formatCurrency(d.nav_per_cu) : null);
    push('最小申赎单位', d.report_unit != null ? `${Number(d.report_unit).toLocaleString()} 份` : null);
    push('现金差额', d.cash_balance != null ? formatCurrency(d.cash_balance) : null);
    push('预估现金差额', d.ecc != null ? formatCurrency(d.ecc) : null);
    push('现金替代比例上限', d.max_cash_ratio != null ? `${d.max_cash_ratio}%` : null);
    push('申购上限', d.creation_limit != null ? Number(d.creation_limit).toLocaleString() : null);
    push('赎回上限', d.redemption_limit != null ? Number(d.redemption_limit).toLocaleString() : null);
    push('允许申购', d.enable_creation != null ? (d.enable_creation ? '是' : '否') : null);
    push('允许赎回', d.enable_redemption != null ? (d.enable_redemption ? '是' : '否') : null);
    push('ETF类型', d.type != null ? (ETF_TYPE_MAP[d.type] || `类型 ${d.type}`) : null);
    push('交易日', d.trading_day);
    push('上一交易日', d.pre_trading_day);
    return rows;
});


const ohlc = computed(() => detail.value?.ohlc_last || {});
const low52 = computed(() => (detail.value ? detail.value['52week_low'] : null));
const high52 = computed(() => (detail.value ? detail.value['52week_high'] : null));
// 红涨绿跌（A股习惯）
const isUp = computed(() => (ohlc.value.chg_pct ?? 0) > 0);
const isDown = computed(() => (ohlc.value.chg_pct ?? 0) < 0);
const hasRange = computed(() =>
    low52.value != null && high52.value != null &&
    ohlc.value.lastPrice != null && high52.value > low52.value
);

// ---------- klinecharts 走势图 ----------
const chartEl = ref(null);
let chart = null;
const CHART_TYPE_KEY = 'etf_chart_type';
const CHART_INDICATOR_KEY = 'etf_chart_indicator';
const chart_type = ref(localStorage.getItem(CHART_TYPE_KEY) || 'candle_solid');
const chart_indicator = ref(localStorage.getItem(CHART_INDICATOR_KEY) || 'VOL');
const chartFilterOptions = [
    {label: 'K线', value: 'candle_solid'},
    {label: '美国线', value: 'ohlc'},
    {label: '面积图', value: 'area'},
];
const chartIndicatorOptions = [
    {label: 'VOL', value: 'VOL'},
    {label: 'MACD', value: 'MACD'},
    {label: 'RSI', value: 'RSI'},
    {label: 'CCI', value: 'CCI'},
    {label: 'BBI', value: 'BBI'},
    {label: 'BOLL', value: 'BOLL'},
    {label: 'KDJ', value: 'KDJ'},
    {label: 'MTM', value: 'MTM'},
];

// 成分股表头：优先用友好中文，未知字段回退原名
const compLabelMap = {
    symbol: '代码', name: '名称', weight: '权重(%)',
    holding: '持仓', holding_ratio: '持仓占比(%)', proportion: '占比(%)',
};
const compColumns = computed(() =>
    composition.value.length ? Object.keys(composition.value[0]) : []
);

// 后端返回 {date, open, high, low, close, volume} → 转成 klinecharts 需要的
// {timestamp(ms), open, high, low, close, volume}
const transformedHistory = computed(() => (history.value || []).map(h => ({
    timestamp: new Date((h.date || '') + 'T00:00:00').getTime(),
    open: h.open,
    high: h.high,
    low: h.low,
    close: h.close,
    volume: h.volume || 0,
})));

function fmtDate(days) {
    const d = new Date(Date.now() - days * 86400000);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}${m}${day}`;
}

async function loadDetail() {
    loading.value = true;
    error.value = null;
    try {
        const r = await axios.get(`/api/v1/etf/${symbol}`);
        detail.value = r.data;
    } catch (e) {
        error.value = '加载ETF详情失败';
        showError('加载ETF详情失败');
    } finally {
        loading.value = false;
    }
}

function buildDataLoader() {
    return {
        getBars: async ({callback}) => {
            callback(transformedHistory.value);
        }
    };
}

function initChart() {
    if (chart || !chartEl.value) return;
    chart = init(chartEl.value);
    chart.setStyles({...chartConfigs});
    chart.setPeriod({span: 1, type: 'day'});
    chart.setSymbol({ticker: symbol});
    chart.setDataLoader(buildDataLoader());
    // 量能指标 + EMA 叠加
    chart.createIndicator(chart_indicator.value, true, {id: 'candle_pane_vol'});
    chart.createIndicator({name: 'EMA', paneId: 'candle_pane'}, true);
    chart.setStyles({candle: {type: chart_type.value}});
}

function refreshChartData() {
    if (!chart) return;
    chart.setDataLoader(buildDataLoader());
}

function changeChartType() {
    if (!chart) return;
    chart.setStyles({candle: {type: chart_type.value}});
    localStorage.setItem(CHART_TYPE_KEY, chart_type.value);
}

function changeChartIndicator() {
    if (!chart) return;
    chart.removeIndicator('candle_pane_vol');
    chart.createIndicator(chart_indicator.value, true, {id: 'candle_pane_vol'});
    chart.createIndicator({name: 'EMA', paneId: 'candle_pane'}, true);
    localStorage.setItem(CHART_INDICATOR_KEY, chart_indicator.value);
}

async function loadHistory() {
    historyLoading.value = true;
    try {
        const r = await axios.get(`/api/v1/etf_history/${symbol}`, {
            params: {
                start_date: fmtDate(periodDays[period.value]),
                end_date: fmtDate(0),
            },
        });
        history.value = r.data || [];
    } catch (e) {
        history.value = [];
    } finally {
        historyLoading.value = false;
    }
    await nextTick();
    if (chart) refreshChartData();
    else initChart();
}

async function loadComposition() {
    compositionLoading.value = true;
    try {
        const r = await axios.get(`/api/v1/etf_composition/${symbol}`);
        composition.value = Array.isArray(r.data) ? r.data : [];
    } catch (e) {
        composition.value = [];
    } finally {
        compositionLoading.value = false;
    }
}

async function loadEtfInfo() {
    try {
        const r = await axios.get(`/api/v1/etf_info/${symbol}`);
        etfInfo.value = (r.data && typeof r.data === 'object') ? r.data : {};
    } catch (e) {
        etfInfo.value = {};
    }
}

function goBack() {
    router.push({path: '/market/etf_insight'});
}

onMounted(async () => {
    await loadDetail();
    // 确保详情容器（含 #chart）已渲染，再初始化 klinecharts
    await nextTick();
    loadHistory();
    loadComposition();
    loadEtfInfo();
});

onUnmounted(() => {
    if (chart) dispose(chart);
});

</script>

<template>
    <div class="card mx-auto relative" style="padding-top: 20px;">

        <!-- 加载态 -->
        <div v-if="loading" class="flex justify-center items-center py-16">
            <ProgressSpinner style="width: 50px; height: 50px"/>
        </div>

        <!-- 错误态 -->
        <div v-else-if="error" class="text-center py-16 text-red-500">
            <i class="pi pi-exclamation-circle text-3xl"></i>
            <p class="mt-3">{{ error }}</p>
            <Button label="返回列表" class="mt-4" severity="secondary" @click="goBack"/>
        </div>

        <!-- 详情 -->
        <div v-else-if="detail">

            <!-- 右上角操作 -->
            <div class="absolute top-8 right-8">
                <Button icon="pi pi-arrow-left" label="返回列表" severity="secondary" size="small" @click="goBack"/>
            </div>

            <!-- 标题 -->
            <h1 class="text-2xl font-bold mb-3 text-gray-800">
                {{ detail.name }}
                <span class="text-lg font-light text-gray-400">({{ detail.symbol }})</span>
            </h1>

            <!-- 实时价格 -->
            <h1 v-if="ohlc.lastPrice != null" class="stock-price mb-1"
                :class="{'text-red-500': isUp, 'text-green-600': isDown}">
                <span class="text-3xl font-bold">{{ formatCurrency(ohlc.lastPrice) }}</span>
                <span v-if="ohlc.lastClose != null" class="text-lg ml-2">
                    {{ formatCurrency(ohlc.lastPrice - ohlc.lastClose, true) }}
                </span>
                <span v-if="ohlc.chg_pct != null" class="text-lg ml-1">
                    {{ formatPercentage(ohlc.chg_pct.toFixed(2), true) }}%
                </span>
            </h1>

            <!-- 概览卡片 -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6 mt-5">
                <Card>
                    <template #title>涨跌额</template>
                    <template #content>
                        <div class="text-xl font-semibold font-mono"
                             :class="{'text-red-500': isUp, 'text-green-600': isDown}">
                            {{ (ohlc.lastPrice != null && ohlc.lastClose != null)
                                ? formatCurrency(ohlc.lastPrice - ohlc.lastClose, true) : '--' }}
                        </div>
                        <div class="text-xs text-gray-500 mt-1">较昨收</div>
                    </template>
                </Card>

                <Card>
                    <template #title>涨跌幅</template>
                    <template #content>
                        <div class="text-xl font-semibold font-mono"
                             :class="{'text-red-500': isUp, 'text-green-600': isDown}">
                            {{ ohlc.chg_pct != null ? formatPercentage(ohlc.chg_pct.toFixed(2), true) + '%' : '--' }}
                        </div>
                        <div class="text-xs text-gray-500 mt-1">当日</div>
                    </template>
                </Card>

                <Card>
                    <template #title>成交额</template>
                    <template #content>
                        <div class="text-xl font-semibold text-blue-700 font-mono">
                            {{ ohlc.amount != null ? formatStockTradeAmount(ohlc.amount) : '--' }}
                        </div>
                        <div class="text-xs text-gray-500 mt-1">当日成交</div>
                    </template>
                </Card>

                <Card>
                    <template #title>昨收</template>
                    <template #content>
                        <div class="text-xl font-semibold text-gray-700 font-mono">
                            {{ ohlc.lastClose != null ? formatCurrency(ohlc.lastClose) : '--' }}
                        </div>
                        <div class="text-xs text-gray-500 mt-1">前收盘价</div>
                    </template>
                </Card>
            </div>

            <!-- 基本资料 -->
            <Card class="mb-6">
                <template #title>
                    <i class="pi pi-info-circle text-indigo-500 mr-1"></i> 基本资料
                </template>
                <template #content>
                    <div v-if="infoRows.length" class="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">
                        <div v-for="row in infoRows" :key="row.label" class="flex flex-col">
                            <span class="text-xs text-gray-500">{{ row.label }}</span>
                            <span class="text-sm font-medium text-gray-800 font-mono">{{ row.value }}</span>
                        </div>
                    </div>
                    <div v-else class="text-center text-gray-400 py-6">暂无基本资料</div>
                </template>
            </Card>

            <!-- 52周价格区间 -->
            <Card class="mb-6">
                <template #title>
                    <i class="pi pi-chart-bar text-blue-500 mr-1"></i> 52周价格区间
                </template>
                <template #content>
                    <div v-if="hasRange">
                        <PriceRange52Week
                            :low52w="low52"
                            :high52w="high52"
                            :currentPrice="ohlc.lastPrice"
                            style="width: 320px;"
                        />
                        <div class="flex justify-between text-xs text-gray-500 mt-2" style="width: 320px;">
                            <span>当前：<b class="text-gray-700">{{ formatCurrency(ohlc.lastPrice) }}</b></span>
                            <span>高：{{ formatCurrency(high52) }} / 低：{{ formatCurrency(low52) }}</span>
                        </div>
                    </div>
                    <div v-else class="text-center text-gray-400 py-6">暂无52周区间数据</div>
                </template>
            </Card>

            <!-- 历史走势（klinecharts） -->
            <Card class="mb-6">
                <template #title>
                    <i class="pi pi-wave-pulse text-red-400 mr-1"></i> 历史走势
                </template>
                <template #content>
                    <div class="flex flex-wrap items-center gap-3 mb-3">
                        <SelectButton
                            v-model="period"
                            :options="periodOptions"
                            optionLabel="label"
                            optionValue="value"
                            @change="loadHistory"
                            size="small"
                        />
                        <SelectButton
                            v-model="chart_type"
                            :options="chartFilterOptions"
                            optionLabel="label"
                            optionValue="value"
                            @change="changeChartType"
                            size="small"
                        />
                        <SelectButton
                            v-model="chart_indicator"
                            :options="chartIndicatorOptions"
                            optionLabel="label"
                            optionValue="value"
                            @change="changeChartIndicator"
                            size="small"
                        />
                    </div>
                    <div class="relative" style="height: 420px;">
                        <div ref="chartEl" id="chart" style="width: 100%; height: 100%;"></div>
                        <ProgressSpinner v-if="historyLoading" style="width: 40px; height: 40px"
                                        class="absolute inset-0 m-auto"/>
                        <div v-if="!historyLoading && !history.length"
                             class="absolute inset-0 flex items-center justify-center text-gray-400">
                            暂无历史行情数据
                        </div>
                    </div>
                </template>
            </Card>

            <!-- 成分股 -->
            <Card>
                <template #title>
                    <i class="pi pi-list text-green-500 mr-1"></i> 成分股构成
                </template>
                <template #content>
                    <ProgressSpinner v-if="compositionLoading" style="width: 40px; height: 40px"/>
                    <DataTable v-else
                               :value="composition"
                               :paginator="composition.length > 10"
                               :rows="10"
                               dataKey="symbol"
                               tableStyle="font-size: 12px"
                               :showGridlines="false"
                               :rowHover="true">
                        <template #empty> 暂无成分股数据（上游未提供） </template>
                        <Column v-for="col in compColumns" :key="col" :field="col" :header="compLabelMap[col] || col"/>
                    </DataTable>
                </template>
            </Card>

        </div>
    </div>
</template>

<style scoped lang="scss">
#chart {
    width: 100%;
    height: 100%;
    border: 1px solid #eee;
    border-radius: 3px
}

.stock-price {
    line-height: 1.2
}

/* 增强 Card 边框：Aura 主题默认只有极淡阴影、无边框，这里补一条清晰但克制的中性边框 */
.p-card {
    border: 1px solid #dedede;
}
:global(html.app-dark) .p-card {
    border-color: #334155;
}
</style>
