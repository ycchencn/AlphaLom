<script setup>

import {computed, onMounted, onUnmounted, watch, nextTick} from 'vue';
import {init, dispose} from 'klinecharts';
import {ref} from 'vue';
import {useRoute} from 'vue-router';
import {chartConfigs} from '@/utils/constants.js';
// DCF 三情景估值图：ECharts 版（旧手绘 SVG 版 StockValuationChart.vue 保留，可随时切回）
import StockValuationChart from '@/components/StockValuationChartEcharts.vue'
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
    retailSentimentLevel,
    sentimentConfidenceLevel,
    formatCurrency,
    formatPercentage,
    calcDcfScore,
    parseNumber
} from '@/utils/function.js';
import MarkdownRenderer from '@/components/MarkdownRenderer.vue';
import {useChartDisplay} from '@/composables/useChartDisplay.js';
import axios from 'axios';
import {useNotification} from '@/composables/useNotification';
import PriceRange52Week from '@/components/PriceRange52Week.vue';
import FactorPanel from '@/components/FactorPanel.vue';
import router from '@/router'
import NavSidePanel from '@/components/NavSidePanel.vue'
import StockAgentChat from '@/components/stock/StockAgentChat.vue';
import * as echarts from 'echarts'
import {
    COLORS, LINE, FONT, PALETTE,
    axisLabel, splitLine, tooltipBase, lineSeriesStyle, markLevels, areaGradient, registerThemeRedraw,
} from '@/utils/echartsTheme'

let chart = ref(null)
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
const renderFearGreedChart = async (attempt = 0) => {
    await nextTick();
    const chart = ensureFgChart();
    if (!chart) {
        // 容器尚未就绪（v-if 刚切换 / 父级过渡动画未结束 / 首帧布局未完成）→
        // ensureFgChart 会因 clientWidth/Height 为 0 返回 null，图就永远空白。
        // 用 requestAnimationFrame 重试（最多 ~0.5s），容器可测后再画，避免「数据到了图却空白」。
        if (attempt < 30) requestAnimationFrame(() => renderFearGreedChart(attempt + 1));
        return;
    }

    const rows = [...(greed_data.value || [])].reverse();
    if (!rows.length) {
        chart.clear();
        return;
    }
    const dates = rows.map((r) => r.trade_date);
    const fg = rows.map((r) => (r.fear_greed == null ? null : Number(r.fear_greed)));
    const close = rows.map((r) => (r.close == null ? null : Number(r.close)));

    const lastFg = fg[fg.length - 1];
    // ⚠️ ECharts 不吃 CSS 变量，必须走 COLORS（统一涨跌色 + 随暗黑模式切换）
    const mainColor = lastFg == null
        ? COLORS.flat
        : (lastFg >= 55 ? COLORS.up : (lastFg <= 45 ? COLORS.down : COLORS.warn));

    chart.setOption({
        grid: {left: 30, right: 48, top: 14, bottom: 20},
        tooltip: tooltipBase({
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
        }),
        xAxis: {type: 'category', data: dates, show: false},
        yAxis: [
            {
                // 左轴：情绪值。有天然量纲 0~100，固定量程 → 读数可与左侧大字直接对照，
                // 也不会因为「本月波动区间很窄」把线放大成一堆锯齿。
                type: 'value',
                min: 0,
                max: 100,
                splitNumber: 2,
                axisLabel: axisLabel(),
                splitLine: splitLine()
            },
            {
                // 右轴：收盘价。与左轴**完全解耦**的自适应量程（scale: true 不强制含 0），
                // 否则价格线会被 0~100 的左轴压平。
                type: 'value',
                scale: true,
                splitNumber: 2,
                axisLabel: axisLabel({color: COLORS.axisLabelThin, formatter: (v) => Number(v).toFixed(2)}),
                splitLine: splitLine({show: false})
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
                ...lineSeriesStyle({color: mainColor, shadow: false}),
                areaStyle: {
                    color: areaGradient(mainColor, 0.22, 0.02)
                },
                // 25/50/75 三条档位参考线（与全站恐惧贪婪分档阈值一致）
                markLine: markLevels([25, 50, 75])
            },
            {
                name: '收盘价',
                type: 'line',
                yAxisIndex: 1,
                data: close,
                smooth: true,
                showSymbol: false,
                connectNulls: true,
                ...lineSeriesStyle({color: COLORS.secondary, width: LINE.secondary, type: 'dotted', opacity: 0.5, shadow: false})
            }
        ]
    });
};

const resizeFgChart = () => {
    fgChart?.resize();
};

// ========================
// 散户情绪（tab7）—— 东财股吧发帖 + LLM 三分类
// ========================
// 数据源：GET /api/v1/stock/retail_sentiment/{symbol}
//   { symbol, latest, history:[...按 trade_date 倒序], meta }
//
// ⚠️ 与上方「恐惧贪婪」不是同一个指标，绝不能共用文案：
//   恐惧贪婪 = 价量指标算出的技术性情绪；散户情绪 = 股吧文本的语义倾向。
//   两者背离才是有效信号，所以这里单独画一条线、单独一套档位。
//
// ⚠️ 该接口刻意未加服务端缓存（数据每日一条，查询很轻），
//   但**只能靠每日 job 更新**，页面不会自动触发抓取 —— 手动刷新走 PUT 接口。
const sentimentData = ref([]);
const sentimentLoading = ref(false);
const sentimentLoaded = ref(false);
const sentimentLatest = computed(() => sentimentData.value[0] || null);
/** 置信度分档（前端视觉降级：证据不足时不把结论显示得像确定的事实）。 */
const sentimentConf = computed(() => sentimentConfidenceLevel(sentimentLatest.value?.confidence));
/** 收盘价映射 date -> close，用于双轴叠加看背离。数据复用 tab1 已取的 `ohlc_data`
 *  （来自 /stock_history，字段 date='YYYY-MM-DD' + close），不再额外发请求。 */
const closeByDate = ref({});

const sentimentChartRef = ref(null);
let sentimentChart = null;

/**
 * 取（或重建）ECharts 实例。
 * 容器在 v-if 分支内，切 tab 才进 DOM；被销毁后旧实例的 getDom() 已脱离文档，
 * 必须 dispose 重建，否则图表挂在不存在的 DOM 上（页面上表现为空白）。
 */
const ensureSentimentChart = () => {
    if (!sentimentChartRef.value) return null;
    if (sentimentChart && sentimentChart.getDom() !== sentimentChartRef.value) {
        sentimentChart.dispose();
        sentimentChart = null;
    }
    if (!sentimentChart) {
        // v-show 隐藏时 clientWidth/Height 为 0，init 会得到 0x0 画布 → 图空白
        if (!sentimentChartRef.value.clientWidth || !sentimentChartRef.value.clientHeight) return null;
        sentimentChart = echarts.init(sentimentChartRef.value);
    }
    return sentimentChart;
};

/** 取「不晚于 date 的最近一个交易日收盘价」。
 *  情绪数据按自然日采（周末也有），而行情只有交易日 —— 直接按日期字符串配对会大片落空，
 *  必须向前回溯到最近的交易日。
 *  `ohlc_data` 定义在本文件靠后位置，此处只在函数体内引用（调用时早已初始化）。 */
const closeOnOrBefore = (date) => {
    if (!date) return null;
    const rows = ohlc_data.value || [];
    let hit = null;
    for (const r of rows) {
        const d = String(r.date || '').slice(0, 10);
        if (d && d <= date) {
            if (!hit || d > hit.date) hit = {date: d, close: r.close};
        }
    }
    return hit && hit.close != null ? Number(hit.close) : null;
};

const renderSentimentChart = async (attempt = 0) => {
    await nextTick();
    const chart = ensureSentimentChart();
    if (!chart) {
        if (attempt < 30) requestAnimationFrame(() => renderSentimentChart(attempt + 1));
        return;
    }

    // 后端 desc → 画图需升序，否则 X 轴时间整体镜像
    const rows = [...(sentimentData.value || [])].reverse();
    if (!rows.length) {
        chart.clear();
        return;
    }

    const dates = rows.map((r) => String(r.trade_date || '').slice(5));
    const scores = rows.map((r) => (r.sentiment_score == null ? null : Number(r.sentiment_score)));
    const closes = rows.map((r) => closeOnOrBefore(String(r.trade_date || '').slice(0, 10)));

    const lastScore = scores[scores.length - 1];
    const mainColor = lastScore == null ? COLORS.flat : retailSentimentLevel(lastScore).color;

    chart.setOption({
        grid: {left: 36, right: 52, top: 26, bottom: 22},
        legend: {
            top: 0, itemWidth: 12, itemHeight: 8,
            textStyle: {fontSize: FONT.legend, color: COLORS.secondary},
        },
        tooltip: tooltipBase({
            valueFormatter: (v) => (v == null ? '--' : Number(v).toFixed(2)),
        }),
        xAxis: {
            type: 'category',
            data: dates,
            axisLabel: axisLabel({fontSize: FONT.label}),
            axisLine: {lineStyle: {color: COLORS.axis}},
        },
        yAxis: [
            {
                type: 'value', name: '情绪', min: 0, max: 100,
                axisLabel: axisLabel({fontSize: FONT.label}),
                splitLine: splitLine(),
            },
            {
                // 价格量纲与情绪分差两个数量级，必须 scale 自适应，否则价格线被压成直线
                type: 'value', name: '收盘价', scale: true,
                axisLabel: axisLabel({fontSize: FONT.label}),
                splitLine: {show: false},
            },
        ],
        series: [
            {
                name: '散户情绪分',
                type: 'line',
                smooth: true,
                showSymbol: rows.length <= 40,
                symbolSize: 4,
                connectNulls: true,
                data: scores,
                ...lineSeriesStyle({color: mainColor, width: LINE.primary}),
                areaStyle: areaGradient(mainColor, 0.16),
                // 20/40/60/80 是「极度看空 / 偏空 / 中性 / 偏多 / 极度看多」的分界
                markLine: {
                    silent: true,
                    symbol: 'none',
                    lineStyle: {color: COLORS.axis, type: 'dashed', opacity: 0.5},
                    label: {show: false},
                    data: [{yAxis: 40}, {yAxis: 60}, {yAxis: 80}],
                },
            },
            {
                name: '收盘价',
                type: 'line',
                yAxisIndex: 1,
                smooth: true,
                showSymbol: false,
                connectNulls: true,
                data: closes,
                lineStyle: {color: COLORS.flat, width: LINE.secondary, type: 'dotted', opacity: 0.65},
                itemStyle: {color: COLORS.flat},
            },
        ],
    }, true);
    chart.resize();
};

