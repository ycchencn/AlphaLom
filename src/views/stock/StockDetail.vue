<script setup>

import {computed, onMounted, onUnmounted, watch, nextTick} from 'vue';
import {init, dispose} from 'klinecharts';
import {ref} from 'vue';
import {useRoute} from 'vue-router';
import {chartConfigs} from '@/utils/constants.js';
import StockValuationChart from '@/components/StockValuationChart.vue'
import {
    fetchStockMarketData,
    fetchStockInfo,
    fetchStockProfile,
    dictToMarkdownRecursive,
    formatDaysAgo,
    fearGreedToText,
    fearGreedLevel,
    fearGreedColor,
    fearGreedLabel,
    formatCurrency,
    formatPercentage,
    calcDcfScore,
    parseNumber
} from '@/utils/function.js';
import MarkdownRenderer from '@/components/MarkdownRenderer.vue';
import {useChartDisplay} from '@/composables/useChartDisplay.js';
import axios from 'axios';
import {useToast} from 'primevue/usetoast';
import {useNotification} from '@/composables/useNotification';
import PriceRange52Week from '@/components/PriceRange52Week.vue';
import router from '@/router'
import Tabs from 'primevue/tabs';
import TabList from 'primevue/tablist';
import Tab from 'primevue/tab';
import TabPanels from 'primevue/tabpanels';
import TabPanel from 'primevue/tabpanel';
import * as echarts from 'echarts'

let chart = ref(null)
const toast = useToast();
const route = useRoute();
const news = ref([]);
const greed_data = ref([]);

// ===== 图表显示开关（后端 system_setting 的 chart_display 组）=====
// klineEnabled=false → 「走势图表」区块整块隐藏（默认开启，见 routes/system_setting.py，仅后端显式配置为 false 才隐藏）。
// 数据照常取（恐贪卡片、DCF 估值都要用 ohlc 数据），只是不渲染 K 线。
const {klineEnabled, loadChartDisplay} = useChartDisplay();

// ===== 恐惧贪婪：ECharts 走势卡片（与大盘页「成长 vs 价值」同款样式）=====
// 形态：左侧当前读数 + 右侧走势图。走势图用**双轴**叠两条线 ——
//   主曲线（左轴，0~100）= 恐惧贪婪值；点线（右轴）= 收盘价。
// 这样「情绪读数」与「股价走势」放在同一张图里，一眼能看出情绪高点是否对应价格高点。
//
// ⚠️ 两轴必须彻底解耦：情绪值域 0~100、收盘价可能是 11 元也可能是 1800 元，
// 若共用一条轴，ECharts 会把两者统一到并集范围 → 情绪线被压成一条贴在顶/底的直线。
// 左轴固定 0~100（情绪有天然量纲，固定量程反而正确），右轴由数据自适应。
//
// 后端按 trade_date 倒序返回，取下标 0 即最新一期。
const greedLatest = computed(() => greed_data.value[0] || null);

// 走势图容器 / 实例。容器在 v-if="greedLatest" 内，首屏数据没到时 DOM 还不存在，
// 所以 init 必须放在数据到位后的 renderFearGreedChart 里（与大盘页同一个坑）。
const fgChartRef = ref(null);
let fgChart = null;

const ensureFgChart = () => {
    // 容器已被 v-if 换掉（或已脱离文档）时，旧实例是孤儿 → 必须先 dispose 再重建，
    // 否则 setOption 会画在脱离文档的 canvas 上（有坐标轴、无折线）。
    const host = fgChart && fgChart.getDom && fgChart.getDom();
    if (fgChart && host !== fgChartRef.value) {
        if (host && !document.contains(host)) {
            fgChart.dispose();
            fgChart = null;
        } else if (!host) {
            fgChart = null;
        }
    }
    if (!fgChart) {
        if (!fgChartRef.value) return null;
        // 尺寸为 0 时 init 会得到一块不可见的画布，等下一帧再试
        if (!fgChartRef.value.clientWidth || !fgChartRef.value.clientHeight) return null;
        fgChart = echarts.init(fgChartRef.value);
    }
    return fgChart;
};

/**
 * 渲染恐惧贪婪走势（主曲线=情绪值，副轴点线=收盘价）。
 *
 * ⚠️ 数据是**倒序**的（后端按 trade_date desc），画图前必须 reverse 成时间升序，
 * 否则 X 轴的先后顺序整个反掉 —— 曲线形状会左右镜像，且不易察觉。
 */
const renderFearGreedChart = async () => {
    await nextTick();
    const chart = ensureFgChart();
    if (!chart) return;

    const rows = [...(greed_data.value || [])].reverse();
    if (!rows.length) {
        chart.clear();
        return;
    }
    const dates = rows.map((r) => r.trade_date);
    const fg = rows.map((r) => (r.fear_greed == null ? null : Number(r.fear_greed)));
    const close = rows.map((r) => (r.close == null ? null : Number(r.close)));

    const lastFg = fg[fg.length - 1];
    const mainColor = lastFg == null
        ? '#909399'
        : (lastFg >= 55 ? '#ef4444' : (lastFg <= 45 ? '#12783c' : '#f59e0b'));

    chart.setOption({
        grid: {left: 30, right: 48, top: 14, bottom: 20},
        tooltip: {
            trigger: 'axis',
            formatter: (params) => {
                const d = rows[params[0].dataIndex];
                const v = d.fear_greed == null ? null : Number(d.fear_greed);
                const lv = v == null ? '--' : fearGreedLabel(v);
                return `${d.trade_date}<br/>`
                    + `恐惧贪婪: <b>${v == null ? '--' : v.toFixed(2)}</b>（${lv}）<br/>`
                    + `波动分: ${d.vol_score == null ? '--' : Number(d.vol_score).toFixed(1)}<br/>`
                    + `动量分: ${d.mom_score == null ? '--' : Number(d.mom_score).toFixed(1)}<br/>`
                    + `收盘价: ${d.close == null ? '--' : Number(d.close).toFixed(2)}`;
            }
        },
        xAxis: {type: 'category', data: dates, show: false},
        yAxis: [
            {
                // 左轴：情绪值。有天然量纲 0~100，固定量程 → 读数可与左侧大字直接对照，
                // 也不会因为「本月波动区间很窄」把线放大成一堆锯齿。
                type: 'value',
                min: 0,
                max: 100,
                splitNumber: 2,
                axisLabel: {fontSize: 9, color: '#94a3b8'},
                splitLine: {lineStyle: {color: '#eef1f6'}}
            },
            {
                // 右轴：收盘价。与左轴**完全解耦**的自适应量程（scale: true 不强制含 0），
                // 否则价格线会被 0~100 的左轴压平。
                type: 'value',
                scale: true,
                splitNumber: 2,
                axisLabel: {fontSize: 9, color: '#cbd5e1', formatter: (v) => Number(v).toFixed(2)},
                splitLine: {show: false}
            }
        ],
        series: [
            {
                name: '恐惧贪婪',
                type: 'line',
                yAxisIndex: 0,
                data: fg,
                smooth: true,
                showSymbol: false,
                connectNulls: true,
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
                // 25/50/75 三条档位参考线（与全站恐惧贪婪分档阈值一致）
                markLine: {
                    silent: true,
                    symbol: 'none',
                    label: {show: false},
                    lineStyle: {type: 'dashed', color: '#e2e8f0'},
                    data: [{yAxis: 25}, {yAxis: 50}, {yAxis: 75}]
                }
            },
            {
                name: '收盘价',
                type: 'line',
                yAxisIndex: 1,
                data: close,
                smooth: true,
                showSymbol: false,
                connectNulls: true,
                lineStyle: {width: 1, color: '#64748b', opacity: 0.5, type: 'dotted'}
            }
        ]
    });
};

