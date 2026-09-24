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
import Tag from 'primevue/tag';
import ProgressSpinner from 'primevue/progressspinner';
import SelectButton from 'primevue/selectbutton';
import PriceRange52Week from '@/components/PriceRange52Week.vue';
import {
    formatCurrency,
    formatPercentage,
    formatStockTradeAmount,
    fearGreedToText,
    fearGreedLevel,
    fearGreedColor,
    fearGreedLabel,
} from '@/utils/function.js';
import {useNotification} from '@/composables/useNotification';
import * as echarts from 'echarts';

const route = useRoute();
const router = useRouter();
const {showError, showSuccess} = useNotification();

const symbol = route.params.symbol;

const detail = ref(null);
const loading = ref(true);
const error = ref(null);

const history = ref([]);
const historyLoading = ref(false);
const period = ref('3Y');
const periodOptions = [
    {label: '1月', value: '1M'},
    {label: '3月', value: '3M'},
    {label: '6月', value: '6M'},
    {label: '1年', value: '1Y'},
    {label: '3年', value: '3Y'},
];
const periodDays = {'1M': 30, '3M': 90, '6M': 180, '1Y': 365, '3Y': 1095};

// 成分股：清单与权重是两条链路、耗时差一个数量级（清单 1 次上游请求，
// 权重要逐只取最新价），所以拆成两个请求分别落两处状态，用 computed 合并 ——
// 这样谁先回来都不会丢数据（直接往同一个数组里 merge 会踩到顺序竞态）。
const compositionRaw = ref([]);
const weightItems = ref({}); // code -> {code, price, weight}
const compositionLoading = ref(false);
// 清单元信息。trading_day 是**清单生成日**，上游快照可能明显早于今天，
// 必须显示出来，否则用户会把陈旧的篮子股数当成当日数据；
// source='pcf' 才有股数，'composition' 是回退链路（只有代码/名称）。
const compositionMeta = ref({ count: 0, trading_day: null, source: null });
// 权重估算状态。supported=false 表示这条 ETF 的篮子取不到 A 股报价
// （跨境 ETF 的港股/美股成分），此时表格不显示「最新价 / 估算权重」两列。
const weightMeta = ref({ loading: false, supported: false, reason: null, priced: 0, total: 0 });

const composition = computed(() => compositionRaw.value.map(row => {
    const w = weightItems.value[row.code];
    return {...row, price: w ? w.price : null, weight: w ? w.weight : null};
}));

// 列随数据能力变化：股票型 ETF 多出「数量 / 最新价 / 估算权重」，
// PCF 缺失或跨境篮子则自动少这几列，而不是留一堆空单元格。
const compositionColumns = computed(() => {
    const cols = [
        {field: 'code', header: '代码', style: 'width: 20%'},
        {field: 'name', header: '名称'},
    ];
    if (compositionMeta.value.source === 'pcf') {
        cols.push({field: 'volume', header: '数量（股）', style: 'width: 18%', headerStyle: 'text-align: left'});
    }
    if (weightMeta.value.supported) {
        cols.push({field: 'price', header: '最新价', style: 'width: 16%', headerStyle: 'text-align: left'});
        cols.push({field: 'weight', header: '估算权重', style: 'width: 16%', headerStyle: 'text-align: left'});
    }
    return cols;
});

// 权重就绪后默认按权重从大到小（282 只成分股，先看大票才有意义），
// 没有权重时退回按代码升序。DataTable 对 sortField/sortOrder 有 watcher，会跟着重排。
const compositionSortField = computed(() => (weightMeta.value.supported ? 'weight' : 'code'));
const compositionSortOrder = computed(() => (weightMeta.value.supported ? -1 : 1));

// ── 成分股快捷入池 ────────────────────────────────────────────────────────
// 成分股穿透看到的「这只 ETF 重仓了什么」往往正是要找的票，让人回到股票池页
// 再手输一遍代码很别扭，所以在列表里直接给一个入池入口。
//
// 与「股票池」页（StockMonitor.vue）共用同一个接口 PUT /stocks/{symbol}，交互也
// 刻意保持一致（已入池显示 Tag「已添加」，否则显示带加号的「添加」按钮），
// 免得同一个动作在两个页面长得不一样。
const pooledSymbols = ref(new Set()); // 已入池代码集合，用于把按钮换成「已添加」
const addingSymbol = ref('');         // 正在提交的代码，只让该行按钮进 loading