/** 拉取情绪数据。
 *  收盘价直接复用 tab1 已取的 `ohlc_data`（K 线数据，即便关闭 K 线显示也会照常加载）；
 *  仅当它为空时才补取一次 /stock_history。行情失败不影响情绪曲线展示。 */
const loadSentiment = async () => {
    if (!stock_code) return;
    sentimentLoading.value = true;
    try {
        const res = await axios.get(`/api/v1/stock/retail_sentiment/${stock_code}`, {params: {limit: 60}});
        const payload = res.data || {};
        sentimentData.value = Array.isArray(payload.history) ? payload.history : [];

        if (!(ohlc_data.value || []).length) {
            try {
                const his = await axios.get(`/api/v1/stock_history/${stock_code}`);
                if (Array.isArray(his.data)) ohlc_data.value = his.data;
            } catch (e) {
                // 行情取不到只影响双轴里的收盘价线，情绪曲线本身仍然可看
            }
        }
    } catch (e) {
        sentimentData.value = [];
    } finally {
        sentimentLoading.value = false;
        sentimentLoaded.value = true;
    }
};

/** 手动触发重算（走 PUT 接口 → 投递队列 → 抓取 + LLM，约 5~25 秒）。 */
const sentimentRefreshing = ref(false);
const refreshSentiment = async () => {
    if (sentimentRefreshing.value) return;
    sentimentRefreshing.value = true;
    try {
        await axios.put(`/api/v1/stock/retail_sentiment/${stock_code}`);
        showSuccess('已提交分析任务', '股吧抓取与大模型分析约需 5~25 秒，稍后刷新查看');
    } catch (e) {
        showError('提交失败', '请稍后重试');
    } finally {
        sentimentRefreshing.value = false;
    }
};

const resizeSentimentChart = () => {
    sentimentChart?.resize();
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

// 报告期筛选选项（按 report_date 月份识别：03→Q1 06→中报 09→Q3 12→年报）
const FIN_PERIOD_FILTERS = [
    {label: '全部', value: 'all'},
    {label: '一季报', value: 'Q1'},
    {label: '中报', value: 'H1'},
    {label: '三季报', value: 'Q3'},
    {label: '年报', value: 'FY'},
];

// 时间范围（periods）：近 N 期；全部=300 覆盖全历史（后端 le=300）
const FIN_PERIOD_OPTIONS = [
    {label: '近3年', value: 12},
    {label: '近5年', value: 20},
    {label: '近10年', value: 40},
    {label: '全部', value: 300},
];

// 核心指标：{ key: 上游字段名, name: 展示名, unit: '%' | '元' | '倍' }
// ⚠️ 字段名必须与上游 report_table 真实 schema 一致（2026-10-09 全量实测过 5 张报表）。
//   曾经 Income/CashFlow/Balance 的 key 是想当然写的（total_revenue/net_operate_cash_flow/total_assets
//   等），上游根本没有这些字段 → 卡片/表格/趋势图全渲染 '--'（每股指标当初实测过所以一直正常）。
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
        {key: 'revenue', name: '营业收入', unit: '元', scale: true},
        {key: 'oper_profit', name: '营业利润', unit: '元', scale: true},
        {key: 'tot_profit', name: '利润总额', unit: '元', scale: true},
        {key: 'net_profit_incl_min_int_inc', name: '净利润', unit: '元', scale: true},
        {key: 'net_profit_excl_min_int_inc', name: '归母净利润', unit: '元', scale: true},
        {key: 's_fa_eps_basic', name: '每股收益', unit: '元'},
    ],
    CashFlow: [
        {key: 'net_cash_flows_oper_act', name: '经营活动现金流净额', unit: '元', scale: true},
        {key: 'net_cash_flows_inv_act', name: '投资活动现金流净额', unit: '元', scale: true},
        {key: 'net_cash_flows_fnc_act', name: '筹资活动现金流净额', unit: '元', scale: true},
        {key: 'net_incr_cash_cash_equ', name: '现金净增加额', unit: '元', scale: true},
    ],
    Balance: [
        {key: 'tot_assets', name: '总资产', unit: '元', scale: true},
        {key: 'tot_liab', name: '总负债', unit: '元', scale: true},
        {key: 'tot_shrhldr_eqy_excl_min_int', name: '股东权益(归母)', unit: '元', scale: true},
    ],
    Capital: [
        {key: 'total_capital', name: '总股本', unit: '股', scale: true},
        {key: 'circulating_capital', name: '流通股本', unit: '股', scale: true},
        {key: 'freeFloatCapital', name: '自由流通股本', unit: '股', scale: true},
    ],
};

const fin_report_type = ref('PershareIndex');
const fin_items = ref([]);
// 报告期筛选：全部 / 一季报(Q1) / 中报(H1) / 三季报(Q3) / 年报(FY)
const fin_period_filter = ref('FY');
// 时间范围（periods）：控制后端取数期数；默认近10年(40)，全部=300 覆盖全历史
const fin_periods = ref(40);
const fin_loading = ref(false);
const fin_error = ref('');
// 趋势图当前选中的指标 key（点击卡片切换）；为空时回落到该报表首个百分比指标
const finSelectedKey = ref('');

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

// 报告期类型识别（按 report_date 月份，与 fmtFinPeriod 一致）：03→Q1 06→中报 09→Q3 12→年报
const PERIOD_MONTH = {Q1: '03', H1: '06', Q3: '09', FY: '12'};
const finPeriodType = (d) =>
    ({'03': 'Q1', '06': 'H1', '09': 'Q3', '12': 'FY'}[String(d).split('-')[1]] || 'all');

// 按报告期筛选后的展示列表（全部 / 指定季报中报年报），纯前端过滤，不重取数据
const finDisplayItems = computed(() => {
    if (fin_period_filter.value === 'all') return fin_items.value;
    const m = PERIOD_MONTH[fin_period_filter.value];
    return fin_items.value.filter((r) => String(r.report_date).split('-')[1] === m);
});

// 最新一期（数组已是降序 → 下标 0）；跟随报告期筛选
const finLatest = computed(() => finDisplayItems.value[0] || null);

// 趋势图当前要画的指标：优先取 finSelectedKey 命中的；未选中/选中项不在当前报表则回落
// 到该报表首个百分比指标（否则首条）。报表切换时 resetFinSelection 会重设 finSelectedKey。
const finActiveIndicator = computed(() => {
    const list = finIndicators.value;
    if (!list.length) return null;
    const hit = list.find((i) => i.key === finSelectedKey.value);
    if (hit) return hit;
    return list.find((i) => i.unit === '%') || list[0];
});

// 选中某指标卡片 → 重绘趋势图（数据已全量加载，纯前端切换）
const selectFinIndicator = (key) => {
    finSelectedKey.value = key;
    renderFinChart();
};

// 报表切换时把选中项重置到该报表的默认指标（首个百分比项），避免沿用上一张报表的 key
const resetFinSelection = () => {
    const list = finIndicators.value;
    const def = list.find((i) => i.unit === '%') || list[0];
    finSelectedKey.value = def ? def.key : '';
};

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
 * 渲染财务趋势图：只画**当前选中的指标**（finActiveIndicator）。
 * 点击上方指标卡片 → selectFinIndicator 切换 finSelectedKey → 重绘。
 * 量纲单一（只有一条线），Y 轴直接按该指标数值缩放。
 */