const resizeFgChart = () => {
    fgChart?.resize();
};

// ========================
// 财务分析（tab4）
// ========================
// 数据源：GET /api/v1/stock/financial_data/{symbol}?report_type=xxx&periods=n
//   后端已解包 {code,data} 信封并摊平 report_table，返回 {items:[{report_date, ...字段}]}（降序）。
//
// 五张报表各有用途，这里只挑「看得懂 + 每期都有值」的核心指标做成卡片 + 趋势图：
//   PershareIndex（每股指标）= 盈利能力的横截面：ROE/毛利率/净利率/负债率/EPS/每股净资产…
//   Income（利润表）      = 规模：营收 / 净利润 / 扣非净利
//   CashFlow（现金流量表）= 含金量：经营现金流净额
//
// ⚠️ 上游 report_table 是「大而全」的扁平字典：不同行业适用的字段不同，不适用的一律为 None
//   （白酒报表里银行的专用科目全是 None）→ 取值必须容忍空值，不能假定字段存在。
//   所以这里的核心指标定义成一张表，缺字段就显示 '--' 而不是渲染出 "undefined"。

const FIN_REPORTS = [
    {label: '每股指标', value: 'PershareIndex'},
    {label: '利润表', value: 'Income'},
    {label: '现金流量表', value: 'CashFlow'},
    {label: '资产负债表', value: 'Balance'},
    {label: '股本结构', value: 'Capital'},
];

// 核心指标：{ key: 上游字段名, name: 展示名, unit: '%' | '元' | '倍' }
// 字段名以实测为准（PershareIndex 里 net_roe=加权ROE、gross_profit=毛利率…）。
const FIN_INDICATORS = {
    PershareIndex: [
        {key: 'net_roe', name: '净资产收益率(ROE)', unit: '%'},
        {key: 'gross_profit', name: '毛利率', unit: '%'},
        {key: 'net_profit', name: '净利率', unit: '%'},
        {key: 'gear_ratio', name: '资产负债率', unit: '%'},
        {key: 's_fa_eps_basic', name: '每股收益', unit: '元'},
        {key: 's_fa_bps', name: '每股净资产', unit: '元'},
        {key: 's_fa_ocfps', name: '每股经营现金流', unit: '元'},
        {key: 'inc_revenue_rate', name: '营收同比增速', unit: '%'},
        {key: 'inc_net_profit_rate', name: '净利同比增速', unit: '%'},
    ],
    Income: [
        {key: 'total_revenue', name: '营业总收入', unit: '元', scale: true},
        {key: 'revenue', name: '营业收入', unit: '元', scale: true},
        {key: 'net_profit', name: '净利润', unit: '元', scale: true},
        {key: 'net_profit_atsopc', name: '归母净利润', unit: '元', scale: true},
        {key: 'deductible_net_profit', name: '扣非净利润', unit: '元', scale: true},
        {key: 'total_profit', name: '利润总额', unit: '元', scale: true},
    ],
    CashFlow: [
        {key: 'net_operate_cash_flow', name: '经营活动现金流净额', unit: '元', scale: true},
        {key: 'net_invest_cash_flow', name: '投资活动现金流净额', unit: '元', scale: true},
        {key: 'net_finance_cash_flow', name: '筹资活动现金流净额', unit: '元', scale: true},
        {key: 'cash_increase', name: '现金净增加额', unit: '元', scale: true},
    ],
    Balance: [
        {key: 'total_assets', name: '总资产', unit: '元', scale: true},
        {key: 'total_liability', name: '总负债', unit: '元', scale: true},
        {key: 'total_owner_equities', name: '股东权益', unit: '元', scale: true},
    ],
    Capital: [
        {key: 'total_capital', name: '总股本', unit: '股', scale: true},
        {key: 'circulating_capital', name: '流通股本', unit: '股', scale: true},
        {key: 'freeFloatCapital', name: '自由流通股本', unit: '股', scale: true},
    ],
};

const fin_report_type = ref('PershareIndex');
const fin_items = ref([]);
const fin_loading = ref(false);
const fin_error = ref('');

// 图表容器与实例（与恐惧贪婪同样的孤儿实例防护——报表切换会重渲染）
const finChartRef = ref(null);
let finChart = null;

const ensureFinChart = () => {
    const host = finChart && finChart.getDom && finChart.getDom();
    if (finChart && host !== finChartRef.value) {
        try {
            finChart.dispose();
        } catch (e) {
            /* ignore */
        }
        finChart = null;
    }
    if (!finChart) {
        if (!finChartRef.value) return null;
        // 容器不可见（宽度/高度为 0）时 init 会画出 0x0 画布 → 拒绝并等下次
        if (!finChartRef.value.clientWidth || !finChartRef.value.clientHeight) return null;
        finChart = echarts.init(finChartRef.value);
    }
    return finChart;
};

// 当前报表对应的核心指标定义
const finIndicators = computed(() => FIN_INDICATORS[fin_report_type.value] || []);

// 最新一期（数组已是降序 → 下标 0）
const finLatest = computed(() => fin_items.value[0] || null);