/** 上游 PCF 的 code 带交易所后缀（'000552.SZ'），入池接口要的是纯代码 */
function componentSymbol(row) {
    return String(row.code || '').split('.')[0];
}

/**
 * 由 PCF 的 exchange 推导市场。
 *
 * 这个值不是给前端看的：它既是 PUT /stocks/{symbol} 的 market（决定入池后落到
 * 股票池页的哪个页签），也会被后端的 ensure_stock_from_api 拿去选上游接口。
 * 所以宁可不给按钮，也不要猜错 —— 认不出来（债券/其他品种成分）就返回 null。
 *
 * ⚠️ 不要用 getMarketByCode() 代替：那个按「长度 5 位 = 港股」之类的启发式判断，
 * 本页拿到的是上游原始代码，exchange 字段才是权威来源。
 */
function componentMarket(row) {
    const exch = String(row.exchange || '').toUpperCase();
    if (exch === 'SH' || exch === 'SZ' || exch === 'BJ') return 'cn';
    if (exch === 'HK') return 'hk';
    if (exch === 'US') return 'us';
    const code = componentSymbol(row);
    if (/^\d{6}$/.test(code)) return 'cn';   // 无后缀的 6 位数字 = A 股
    if (/^\d{5}$/.test(code)) return 'hk';   // 无后缀的 5 位数字 = 港股
    return null;
}

/**
 * 拉取「本页成分涉及的市场」里已入池的代码。
 *
 * 只在成分里实际出现的市场上各查一次（多数 ETF 全是 A 股 → 1 个请求）：
 * /stocks_monitored 的 market 按市场分段返回，全量拉要 3 个请求，没必要。
 *
 * 拉失败只降级为「全部显示成未添加」，不影响加入功能本身 ——
 * 代价是重复点已入池的票，后端会当普通字段更新处理（提示成功但没新建分析任务）。
 */
async function loadPooledSymbols() {
    const markets = [...new Set(compositionRaw.value.map(componentMarket).filter(Boolean))];
    if (!markets.length) {
        pooledSymbols.value = new Set();
        return;
    }
    try {
        const results = await Promise.all(markets.map(m => axios.get('/api/v1/stocks_monitored', {
            params: {simple: 1, page_size: 1000, market: m}
        })));
        const set = new Set();
        for (const r of results) {
            for (const s of (Array.isArray(r.data) ? r.data : [])) set.add(String(s.symbol));
        }
        pooledSymbols.value = set;
    } catch (e) {
        console.warn('加载已入池状态失败，成分股按钮将全部显示为「未添加」', e);
        pooledSymbols.value = new Set();
    }
}

/**
 * 把一只成分股加入股票池。
 *
 * ⚠️ 后端对「新建入库 / monitoring 0→1」的票会顺带投递一次个股分析
 * （恐惧贪婪 / 因子 / DCF / 报价），而任务队列是串行消费的，
 * 所以提示只能说到「正在后台分析、稍后查看」，不能说数据已经齐了。
 */
async function addComponentToPool(row) {
    const code = componentSymbol(row);
    const market = componentMarket(row);
    if (!code || !market) return;

    addingSymbol.value = code;
    try {
        const res = await axios.put(`/api/v1/stocks/${encodeURIComponent(code)}`, {
            market,
            monitoring: 1,
            securities_type: 'stock'
        });
        // Set 是原地修改的，换成新实例才会触发用到它的渲染
        pooledSymbols.value = new Set([...pooledSymbols.value, code]);
        const label = row.name ? `${code} ${row.name}` : code;
        if (res.data && res.data.analysis_triggered) {
            showSuccess(`已加入股票池：${label}，正在后台分析，稍后到「股票池」页查看`);
        } else {
            showSuccess(`已加入股票池：${label}`);
        }
    } catch (error) {
        let message = '加入股票池失败，请重试';
        if (axios.isAxiosError(error)) {
            if (error.response) {
                const {data} = error.response;
                message = (data && (data.message || data.detail)) || message;
            } else if (error.request) {
                message = '网络连接失败，请检查网络后重试';
            }
        }
        showError(message);
    } finally {
        addingSymbol.value = '';
    }
}

function formatVolume(v) {
    return v == null || v === '' ? '—' : Number(v).toLocaleString();
}

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