const renderFinChart = async () => {
    await nextTick();
    const chart = ensureFinChart();
    if (!chart) return;

    const ind = finActiveIndicator.value;
    const rows = [...(finDisplayItems.value || [])].reverse(); // 升序：左旧右新
    if (!ind || rows.length < 2) {
        chart.clear();
        return;
    }

    const dates = rows.map((r) => fmtFinPeriod(r.report_date));
    const isPct = ind.unit === '%';

    const series = [{
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
        ...lineSeriesStyle({color: PALETTE[0], width: LINE.primary, shadow: false}),
        itemStyle: {color: PALETTE[0]},
    }];

    chart.setOption({
        grid: {left: 46, right: 16, top: 30, bottom: 24},
        legend: {top: 0, textStyle: {fontSize: FONT.legend, color: COLORS.secondary}},
        tooltip: tooltipBase({
            valueFormatter: (v) => (v === null || v === undefined
                ? '--'
                : isPct ? `${Number(v).toFixed(2)}%` : Number(v).toFixed(2)),
        }),
        xAxis: {
            type: 'category',
            data: dates,
            axisLabel: axisLabel({fontSize: FONT.label}),
            axisLine: {lineStyle: {color: COLORS.axisLine}},
        },
        yAxis: {
            type: 'value',
            scale: true,
            axisLabel: axisLabel({fontSize: FONT.label}),
            splitLine: splitLine(),
        },
        series,
    }, true); // notMerge=true：切报表/切指标时彻底替换，避免旧 series 残留
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

// 左侧导航面板（NavSidePanel）的跳转项：与原来的 5 个 Tab 一一对应。
// 「因子分析」是新拆出的 Tab：把原技术面分析里的因子看板 / 因子雷达 / 横向对比
// 独立出来（技术面分析只保留 K 线 + 仪表盘 + 恐贪 + 深度诊断），见 FactorPanel 的 mode 参数。
const tabItems = [
    { key: 'tab1', label: '技术面分析' },
    { key: 'tab6', label: '因子分析' },
    { key: 'tab2', label: '基本面分析' },
    { key: 'tab3', label: '新闻动态' },
    // 散户情绪：东财股吧发帖的 LLM 语义分析（与「恐惧贪婪」是两个不同指标，见卡片说明）
    { key: 'tab7', label: '散户情绪' },
    { key: 'tab4', label: '财务分析' },
    { key: 'tab5', label: '研报数据' },
];
const onTabSelect = (key) => {
    activeTab.value = key;
};

/** 拉取财务数据。切换报表时重新取（不同 report_type 是不同接口调用）。 */
const loadFinancialData = async (reportType = fin_report_type.value) => {
    fin_loading.value = true;
    fin_error.value = '';
    try {
        const {data} = await axios.get(`/api/v1/stock/financial_data/${stock_code}`, {
            params: {report_type: reportType, periods: fin_periods.value},
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
// PE-TTM 估值（仅 A 股）：latest 顶部报价用，history 基本面走势图用。
// 数据来自 /api/v1/stock/pe_ttm/{symbol}（日更任务每日盘后落库，见后端说明）。
const pe_ttm = ref(null);
// 是否 A 股：`stocks.market` 为 'cn' 才展示 PE-TTM（上游只对 A 股提供估值）。
const is_cn_stock = computed(() => (stock_info.value?.market || 'cn') === 'cn');
// 顶部报价的 PE-TTM 最新值（取最新一条，无数据时 null）
const peTtmLatest = computed(() => pe_ttm.value?.latest?.pe_ttm ?? null);
const peTtmDate = computed(() => pe_ttm.value?.latest?.trade_date ?? null);

async function loadPeTtm() {
    try {
        const {data} = await axios.get(`/api/v1/stock/pe_ttm/${stock_code}`, {params: {limit: 600}});
        pe_ttm.value = data ?? null;
    } catch (e) {
        // 接口挂了保持空态（顶部不显示 PE-TTM、走势图显示空态），不影响本页其它区块
        pe_ttm.value = null;
    }
    // 数据到位后画基本面走势图；容器在 v-show 的 tab2 里，切到该 tab 时由 activeTab watch 重绘
    renderPeTtmChart();
}

// ==================== PE-TTM 走势图（基本面分析 tab）====================
const peTtmChartRef = ref(null);
let peTtmChart = null;

const ensurePeTtmChart = () => {
    const host = peTtmChart && peTtmChart.getDom && peTtmChart.getDom();
    if (peTtmChart && host !== peTtmChartRef.value) {
        try { peTtmChart.dispose(); } catch (e) { /* ignore */ }
        peTtmChart = null;
    }
    if (!peTtmChart) {
        if (!peTtmChartRef.value) return null;
        // 容器不可见（v-show 非激活）时 init 会画出 0x0 画布 → 拒绝并等切 tab 后重绘
        if (!peTtmChartRef.value.clientWidth || !peTtmChartRef.value.clientHeight) return null;
        peTtmChart = echarts.init(peTtmChartRef.value);
    }
    return peTtmChart;
};

const renderPeTtmChart = async () => {
    await nextTick();
    const chart = ensurePeTtmChart();
    if (!chart) return;
    // 仅 A 股才画（非 A 股没有数据，history 为空）；单点也画（标记当前位置）
    const rows = pe_ttm.value?.history || [];
    if (!is_cn_stock.value || rows.length < 1) {
        chart.clear();
        return;
    }
    const dates = rows.map((r) => String(r.trade_date).slice(5)); // MM-DD，短标签
    const series = [{
        name: 'PE-TTM',
        type: 'line',
        smooth: true,
        showSymbol: rows.length <= 120,
        symbolSize: 4,
        connectNulls: true,
        data: rows.map((r) => (r.pe_ttm == null ? null : Number(r.pe_ttm))),
        ...lineSeriesStyle({color: PALETTE[2], width: LINE.primary, shadow: false}),
        itemStyle: {color: PALETTE[2]},
        areaStyle: areaGradient(PALETTE[2], 0.18),
    }];
    chart.setOption({
        grid: {left: 46, right: 16, top: 30, bottom: 24},
        legend: {top: 0, textStyle: {fontSize: FONT.legend, color: COLORS.secondary}},
        tooltip: tooltipBase({
            valueFormatter: (v) => (v === null || v === undefined ? '--' : `${Number(v).toFixed(2)}x`),
        }),
        xAxis: {
            type: 'category',
            data: dates,
            axisLabel: axisLabel({fontSize: FONT.label}),
            axisLine: {lineStyle: {color: COLORS.axisLine}},
        },
        yAxis: {
            type: 'value',
            name: 'PE-TTM',
            axisLabel: axisLabel({fontSize: FONT.label}),
            splitLine: splitLine(),
        },
        series,
    }, true);
    chart.resize();
};

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
const agentChatVisible = ref(false)
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

/* ============ 基本面分析 tab 辅助：评分维度明细 / 估值结论摘要 ============ */
const reAnalyzing = ref(false)

/** 雷达图 5 个维度的实际分值（与 render() 中雷达 indicator 一一对应） */
const scoreDimensions = computed(() => {
    const fs = fundamental_scores.value || {}
    const dcfScore = calcDcfScore(
        ohlc_last.value?.close ?? 0, optimistic.value, neutral.value, conservative.value
    ).finalScore
    return [
        { key: 'cash', label: '现金流质量', value: fs.cash_quality_score ?? null },
        { key: 'dcf', label: 'DCF估值', value: Number.isFinite(dcfScore) ? Math.round(dcfScore) : null },
        { key: 'debt', label: '资产负债', value: fs.debt_ratio_score ?? null },
        { key: 'profit', label: '归母净利润', value: fs.profit_growth_score ?? null },
        { key: 'roe', label: '净资产收益率', value: fs.roe_score ?? null },
    ]
})
const hasScores = computed(() => scoreDimensions.value.some(d => d.value != null && d.value !== 0))

/** 评分着色：高=红（优）/ 中=橙 / 低=绿（弱），与全站「涨红跌绿、利好=红」一致 */
const scoreColor = (v) => {
    if (v == null) return COLORS.secondary
    if (v >= 75) return COLORS.up
    if (v >= 50) return COLORS.warn
    return COLORS.down
}

/** DCF 估值结论摘要（复用 dcf_research_report.content_json，与下方图表同源） */
const dcfCurrentPrice = computed(() =>
    parseNumber(dcf_research_report.value?.content_json?.当前股价) || ohlc_last.value?.close || 0
)
const dcfNeutralValue = computed(() =>
    parseNumber(dcf_research_report.value?.content_json?.每股内在价值?.中性情景)
)
const dcfMarginPct = computed(() => {
    const p = dcfCurrentPrice.value
    const v = dcfNeutralValue.value
    if (!p || !v) return null
    return Number(((v - p) / p * 100).toFixed(1))
})
const marginColor = computed(() => {
    const m = dcfMarginPct.value
    if (m == null) return COLORS.secondary
    return m >= 0 ? COLORS.up : COLORS.down
})
const valuationVerdict = computed(() => dcf_research_report.value?.content_json?.估值判断 || '—')
const verdictSeverity = computed(() => {
    const t = valuationVerdict.value || ''
    if (t.includes('低估')) return 'success'
    if (t.includes('泡沫') || t.includes('高估')) return 'danger'
    if (t.includes('合理')) return 'info'
    return 'warn'
})
const fmtPrice = (v) => (v ? '¥' + Number(v).toFixed(2) : '—')

// ==================== 个股分析可选智能体 ====================
// 「重新分析 / 重新分析 DCF」时可指定一个「属于当前用户」的智能体来驱动大模型分析
// （persona = 该智能体的 system_prompt，模型 = 其 platform/model）。不指定则走系统默认场景。
// 选择用 localStorage 记忆（会话级偏好，契合项目现有的偏好持久化模式）。
const agents = ref([])
const agentsLoading = ref(false)
const STORAGE_AGENT_KEY = 'stock_analysis_agent_id'
const selectedAgentId = ref(
    localStorage.getItem(STORAGE_AGENT_KEY)
        ? Number(localStorage.getItem(STORAGE_AGENT_KEY))
        : null
)

function fetchAgents() {
    agentsLoading.value = true
    return axios.get('/api/v1/agents')
        .then((response) => {
            agents.value = response.data?.data || []
        })
        .catch(() => {
            agents.value = []
        })
        .finally(() => {
            agentsLoading.value = false
        })
}

watch(selectedAgentId, (v) => {
    if (v) localStorage.setItem(STORAGE_AGENT_KEY, String(v))
    else localStorage.removeItem(STORAGE_AGENT_KEY)
})

const reAnalyze = () => {
    if (reAnalyzing.value) return
    reAnalyzing.value = true
    axios.put(`/api/v1/stock/re_analysis/${stock_code}`, {agent_id: selectedAgentId.value || null})
        .then(() => showSuccess('已提交重新分析任务'))
        .catch(() => showError('操作失败，请重试'))
        .finally(() => { reAnalyzing.value = false })
}

// ==================== 股票池分组（标签式 group_name）====================
// 与「个股监控」页共用同一套后端接口，分组就是 user_stock_pool.group_name 标签：
//   GET /stock/group/{symbol}  本票「在不在我的池中 + 当前分组」
//   GET /stock/groups          可选分组（含每组股票数）
//   PUT /stock/group           已在池中 → 只改标签（轻量，不动监控状态、不触发分析）
//   PUT /stocks/{symbol}       不在池中 → 「加入监控 + 归类」一步到位
//
// ⚠️ 详情页可由任意入口打开（搜索 / 新闻 / 研报跳转），这只票**未必在用户池里**，
//    而 PUT /stock/group 对不在池中的票直接 404（见 StockService.set_stock_group）。
//    所以必须先探明 in_pool 再决定走哪条链路，否则用户点「确定」只会看到一句报错。
const groups = ref([]);              // [{group_name, count}]
const inPool = ref(null);            // null = 尚未探明（不据此做任何结论性判定）
const currentGroup = ref('');        // 当前分组名，'' = 在池中但未分组
const groupDialogVisible = ref(false);
const groupSaving = ref(false);
const creatingGroup = ref(false);
const newGroupName = ref('');
const pendingGroup = ref('');        // 弹窗中选中的分组
const groupListRef = ref(null);      // 分组列表容器（用于把当前分组滚进可视区）

// 分组选项 = 未分组 + 已有分组。当前分组即使已经空掉（组内最后一只票被移走）也要列出来，
// 否则用户想「保持原样」却选不到它 —— 用 names 集合兜这一下。
const groupOptions = computed(() => {
    const opts = [{name: '', label: '未分组', count: null}];
    const names = new Set(['']);
    for (const g of groups.value) {
        if (!g.group_name || names.has(g.group_name)) continue;
        names.add(g.group_name);
        opts.push({name: g.group_name, label: g.group_name, count: g.count});
    }
    if (currentGroup.value && !names.has(currentGroup.value)) {
        opts.push({name: currentGroup.value, label: currentGroup.value, count: null});
    }
    return opts;
});

function handleOpErr(error) {
    let message = '操作失败，请重试';
    if (axios.isAxiosError(error) && error.response) {
        const d = error.response.data;
        message = (d && (d.message || d.detail)) || message;
    } else if (error instanceof Error) {
        message = error.message;
    }
    showError(message);
}

/** 探明「本票分组状态 + 分组清单」。两个请求互不依赖，并行发。 */
async function loadGroupState() {
    const [stateRes, listRes] = await Promise.allSettled([
        axios.get(`/api/v1/stock/group/${encodeURIComponent(stock_code)}`),
        axios.get('/api/v1/stock/groups'),
    ]);
    if (stateRes.status === 'fulfilled' && stateRes.value.data) {
        const d = stateRes.value.data;
        inPool.value = !!d.in_pool;
        currentGroup.value = d.group_name || '';
    } else {
        inPool.value = null;   // 探明失败就不据它下结论，交给写接口自己兜（见 applyGroup）
    }
    if (listRes.status === 'fulfilled') {
        groups.value = Array.isArray(listRes.value.data) ? listRes.value.data : [];
    }
}

/**
 * 把「当前分组」滚进可视区。
 *
 * 分组一多（本项目实测 11 组）列表就会滚动，而当前分组往往排在可视区之外 ——
 * 用户打开弹窗看到的是满满一屏**别的**分组，会以为一个都没选中。
 *
 * 用 offsetTop 而不是 getBoundingClientRect：offsetTop 是相对 offsetParent 的静态
 * 位置，既不受容器自身滚动影响，也不受弹窗入场缩放动画影响（rect 在动画期间是被
 * 缩放过的，算出来的偏移会偏小）。
 * 两者 offsetParent 不同则说明中间还有别的定位祖先，差值不再等于容器内偏移 —— 这时
 * 宁可不动，也不要滚到一个错误的位置。
 */
function revealActiveGroup() {
    const host = groupListRef.value;
    const active = host && host.querySelector('.gp-item.is-active');
    if (!host || !active || active.offsetParent !== host.offsetParent) return;
    const top = active.offsetTop - host.offsetTop;   // 调用时 scrollTop 恒为 0，差值即内容偏移
    host.scrollTop = Math.max(
        0, top - (host.clientHeight - active.offsetHeight) / 2);
}

async function openGroupDialog() {
    creatingGroup.value = false;
    newGroupName.value = '';
    groupDialogVisible.value = true;
    await loadGroupState();      // 状态回来后再对齐选中项，避免默认选中的是过期分组
    pendingGroup.value = currentGroup.value;
    await nextTick();
    revealActiveGroup();
}

function startCreateGroup() {
    newGroupName.value = '';
    creatingGroup.value = true;
}

/** 已在池中：只改标签，不碰监控状态。 */
function putStockGroup(name) {
    return axios.put('/api/v1/stock/group', {symbol: stock_code, group_name: name || null});
}

/** 不在池中：一次调用完成「加入监控 + 归类」，后端会给票补行情并投递一次异步分析。 */
function addAndGroup(name) {
    return axios.put(`/api/v1/stocks/${encodeURIComponent(stock_code)}`, {
        monitoring: 1,
        monitor_by: 'user',
        group_name: name || null,
    });
}

async function applyGroup(groupName) {
    if (groupSaving.value) return;
    const name = (groupName || '').trim();
    // 与后端 String(50) 对齐提前拦住：严格模式下超长是 1406，会以 500 冒出来
    if (name.length > 50) {
        showError('分组名称不能超过 50 个字符');
        return;
    }
    groupSaving.value = true;
    let added = false;                  // 本次是不是走了「先加入监控」那条链路
    try {
        if (inPool.value === true) {
            await putStockGroup(name);
        } else if (inPool.value === false) {
            await addAndGroup(name);
            added = true;
        } else {
            // 状态没探明：先按「已在池」试轻量接口；404 说明其实不在池，再走加入。
            // 这样即使状态接口挂了，功能仍然可用（不会变成「点了没反应」）。
            try {
                await putStockGroup(name);
            } catch (e) {
                if (axios.isAxiosError(e) && e.response && e.response.status === 404) {
                    await addAndGroup(name);
                    added = true;
                } else {
                    throw e;
                }
            }
        }
        showSuccess(added
            ? (name ? `已加入监控并归入「${name}」` : '已加入监控（未分组）')
            : (name ? `已移入分组「${name}」` : '已取消分组'));
        groupDialogVisible.value = false;
        await loadGroupState();
    } catch (error) {
        handleOpErr(error);
    } finally {
        groupSaving.value = false;
    }
}

function confirmGroup() {
    applyGroup(pendingGroup.value);
}

async function confirmCreateGroup() {
    const name = newGroupName.value.trim();
    if (!name) {
        showError('请输入分组名称');
        return;
    }
    await applyGroup(name);
}

/** 关闭监控：把票移出当前用户的池子（公共字段与分析数据保留）。 */
async function closeMonitor() {
    try {
        await axios.put(`/api/v1/stocks/${encodeURIComponent(stock_code)}?is_update_history=0`, {
            monitoring: 0,
            monitor_by: 'user',
        });
        showSuccess('操作成功，个股监控已关闭');
        router.push({path: '/quant/stock_monitor'});
    } catch (error) {
        handleOpErr(error);
    }
}

/**
 * 「操作」下拉菜单。
 *
 * ⚠️ 必须是 computed：改完分组菜单上要立刻反映新分组，静态数组只在 setup 时求值一次，
 *    会出现「弹窗里已经改了、菜单还显示旧分组」的矛盾。
 * 当前分组直接带进 label，不开弹窗也能看到这只票归在哪组。
 *
 * ⚠️ 原实现里「重新分析」和「关闭监控」都是 `try { axios.put(...) } catch {}` ——
 *    没有 await，Promise 的 rejection 落不到同步 catch 里，错误提示是**永远不会触发**的
 *    死代码；「关闭监控」还会在请求发出后立刻跳页并报「操作成功」，失败了也照跳。
 *    这里统一改成 await + 统一错误提取。
 */
const items = computed(() => {
    const menu = [
        {
            label: '重新分析',
            icon: 'pi pi-refresh',
            disabled: reAnalyzing.value,
            command: reAnalyze,
        },
        {
            label: currentGroup.value ? `设置分组 · ${currentGroup.value}` : '设置分组',
            icon: 'pi pi-folder',
            command: () => openGroupDialog(),
        },
    ];
    if (currentGroup.value) {
        menu.push({label: '取消分组', icon: 'pi pi-times', command: () => applyGroup('')});
    }
    // 只有「明确探明不在池中」才切换成「加入监控」；未探明时保持原来的「关闭监控」，
    // 不做基于猜测的菜单切换。加入监控也走分组弹窗，让用户顺手选个分组。
    if (inPool.value === false) {
        menu.push({label: '加入监控', icon: 'pi pi-plus', command: () => openGroupDialog()});
    } else {
        menu.push({label: '关闭监控', icon: 'pi pi-ban', command: () => closeMonitor()});
    }
    return menu;
});

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
        textStyle: {fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif', fontSize: FONT.label, color: '#333'},
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
                    width: LINE.primary
                }
            }
        ]
    };
    echart1.value.setOption(option)
}

onMounted(async () => {

    window.addEventListener('resize', resizeFgChart);
    window.addEventListener('resize', resizeFinChart);
    window.addEventListener('resize', resizeSentimentChart);
    // ⚠️ 必须在这里就拉分组状态：菜单项要显示「设置分组 · 当前分组」、并在未入池时
    //    换成「加入监控」，这些判定全依赖它。只在打开弹窗时拉的话，首次进入页面
    //    菜单永远是默认态（不显示当前分组、未入池的票还挂着「关闭监控」），
    //    用户要先点一次弹窗才「变成对的」。
    // 不 await：与首屏取数并行，不拖慢标题/行情渲染。
    loadGroupState();
    // 拉取当前用户的智能体列表（供「重新分析」指定 agent 驱动大模型）。
    fetchAgents();
    stock_info.value = await fetchStockInfo(stock_code);
    stock_profile.value = await fetchStockProfile(stock_code)
    // PE-TTM 估值（仅 A 股）。不 await：与首屏取数并行，标题/行情先出，
    // 估值数据到位后顶部报价与基本面走势图自动补上。
    loadPeTtm();
    // 获取日K
    ohlc_data.value = await fetchStockMarketData(stock_code);
    // 1. 提取close数组，自动过滤空值/0值（停牌无收盘价的场景）
    realHistoryData.value = ohlc_data.value
        .map(ohlcItem => ohlcItem.close) // 提取每个K线的close字段
        .filter(close => close != null && close > 0); // 过滤空值、停牌0值，避免后续计算报错
    realHistoryData.value = realHistoryData.value.slice(-365 / 2)
    // 最新的一个K线
    ohlc_last.value = ohlc_data.value[ohlc_data.value.length - 1]

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

        // 先关 loading → 模板 v-if 切到图表块，<div ref="fgChartRef"> 进 DOM；
        // 再渲染走势图（renderFearGreedChart 内部 await nextTick 后容器已挂载，可 init）。
        greedLoading.value = false;
        renderFearGreedChart();

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

// 切换报表 → 重置选中指标到该报表默认项、重新取数并重绘
watch(fin_report_type, (val) => {
    resetFinSelection();
    loadFinancialData(val);
});

// 切换报告期筛选 → 仅重绘趋势图（数据已全量加载，无需重取）
watch(fin_period_filter, () => {
    renderFinChart();
});

// 切换时间范围 → 重新取数（periods 变化需后端重拉，非前端过滤）
watch(fin_periods, () => {
    loadFinancialData();
});

// 切到「财务分析」tab 时才首次渲染趋势图：
// v-show 非激活时容器 display:none、clientWidth 为 0，
// 过早 init 会得到 0x0 画布（表现为「图是空的」）。所以数据虽早就取好，
// 图表必须等到 tab 真正可见再画。
watch(activeTab, (val) => {
    if (val === 'tab4') {
        // 容器刚由隐藏变可见，等一帧让布局完成
        nextTick(() => renderFinChart());
    }
    if (val === 'tab2') {
        // PE-TTM 走势图也在 v-show 的 tab2 里，切到该 tab 时容器才可见，需重绘
        nextTick(() => renderPeTtmChart());
    }
    if (val === 'tab7') {
        // 散户情绪做懒加载：多数用户不看这个 tab，没必要首屏就发请求。
        // ⚠️ 顺序不能反：先 await 数据（容器由 v-if/v-else 决定是否进 DOM），
        //    再等一帧画图；直接画会因容器还是 loading 态而拿到 null。
        nextTick(async () => {
            if (!sentimentLoaded.value) await loadSentiment();
            await nextTick();
            renderSentimentChart();
        });
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
        axios.put(`/api/v1/stock/re_analysis_dcf/${stock_code}`, {agent_id: selectedAgentId.value || null});
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
// 切主题同样要重画：ECharts 的 setOption 是快照，CSS 变量换了不会改已画的图。
// 只重画**当前 tab** 的图 —— 其它 tab 用 v-show 隐藏，容器尺寸为 0，
// 在 0 尺寸上重画会得到空图，等 tab 切过去时不会再重画（tab 切换只改 activeTab）。
const stopThemeRedraw = registerThemeRedraw(() => {
    if (activeTab.value === 'tab1') {
        renderFearGreedChart();
        renderSentimentChart();
    } else if (activeTab.value === 'tab4') {
        renderFinChart();
    }
});
onUnmounted(() => {
    stopThemeRedraw && stopThemeRedraw();
    dispose('chart');
    window.removeEventListener('resize', resizeFgChart);
    window.removeEventListener('resize', resizeFinChart);
    window.removeEventListener('resize', resizeSentimentChart);
    fgChart?.dispose();
    fgChart = null;
    finChart?.dispose();
    finChart = null;
    sentimentChart?.dispose();
    sentimentChart = null;
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
                <div class="flex gap-3 items-center">
                    <label class="text-xs text-gray-500 whitespace-nowrap">分析智能体</label>
                    <select
                        v-model="selectedAgentId"
                        :disabled="agentsLoading"
                        class="text-sm border border-gray-300 rounded px-2 py-1 bg-white max-w-[12rem]"
                    >
                        <option :value="null">系统默认</option>
                        <option v-for="a in agents" :key="a.id" :value="a.id">
                            {{ a.emoji || '🤖' }} {{ a.name }}
                        </option>
                    </select>
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

    <!-- 个股内嵌智能体对话抽屉 -->
    <Drawer
        v-model:visible="agentChatVisible"
        header="智能体对话"
        position="right"
        class="!w-full md:!w-[40rem] lg:!w-[52rem]"
        :footer="false"
        body-class="p-0"
    >
        <StockAgentChat
            v-if="agentChatVisible"
            :stock-code="stock_code"
            :stock-name="stock_info?.name || ''"
        />
    </Drawer>

    <!-- 设置分组：分组是 user_stock_pool.group_name 标签，与个股监控页共用同一套接口 -->
    <Dialog v-model:visible="groupDialogVisible" modal header="设置分组" :style="{ width: '26rem' }">
        <div class="gp-body">
            <!-- 未入池：先说清楚「确定」会顺带把票加入监控，避免用户以为只是打个标签 -->
            <div v-if="inPool === false" class="gp-notice">
                <i class="pi pi-info-circle"/>
                <span>该股票尚未加入监控。确定后将<strong>同时把它加入监控</strong>并归入所选分组，后台会补一次行情与数据分析。</span>
            </div>

            <div class="gp-current">
                当前分组：<b>{{ currentGroup || '未分组' }}</b>
                <span v-if="inPool === false" class="gp-current__hint">（未加入监控）</span>
            </div>

            <div ref="groupListRef" class="gp-list" role="radiogroup" aria-label="选择分组">
                <button
                    v-for="opt in groupOptions"
                    :key="opt.name || '__ungrouped__'"
                    type="button"
                    role="radio"
                    :aria-checked="pendingGroup === opt.name"
                    class="gp-item"
                    :class="{'is-active': pendingGroup === opt.name}"
                    @click="pendingGroup = opt.name"
                >
                    <i class="pi" :class="pendingGroup === opt.name ? 'pi-check-circle' : 'pi-circle'"/>
                    <span class="gp-item__name">{{ opt.label }}</span>
                    <span v-if="opt.count !== null" class="gp-item__count">{{ opt.count }} 只</span>
                </button>
            </div>

            <!-- 新建分组：与监控页一致 —— 建组即把当前这只票归入该组 -->
            <div v-if="creatingGroup" class="gp-create">
                <InputText
                    v-model="newGroupName"
                    placeholder="输入新分组名称"
                    maxlength="50"
                    class="w-full"
                    @keyup.enter="confirmCreateGroup"
                />
                <div class="gp-create__actions">
                    <Button label="取消" severity="secondary" size="small" text
                            @click="creatingGroup = false"/>
                    <Button label="创建并归入" size="small" :loading="groupSaving"
                            @click="confirmCreateGroup"/>
                </div>
            </div>
            <Button v-else label="新建分组" icon="pi pi-plus" severity="secondary" size="small" text
                    class="gp-new" @click="startCreateGroup"/>

            <div v-if="!currentGroup && inPool === true" class="gp-tip">
                加入分组后，个股监控页左侧面板会多出这个分组，可整组一起看。
            </div>
        </div>

        <template #footer>
            <div class="flex justify-end gap-2">
                <Button label="取消" severity="secondary" @click="groupDialogVisible = false"/>
                <Button label="确定" :loading="groupSaving" :disabled="creatingGroup" @click="confirmGroup"/>
            </div>
        </template>
    </Dialog>

    <div class="card relative mb-0 pb-0 stock-info-top">

        <!-- 标题 -->
        <h1 class="text-2xl font-bold mb-3 text-gray-800">
            <span>{{ stock_info?.name || '加载中...' }} ({{ stock_code }})</span> <i
            class="text-sm font-light">{{ stock_info?.concepts || '加载中...' }}</i>
        </h1>

        <h1 class="stock-price" v-if="ohlc_data.length > 0" :class="{
                              'text-red-500': ohlc_last['chg_pct'] > 0,
                              'text-green-600': ohlc_last['chg_pct'] < 0,
                              }">
            <span class="text-3xl font-bold">{{ formatCurrency(ohlc_last['close']) }}</span>&nbsp;
            <span class="text-lg">{{ formatCurrency(ohlc_last['change_amount'], true) }}</span>&nbsp;
            <span class="text-lg">{{
                    formatPercentage(ohlc_last['chg_pct'].toFixed(2), true)
                }}%</span>
        </h1>

        <!-- PE-TTM 估值（仅 A 股）：上游只对 A 股提供 PE-TTM，港股/美股不显示。
             数据由日更任务每日盘后落库，此处展示最新一条。 -->
        <div v-if="is_cn_stock && peTtmLatest != null" class="pe-ttm-top">
            <i class="pi pi-chart-line text-blue-500"></i>
            <span class="pe-ttm-label">PE-TTM</span>
            <b class="pe-ttm-value">{{ Number(peTtmLatest).toFixed(2) }}</b>
            <span class="pe-ttm-date" v-if="peTtmDate">（{{ peTtmDate }}）</span>
        </div>

        <div class="absolute top-8 right-8 action-bar">
            <Button v-tooltip.top="'用这只股票跑一次等权买入持有，直接看净值与最大回撤'"
                    label="快速回测" icon="pi pi-chart-line" size="small" severity="secondary"
                    class="whitespace-nowrap" @click="goQuickBacktest()"></Button>
            <Button label="AI 估值分析" size="small" class="whitespace-nowrap" @click="showDcfDrawer()" :loading="loading"></Button>
            <Button label="智能体对话" icon="pi pi-comments" size="small" severity="secondary" class="whitespace-nowrap" @click="agentChatVisible = true"></Button>
            <!-- <Button :label="watched ? '已关注' : '关注'" size="small" @click="toggleLike()" :severity="watched ? '' : 'secondary'"></Button>-->
            <SplitButton label="操作" :model="items" size="small" severity="secondary"/>
        </div>
    </div>

    <div class="sd-layout">
        <NavSidePanel
            title="分析"
            :items="tabItems"
            :activeKey="activeTab"
            @select="onTabSelect"
        />

        <div class="sd-content">
            <div v-show="activeTab === 'tab1'">

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

                <!-- 技术面仪表盘（因子看板 / 因子雷达与横向对比已拆到「因子分析」Tab）。
                     数据来自 routes/factor.py，组件自带取数，失败静默降级不影响本页其它区块。 -->
                <FactorPanel v-if="stock_code" :symbol="stock_code" mode="dashboard"
                             :active="activeTab === 'tab1'"/>

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

            </div>

            <!-- 因子分析：从技术面分析拆出的独立 Tab，只放因子看板 + 因子雷达 + 横向对比。
                 组件常驻（数据只取一次），active 随 tab 切换驱动重绘（见 FactorPanel）。 -->
            <div v-show="activeTab === 'tab6'">
                <FactorPanel v-if="stock_code" :symbol="stock_code" mode="factors"
                             :active="activeTab === 'tab6'"/>
            </div>

            <div v-show="activeTab === 'tab2'">

                <!-- 公司概况 -->
                <Card class="mt-5">
                    <template #title>
                        <div class="flex items-center gap-2">
                            <i class="pi pi-building text-blue-500"></i>
                            <span>公司概况</span>
                        </div>
                    </template>
                    <template #content>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2 text-sm">
                            <div class="flex justify-between border-b border-gray-100 py-1.5">
                                <span class="text-gray-500">公司名称</span>
                                <span class="font-medium text-right">{{ stock_profile?.company_name || '—' }}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-100 py-1.5">
                                <span class="text-gray-500">所属行业</span>
                                <span class="font-medium text-right">{{ stock_profile?.industry || '—' }}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-100 py-1.5">
                                <span class="text-gray-500">实际控制人</span>
                                <span class="font-medium text-right">{{ stock_profile?.actual_controller || '—' }}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-100 py-1.5" v-if="stock_profile?.office_address">
                                <span class="text-gray-500">办公地址</span>
                                <span class="font-medium text-right">{{ stock_profile.office_address }}</span>
                            </div>
                            <div class="flex justify-between border-b border-gray-100 py-1.5" v-if="stock_profile?.website">
                                <span class="text-gray-500">公司网站</span>
                                <a :href="'https://' + stock_profile.website" target="_blank" class="text-blue-500 hover:underline">{{ stock_profile.website }}</a>
                            </div>
                        </div>
                        <Divider class="my-3" />
                        <div class="text-sm" v-if="stock_profile?.company_introduction">
                            <div class="text-gray-500 mb-1">公司介绍</div>
                            <div class="text-gray-700 leading-relaxed">{{ stock_profile.company_introduction }}</div>
                        </div>
                        <div class="text-sm mt-3" v-if="stock_profile?.business_scope">
                            <div class="text-gray-500 mb-1">经营范围</div>
                            <div class="text-gray-700 leading-relaxed">{{ stock_profile.business_scope }}</div>
                        </div>
                    </template>
                </Card>

                <!-- PE-TTM 估值走势（仅 A 股）：数据由日更任务每日盘后落库。
                     展示近约两年半的滚动市盈率变化，帮助判断估值中枢与当前分位。 -->
                <Card class="mt-5" v-if="is_cn_stock">
                    <template #title>
                        <div class="flex items-center gap-2">
                            <i class="pi pi-chart-line text-blue-500"></i>
                            <span>PE-TTM 估值走势</span>
                            <span v-if="peTtmLatest != null" class="text-sm font-light text-gray-400">
                                （最新 {{ Number(peTtmLatest).toFixed(2) }}<template v-if="peTtmDate"> · {{ peTtmDate }}</template>）
                            </span>
                        </div>
                    </template>
                    <template #content>
                        <div ref="peTtmChartRef" class="pe-ttm-chart"></div>
                        <p v-if="!pe_ttm?.history?.length" class="text-xs text-gray-400 mt-2">
                            暂无 PE-TTM 数据（估值日更任务每日盘后落库，新纳入监控的标的从纳入日起累积）。
                        </p>
                    </template>
                </Card>

                <!-- 基本面评分 + DCF 估值结论 -->
                <div class="flex flex-col lg:flex-row gap-5 mt-5">

                    <!-- 基本面评分雷达 + 维度明细 -->
                    <Card class="w-full lg:w-1/2">
                        <template #title>
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <i class="pi pi-chart-pie text-green-500"></i>
                                    <span>基本面评分</span>
                                </div>
                                <div class="flex items-center gap-2">
                                    <select
                                        v-model="selectedAgentId"
                                        :disabled="agentsLoading"
                                        class="text-xs border border-gray-300 rounded px-1.5 py-0.5 bg-white max-w-[10rem]"
                                    >
                                        <option :value="null">系统默认</option>
                                        <option v-for="a in agents" :key="a.id" :value="a.id">
                                            {{ a.emoji || '🤖' }} {{ a.name }}
                                        </option>
                                    </select>
                                    <Button label="重新分析" size="small" severity="secondary" text
                                            :loading="reAnalyzing" @click="reAnalyze" />
                                </div>
                            </div>
                        </template>
                        <template #content>
                            <div class="flex flex-col md:flex-row gap-4 items-center">
                                <div ref="el" id="el" class="w-full md:w-1/2" style="height:240px"></div>
                                <div class="w-full md:w-1/2 flex flex-col gap-2.5">
                                    <div v-for="dim in scoreDimensions" :key="dim.key" class="text-sm">
                                        <div class="flex justify-between mb-1">
                                            <span class="text-gray-600">{{ dim.label }}</span>
                                            <span class="font-semibold" :style="{ color: scoreColor(dim.value) }">{{ dim.value ?? '—' }}</span>
                                        </div>
                                        <div class="h-1.5 rounded bg-gray-100 overflow-hidden">
                                            <div class="h-full rounded transition-all"
                                                 :style="{ width: (dim.value || 0) + '%', background: scoreColor(dim.value) }"></div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <p v-if="!hasScores" class="text-xs text-gray-400 mt-3">
                                该标的尚未生成基本面评分，可点击「重新分析」触发计算。
                            </p>
                        </template>
                    </Card>

                    <!-- DCF 估值结论 -->
                    <Card class="w-full lg:w-1/2" v-if="dcf_research_report?.content_json">
                        <template #title>
                            <div class="flex items-center gap-2">
                                <i class="pi pi-chart-line text-green-500"></i>
                                <span>DCF 估值结论</span>
                            </div>
                        </template>
                        <template #content>
                            <div class="grid grid-cols-2 gap-3">
                                <div class="rounded-lg bg-gray-50 p-3">
                                    <div class="text-xs text-gray-500">当前股价</div>
                                    <div class="text-lg font-bold">{{ fmtPrice(dcfCurrentPrice) }}</div>
                                </div>
                                <div class="rounded-lg bg-gray-50 p-3">
                                    <div class="text-xs text-gray-500">中性情景内在价值</div>
                                    <div class="text-lg font-bold" :style="{ color: COLORS.up }">{{ fmtPrice(dcfNeutralValue) }}</div>
                                </div>
                                <div class="rounded-lg bg-gray-50 p-3">
                                    <div class="text-xs text-gray-500">安全边际（中性）</div>
                                    <div class="text-lg font-bold" :style="{ color: marginColor }">
                                        {{ dcfMarginPct == null ? '—' : (dcfMarginPct > 0 ? '+' : '') + dcfMarginPct + '%' }}
                                    </div>
                                </div>
                                <div class="rounded-lg bg-gray-50 p-3">
                                    <div class="text-xs text-gray-500">估值判断</div>
                                    <Tag :severity="verdictSeverity" class="mt-1">{{ valuationVerdict }}</Tag>
                                </div>
                            </div>
                        </template>
                    </Card>

                </div>

                <!-- DCF 估值走势图：单独一行，避免被半宽卡片挤压 -->
                <Card class="mt-5 mb-5 w-full" v-if="dcf_research_report?.content_json">
                    <template #title>
                        <div class="flex items-center gap-2">
                            <i class="pi pi-chart-line text-green-500"></i>
                            <span>DCF 估值走势图</span>
                        </div>
                    </template>
                    <template #content>
                        <StockValuationChart
                            :data="dcf_research_report.content_json"
                            :currentPrice="ohlc_last['close']"
                            title=""
                            ratingText=""
                            ratingColor="#f97316"
                            :historyData="realHistoryData"
                            :chartHeight="320"
                        />
                    </template>
                </Card>

            </div>

            <div v-show="activeTab === 'tab3'">
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
            </div>

            <!-- 散户情绪：东方财富股吧发帖 → LLM 三分类 → 后端公式算分
                 ⚠️ 与 tab1 的「恐惧&贪婪」是两个不同指标（文本语义 vs 价量技术），
                 文案、档位、配色体系都独立，不能让用户以为是同一个东西。 -->
            <div v-show="activeTab === 'tab7'">
                <div class="rs-head mt-5">
                    <div class="font-semibold text-lg">
                        <i class="pi pi-comments text-blue-500"></i> 股吧散户情绪
                    </div>
                    <Button label="重新分析" icon="pi pi-refresh" size="small"
                            severity="secondary" text
                            :loading="sentimentRefreshing"
                            @click="refreshSentiment"/>
                </div>
                <Divider/>

                <div v-if="sentimentLoading" class="fg-loading">
                    <i class="pi pi-spin pi-spinner"></i> 散户情绪数据加载中...
                </div>

                <template v-else-if="sentimentLatest">
                    <div class="rs-body">
                        <!-- 左：当前读数 -->
                        <div class="rs-current">
                            <div class="rs-value"
                                 :style="{ color: retailSentimentLevel(sentimentLatest.sentiment_score).color }">
                                {{ Number(sentimentLatest.sentiment_score ?? 50).toFixed(1) }}
                            </div>
                            <div class="rs-label"
                                 :style="{ color: retailSentimentLevel(sentimentLatest.sentiment_score).color }">
                                {{ retailSentimentLevel(sentimentLatest.sentiment_score).text }}
                            </div>
                            <div class="rs-date">{{ sentimentLatest.trade_date }}</div>

                            <!-- 置信度：低于 50 时视觉降级（虚线边框 + 灰字），提醒结论不可尽信 -->
                            <div class="rs-conf" :class="{ weak: sentimentConf.weak }"
                                 :style="{ color: sentimentConf.color, borderColor: sentimentConf.color }">
                                {{ sentimentConf.text }} {{ Number(sentimentLatest.confidence ?? 0).toFixed(0) }}
                            </div>

                            <div class="rs-advice">
                                {{ retailSentimentLevel(sentimentLatest.sentiment_score).advice }}
                            </div>

                            <!-- 多空占比条：一段式堆叠，和为 100% -->
                            <div class="rs-ratio">
                                <div class="rs-ratio-bar">
                                    <span class="seg bull"
                                          :style="{ width: Number(sentimentLatest.bullish_ratio ?? 0) + '%' }"></span>
                                    <span class="seg neut"
                                          :style="{ width: Number(sentimentLatest.neutral_ratio ?? 0) + '%' }"></span>
                                    <span class="seg bear"
                                          :style="{ width: Number(sentimentLatest.bearish_ratio ?? 0) + '%' }"></span>
                                </div>
                                <div class="rs-ratio-legend">
                                    <span class="bull">看多 {{ Number(sentimentLatest.bullish_ratio ?? 0).toFixed(0) }}%</span>
                                    <span class="neut">中性 {{ Number(sentimentLatest.neutral_ratio ?? 0).toFixed(0) }}%</span>
                                    <span class="bear">看空 {{ Number(sentimentLatest.bearish_ratio ?? 0).toFixed(0) }}%</span>
                                </div>
                            </div>

                            <div class="rs-meta">
                                <div>24h 发帖 <b>{{ sentimentLatest.post_count ?? 0 }}</b> 条 ·
                                    送入分析 <b>{{ sentimentLatest.sample_size ?? 0 }}</b> 条
                                </div>
                                <div>模型判定有效自发帖 <b>{{ sentimentLatest.effective_count ?? 0 }}</b> 条 ·
                                    活跃度 <b>{{ sentimentLatest.heat_level || '--' }}</b>
                                </div>
                            </div>
                        </div>

                        <!-- 右：情绪走势（副轴叠收盘价，用于看背离） -->
                        <div class="rs-chart-wrap">
                            <div class="rs-chart-title">
                                情绪走势（实线 = 散户情绪分 0~100；点线 = 收盘价，右轴）
                            </div>
                            <div ref="sentimentChartRef" class="rs-chart"></div>
                        </div>
                    </div>

                    <!-- 语义结论：话题 / 理由 / 关键词 / 代表性帖子 -->
                    <div class="rs-detail">
                        <div class="rs-detail-head">
                            <span class="rs-detail-label">当期焦点</span>
                            <span class="rs-topic">{{ sentimentLatest.dominant_topic || '--' }}</span>
                        </div>

                        <div class="rs-reasoning" v-if="sentimentLatest.reasoning">
                            {{ sentimentLatest.reasoning }}
                        </div>

                        <div class="rs-keywords" v-if="(sentimentLatest.keywords || []).length">
                            <span v-for="kw in sentimentLatest.keywords" :key="kw" class="kw-chip">{{ kw }}</span>
                        </div>

                        <div class="rs-posts" v-if="(sentimentLatest.notable_posts || []).length">
                            <div class="rs-posts-title">代表性帖子</div>
                            <div v-for="(p, i) in sentimentLatest.notable_posts" :key="i" class="rs-post">
                                <span class="stance"
                                      :class="p.stance === '看多' ? 'bull' : (p.stance === '看空' ? 'bear' : 'neut')">
                                    {{ p.stance || '中性' }}
                                </span>
                                <span class="post-title">{{ p.title }}</span>
                            </div>
                        </div>
                    </div>
                </template>

                <div v-else class="empty-tip">
                    该股票暂无散户情绪数据。系统每个交易日 19:10 自动采集，
                    也可点右上角「重新分析」立即触发（首次约 5~25 秒）。
                </div>

                <div class="rs-footnote">
                    本指标由东方财富股吧发帖经大模型语义分析得出，反映散户<strong>主观表达</strong>的情绪；
                    与「技术面分析」中的恐惧&amp;贪婪（由价量指标计算）是两个不同指标，不可互相替代。
                    散户情绪更适合作为<strong>反向参考</strong>：极度看多常出现在阶段高点附近，
                    极度看空常伴随恐慌抛售。样本不足时置信度会自动降低，此时结论仅供参考。
                </div>
            </div>

            <!-- 财务分析：报表切换 + 核心指标卡片 + 趋势图 -->
            <div v-show="activeTab === 'tab4'">
                <div class="mt-5">

                    <div class="font-semibold text-lg">
                        <i class="pi pi-chart-bar text-blue-500"></i> 财务分析
                    </div>
                    <Divider/>

                    <!-- 报表切换（5 种，与后端白名单一致） -->
                    <div class="p-0 mb-3">
                        <SelectButton
                            v-model="fin_report_type"
                            :options="FIN_REPORTS"
                            optionLabel="label"
                            optionValue="value"
                            size="small"
                            :allowEmpty="false"
                        />
                    </div>

                    <!-- 报告期筛选：全部 / 一季报 / 中报 / 三季报 / 年报 -->
                    <div class="p-0 mb-3" v-if="!fin_loading && !fin_error">
                        <SelectButton
                            v-model="fin_period_filter"
                            :options="FIN_PERIOD_FILTERS"
                            optionLabel="label"
                            optionValue="value"
                            size="small"
                            :allowEmpty="false"
                        />
                    </div>

                    <!-- 时间范围：近3年/近5年/近10年/全部（控制后端取数期数） -->
                    <div class="p-0 mb-3" v-if="!fin_loading && !fin_error">
                        <SelectButton
                            v-model="fin_periods"
                            :options="FIN_PERIOD_OPTIONS"
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

                    <div v-else-if="!finDisplayItems.length" class="fin-state">
                        暂无该报表的财务数据
                    </div>

                    <template v-else>

                        <!-- 核心指标卡片：最新一期（点击切换趋势图指标） -->
                        <div class="fin-cards">
                            <div
                                class="fin-card"
                                :class="{ 'fin-card--active': ind.key === finActiveIndicator?.key }"
                                v-for="ind in finIndicators"
                                :key="ind.key"
                                @click="selectFinIndicator(ind.key)"
                            >
                                <div class="fin-card-label">{{ ind.name }}</div>
                                <div class="fin-card-value">
                                    {{ fmtFinValue(finLatest?.[ind.key], ind.unit, ind.scale) }}
                                </div>
                                <div class="fin-card-date">{{ fmtFinPeriod(finLatest?.report_date) }}</div>
                            </div>
                        </div>

                        <!-- 趋势图：仅显示选中的指标 -->
                        <div class="fin-chart-wrap" v-if="finDisplayItems.length >= 2 && finActiveIndicator">
                            <div class="fin-chart-title">
                                指标趋势 · {{ finActiveIndicator.name }}
                                <span class="fin-chart-unit" v-if="finActiveIndicator.unit === '%'">（%）</span>
                                <span class="fin-chart-hint">点上方卡片切换</span>
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
                                <tr v-for="row in finDisplayItems" :key="row.report_date">
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
            </div>

            <div v-show="activeTab === 'tab5'">
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
            </div>
        </div>
    </div>

</template>

<style scoped lang="scss">

#chart {
    width: 100%;
    /* 350px = 蜡烛图主窗格 + VOL 窗格的合计高度（恐惧贪婪已改为下方独立卡片，
       不再占据 K 线内的子窗格，所以高度回到并入前的值）。 */
    height: 350px;
    border: 1px solid var(--app-border-base);
    border-radius: 3px
}

.news-item {
    font-size: 0.95rem;
    line-height: 1.5;
}

.news-time {
    color: var(--app-text-secondary);
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
    background-color: var(--app-bg-active);
    border: 1px solid var(--app-border-strong);
    border-radius: 4px;
    padding: 2px 6px;
    margin-right: 4px;
    margin-top: 2px;
    font-size: 0.85rem;
    color: var(--app-text-secondary);
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
    background: var(--app-bg-card);
    border: 1px solid var(--app-border-base);
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
            color: var(--app-text-muted);
            margin-top: 0.25rem;
        }

        .fg-advice {
            font-size: 0.8rem;
            color: var(--app-text-secondary);
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
                color: var(--app-text-secondary);

                .score-name {
                    flex: 0 0 3.6rem;
                    white-space: nowrap;
                }

                // 迷你进度条：0~100 分项得分
                .score-track {
                    flex: 1;
                    height: 5px;
                    background: var(--app-track-bg);
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
                    color: var(--app-text-primary);
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
            color: var(--app-text-muted);
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
    color: var(--app-text-muted);
    font-size: 0.9rem;
}

/* 各区块「加载中」占位：与 .empty-tip 同类观感，避免首屏闪现「无数据」 */
.fg-loading {
    padding: 2rem 0;
    text-align: center;
    color: var(--app-text-muted);
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
    background: var(--app-bg-card);
    border: 1px solid var(--app-border-base);
    border-radius: 0.5rem;
    padding: 0.7rem 0.9rem;
    cursor: pointer;
    transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;

    &:hover {
        border-color: var(--app-select-border);
        box-shadow: 0 2px 8px var(--app-info-bg);
    }

    /* 选中态：蓝色描边 + 左侧条，强调「当前趋势图指标」 */
    &.fin-card--active {
        border-color: var(--app-select-border);
        box-shadow: 0 0 0 2px var(--app-info-bg);
    }

    .fin-card-label {
        font-size: 0.85rem;
        color: var(--app-text-muted);
        line-height: 1.3;
        min-height: 2.2em; /* 两行标签占位，避免卡片高度参差 */
    }

    .fin-card-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--app-text-primary);
        line-height: 1.2;
        margin-top: 0.25rem;
        white-space: nowrap;
    }

    .fin-card-date {
        font-size: 0.75rem;
        color: var(--app-text-muted);
        margin-top: 0.15rem;
    }
}

.fin-chart-wrap {
    margin-top: 1rem;
    background: var(--app-bg-card);
    border: 1px solid var(--app-border-base);
    border-radius: 0.5rem;
    padding: 0.75rem 1rem 0.5rem;

    .fin-chart-title {
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--app-text-primary);
        margin-bottom: 0.25rem;

        .fin-chart-unit {
            color: var(--app-text-secondary);
            font-weight: 400;
        }

        .fin-chart-hint {
            float: right;
            font-size: 0.72rem;
            font-weight: 400;
            color: var(--app-text-muted);
        }
    }

    .fin-chart {
        width: 100%;
        height: 320px;
    }
}

.fin-state {
    padding: 2rem 0;
    text-align: center;
    color: var(--app-text-muted);
    font-size: 0.9rem;

    &.fin-state--error {
        color: var(--app-up);
    }
}

/* 明细表：期数多、指标多 → 横向滚动，不换行挤压 */
.fin-table-wrap {
    margin-top: 1rem;
    overflow-x: auto;
    border: 1px solid var(--app-border-base);
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
        border-bottom: 1px solid var(--app-border-weak);
        color: var(--app-text-primary);
    }

    thead th {
        background: var(--app-bg-subtle);
        color: var(--app-text-secondary);
        font-weight: 600;
        position: sticky;
        top: 0;
        z-index: 1;
    }

    tbody tr:hover td {
        background: var(--app-bg-subtle);
    }

    tbody tr:last-child td {
        border-bottom: none;
    }

    .fin-th-label,
    .fin-td-label {
        text-align: left;
        font-weight: 600;
        color: var(--app-text-primary);
        position: sticky;
        left: 0;
        background: var(--app-bg-card);
    }

    thead .fin-th-label {
        background: var(--app-bg-subtle);
    }

    .fin-td-sub {
        display: block;
        font-size: 0.7rem;
        font-weight: 400;
        color: var(--app-text-muted);
    }
}

/* ===== 散户情绪（tab7）===== */
/* 布局刻意与上方「恐惧&贪婪」卡片同构（左读数 + 右走势），但配色体系独立：
   恐贪用恐惧绿/贪婪红，散户情绪用「看空绿/中性灰/看多红」——A 股涨跌色口径不变，
   只是语义从「市场情绪」变成「散户立场」，文案必须能一眼区分。 */
.rs-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
}

.rs-body {
    display: flex;
    gap: 1rem;
    align-items: stretch;
}

.rs-current {
    flex: 0 0 260px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.35rem;
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    background: var(--app-bg-subtle);
    border: 1px solid var(--app-border-base);
}

.rs-value {
    font-size: 2.4rem;
    font-weight: 700;
    line-height: 1.1;
}

.rs-label {
    font-size: 0.95rem;
    font-weight: 600;
}

.rs-date {
    font-size: 0.75rem;
    color: var(--app-text-muted);
}

/* 置信度徽标：weak（置信度 < 50）用虚线边框，视觉上明确「这条结论不硬」 */
.rs-conf {
    font-size: 0.7rem;
    padding: 0.05rem 0.4rem;
    border: 1px solid;
    border-radius: 0.75rem;

    &.weak {
        border-style: dashed;
        opacity: 0.9;
    }
}

.rs-advice {
    font-size: 0.75rem;
    color: var(--app-text-secondary);
    line-height: 1.55;
}

.rs-ratio {
    width: 100%;
    margin-top: 0.35rem;
}

.rs-ratio-bar {
    display: flex;
    height: 8px;
    border-radius: 4px;
    overflow: hidden;
    background: var(--app-track-bg);

    .seg {
        display: block;
        height: 100%;
    }

    .bull {
        background: var(--app-up);
    }

    .neut {
        background: var(--app-flat);
    }

    .bear {
        background: var(--app-down);
    }
}

.rs-ratio-legend {
    display: flex;
    justify-content: space-between;
    margin-top: 0.25rem;
    font-size: 0.68rem;

    .bull {
        color: var(--app-up);
    }

    .neut {
        color: var(--app-flat);
    }

    .bear {
        color: var(--app-down);
    }
}

.rs-meta {
    font-size: 0.68rem;
    color: var(--app-text-muted);
    line-height: 1.7;
}

.rs-chart-wrap {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
}

.rs-chart-title {
    font-size: 0.72rem;
    color: var(--app-text-muted);
    margin-bottom: 0.25rem;
}

.rs-chart {
    width: 100%;
    height: 260px;
}

.rs-detail {
    margin-top: 1rem;
    padding: 0.85rem 1rem;
    background: var(--app-bg-subtle);
    border: 1px solid var(--app-border-base);
    border-radius: 0.5rem;
}

.rs-detail-head {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.rs-detail-label {
    font-size: 0.7rem;
    color: var(--app-text-muted);
}

.rs-topic {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--app-text-primary);
}

.rs-reasoning {
    margin-top: 0.4rem;
    font-size: 0.78rem;
    color: var(--app-text-secondary);
    line-height: 1.7;
}

.rs-keywords {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin-top: 0.5rem;
}

.kw-chip {
    font-size: 0.68rem;
    padding: 0.05rem 0.45rem;
    border-radius: 0.6rem;
    background: var(--app-bg-active);
    color: var(--app-text-secondary);
}

.rs-posts {
    margin-top: 0.6rem;
}

.rs-posts-title {
    font-size: 0.7rem;
    color: var(--app-text-muted);
    margin-bottom: 0.3rem;
}

.rs-post {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    font-size: 0.76rem;
    color: var(--app-text-primary);
    line-height: 1.7;

    .stance {
        flex: 0 0 auto;
        font-size: 0.65rem;
        padding: 0 0.3rem;
        border-radius: 0.25rem;

        &.bull {
            background: var(--app-up-wash);
            color: var(--app-up);
        }

        &.bear {
            background: var(--app-down-wash);
            color: var(--app-down);
        }

        &.neut {
            background: var(--app-bg-active);
            color: var(--app-text-secondary);
        }
    }

    .post-title {
        flex: 1 1 auto;
        min-width: 0;
    }
}

.rs-footnote {
    margin-top: 1rem;
    padding: 0.6rem 0.8rem;
    font-size: 0.7rem;
    line-height: 1.7;
    color: var(--app-text-muted);
    background: var(--app-bg-subtle);
    border-left: 2px solid var(--app-border-strong);
    border-radius: 2px;
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

    /* 散户情绪同样是「左值 + 右图」，窄屏下改为上下堆叠 */
    .rs-body {
        flex-direction: column;
        gap: 0.75rem;

        .rs-current {
            flex: 0 0 auto;
            width: 100%;
        }

        .rs-chart-wrap .rs-chart {
            min-height: 200px;
        }
    }

    .fin-cards {
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    }

    .fin-chart-wrap .fin-chart {
        height: 240px;
    }
}

/* ========================
   股票详情：左侧 NavSidePanel 导航 + 右侧内容区
   面板用自身的 border-r 与内容紧贴（不另加 gap）；
   窄屏（≤1100px）NavSidePanel 自动变顶部横滚条，这里同步把布局改为纵向堆叠。
   ======================== */
.sd-layout {
    display: flex;
    align-items: stretch;
}

.sd-content {
    flex: 1 1 auto;
    min-width: 0;
    padding-left: 16px;
}

@media (max-width: 1100px) {
    .sd-layout {
        flex-direction: column;
    }

    .sd-content {
        padding-left: 0;
    }
}

.stock-info-top {
    padding: 20px 15px;
    border-bottom: 1px solid var(--app-border-base);
}

/* 顶部报价区的 PE-TTM 估值（仅 A 股） */
.pe-ttm-top {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    margin-top: 6px;
    font-size: 13px;
    color: var(--app-text-secondary);
}
.pe-ttm-label {
    font-size: 12px;
    color: var(--app-text-muted);
}
.pe-ttm-value {
    font-size: 15px;
    color: var(--app-select-text);
    font-variant-numeric: tabular-nums;
}
.pe-ttm-date {
    font-size: 11px;
    color: var(--app-text-muted);
}

/* 基本面分析 tab 的 PE-TTM 走势图 */
.pe-ttm-chart {
    width: 100%;
    height: 260px;
}

/* 基本面分析 tab 的卡片（PrimeVue <Card>）边框与「技术面分析」FactorPanel 的 .fp-card 对齐。
   .fp-card 是 0.5px 淡灰描边 + 12px 圆角；而全局 .p-card 被 _core.scss 压成 2px 圆角、
   Aura 默认 1px 边框，同一株详情页里两个 tab 的卡片观感明显割裂。这里局部覆盖，
   只作用于本页（StockDetail 里的 <Card> 全都在基本面分析 tab），不影响其它页面。 */
:deep(.p-card) {
    border: 0.5px solid var(--app-line-soft);
    border-radius: 12px;
}

/* ===== 设置分组弹窗 ===== */
.gp-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.gp-notice {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    padding: 10px 12px;
    border-radius: 6px;
    background-color: var(--app-warn-bg);
    border: 1px solid var(--app-warn-border);
    color: var(--app-warn-text);
    font-size: 12px;
    line-height: 1.6;
    /* 长文案可能把弹窗撑宽：允许在任意位置折行，且不参与父级的最小宽度计算 */
    min-width: 0;
    overflow-wrap: anywhere;

    .pi {
        flex-shrink: 0;
        margin-top: 2px;
    }
}

.gp-current {
    font-size: 12px;
    color: var(--app-text-secondary);
    min-width: 0;
    overflow-wrap: anywhere;

    b {
        color: var(--app-text-primary);
    }

    &__hint {
        color: var(--app-text-muted);
    }
}

.gp-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: 232px;
    overflow-y: auto;
    overflow-x: hidden;
}

.gp-item {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 7px 10px;
    border: 1px solid var(--app-border-base);
    border-radius: 6px;
    background-color: var(--app-bg-card);
    color: var(--app-text-primary);
    font-size: 13px;
    text-align: left;
    cursor: pointer;
    transition: background-color 0.15s, border-color 0.15s;

    &:hover {
        background-color: var(--app-bg-hover);
    }

    &.is-active {
        border-color: var(--app-select-border);
        background-color: var(--app-select-bg);
        color: var(--app-select-text);
        font-weight: 600;
    }

    .pi {
        flex-shrink: 0;
    }

    &__name {
        min-width: 0;
        flex: 1 1 auto;
        overflow-wrap: anywhere;
    }

    &__count {
        flex-shrink: 0;
        font-size: 11px;
        font-weight: 400;
        color: var(--app-text-muted);
    }
}

.gp-create {
    display: flex;
    flex-direction: column;
    gap: 8px;

    &__actions {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
    }
}

.gp-new {
    align-self: flex-start;
}

.gp-tip {
    font-size: 11px;
    color: var(--app-text-muted);
    line-height: 1.6;
    min-width: 0;
    overflow-wrap: anywhere;
}

</style>