/** 大额紧凑显示：亿 / 万，避免 12 位数字挤爆卡片 */
const compactMoney = (n) => {
    const abs = Math.abs(n);
    if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
    if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万`;
    return n.toFixed(2);
};

/** 数值格式化：大额（元/股）走紧凑单位，百分比保留两位。 */
const fmtFinValue = (v, unit, scale) => {
    if (v === null || v === undefined || v === '') return '--';
    const n = Number(v);
    if (!Number.isFinite(n)) return '--';
    if (scale) return compactMoney(n);
    if (unit === '%') return `${n.toFixed(2)}%`;
    return n.toFixed(2);
};

/** 报告期格式：2026-03-31 → 2026Q1 / 2025-12-31 → 2025年报 */
const fmtFinPeriod = (d) => {
    if (!d) return '--';
    const [y, m] = String(d).split('-');
    const q = {'03': 'Q1', '06': '中报', '09': 'Q3', '12': '年报'}[m];
    return q ? `${y}${q}` : d;
};

/**
 * 渲染财务趋势图：X=报告期，Y=当前报表前 3 个核心指标（各自独立量纲 → 多轴会很乱，
 * 所以只画**百分比型**指标；元/股类指标量纲差异太大，交给上方卡片展示绝对值）。
 *
 * 若当前报表没有百分比指标（如现金流量表），退回画第一个指标（元），
 * 并直接显示数值不画百分比 —— 有图总比空着好。
 */
const renderFinChart = async () => {
    await nextTick();
    const chart = ensureFinChart();
    if (!chart) return;

    const rows = [...(fin_items.value || [])].reverse(); // 升序：左旧右新
    if (rows.length < 2) {
        chart.clear();
        return;
    }

    const dates = rows.map((r) => fmtFinPeriod(r.report_date));
    // 优先百分比型指标；没有就取前 3 个
    let inds = finIndicators.value.filter((i) => i.unit === '%').slice(0, 3);
    if (!inds.length) inds = finIndicators.value.slice(0, 1);

    const PALETTE = ['#3b82f6', '#f97316', '#10b981', '#8b5cf6'];

    const series = inds.map((ind, idx) => ({
        name: ind.name,
        type: 'line',
        smooth: true,
        showSymbol: true,
        symbolSize: 6,
        connectNulls: true,
        data: rows.map((r) => {
            const v = r[ind.key];
            return v === null || v === undefined ? null : Number(v);
        }),
        lineStyle: {width: 2, color: PALETTE[idx % PALETTE.length]},
        itemStyle: {color: PALETTE[idx % PALETTE.length]},
    }));

    chart.setOption({
        grid: {left: 46, right: 16, top: 30, bottom: 24},
        legend: {top: 0, textStyle: {fontSize: 11, color: '#64748b'}},
        tooltip: {
            trigger: 'axis',
            valueFormatter: (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(2)),
        },
        xAxis: {
            type: 'category',
            data: dates,
            axisLabel: {fontSize: 10, color: '#94a3b8'},
            axisLine: {lineStyle: {color: '#e2e8f0'}},
        },
        yAxis: {
            type: 'value',
            scale: true,
            axisLabel: {fontSize: 10, color: '#94a3b8'},
            splitLine: {lineStyle: {color: '#eef1f6'}},
        },
        series,
    }, true); // notMerge=true：切报表时彻底替换，避免旧 series 残留
};

const resizeFinChart = () => {
    // 页面 resize 时容器可能刚从「隐藏」变为「可见」：
    // 若此前因尺寸为 0 没建成实例，这里补一次 init。
    if (!finChart && finChartRef.value?.clientWidth) {
        renderFinChart();
        return;
    }
    finChart?.resize();
};

/** 当前激活的 tab（用于「切到 tab4 时才首次渲染图表」）。 */
const activeTab = ref('tab1');

/** 拉取财务数据。切换报表时重新取（不同 report_type 是不同接口调用）。 */
const loadFinancialData = async (reportType = fin_report_type.value) => {
    fin_loading.value = true;
    fin_error.value = '';
    try {
        const {data} = await axios.get(`/api/v1/stock/financial_data/${stock_code}`, {
            params: {report_type: reportType, periods: 12},
        });
        // 快速切换报表时丢弃乱序响应（与股票搜索同一个坑）
        if (reportType !== fin_report_type.value) return;
        fin_items.value = Array.isArray(data?.items) ? data.items : [];
        fin_loading.value = false;
        renderFinChart();
    } catch (e) {
        if (reportType !== fin_report_type.value) return;
        fin_items.value = [];
        fin_error.value = e?.response?.status === 401 ? '登录状态已失效，请重新登录' : '财务数据加载失败';
        fin_loading.value = false;
    }
};

const ohlc_data = ref([]);
const ohlc_last = ref({})
const loading = ref(false);
// 各区块独立加载态：先展示「加载中」，数据到位后再切换内容；
// 避免首屏数据未回时因判据为「空」而先闪「无数据」、随后整块跳成真实内容。
const pageLoading = ref(true);     // 标题 + 行情价（核心首屏数据）
const greedLoading = ref(true);    // 恐惧贪婪卡片
const newsLoading = ref(true);     // 新闻动态
const reportsLoading = ref(true);  // 研报数据
const techLoading = ref(true);     // 技术面深度诊断
const {showSuccess, showError} = useNotification();
const stock_code = route.params.symbol;
const stock_profile = ref(null);
const stock_info = ref({
    name: '',
    concepts: ''
});
const watched = ref(false)
// 1. 定义本地存储的键名
const CHART_TYPE_STORAGE_KEY = 'user_chart_type';
const CHART_INDICATOR_STORAGE_KEY = 'user_chart_indicator';
// 2. 修改初始化逻辑：从本地存储读取，如果没有则使用默认值
// 原来的默认值是 'candle_solid'，现在我们动态获取
const defaultType = localStorage.getItem(CHART_TYPE_STORAGE_KEY) || 'candle_up_stroke';
const defaultIndicator = localStorage.getItem(CHART_INDICATOR_STORAGE_KEY) || 'VOL';
const chart_type = ref(defaultType);
const chart_indicator = ref(defaultIndicator)
const dcf_research_report = ref({
    content_text: ""
})
const tech_report = ref(null)
const dcf_research_report_drawer = ref(false)
const fundamental_scores = ref(null)
const research_reports = ref([])
const selected_report = ref(null)
const report_drawer = ref(false)
const report_loading = ref(false)

// 可选：真实历史价格数据
const realHistoryData = ref([])

const optimistic = ref(95)
const neutral = ref(78)
const conservative = ref(55)

const items = [
    {
        label: '重新分析',
        command: () => {
            try {
                axios.put(`/api/v1/stock/re_analysis/${stock_code}`, {});
                showSuccess('已提交重新分析任务');
            } catch (error) {
                let message = '操作失败，请重试';
                if (axios.isAxiosError(error)) {
                    if (error.response) {
                        const {status, data} = error.response;
                        console.error('HTTP 错误:', status, data);

                        if (status === 404) {
                            message = '股票代码不存在';
                        } else if (status === 409) {
                            message = '该股票已在监控列表中';
                        }
                        // 可继续扩展其他业务状态码
                    } else if (error.request) {
                        message = '网络连接失败，请检查网络后重试';
                    } else {
                        console.error('请求配置错误:', error.message);
                        message = '请求出错，请联系管理员';
                    }
                } else {
                    console.error('未知错误:', error);
                    message = '发生未知错误';
                }
                showError(message);
            }
        }
    },
    {
        label: '设置分组',
        command: () => {
            toast.add({severity: 'success', summary: 'Updated', detail: 'Data Updated', life: 3000});
        }
    },
    {
        label: '关闭监控',
        command: () => {
            // === 2. 发起请求 ===
            try {
                axios.put(`/api/v1/stocks/${encodeURIComponent(stock_code)}?is_update_history=0`, {
                    monitoring: 0,
                    monitor_by: 'user',
                });
                router.push({path: '/quant/stock_monitor'});
                showSuccess('操作成功，个股监控已关闭');
            } catch (error) {
                let message = '操作失败，请重试';
                if (axios.isAxiosError(error)) {
                    if (error.response) {
                        const {status, data} = error.response;
                        console.error('HTTP 错误:', status, data);

                        if (status === 404) {
                            message = '股票代码不存在';
                        } else if (status === 409) {
                            message = '该股票已在监控列表中';
                        }
                        // 可继续扩展其他业务状态码
                    } else if (error.request) {
                        message = '网络连接失败，请检查网络后重试';
                    } else {
                        console.error('请求配置错误:', error.message);
                        message = '请求出错，请联系管理员';
                    }
                } else {
                    console.error('未知错误:', error);
                    message = '发生未知错误';
                }
                showError(message);
            }
        }
    }
];

/**
 * 快速回测：把当前标的带到组合回测页并自动执行一次。
 * 组合回测页识别到 ?symbols= 会自己跑一遍（restoreFromQuery），所以这里只负责跳转。
 * 单只标的在「等权买入持有」下就等于这只票的买入持有净值与回撤曲线，
 * 用来快速看历史最大回撤，不必先去那页搜一次代码再点「开始回测」。
 * ⚠️ 只传 symbols：区间 / 基准 / 初始资金沿用组合回测页自己的默认值
 * （近 1 年、沪深300、100 万）——传了 start_date/end_date 反而把它的默认区间钉死。
 */
const goQuickBacktest = () => {
    if (!stock_code) return;
    router.push({path: '/quant/portfolio_backtest', query: {symbols: stock_code}});
};

const echart1 = ref(null)

function render() {
    // ⚠️ 防御：该雷达图依赖基本面评分（/stock/fundamental_scores/{symbol}）。
    // 标的尚未跑过评分任务时接口返回 null，旧代码直接读 null['cash_quality_score']
    // 会抛 TypeError 并中断后续渲染 —— 详情页打开就是一片没画出来的空白。
    // 评分缺失时保留原始分数、各维度记 0，至少把雷达图按「无数据」画出来。
    const fs = fundamental_scores.value || {};
    const score = calcDcfScore(
        ohlc_last.value.close,
        optimistic.value,
        neutral.value,
        conservative.value
    );
    let option = {
        title: {
            text: ''
        },
        textStyle: {fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif', fontSize: 10, color: '#333'},
        legend: {
            data: ['d1']
        },
        radar: {
            indicator: [
                {name: '现金流质量', max: 100},
                {name: 'DCF估值', max: 100},
                {name: '资产负债', max: 100},
                {name: '归母净利润', max: 100},
                {name: '净资产收益率', max: 100}
            ]
        },
        series: [
            {
                name: '',
                type: 'radar',
                data: [
                    {
                        value: [
                            fs['cash_quality_score'] ?? 0,
                            score.finalScore,
                            fs['debt_ratio_score'] ?? 0,
                            fs['profit_growth_score'] ?? 0,
                            fs['roe_score'] ?? 0
                        ],
                        name: ''
                    }
                ],
                symbolSize: 3,
                lineStyle: {
                    width: 2
                }
            }
        ]
    };
    echart1.value.setOption(option)
}

onMounted(async () => {

    window.addEventListener('resize', resizeFgChart);
    window.addEventListener('resize', resizeFinChart);
    stock_info.value = await fetchStockInfo(stock_code);
    stock_profile.value = await fetchStockProfile(stock_code)
    // 获取日K
    ohlc_data.value = await fetchStockMarketData(stock_code);
    // 1. 提取close数组，自动过滤空值/0值（停牌无收盘价的场景）
    realHistoryData.value = ohlc_data.value
        .map(ohlcItem => ohlcItem.close) // 提取每个K线的close字段
        .filter(close => close != null && close > 0); // 过滤空值、停牌0值，避免后续计算报错
    realHistoryData.value = realHistoryData.value.slice(-365 / 2)
    // 最新的一个K线
    ohlc_last.value = ohlc_data.value[ohlc_data.value.length - 1]

    // 核心首屏数据已就绪（标题 + 行情价），关闭首屏 loading，交还价格/标题渲染。
    pageLoading.value = false;

    // 图表显示开关（后端 system_setting 的 chart_display 组，默认关闭 K 线）。
    // ⚠️ 必须在 init('chart') 之前 await 到结果：容器 `#chart` 归 v-if="klineEnabled" 管，
    // 开关还没落地就 init 会拿到 null 直接抛错（页面整片白）。
    // 数据（ohlc_data）照常取 —— 恐贪卡片与 DCF 估值都要用，只是不画 K 线。
    await loadChartDisplay();

    if (klineEnabled.value) {
        // 初始化图表
        chart = init('chart');
        // 3. 使用从本地存储读取的值来初始化图表样式
        chart.setStyles({
            ...chartConfigs, // 如果有其他全局配置，展开它
        });

        // 触发一次k线设置
        changeChartType()
        chart.setSymbol({ticker: stock_code});
        chart.setPeriod({span: 1, type: 'day'});
        chart.setDataLoader({
            getBars: async ({callback, range}) => {
                callback(ohlc_data.value);
            }
        });

        // 设置技术指标
        chart.createIndicator(chart_indicator.value, true, {id: 'candle_pane_vol'});

        // 将指标叠加到蜡烛图窗口
        chart.createIndicator({name: 'EMA', paneId: 'candle_pane'}, true)
    }

    // 加载新闻关联数据
    // ⚠️ 必须显式传 relation_level_only=false：该接口的默认行为是只返回 relation_level > 0 的新闻，
    //    而个人股页需要看到全部关联新闻 —— 否则 relation_level 为 0 / NULL 的会被静默丢弃。
    axios.get('/api/v1/market/search_news', {
        params: {stock_code: stock_code, page_size: 20, relation_level_only: false}
    }).then(response => {
        news.value = response.data?.items || [];
        newsLoading.value = false;
    }).catch(() => {
        newsLoading.value = false;
    });

    // 获取技术分析报告
    axios.get(`/api/v1/stock/tech_analysis_report/${stock_code}`).then(response => {
        tech_report.value = response.data
        techLoading.value = false;
    }).catch(() => {
        techLoading.value = false;
    });

    // 获取DCF分析报告
    axios.get(`/api/v1/stock/dcf_research_report/${stock_code}`).then(response => {
        loading.value = false;
        const dcf = response.data;
        dcf_research_report.value = dcf;
        // ⚠️ 部分标的无 DCF 数据 → response.data 为 null，必须先判空再读 content_json，
        // 否则会抛 "Cannot read properties of null (reading 'content_json')" 并中断后续（基本面评分 / 雷达图）。
        if (dcf && dcf.content_json) {
            neutral.value = parseNumber(dcf.content_json?.每股内在价值?.中性情景)
            optimistic.value = parseNumber(dcf.content_json?.每股内在价值?.乐观情景)
            conservative.value = parseNumber(dcf.content_json?.每股内在价值?.保守情景)
        }

        // 获取基本面评分数据
        axios.get(`/api/v1/stock/fundamental_scores/${stock_code}`).then(response => {
            loading.value = false;
            fundamental_scores.value = response.data

            let chartDom = document.getElementById('el');
            // 容器可能尚未挂载（v-if 未满足）→ init(null) 会抛错；先判空再画。
            if (chartDom) {
                echart1.value = echarts.init(chartDom)
                render()
            }
        });
    });

    // 贪婪与恐惧数据：喂给下方 ECharts 走势卡片 + 左栏信息带
    // ⚠️ 显式传 limit=250（约一年交易日）而不是依赖后端默认值，
    // 避免以后默认值被调整时静默改变图表周期。
    axios.get('/api/v1/stock/greed_data/' + stock_code, {params: {limit: 250}}).then(response => {

        // 后端按 trade_date 倒序返回。「最新值」取第一条，所以保留这份倒序数组给左栏用；
        // 画图时在 renderFearGreedChart 内部再 reverse 成升序。
        // ⚠️ 兼容多种返回形态：裸数组 / {data:[...]} / {items:[...]}，
        // 避免老构建或不同封装下取到空（接口本身返回裸数组，这里兜底即可）。
        const _raw = response.data;
        const _arr = Array.isArray(_raw) ? _raw
            : (_raw && Array.isArray(_raw.data)) ? _raw.data
            : (_raw && Array.isArray(_raw.items)) ? _raw.items
            : [];
        greed_data.value = _arr;

        // 数据到位后渲染走势图（此刻 v-if 才让容器进 DOM，可以 init 了）
        renderFearGreedChart();
        greedLoading.value = false;

    }).catch(() => {
        greedLoading.value = false;
    });

    // 加载研报列表
    axios.get(`/api/v1/stock/research_reports/${stock_code}`).then(response => {
        research_reports.value = response.data || [];
        reportsLoading.value = false;
    }).catch(() => {
        reportsLoading.value = false;
    });

    // 财务分析（tab4）：进页面就先取一次默认报表（每股指标），
    // 切报表时由 watch 触发重取，不必等用户点到 tab4 才开始加载。
    loadFinancialData();

});