// ---------- 恐惧贪婪卡片（UI 与个股页 StockDetail / 大盘页 MarketOverview 同构）----------
// 与个股页一样用**原生 ECharts**（而不是页面别处的 klinecharts / primevue chart）：
// 需要 markLine 分档参考线 + 按分值着色的渐变面积，另两款做不到，观感会与另两页对不上。
//
// ⚠️ 数据来源与个股共用一张表 `stocks_fear_greed`，但**不是上游直读**，而是
// `job_update_stock_greedy_data` 用 ETF 自己的日线计算出来再落库的
// （走 is_etf() → get_etf_history）。上游 /cn/market/fear_greed 实测只覆盖指数，
// ETF 与个股都不在其中。因此新入池的 ETF 必须跑过该 job 才会有数据。
const greedData = ref([]);
const fgChartRef = ref(null);
let fgChart = null;
// 后端按 trade_date 倒序返回，取下标 0 即最新一期
const greedLatest = computed(() => greedData.value[0] || null);

/**
 * 懒初始化恐惧贪婪走势图的 ECharts 实例。
 *
 * ⚠️ 图表容器在 `v-if="greedLatest"` 内部 —— 首屏 onMounted 时数据还没到、
 * greedLatest 为 null，那个 div 根本没进 DOM，fgChartRef.value 是 **null**。
 * 此时调 echarts.init(null) 会在 echarts 内部抛
 * `Cannot read properties of null (reading 'getAttribute')`，而这个异常发生在
 * 渲染阶段，会把整个组件的挂载链打断 —— 表现是**页面所有数据都不渲染**，
 * 但接口其实一个都没发出去（极易误判成后端问题）。
 * 所以必须在数据到位、DOM 真正存在之后再 init。
 */
const ensureFgChart = () => {
    if (fgChart) return fgChart;
    if (!fgChartRef.value) return null;
    fgChart = echarts.init(fgChartRef.value);
    return fgChart;
};

/**
 * 绘制「近一年走势」。
 *
 * 配置与个股页 / 大盘页的恐惧贪婪图保持一致：固定 0~100 的 y 轴、
 * 25/50/75 三条分档虚线、渐变面积。
 * y 轴固定量程是必要的 —— 自适应量程会把「26 分」和「74 分」画成视觉上一样高的波动，
 * 情绪指标失去可读性。ETF 历史长度不一（新 ETF 可能不足一年），
 * 这里按实际行数绘制，不做补齐。
 *
 * @param {Array} rows 已按交易日**升序**排列的记录
 */
const renderFearGreedChart = async (rows) => {
    // nextTick：数据赋值 → v-if 变真 → DOM 出现，等这一拍再 init
    await nextTick();
    const instance = ensureFgChart();
    if (!instance) return;

    if (!rows || !rows.length) {
        instance.clear();
        return;
    }

    instance.setOption({
        grid: {left: 32, right: 12, top: 16, bottom: 22},
        tooltip: {
            trigger: 'axis',
            formatter: (params) => {
                const p = params[0];
                const d = rows[p.dataIndex];
                return `${d.trade_date}<br/>综合: <b>${d.fear_greed}</b>（${fearGreedLabel(d.fear_greed)}）`
                    + `<br/>波动分: ${d.vol_score ?? '--'}<br/>动量分: ${d.mom_score ?? '--'}`;
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
            // 25 / 50 / 75 为情绪分档参考线
            markLine: {
                silent: true,
                symbol: 'none',
                label: {show: false},
                lineStyle: {type: 'dashed', color: '#cbd5e1'},
                data: [{yAxis: 50}, {yAxis: 25}, {yAxis: 75}]
            }
        }]
    });
};

async function loadFearGreed() {
    try {
        // ⚠️ 显式传 limit=250（约一年交易日）而不是依赖后端默认值，
        // 避免以后默认值被调整时静默改变图表周期。
        const r = await axios.get(`/api/v1/etf_greed_data/${symbol}`, {params: {limit: 250}});
        // 后端按 trade_date 倒序返回：倒序数组给卡片左栏取「最新一条」，
        // 图表另用升序副本。不要再靠 index 0 / last 猜顺序。
        greedData.value = Array.isArray(r.data) ? r.data : [];
        const sorted = [...greedData.value].sort(
            (a, b) => new Date(a.trade_date).getTime() - new Date(b.trade_date).getTime()
        );
        renderFearGreedChart(sorted);
    } catch (e) {
        greedData.value = [];
    }
}

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