// 切换报表 → 重新取数并重绘（不同 report_type 是不同的一次接口调用）
watch(fin_report_type, (val) => {
    loadFinancialData(val);
});

// 切到「财务分析」tab 时才首次渲染趋势图：
// PrimeVue 的 TabPanel 非激活时容器 display:none、clientWidth 为 0，
// 过早 init 会得到 0x0 画布（表现为「图是空的」）。所以数据虽早就取好，
// 图表必须等到 tab 真正可见再画。
watch(activeTab, (val) => {
    if (val === 'tab4') {
        // 容器刚由隐藏变可见，等一帧让布局完成
        nextTick(() => renderFinChart());
    }
});

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

const changeChartIndicator = function () {
    // 技术指标操作
    chart.removeIndicator('candle_pane_vol')
    chart.createIndicator(chart_indicator.value, true, {id: 'candle_pane_vol'});
    chart.createIndicator({name: 'EMA', paneId: 'candle_pane'}, true)
    // 关键：将当前选择的类型保存到本地存储
    localStorage.setItem(CHART_INDICATOR_STORAGE_KEY, chart_indicator.value);
}


const changeChartType = function () {
    chart.setStyles({
        // 蜡烛图
        candle: {
            // 蜡烛图类型 'candle_solid'|'candle_stroke'|'candle_up_stroke'|'candle_down_stroke'|'ohlc'|'area'
            type: chart_type.value
        }
    });
    // 关键：将当前选择的类型保存到本地存储
    localStorage.setItem(CHART_TYPE_STORAGE_KEY, chart_type.value);
}

const showDcfDrawer = function () {
    // 分析数据
    loading.value = true;
    axios.get(`/api/v1/stock/dcf_research_report/${stock_code}`).then(response => {
        loading.value = false;
        dcf_research_report.value = response.data
        if (dcf_research_report.value === null) {
            showError("获取数据失败，DCF估值分析数据为空")
            return
        }
        dcf_research_report_drawer.value = true;
    });
}

const reanalysisDcf = function () {
    try {
        axios.put(`/api/v1/stock/re_analysis_dcf/${stock_code}`, {});
        showSuccess('已提交重新分析任务');
    } catch (error) {
        let message = '操作失败，请重试';
        if (axios.isAxiosError(error)) {
            if (error.response) {
                const {status, data} = error.response;
                console.error('HTTP 错误:', status, data);

                if (status === 404) {
                    message = '股票代码不存在';
                } else if (status === 409) {
                    message = '该股票已在监控列表中';
                }
                // 可继续扩展其他业务状态码
            } else if (error.request) {
                message = '网络连接失败，请检查网络后重试';
            } else {
                console.error('请求配置错误:', error.message);
                message = '请求出错，请联系管理员';
            }
        } else {
            console.error('未知错误:', error);
            message = '发生未知错误';
        }
        showError(message);
    }
}

const viewReport = function (report) {
    report_loading.value = true;
    axios.get(`/api/v1/stock/research_report/${report.id}`).then(response => {
        selected_report.value = response.data;
        report_drawer.value = true;
    }).catch(error => {
        showError('获取研报详情失败');
    }).finally(() => {
        report_loading.value = false;
    });
}

const injectScaleCss = function (htmlContent) {
    const scaleCss = `<style>body { width: 90%; margin: 0 auto; }</style>`;
    if (htmlContent.includes('</head>')) {
        return htmlContent.replace('</head>', scaleCss + '</head>');
    }
    return scaleCss + htmlContent;
}

const getRatingSeverity = function (rating) {
    if (!rating) return 'secondary';
    const r = rating.toLowerCase();
    if (r.includes('买入') || r.includes('buy') || r.includes('强推')) return 'success';
    if (r.includes('增持') || r.includes('推荐')) return 'success';
    if (r.includes('中性') || r.includes('持有')) return 'warning';
    if (r.includes('卖出') || r.includes('减持')) return 'danger';
    return 'secondary';
}


// 恐惧贪婪走独立的 ECharts 卡片，需要自己管 resize（与基本面雷达图一样）；
// klinecharts 那边自己按容器尺寸重建画布，不用管。
onUnmounted(() => {
    dispose('chart');
    window.removeEventListener('resize', resizeFgChart);
    window.removeEventListener('resize', resizeFinChart);
    fgChart?.dispose();
    fgChart = null;
    finChart?.dispose();
    finChart = null;
});

</script>