// 成分股改走 PCF（申赎清单）：比 etf_composition 多出 component_volume（每篮子股数）。
// 后端 /etf_pcf 已归一化为 {code, name, exchange, volume, trading_day}（按代码升序）。

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
        const r = await axios.get(`/api/v1/etf_pcf/${symbol}`);
        const d = r.data || {};
        compositionRaw.value = Array.isArray(d.composition) ? d.composition : [];
        compositionMeta.value = {
            count: d.count || compositionRaw.value.length,
            trading_day: d.trading_day || null,
            source: d.source || null,
        };
    } catch (e) {
        compositionRaw.value = [];
        compositionMeta.value = {count: 0, trading_day: null, source: null};
    } finally {
        compositionLoading.value = false;
    }
    // 成分到手后才谈得上「哪些已经在股票池里」，拿不到成分时这里会自己清空
    loadPooledSymbols();
}

// 权重单独拉：跨境 ETF 会在后端直接判定不支持，不发取价请求，这里拿到的是空表。
async function loadWeights() {
    weightMeta.value = {...weightMeta.value, loading: true};
    try {
        const r = await axios.get(`/api/v1/etf_pcf_weight/${symbol}`);
        const d = r.data || {};
        const map = {};
        for (const it of (Array.isArray(d.items) ? d.items : [])) {
            if (it && it.code) map[it.code] = it;
        }
        weightItems.value = map;
        weightMeta.value = {
            loading: false,
            supported: !!d.supported,
            reason: d.reason || null,
            priced: d.priced || 0,
            total: d.total || 0,
        };
    } catch (e) {
        weightItems.value = {};
        weightMeta.value = {loading: false, supported: false, reason: 'error', priced: 0, total: 0};
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

/**
 * ⚠️ ECharts 画布尺寸是 **init 时按容器实测值固定下来的**，不是响应式的：
 * 侧边栏折叠、窗口拖拽后画布不会自己跟着变，表现为图表被拉伸变形或右侧留白。
 * 项目未引入 ResizeObserver 封装，沿用个股页 / 大盘页的做法监听 window resize。
 * 必须与 removeEventListener 成对，否则页面来回切换会累积监听器。
 */
const resizeFgChart = () => fgChart?.resize();

onMounted(async () => {
    await loadDetail();
    // 确保详情容器（含 #chart）已渲染，再初始化 klinecharts
    await nextTick();
    loadHistory();
    loadComposition();
    loadEtfInfo();
    loadFearGreed();
    // 不 await：清单先渲染，权重（要逐只取价）回来后再补上两列
    loadWeights();
    window.addEventListener('resize', resizeFgChart);
});

onUnmounted(() => {
    if (chart) dispose(chart);
    window.removeEventListener('resize', resizeFgChart);
    // 组件卸载时销毁 ECharts 实例：只把 ref 置空不够，
    // 实例内部仍持有 canvas 与事件监听，反复进出详情页会持续泄漏内存。
    if (fgChart) {
        fgChart.dispose();
        fgChart = null;
    }
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

            <!-- 第一行：概览卡片 + 52周价格区间 -->
            <div class="flex flex-col lg:flex-row gap-4 mb-6 mt-5">
                <!-- 概览卡片 -->
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4 flex-1">
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

                <!-- 52周价格区间（合并到第一行右侧） -->
                <Card class="lg:w-80 shrink-0">
                    <template #title>
                        <i class="pi pi-chart-bar text-blue-500 mr-1"></i> 52周价格区间
                    </template>
                    <template #content>
                        <div v-if="hasRange">
                            <PriceRange52Week
                                :low52w="low52"
                                :high52w="high52"
                                :currentPrice="ohlc.lastPrice"
                                style="width: 100%;"
                            />
                            <div class="flex justify-between text-xs text-gray-500 mt-2">
                                <span>当前：<b class="text-gray-700">{{ formatCurrency(ohlc.lastPrice) }}</b></span>
                                <span>高：{{ formatCurrency(high52) }} / 低：{{ formatCurrency(low52) }}</span>
                            </div>
                        </div>
                        <div v-else class="text-center text-gray-400 py-6">暂无52周区间数据</div>
                    </template>
                </Card>
            </div>

            <!-- 基本资料 -->
            <Card class="mb-6">
                <template #title>
                    <i class="pi pi-info-circle text-indigo-500 mr-1"></i> 基本资料
                </template>
                <template #content>
                    <div v-if="infoRows.length" class="grid grid-cols-2 md:grid-cols-5 gap-x-6 gap-y-4">
                        <div v-for="row in infoRows" :key="row.label" class="flex flex-col">
                            <span class="text-base text-gray-500">{{ row.label }}</span>
                            <span class="text-gray-800 font-mono">{{ row.value }}</span>
                        </div>
                    </div>
                    <div v-else class="text-center text-gray-400 py-6">暂无基本资料</div>
                </template>
            </Card>

            <!-- 恐惧贪婪：布局与个股页 / 大盘页保持一致 ——
                 左栏「当前值 + 情绪档位 + 分量条」、右栏「近一年走势图」。
                 用 Card 包裹与页面其它区块统一（本页普遍是 Card 风格），
                 不再像个股页那样补一层自绘 .fg-card。 -->
            <Card class="mb-6">
                <template #title>
                    <i class="pi pi-sun text-orange-500 mr-1"></i> 恐惧&贪婪指标
                </template>
                <template #content>
                    <div v-if="greedLatest" class="fear-greed-body">
                        <!-- 左：当前值 -->
                        <div class="fg-current">
                            <div class="fg-value" :style="{ color: fearGreedColor(greedLatest.fear_greed) }">
                                {{ Number(greedLatest.fear_greed ?? 0).toFixed(2) }}
                            </div>
                            <div class="fg-label" :style="{ color: fearGreedColor(greedLatest.fear_greed) }">
                                {{ fearGreedLevel(greedLatest.fear_greed).text }}
                            </div>
                            <div class="fg-date">{{ greedLatest.trade_date }}</div>

                            <!-- 解读：一句话说明当前情绪意味着什么 -->
                            <div class="fg-advice">
                                {{ fearGreedToText(greedLatest.fear_greed).advice }}
                            </div>

                            <!-- 分量拆解：用迷你条直观表达两个 0~100 分项的相对高低 -->
                            <div class="fg-scores">
                                <div class="fg-score">
                                    <span class="score-name">波动分</span>
                                    <span class="score-track">
                                        <span class="score-fill"
                                              :style="{ width: Math.min(100, Number(greedLatest.vol_score ?? 0)) + '%',
                                                        background: fearGreedColor(greedLatest.vol_score) }"></span>
                                    </span>
                                    <span class="score-val">{{ Number(greedLatest.vol_score ?? 0).toFixed(1) }}</span>
                                </div>
                                <div class="fg-score">
                                    <span class="score-name">动量分</span>
                                    <span class="score-track">
                                        <span class="score-fill"
                                              :style="{ width: Math.min(100, Number(greedLatest.mom_score ?? 0)) + '%',
                                                        background: fearGreedColor(greedLatest.mom_score) }"></span>
                                    </span>
                                    <span class="score-val">{{ Number(greedLatest.mom_score ?? 0).toFixed(1) }}</span>
                                </div>
                                <div class="fg-score">
                                    <span class="score-name">收盘价</span>
                                    <span class="score-val score-val-wide">
                                        {{ Number(greedLatest.close ?? 0).toFixed(2) }}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <!-- 右：近一年走势 -->
                        <div class="fg-chart-wrap">
                            <div class="fg-chart-title">近一年走势</div>
                            <div ref="fgChartRef" class="fg-chart"></div>
                        </div>
                    </div>
                    <div v-else class="empty-tip">该 ETF 暂无恐惧贪婪数据</div>
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
                    <!-- 240px：与 K 线下方「成分股构成」配合的紧凑高度。
                         原来写 420px 会把成分股整块推到首屏之外（1600x1050 下文档高 2239px，
                         成分股卡片起点 1073px），而 ETF 详情的核心信息正是成分股穿透。 -->
                    <div class="relative" style="height: 380px;">
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

            <!-- 成分股（申赎清单 PCF） -->
            <Card>
                <template #title>
                    <i class="pi pi-list text-green-500 mr-1"></i> 成分股构成
                    <span v-if="composition.length" class="text-sm font-light text-gray-400 ml-1">
                        （共 {{ composition.length }} 只<template v-if="compositionMeta.trading_day"> · 清单日 {{ compositionMeta.trading_day }}</template>）
                    </span>
                </template>
                <template #content>
                    <!-- 清单日期是「上游生成日」而不是查询日，单独说明一句，避免把旧篮子当成当日数据 -->
                    <div v-if="composition.length && compositionMeta.source === 'pcf'"
                         class="text-xs text-gray-400 mb-2">
                        数量为每个申赎单位（最小申购赎回篮子）包含的股数{{ compositionMeta.trading_day ? `，清单生成于 ${compositionMeta.trading_day}` : '' }}。
                    </div>
                    <div v-if="weightMeta.loading" class="text-xs text-gray-400 mb-2">
                        <i class="pi pi-spin pi-spinner mr-1"></i> 正在按最新价估算权重…
                    </div>
                    <div v-else-if="weightMeta.supported" class="text-xs text-gray-400 mb-2">
                        权重为估算值：篮子股数 × 最新价后归一，已取到 {{ weightMeta.priced }}/{{ weightMeta.total }} 只报价。
                    </div>
                    <div v-else-if="composition.length" class="text-xs text-gray-400 mb-2">
                        暂无权重估算{{
                            weightMeta.reason === 'non_cn_components' ? '（篮子含港股/美股等非 A 股成分，没有对应报价源）' : ''
                        }}。
                    </div>
                    <div v-if="!compositionLoading && composition.length && compositionMeta.source !== 'pcf'"
                         class="text-xs text-gray-400 mb-2">
                        上游未提供申赎清单，仅有代码与名称。
                    </div>

                    <ProgressSpinner v-if="compositionLoading" style="width: 40px; height: 40px"/>
                    <DataTable v-else
                               :value="composition"
                               :paginator="composition.length > 10"
                               :rows="10"
                               dataKey="code"
                               tableStyle="font-size: 12px"
                               :showGridlines="false"
                               :rowHover="true"
                               removableSort
                               :sortField="compositionSortField"
                               :sortOrder="compositionSortOrder">
                        <template #empty> 暂无成分股数据（上游未提供） </template>
                        <Column v-for="col in compositionColumns"
                                :key="col.field"
                                :field="col.field"
                                :header="col.header"
                                :style="col.style"
                                :headerStyle="col.headerStyle"
                                sortable>
                            <template #body="{ data, field }">
                                <span v-if="field === 'volume'" class="block text-left font-mono">
                                    {{ formatVolume(data.volume) }}
                                </span>
                                <span v-else-if="field === 'price'" class="block text-left font-mono">
                                    {{ data.price != null ? formatCurrency(data.price) : '—' }}
                                </span>
                                <span v-else-if="field === 'weight'" class="block text-left font-mono">
                                    {{ data.weight != null ? data.weight.toFixed(2) + '%' : '—' }}
                                </span>
                                <span v-else>{{ data[field] }}</span>
                            </template>
                        </Column>
                        <!-- 入池列固定排最后、不参与排序：入池是动作，不是可比较的值。
                             表头直接写动作本身（不写「操作」这种通用壳子，用户看不出是干什么的）。
                             认不出市场的成分（债券等）只给一个占位「—」，不给按钮。 -->
                        <Column header="加入股票池" style="width: 118px" headerStyle="text-align: center">
                            <template #body="{ data }">
                                <div class="flex justify-center">
                                    <span v-if="!componentMarket(data)" class="text-gray-300">—</span>
                                    <Tag v-else-if="pooledSymbols.has(componentSymbol(data))"
                                         value="已添加" severity="secondary"/>
                                    <Button v-else icon="pi pi-plus" label="添加" size="small"
                                            class="whitespace-nowrap"
                                            :loading="addingSymbol === componentSymbol(data)"
                                            @click="addComponentToPool(data)"/>
                                </div>
                            </template>
                        </Column>
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

/* ========================
   恐惧贪婪卡片
   与个股页 StockDetail.vue / 大盘页 MarketOverview.vue 的同名样式保持一致
   （左值 + 右图表）。改这里时请同步那两页，三页观感必须一致。
   差异：本页区块在 Card 内，故不再自绘 .fg-card 外壳。
   ======================== */
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

        /* 情绪解读：与「数值 → 档位 → 日期 → 解读」的阅读顺序一致 */
        .fg-advice {
            font-size: 0.8rem;
            color: #64748b;
            margin-top: 0.5rem;
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

                // 收盘价没有可归一化的量纲，不配进度条，占满右侧
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
        justify-content: center;

        .fg-chart-title {
            font-size: 0.85rem;
            color: #94a3b8;
            margin-bottom: 0.3rem;
        }

        .fg-chart {
            flex: 1;
            min-height: 200px;
            width: 100%;
        }
    }
}

.empty-tip {
    padding: 2rem 0;
    text-align: center;
    color: #94a3b8;
    font-size: 0.9rem;
}

/* 窄屏：横向布局改为纵向堆叠。个股页左侧固定 300px 会顶满小屏整宽导致图表被挤走，
   这里同样改为自适应宽度。 */
@media (max-width: 768px) {
    .fear-greed-body {
        flex-direction: column;
        gap: 1rem;

        .fg-current {
            flex: none;
            width: 100%;
        }
    }
}
</style>