<template>

    <Toast/>

    <Drawer
        v-model:visible="dcf_research_report_drawer"
        header="DCF估值模型分析报告"
        position="right"
        class="!w-full md:!w-200 lg:!w-[75rem]"
        :footer="false"
        body-class="p-0"
    >
        <!-- 内容容器：使用 flex 布局以便底部固定 -->
        <div class="flex flex-col h-full">

            <!-- 滚动区域 -->
            <div class="flex-1 overflow-y-auto">
                <!-- Markdown 内容 -->
                <span class="text-sm">大模型：{{ dcf_research_report.broker_name }}</span>
                <Divider/>
                <!-- 注意：如果内容很长，确保 MarkdownRenderer 内部没有设置固定高度 -->
                <MarkdownRenderer fontSize="11px" :markdown="dcf_research_report?.content_text || '暂无报告内容'"/>
                <Divider/>
                <div class="text-center text-sm">
                    <b>本报告基于公开数据和特定假设模型构建，不构成任何投资建议。股市有风险，投资需谨慎。</b>
                </div>
                <!-- 底部占位符，防止内容被底部按钮栏遮挡 (如果按钮栏是 absolute/fixed) -->
                <div class="h-4"></div>
            </div>

            <!-- 底部操作栏 -->
            <div class="border-t border-gray-300 p-4 flex justify-between items-center shrink-0">
                <div class="text-xs text-gray-400">
                    最近更新：{{ formatDaysAgo(dcf_research_report?.created_at) || '加载中...' }}
                </div>
                <div class="flex gap-3">
                    <!-- 重新分析按钮 -->
                    <Button
                        @click="reanalysisDcf"
                        variant="solid"
                        class="bg-blue-600 hover:bg-blue-700 text-white shadow-sm"
                        size="small"
                    >重新分析
                    </Button>
                </div>
            </div>
        </div>
    </Drawer>

    <!-- 研报详情抽屉 -->
    <Drawer
        v-model:visible="report_drawer"
        header="研报详情"
        position="right"
        class="!w-full md:!w-200 lg:!w-[100rem]"
        :footer="false"
        body-class="p-0"
    >
        <div class="flex flex-col h-full" v-if="selected_report">
            <!-- 顶部信息区 -->
            <div class="p-4 border-b border-gray-200 shrink-0">
                <h2 class="text-xl font-bold mb-2">{{ selected_report.title }}</h2>
                <div class="flex gap-4 text-sm text-gray-500">
                    <span><i class="pi pi-building"></i> {{ selected_report.broker_name }}</span>
                    <span><i class="pi pi-user"></i> {{ selected_report.analyst_name || '-' }}</span>
                    <span><i class="pi pi-calendar"></i> {{ formatDaysAgo(selected_report.publish_time) }}</span>
                </div>
            </div>

            <!-- iframe 内容区：占满剩余空间 -->
            <div class="flex-1 overflow-hidden">
                <iframe
                    v-if="selected_report.content_text"
                    :srcdoc="injectScaleCss(selected_report.content_text)"
                    class="w-full h-full border-0"
                    sandbox="allow-scripts allow-same-origin"
                />
                <div v-else class="flex items-center justify-center h-full text-gray-400">
                    暂无内容
                </div>
            </div>

            <!-- 底部操作栏 -->
            <div class="border-t border-gray-300 p-4 flex justify-between items-center shrink-0">
                <div class="text-xs text-gray-400">
                    发布时间：{{ formatDaysAgo(selected_report.publish_time) || '加载中...' }}
                </div>
            </div>
        </div>
    </Drawer>

    <div class="card relative mb-0 pb-0" style="padding: 20px 15px;">

        <!-- 标题 -->
        <h1 class="text-2xl font-bold mb-3 text-gray-800">
            <span>{{ stock_info?.name || '加载中...' }} ({{ stock_code }})</span> <i
            class="text-sm font-light">{{ stock_info?.concepts || '加载中...' }}</i>
        </h1>

        <div v-if="pageLoading" class="price-loading">
            <i class="pi pi-spin pi-spinner"></i> 行情加载中...
        </div>
        <h1 class="stock-price" v-else-if="ohlc_data.length > 0" :class="{
                              'text-red-500': ohlc_last['chg_pct'] > 0,
                              'text-green-600': ohlc_last['chg_pct'] < 0,
                              }">
            <span class="text-3xl font-bold">{{ formatCurrency(ohlc_last['close']) }}</span>&nbsp;
            <span class="text-lg">{{ formatCurrency(ohlc_last['change_amount'], true) }}</span>&nbsp;
            <span class="text-lg">{{
                    formatPercentage(ohlc_last['chg_pct'].toFixed(2), true)
                }}%</span>
        </h1>

        <div class="absolute top-8 right-8 action-bar">
            <Button v-tooltip.top="'用这只股票跑一次等权买入持有，直接看净值与最大回撤'"
                    label="快速回测" icon="pi pi-chart-line" size="small" severity="secondary"
                    class="whitespace-nowrap" @click="goQuickBacktest()"></Button>
            <Button label="AI 估值分析" size="small" class="whitespace-nowrap" @click="showDcfDrawer()" :loading="loading"></Button>
            <!-- <Button :label="watched ? '已关注' : '关注'" size="small" @click="toggleLike()" :severity="watched ? '' : 'secondary'"></Button>-->
            <SplitButton label="操作" :model="items" size="small" severity="secondary"/>
        </div>
    </div>

    <Tabs v-model:value="activeTab">
        <TabList style="border-top: 1px solid #eee;">
            <Tab value="tab1">技术面分析</Tab>
            <Tab value="tab2">基本面分析</Tab>
            <Tab value="tab3">新闻动态</Tab>
            <Tab value="tab4">财务分析</Tab>
            <Tab value="tab5">研报数据</Tab>
        </TabList>
        <TabPanels>
            <TabPanel value="tab1">

                <!-- 「走势图表」区块由后端配置 chart_display.kline_enabled 控制（默认关闭，整块隐藏）。
                     注意：区块隐藏但**数据照常加载**（ohlc_data 供恐贪卡片与 DCF 估值使用），
                     所以这里只包渲染、不影响 onMounted 里的取数。 -->
                <div class="mt-5" v-if="klineEnabled">
                    <div class="font-semibold text-lg">
                        <i class="pi pi-wave-pulse text-red-400"></i> 走势图表
                    </div>
                    <Divider/>
                    <div class="w-full md:w-3/3 flex flex-col min-h-0">
                        <div class="card p-0 mb-3">
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
                                data-testid="market-filter"
                                size="small"
                                class="ml-3"
                            />
                        </div>
                    </div>
                    <div id="chart"></div>
                </div>

                <!-- 恐惧贪婪：走势 + 当前读数（与大盘页「成长 vs 价值」同款卡片）。
                     左侧竖排当前值 / 档位 / 日期 / 解读 + 分项迷你条，
                     右侧 ECharts 双轴折线（主曲线=情绪值 0~100，点线=收盘价）。 -->
                <div class="mt-5">
                    <div class="font-semibold text-lg">
                        <i class="pi pi-sun text-orange-500"></i> 恐惧&贪婪指标
                    </div>
                    <Divider/>

                    <div v-if="greedLoading" class="fg-loading">
                        <i class="pi pi-spin pi-spinner"></i> 恐惧贪婪数据加载中...
                    </div>
                    <div v-else-if="greedLatest" class="fg-card fg-body">
                        <!-- 左：当前读数 -->
                        <div class="fg-current">
                            <div class="fg-value" :style="{ color: fearGreedColor(greedLatest.fear_greed) }">
                                {{ Number(greedLatest.fear_greed ?? 0).toFixed(2) }}
                            </div>
                            <div class="fg-label" :style="{ color: fearGreedColor(greedLatest.fear_greed) }">
                                {{ fearGreedLevel(greedLatest.fear_greed).text }}
                            </div>
                            <div class="fg-date">{{ greedLatest.trade_date }}</div>
                            <div class="fg-advice">
                                {{ fearGreedToText(greedLatest.fear_greed).advice }}
                            </div>

                            <!-- 分量拆解：0~100 的迷你条，直观表达两个分项的相对高低 -->
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

                        <!-- 右：近一年情绪走势（副轴叠收盘价点线） -->
                        <div class="fg-chart-wrap">
                            <div class="fg-chart-title">
                                近一年走势（实线 = 恐惧贪婪值，0~100；点线 = 收盘价，右轴）
                            </div>
                            <div ref="fgChartRef" class="fg-chart"></div>
                        </div>
                    </div>
                    <div v-else class="empty-tip">该股票暂无恐惧贪婪数据</div>
                </div>

                <div class="mt-5 fg-loading" v-if="techLoading">
                    <i class="pi pi-spin pi-spinner"></i> 技术面分析加载中...
                </div>
                <div class="mt-5" v-else-if="tech_report">
                    <div class="font-semibold text-lg">
                        <i class="pi pi-chart-line text-green-500"></i> 技术面深度诊断
                    </div>
                    <Divider/>
                    <MarkdownRenderer
                        fontSize="11px"
                        :markdown="dictToMarkdownRecursive(tech_report.content_json['技术面深度诊断'])">
                    </MarkdownRenderer>
                </div>

            </TabPanel>

            <TabPanel value="tab2">

                <div class="mt-5 flex flex-col md:flex-row gap-6">

                    <!-- 左侧 -->
                    <div class="w-full md:w-1/2 flex flex-col">

                        <div class="text-sm text-gray-500 mb-2">
                            公司名：{{ stock_profile?.company_name || '加载中...' }}
                        </div>

                        <div class="text-sm text-gray-500 mb-2">
                            行业：{{ stock_profile?.industry || '加载中...' }}
                        </div>

                        <div class="text-sm text-gray-500 mb-2">
                            实控人：{{ stock_profile?.actual_controller || '加载中...' }}
                        </div>

                        <div class="text-sm text-gray-500 mb-2" v-if="stock_profile?.office_address">
                            地址：{{ stock_profile?.office_address || '加载中...' }}
                        </div>

                        <div class="text-sm text-gray-500 mb-2" v-if="stock_profile?.website">
                            网站：<a :href="'https://' + stock_profile?.website"
                                    target="_blank">{{ stock_profile?.website || '加载中...' }}</a>
                        </div>

                        <div class="text-sm text-gray-500 mb-2">
                            公司介绍：{{ stock_profile?.company_introduction || '加载中...' }}
                        </div>

                        <div class="text-sm text-gray-500 mb-2">
                            经营范围：{{ stock_profile?.business_scope || '加载中...' }}
                        </div>

                    </div>

                    <!-- 右侧 -->
                    <div class="w-full md:w-1/2 flex flex-col">
                        <div ref="el" id="el"></div>
                    </div>

                </div>

                <div class="flex flex-col md:flex-row gap-6 mt-5" v-if="dcf_research_report">

                    <div class="w-full md:w-1/2 flex flex-col">
                        <div class="font-semibold text-lg">
                            <i class="pi pi-chart-line text-green-500"></i> DCF 三情景估值
                        </div>
                        <Divider/>
                        <StockValuationChart
                            v-if="dcf_research_report?.content_json"
                            :data="dcf_research_report?.content_json"
                            :currentPrice="ohlc_last['close']"
                            title=""
                            ratingText=""
                            ratingColor="#f97316"
                            :historyData="realHistoryData"
                        />
                    </div>

                </div>


            </TabPanel>

            <TabPanel value="tab3">
                <DataTable
                    tableStyle="font-size:12px"
                    :value="news"
                    :loading="newsLoading"
                    :paginator="true"
                    :rows="5"
                    dataKey="id"
                    :rowHover="true"
                    filterDisplay="menu"
                    :globalFilterFields="['stock_code']"
                    :showGridlines="false"
                >
                    <template #empty> No data found.</template>
                    <template #loading> 新闻加载中，请稍候...</template>
                    <Column field="stock_name" filterField="stock_name" header="">
                        <template #body="{ data }">
                            <div class="news-item">

                                <div class="news-time">{{ formatDaysAgo(data.news_time) }} <a v-if="data.url !== null"
                                                                                              :href="data.url"
                                                                                              target="_blank"><i
                                    class="pi pi-link"></i></a></div>
                                <p class="news-digest font-semibold text-md" style="padding: 5px 0;">
                                    <Tag v-if="data.news_type === 'report'" severity="danger" class="stock-tag">研</Tag>
                                    {{ data.digest }}
                                </p>

                                <!-- 关联股票 -->
                                <div v-if="data.relations_stocks && data.relations_stocks.length"
                                     class="relations-stocks text-sm">
                                    <strong>关联股票：</strong>
                                    <template v-for="(stock, index) in data.relations_stocks" :key="stock.code">
                                        <Tag v-if="stock.code === stock_code" severity="success" class="stock-tag">
                                            {{ stock.code }} ({{ stock.name }})
                                        </Tag>
                                        <span v-else class="stock-tag">
                                              {{ stock.code }} ({{ stock.name }})
                                            </span>
                                        <span v-if="index < data.relations_stocks.length - 1">、</span>
                                    </template>
                                </div>

                                <!-- 标签 -->
                                <div v-if="data.tags && data.tags.length" class="tags">
                                    <strong>标签：</strong>
                                    <span
                                        v-for="tag in data.tags"
                                        :key="tag"
                                        class="tag-badge"
                                    >{{ tag }}&nbsp;</span>
                                </div>

                                <div class="tags">
                                    <span v-if="data.bullish_level > 0">利多</span>
                                    <span v-if="data.bullish_level < 0">利空</span>：
                                    <Rating :modelValue="data.bullish_level / 2" readonly/>
                                </div>
                            </div>
                        </template>
                    </Column>
                </DataTable>
            </TabPanel>

            <!-- 财务分析：报表切换 + 核心指标卡片 + 趋势图 -->
            <TabPanel value="tab4">
                <div class="mt-5">

                    <div class="font-semibold text-lg">
                        <i class="pi pi-chart-bar text-blue-500"></i> 财务分析
                    </div>
                    <Divider/>

                    <!-- 报表切换（5 种，与后端白名单一致） -->
                    <div class="card p-0 mb-3">
                        <SelectButton
                            v-model="fin_report_type"
                            :options="FIN_REPORTS"
                            optionLabel="label"
                            optionValue="value"
                            size="small"
                            :allowEmpty="false"
                        />
                    </div>

                    <div v-if="fin_loading" class="fin-state">
                        <i class="pi pi-spin pi-spinner"></i> 财务数据加载中...
                    </div>

                    <div v-else-if="fin_error" class="fin-state fin-state--error">
                        <i class="pi pi-exclamation-circle"></i> {{ fin_error }}
                    </div>

                    <div v-else-if="!fin_items.length" class="fin-state">
                        暂无该报表的财务数据
                    </div>

                    <template v-else>

                        <!-- 核心指标卡片：最新一期 -->
                        <div class="fin-cards">
                            <div class="fin-card" v-for="ind in finIndicators" :key="ind.key">
                                <div class="fin-card-label">{{ ind.name }}</div>
                                <div class="fin-card-value">
                                    {{ fmtFinValue(finLatest?.[ind.key], ind.unit, ind.scale) }}
                                </div>
                                <div class="fin-card-date">{{ fmtFinPeriod(finLatest?.report_date) }}</div>
                            </div>
                        </div>

                        <!-- 趋势图 -->
                        <div class="fin-chart-wrap" v-if="fin_items.length >= 2">
                            <div class="fin-chart-title">
                                指标趋势（近 {{ fin_items.length }} 期）
                            </div>
                            <div ref="finChartRef" class="fin-chart"></div>
                        </div>

                        <!-- 明细表：横向滚动，容忍空值 -->
                        <div class="fin-table-wrap">
                            <table class="fin-table">
                                <thead>
                                <tr>
                                    <th class="fin-th-label">报告期</th>
                                    <th v-for="ind in finIndicators" :key="ind.key">{{ ind.name }}</th>
                                </tr>
                                </thead>
                                <tbody>
                                <tr v-for="row in fin_items" :key="row.report_date">
                                    <td class="fin-td-label">
                                        {{ fmtFinPeriod(row.report_date) }}
                                        <span class="fin-td-sub" v-if="row.announce_date">
                                            {{ row.announce_date }} 披露
                                        </span>
                                    </td>
                                    <td v-for="ind in finIndicators" :key="ind.key">
                                        {{ fmtFinValue(row[ind.key], ind.unit, ind.scale) }}
                                    </td>
                                </tr>
                                </tbody>
                            </table>
                        </div>

                    </template>

                </div>
            </TabPanel>

            <TabPanel value="tab5">
                <div class="mt-5">
                    <div class="font-semibold text-lg mb-3">
                        <i class="pi pi-file text-blue-500"></i> 深度研报
                    </div>
                    <DataTable
                        :value="research_reports"
                        :paginator="true"
                        :rows="10"
                        tableStyle="font-size:12px"
                        :rowHover="true"
                        :showGridlines="false"
                        :loading="reportsLoading"
                    >
                        <template #empty>暂无研报数据</template>
                        <template #loading>加载中...</template>

                        <Column field="title" header="标题">
                            <template #body="{ data }">
                                <a @click="viewReport(data)" class="text-blue-600 hover:underline cursor-pointer">
                                    {{ data.title }}
                                </a>
                            </template>
                        </Column>

                        <Column field="broker_name" header="券商" style="width: 250px" />

                        <Column field="publish_time" header="发布时间" style="width: 120px">
                            <template #body="{ data }">
                                {{ formatDaysAgo(data.publish_time) }}
                            </template>
                        </Column>
                    </DataTable>
                </div>
            </TabPanel>
        </TabPanels>
    </Tabs>

</template>

<style scoped lang="scss">

#chart {
    width: 100%;
    /* 350px = 蜡烛图主窗格 + VOL 窗格的合计高度（恐惧贪婪已改为下方独立卡片，
       不再占据 K 线内的子窗格，所以高度回到并入前的值）。 */
    height: 350px;
    border: 1px solid #eee;
    border-radius: 3px
}

.news-item {
    font-size: 0.95rem;
    line-height: 1.5;
}

.news-time {
    color: #666;
    font-weight: bold;
}

.news-digest {
    margin: 4px 0;
}

.relations-stocks,
.tags {
    margin-top: 6px;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
}

.relations-stocks .stock-tag {
    white-space: nowrap;
}

.tags .tag-badge {
    display: inline-block;
    background-color: #e9ecef;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 2px 6px;
    margin-right: 4px;
    margin-top: 2px;
    font-size: 0.85rem;
    color: #495057;
}

.info-icon {
    font-size: 12px;
}

#el {
    margin: 0 auto;
    width: 300px;
    height: 300px
}

/* ========================
   恐惧贪婪：走势卡片（样式对齐大盘页「成长 vs 价值」）
   左栏固定宽 = 当前读数 + 分项条；右栏 flex = ECharts 走势图。
   卡片外壳（白底、圆角、内边距）与大盘页 Card 观感一致。
   ======================== */
.fg-card {
    background: #fff;
    border: 1px solid #eef1f6;
    border-radius: 0.5rem;
    padding: 0.85rem 1.25rem;
}

.fg-body {
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

        .fg-advice {
            font-size: 0.8rem;
            color: #64748b;
            margin-top: 0.3rem;
            text-align: center;
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
                    min-width: 30px;

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
                    text-align: left;
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
        }
    }
}

.empty-tip {
    padding: 2rem 0;
    text-align: center;
    color: #94a3b8;
    font-size: 0.9rem;
}

/* 各区块「加载中」占位：与 .empty-tip 同类观感，避免首屏闪现「无数据」 */
.fg-loading,
.price-loading {
    padding: 2rem 0;
    text-align: center;
    color: #94a3b8;
    font-size: 0.9rem;

    .pi-spinner {
        margin-right: 0.4rem;
        vertical-align: -0.05em;
    }
}

/* 右上角动作区（快速回测 / AI 估值分析 / 操作）：
   absolute 定位是为了与股票名称同行，但按钮一多、窄屏就会压到标题上。
   这里只统一间距与换行；≤768px 改为普通流靠右（scoped 类的属性选择器
   特异性高于 Tailwind 的 .absolute，所以 position: static 能生效）。 */
.action-bar {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: flex-start;
    gap: 0.5rem;
}

/* ========================
   财务分析（tab4）
   指标卡片用 auto-fill 网格：桌面一行 4~5 个，窄屏自动折行，
   避免固定列数在手机上把指标名挤成两行。
   ======================== */
.fin-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 0.75rem;
}

.fin-card {
    background: #fff;
    border: 1px solid #eef1f6;
    border-radius: 0.5rem;
    padding: 0.7rem 0.9rem;

    .fin-card-label {
        font-size: 0.85rem;
        color: #94a3b8;
        line-height: 1.3;
        min-height: 2.2em; /* 两行标签占位，避免卡片高度参差 */
    }

    .fin-card-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #1e293b;
        line-height: 1.2;
        margin-top: 0.25rem;
        white-space: nowrap;
    }

    .fin-card-date {
        font-size: 0.75rem;
        color: #cbd5e1;
        margin-top: 0.15rem;
    }
}

.fin-chart-wrap {
    margin-top: 1rem;
    background: #fff;
    border: 1px solid #eef1f6;
    border-radius: 0.5rem;
    padding: 0.75rem 1rem 0.5rem;

    .fin-chart-title {
        font-size: 0.9rem;
        font-weight: 600;
        color: #475569;
        margin-bottom: 0.25rem;
    }

    .fin-chart {
        width: 100%;
        height: 320px;
    }
}

.fin-state {
    padding: 2rem 0;
    text-align: center;
    color: #94a3b8;
    font-size: 0.9rem;

    &.fin-state--error {
        color: #ef4444;
    }
}

/* 明细表：期数多、指标多 → 横向滚动，不换行挤压 */
.fin-table-wrap {
    margin-top: 1rem;
    overflow-x: auto;
    border: 1px solid #eef1f6;
    border-radius: 0.5rem;
}

.fin-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    white-space: nowrap;

    th,
    td {
        padding: 0.5rem 0.75rem;
        text-align: right;
        border-bottom: 1px solid #f1f5f9;
        color: #334155;
    }

    thead th {
        background: #f8fafc;
        color: #64748b;
        font-weight: 600;
        position: sticky;
        top: 0;
        z-index: 1;
    }

    tbody tr:hover td {
        background: #f8fafc;
    }

    tbody tr:last-child td {
        border-bottom: none;
    }

    .fin-th-label,
    .fin-td-label {
        text-align: left;
        font-weight: 600;
        color: #1e293b;
        position: sticky;
        left: 0;
        background: #fff;
    }

    thead .fin-th-label {
        background: #f8fafc;
    }

    .fin-td-sub {
        display: block;
        font-size: 0.7rem;
        font-weight: 400;
        color: #cbd5e1;
    }
}

/* 窄屏：右上角动作区改为普通流；恐惧贪婪卡片由「左值 + 右图」改为上下堆叠
   （300px 定宽左栏在手机上会把图表挤没），图表给一个保底高度。 */
@media (max-width: 768px) {
    .action-bar {
        position: static;
        margin-bottom: 0.5rem;
    }

    .fg-body {
        flex-direction: column;
        gap: 0.75rem;

        .fg-current {
            flex: 0 0 auto;
            width: 100%;
        }

        .fg-chart-wrap .fg-chart {
            min-height: 180px;
        }
    }

    .fin-cards {
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    }

    .fin-chart-wrap .fin-chart {
        height: 240px;
    }
}

</style>
