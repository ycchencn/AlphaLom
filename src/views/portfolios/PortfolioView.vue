<script setup>
import {ref, onMounted, onUnmounted, computed, watch, nextTick} from 'vue';
import {useRoute} from 'vue-router';
import * as echarts from 'echarts';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Card from 'primevue/card';
import Badge from 'primevue/badge';
import {useNotification} from '@/composables/useNotification';
import {
    fetchPortfolioInfo,
    formatCurrency,
    formatHoldingDuration,
    formatDaysAgo,
    fetchPortfolioSummaryDaily,
    fetchPortfolioTransaction
} from '@/utils/function.js';
import axios from 'axios';
import Dialog from 'primevue/dialog';
import MarkdownEditor from '@/components/MarkdownEditor.vue';

const {showSuccess, showError} = useNotification();

// 状态
const route = useRoute();
const portfolioId = route.params.portfolio_id;
const profInfo = ref(null);
const profSummary = ref(null);
const profTransaction = ref(null);
const loading = ref(true);
// ⚠️ 加载失败要单独留一个状态：以前所有异常都被 try/catch 吞掉，`loading` 又在 finally 置 false，
// 于是「接口 401」的表现是有概览区、但标题永远停在「加载中...」，用户完全看不出发生了什么
// （而这正是「列表能看、点进去就 401」那个 bug 的观感）。现在区分「加载中 / 加载失败 / 成功」。
const loadError = ref('');
// ⚠️ 原来这里有 lineData / lineDataAssets / lineOptions 三个 ref，是喂给 PrimeVue <Chart>（Chart.js）的。
// 两张走势图换成 ECharts 之后它们**只写不读**（模板里的 <Chart> 已删除）→ 已清理。
const modal_visible = ref(false);
const editDialogVisible = ref(false);
const editSubmitting = ref(false);
const code = ref(``);

// 盈亏日历数据 / 量化报告抽屉 / 操作建议索引（按 stock_code）
const profitData = ref({});
const portfolio_quantstat = ref(null);
const dcf_research_report_drawer = ref(false);
const actionMap = ref({});

// ==================== 净资产 / 累计收益率走势图（ECharts） ====================
// 形态与全站其它走势卡片一致：平滑曲线 + 渐变面积 + 定制 tooltip + 货币/百分比轴标签。
// ⚠️ 两张图（净资产、累计收益率）**各自独立一个实例**：容器分别在不同 Card 里，
//    共用一个实例会让后 init 的那个把先 init 的画面顶掉（表现为只有一张图有内容）。
const equityChartRef = ref(null);
const returnChartRef = ref(null);
let equityChart = null;
let returnChart = null;

// 行业分布饼图（按持仓市值加权）
const industryChartRef = ref(null);
let industryChart = null;

// 档位配色（红涨绿跌，A 股口径）
const UP_COLOR = '#ef4444';
const DOWN_COLOR = '#12783c';

// 孤儿实例三件套（与 MarketOverview / StockDetail 同构）：
// 容器在 v-if 内 → init 必须等数据到位；宿主 DOM 被替换/摘除时要 dispose 重建。
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

// 把「货币」轴刻度压成 1.2万 / 356万 这种短标签，否则 1234567.89 会把轴挤爆
const compactMoney = (v) => {
    const n = Number(v);
    if (!isFinite(n)) return '—';
    const abs = Math.abs(n);
    if (abs >= 1e8) return (n / 1e8).toFixed(2) + '亿';
    if (abs >= 1e4) return (n / 1e4).toFixed(1) + '万';
    return n.toFixed(0);
};

// 收益率序列：以**第一个点**为基准算累计收益率（%）。
// ⚠️ 不能用 init_cash 当基准：summary 的第一天已经是「建仓后」的资产，用 init_cash 会让首日
//    就显示一个非零起点。以序列首值为基准，曲线必然从 0% 起，符合「区间收益」的直觉。
const returnPct = (values) => {
    if (!values.length) return [];
    const base = Number(values[0]);
    if (!isFinite(base) || base === 0) return values.map(() => null);
    return values.map((v) => {
        const n = Number(v);
        return isFinite(n) ? ((n / base) - 1) * 100 : null;
    });
};

const renderEquityChart = async () => {
    await nextTick();
    equityChart = ensureChart(equityChart, equityChartRef);
    if (!equityChart) return;

    const rows = profSummary.value || [];
    if (!rows.length) { equityChart.clear(); return; }

    const sorted = [...rows].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    const dates = sorted.map((r) => r.date);
    const assets = sorted.map((r) => Number(r.total_assets));

    const first = assets[0];
    const last = assets[assets.length - 1];
    const up = last >= first;
    const mainColor = up ? UP_COLOR : DOWN_COLOR;
    const areaFrom = up ? 'rgba(239,68,68,0.20)' : 'rgba(18,120,60,0.20)';
    const areaTo = up ? 'rgba(239,68,68,0.02)' : 'rgba(18,120,60,0.02)';

    // 极值标注：最大 / 最小净资产（只看纵轴看不出「我在哪」，标出来才有体感）
    let maxIdx = 0, minIdx = 0;
    assets.forEach((v, i) => {
        if (v > assets[maxIdx]) maxIdx = i;
        if (v < assets[minIdx]) minIdx = i;
    });

    equityChart.setOption({
        grid: {left: 52, right: 20, top: 16, bottom: 26},
        tooltip: {
            trigger: 'axis',
            axisPointer: {type: 'line', lineStyle: {color: '#cbd5e1', type: 'dashed'}},
            formatter: (params) => {
                const p = params[0];
                const idx = p.dataIndex;
                const prev = idx > 0 ? assets[idx - 1] : null;
                const chg = prev ? ((assets[idx] / prev) - 1) * 100 : null;
                const chgHtml = chg == null ? ''
                    : `<br/>较前一日：<b style="color:${chg >= 0 ? UP_COLOR : DOWN_COLOR}">`
                      + `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</b>`;
                return `<div style="font-size:12px">`
                    + `<b>${p.axisValue}</b><br/>`
                    + `净资产：<b>${formatCurrency(assets[idx])}</b>`
                    + chgHtml
                    + `</div>`;
            }
        },
        xAxis: {
            type: 'category',
            data: dates,
            boundaryGap: false,
            axisLine: {lineStyle: {color: '#eef1f6'}},
            axisLabel: {fontSize: 9, color: '#94a3b8', hideOverlap: true},
            axisTick: {show: false}
        },
        yAxis: {
            type: 'value',
            scale: true,
            splitNumber: 4,
            axisLabel: {fontSize: 9, color: '#94a3b8', formatter: compactMoney},
            splitLine: {lineStyle: {color: '#eef1f6'}}
        },
        series: [{
            name: '净资产',
            type: 'line',
            smooth: true,
            showSymbol: false,
            connectNulls: true,
            lineStyle: {width: 2, color: mainColor},
            data: assets.map((v, i) => {
                if (i === 0 || i === assets.length - 1 || i === maxIdx || i === minIdx) {
                    return {value: v, symbol: 'circle', symbolSize: 5};
                }
                return v;
            }),
            itemStyle: {color: mainColor},
            areaStyle: {
                color: {
                    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{offset: 0, color: areaFrom}, {offset: 1, color: areaTo}]
                }
            },
            markPoint: {
                symbol: 'pin',
                symbolSize: 30,
                label: {fontSize: 9, color: '#fff', formatter: (p) => compactMoney(p.value)},
                data: [
                    {type: 'max', name: '最高', itemStyle: {color: '#94a3b8'}},
                    {type: 'min', name: '最低', itemStyle: {color: '#cbd5e1'}}
                ]
            }
        }]
    });
};

const renderReturnChart = async () => {
    await nextTick();
    returnChart = ensureChart(returnChart, returnChartRef);
    if (!returnChart) return;

    const rows = profSummary.value || [];
    if (rows.length < 2) { returnChart.clear(); return; }

    const sorted = [...rows].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    const dates = sorted.map((r) => r.date);
    const pct = returnPct(sorted.map((r) => Number(r.total_assets)));

    const last = pct[pct.length - 1];
    const up = (last ?? 0) >= 0;
    const mainColor = up ? UP_COLOR : DOWN_COLOR;
    const areaFrom = up ? 'rgba(239,68,68,0.22)' : 'rgba(18,120,60,0.22)';
    const areaTo = up ? 'rgba(239,68,68,0.02)' : 'rgba(18,120,60,0.02)';

    returnChart.setOption({
        grid: {left: 46, right: 20, top: 16, bottom: 26},
        tooltip: {
            trigger: 'axis',
            axisPointer: {type: 'line', lineStyle: {color: '#cbd5e1', type: 'dashed'}},
            formatter: (params) => {
                const p = params[0];
                const v = pct[p.dataIndex];
                if (v == null) return `<b>${p.axisValue}</b><br/>收益率：—`;
                return `<div style="font-size:12px"><b>${p.axisValue}</b><br/>`
                    + `累计收益率：<b style="color:${v >= 0 ? UP_COLOR : DOWN_COLOR}">`
                    + `${v >= 0 ? '+' : ''}${v.toFixed(2)}%</b><br/>`
                    + `净资产：${formatCurrency(sorted[p.dataIndex].total_assets)}</div>`;
            }
        },
        xAxis: {
            type: 'category',
            data: dates,
            boundaryGap: false,
            axisLine: {lineStyle: {color: '#eef1f6'}},
            axisLabel: {fontSize: 9, color: '#94a3b8', hideOverlap: true},
            axisTick: {show: false}
        },
        yAxis: {
            type: 'value',
            scale: true,
            splitNumber: 4,
            axisLabel: {fontSize: 9, color: '#94a3b8', formatter: (v) => Number(v).toFixed(1) + '%'},
            splitLine: {lineStyle: {color: '#eef1f6'}}
        },
        series: [{
            name: '累计收益率',
            type: 'line',
            data: pct,
            smooth: true,
            showSymbol: false,
            connectNulls: true,
            lineStyle: {width: 2, color: mainColor},
            itemStyle: {color: mainColor},
            areaStyle: {
                color: {
                    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{offset: 0, color: areaFrom}, {offset: 1, color: areaTo}]
                }
            },
            // 0% 基准线：收益/亏损的分界，没有它看不出「什么时候开始亏的」
            markLine: {
                silent: true,
                symbol: 'none',
                label: {show: false},
                lineStyle: {type: 'dashed', color: '#e2e8f0'},
                data: [{yAxis: 0}]
            }
        }]
    });
};

const resizeCharts = () => {
    equityChart?.resize();
    returnChart?.resize();
    industryChart?.resize();
};

// 行业分布饼图：扇区权重 = 持仓市值（size×price），tooltip 同时给出市值与占组合总市值比。
// ⚠️ 颜色用固定调色板（红涨绿跌之外的中性色），行业数量不固定，ECharts 会循环取色。
const INDUSTRY_PALETTE = [
    '#ef4444', '#12783c', '#3b82f6', '#f59e0b', '#8b5cf6',
    '#ec4899', '#14b8a6', '#6366f1', '#f97316', '#0ea5e9',
    '#a855f7', '#22c55e'
];

const renderIndustryPie = async () => {
    await nextTick();
    industryChart = ensureChart(industryChart, industryChartRef);
    if (!industryChart) return;

    const dist = industryDistribution.value;
    if (!dist || !dist.data.length) { industryChart.clear(); return; }

    industryChart.setOption({
        color: INDUSTRY_PALETTE,
        tooltip: {
            trigger: 'item',
            formatter: (p) => {
                const pct = dist.total ? (p.value / dist.total * 100) : 0;
                return `<div style="font-size:12px"><b>${p.name}</b><br/>`
                    + `持仓市值：${formatCurrency(p.value)}<br/>`
                    + `行业占比：<b>${pct.toFixed(2)}%</b></div>`;
            }
        },
        legend: {
            type: 'scroll',
            orient: 'horizontal',
            bottom: 2,
            left: 'center',
            itemWidth: 10,
            itemHeight: 10,
            itemGap: 10,
            textStyle: { fontSize: 11, color: '#64748b' }
        },
        series: [{
            name: '行业分布',
            type: 'pie',
            radius: ['42%', '62%'],
            center: ['50%', '44%'],
            avoidLabelOverlap: true,
            itemStyle: { borderColor: '#fff', borderWidth: 2 },
            label: { show: false },
            labelLine: { show: false },
            emphasis: {
                label: { show: false },
                itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' }
            },
            data: dist.data
        }]
    });
};

// 空态用的「区间统计」，让图表区在数据不足时也有信息而不是空白
const returnStats = computed(() => {
    const rows = profSummary.value || [];
    if (rows.length < 2) return null;
    const sorted = [...rows].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    const pct = returnPct(sorted.map((r) => Number(r.total_assets))).filter((v) => v != null);
    if (!pct.length) return null;
    return {
        total: pct[pct.length - 1],
        max: Math.max(...pct),
        min: Math.min(...pct),
        days: sorted.length
    };
});

// 行业分布（按持仓市值加权）：把持仓明细按 industry 聚合，权重 = 持仓量 × 现价。
// 后端已在资产里补了 `industry` 字段（来自 stocks.industry，关联不到标「其他」），
// 这里纯前端聚合，和页面其它「市值/占比」口径一致（getMarketValue 也是 size×price）。
const industryDistribution = computed(() => {
    const assets = profInfo.value?.assets || [];
    const byIndustry = {};
    let total = 0;
    assets.forEach((a) => {
        const mv = (a.position_size || 0) * (a.position_price || 0);
        if (!mv) return; // 市值为 0 的标的（如已清仓）不计入分布
        const ind = a.industry || '其他';
        byIndustry[ind] = (byIndustry[ind] || 0) + mv;
        total += mv;
    });
    const data = Object.keys(byIndustry)
        .map((name) => ({ name, value: byIndustry[name] }))
        .sort((x, y) => y.value - x.value); // 市值大的行业排前面
    return { data, total };
});

// 编辑表单数据
const editForm = ref({
    name: '',
    strategy_type: 1,
    init_cash: 0,
    desc: '',
    llm_setting: {
        model: '',
        platform: 'aliyun'
    }
});

// 策略类型选项
const strategyTypeOptions = [
    { label: '技术面', value: 0 },
    { label: 'AI主观', value: 1 },
];

// 大模型平台选项
const platformOptions = [
    { label: '阿里云百炼', value: 'aliyun' },
    { label: 'DeepSeek', value: 'deepseek' },
    { label: '火山引擎', value: 'volcengine' },
    { label: 'SiliconFlow', value: 'siliconflow' },
    { label: '智谱', value: 'zhipu' },
];

// ---- 模型列表（后端 GET /api/v1/llm/models?platform=xx，实时调各平台 /models 接口）----
// 与平台下拉联动：切换平台后拉取该平台可用模型（客户端按平台缓存，切回不重复请求）；
// 接口失败时退化为可手动输入，不阻塞编辑流程
const modelOptionsByPlatform = ref({});
const modelsLoading = ref(false);
const loadLlmModels = (platform) => {
    if (!platform || modelOptionsByPlatform.value[platform] !== undefined) return; // 已有缓存
    modelsLoading.value = true;
    axios.get('/api/v1/llm/models', { params: { platform } })
        .then(response => {
            const info = (response.data || {})[platform];
            modelOptionsByPlatform.value[platform] = info?.models || [];
            if (info?.error) {
                showError(`获取 ${platform} 模型列表失败，可手动输入模型名称`);
            }
        })
        .catch(err => {
            console.error('模型列表加载失败', err);
            modelOptionsByPlatform.value[platform] = [];
            showError('获取模型列表失败，可手动输入模型名称');
        })
        .finally(() => {
            modelsLoading.value = false;
        });
};

// 当前平台下的可选模型
const modelOptions = computed(() => modelOptionsByPlatform.value[editForm.value.llm_setting.platform] || []);

// 平台切换联动：拉取新平台的模型列表；当前模型不在新平台选项里时，自动切到首个模型（没有则清空）
watch(() => editForm.value.llm_setting.platform, (platform) => {
    loadLlmModels(platform);
    if (editForm.value.llm_setting.model && !modelOptions.value.includes(editForm.value.llm_setting.model)) {
        editForm.value.llm_setting.model = modelOptions.value[0] || '';
    }
});

// 打开编辑弹窗即拉当前平台的模型列表
watch(editDialogVisible, (visible) => {
    if (visible) loadLlmModels(editForm.value.llm_setting.platform);
});

// 编辑器选项对象
const editorOptions = {
    minimap: {enabled: false}, // 启用缩略图
    fontSize: 12,
    scrollBeyondLastLine: false,
    automaticLayout: true
};

// 处理编辑器挂载完成事件
const handleEditorDidMount = (editor) => {
    // console.log('Editor mounted!', editor);
    // editorInstance = editor;
    // 你可以在 editorInstance 上调用任何 Monaco Editor API
    // 例如: editor.addAction(...)
};

// 在获取 profInfo 后，为每个 asset 添加 positionPct 和 marketValue
const enrichAssets = (info) => {
    if (!info?.assets || !Array.isArray(info.assets)) return;

    // 优先使用 summary.total_assets（最准确）
    const totalAssets = info.summary?.total_assets;

    if (typeof totalAssets !== 'number' || totalAssets <= 0) {
        // 如果没有 total_assets，回退到手动计算：股票市值 + 现金
        const totalPositionValue = info.assets.reduce((sum, asset) => {
            return sum + ((asset.position_size || 0) * (asset.position_price || 0));
        }, 0);
        const cash = info.current_cash || 0;
        info._fallbackTotalAssets = totalPositionValue + cash;
    }

    // 1. 首先确保 daily_pnl 是按日期排序的（最新的在最后或最前）
    // 假设数据是按时间倒序排列的（最新的在索引0），如果不是，请先排序
    const sortedPnL = [...info.daily_pnl].sort((a, b) => new Date(b.date) - new Date(a.date));

    // 2. 创建一个映射表，存储“昨天”的数据，用于快速查找
    // 键为 stock_code，值为昨天的 market_value
    const yesterdayDataMap = new Map();
    const todayDataMap = new Map();

    if (sortedPnL.length > 1) {
        // 获取昨天的数据组（索引为1，因为0是今天）
        // 注意：这里假设 sortedPnL[0] 是今天，sortedPnL[1] 是昨天
        const yesterdayDate = profSummary.value[profSummary.value.length - 2].date;
        const yesterdayGroup = sortedPnL.filter(record => record.date === yesterdayDate);
        yesterdayGroup.forEach(record => {
            yesterdayDataMap.set(record.stock_code, {
                unrealized_pnl: record.unrealized_pnl
            });
        });
        const todayDate = profSummary.value[profSummary.value.length - 1].date;
        const todayGroup = sortedPnL.filter(record => record.date === todayDate);
        todayGroup.forEach(record => {
            todayDataMap.set(record.stock_code, {
                unrealized_pnl: record.unrealized_pnl
            });
        });
    }

    // 3. 遍历今天的资产列表 (info.assets)，计算日变动
    info.assets.forEach(asset => {
        const todayMV = todayDataMap.unrealized_pnl;
        asset.marketValue = todayMV;

        // 计算占总资产比例 (保持原有逻辑)
        const denominator = typeof totalAssets === 'number' && totalAssets > 0
            ? totalAssets
            : (info._fallbackTotalAssets || 1);
        asset.positionPct = (todayMV / denominator) * 100;

        // --- 关键：计算日变动 ---
        const todayInfo = todayDataMap.get(asset.stock_code);
        const yesterdayInfo = yesterdayDataMap.get(asset.stock_code);

        if (yesterdayInfo && todayInfo) {
            // 如果昨天持有该股票
            // 注意：这里直接用市值相减，已经自动包含了价格波动和分红等所有因素
            asset.dailyChange = todayInfo.unrealized_pnl - yesterdayInfo.unrealized_pnl;
        } else {
            // 如果昨天没有持有（新买入），通常日变动设为 0
            // 或者如果你想显示“买入当天的盈亏”，可以计算 (现价-成本)*数量
            // 这里遵循“相对昨天”的定义，设为 0
            asset.dailyChange = 0;
            asset.dailyChangePct = 0;
        }
    });

    // 为每个 asset 添加计算字段
    info.assets.forEach(asset => {
        const mv = (asset.position_size || 0) * (asset.position_price || 0);
        asset.marketValue = mv;
        const denominator = typeof totalAssets === 'number' && totalAssets > 0
            ? totalAssets
            : (info._fallbackTotalAssets || 1); // 避免除零
        asset.positionPct = (mv / denominator) * 100;
    });
};

// 在 script setup 内部，ref 之后
// 👇 替换原有的 buyActions computed
const buyActions = computed(() => {
    // 如果数据未加载，返回空数组
    if (!profInfo.value?.position_plan?.actions || !profInfo.value?.assets) {
        return [];
    }
    // 提取当前所有的持仓股票代码，用于快速查找
    const heldStockCodes = new Set(profInfo.value.assets.map(asset => asset.stock_code));
    // 过滤出买入动作，并标记是“买入”还是“加仓”
    return profInfo.value.position_plan.actions
        .filter(a => a.action === 'buy')
        .map(action => {
            // 检查当前持仓中是否包含这只股票
            const isHeld = heldStockCodes.has(action.stock_code);
            // 给对象添加一个新属性，用于模板显示
            return {
                ...action,
                displayType: isHeld ? 'add' : 'buy' // 'add'代表加仓, 'buy'代表新建仓
            };
        });
});
const holdActions = computed(() =>
    profInfo.value?.position_plan?.actions?.filter(a => a.action === 'hold') || []
);
const sellActions = computed(() =>
    profInfo.value?.position_plan?.actions?.filter(a => a.action === 'sell') || []
);

// 获取单个股票的持仓市值
const getMarketValue = (asset) => {
    return (asset.position_size || 0) * (asset.position_price || 0);
};

const getUnrealizedPnL = (asset) => {
    if (!asset.cost_price || !asset.position_price || !asset.position_size) return 0;
    return (asset.position_price - asset.cost_price) * asset.position_size;
};

const getPnLPct = (asset) => {
    if (!asset.cost_price || asset.cost_price === 0) return 0;
    return ((asset.position_price / asset.cost_price) - 1) * 100;
};

onMounted(async () => {

    // 窗口尺寸变化时让两张 ECharts 自适应（Chart.js 有自己的 responsive，ECharts 需要手动 resize）
    window.addEventListener('resize', resizeCharts);

    try {
        loadError.value = '';

        // 获取统计数据
        const summary = await fetchPortfolioSummaryDaily(portfolioId) || [];
        profSummary.value = summary;

        // 获取交易记录
        profTransaction.value = await fetchPortfolioTransaction(portfolioId) || [];

        // 获取策略信息
        const data = await fetchPortfolioInfo(portfolioId);
        enrichAssets(data); // 👈 关键：注入计算字段
        profInfo.value = data;
        code.value = profInfo.value.llm_prompt;
        /**
         * [
         *   {
         *     "cash_balance": 707772.5,
         *     "created_at": "2026-01-15T23:59:58",
         *     "cumulative_realized_pnl": 0.0,
         *     "daily_pnl_change": 0.0,
         *     "date": "2026-01-15",
         *     "id": 22,
         *     "portfolio_id": "1",
         *     "position_ratio": 0.6221,
         *     "total_assets": 1872931.0,
         *     "total_pnl_pct": 0.0,
         *     "total_unrealized_pnl": 0.0,
         *     "updated_at": "2026-01-15T23:59:58"
         *   },
         *
         * **/

        // 👇 2. 遍历并安全赋值
        summary.forEach(item => {
            // 确保 item 存在，且包含必要的字段
            if (item && item.date) {
                // 使用 || 0 确保如果 daily_pnl_change 为 null/undefined 时，默认为 0
                profitData.value[item.date] = item.daily_pnl_change || 0;
            }
        });

        // 数据齐了才画（容器在 v-if 内，必须等 DOM 到位）
        await renderEquityChart();
        await renderReturnChart();
        await renderIndustryPie();

    } catch (err) {
        // 401 已由 main.js 的响应拦截器处理（清令牌 + 跳登录），这里只负责把页面状态摆正，
        // 避免用户停在一个「标题加载中、下面啥都没有」的页面上猜发生了什么。
        const status = err?.response?.status;
        if (status === 401) {
            loadError.value = '登录状态已失效，正在跳转登录页…';
        } else if (status === 404) {
            loadError.value = '该组合不存在，或不属于当前账号。';
        } else {
            loadError.value = '组合数据加载失败，请稍后重试。';
        }
        console.error('Failed to load portfolio:', err);
    } finally {
        loading.value = false;
    }
});

// 数据加载完（profInfo 就位）后再绑定操作建议索引 —— 原来单独挂在一个 onMounted 里，
// 而那时异步数据还没回来，`position_plan` 必然为 undefined → actionMap 永远是空的。
watch(profInfo, (info) => {
    if (info?.position_plan?.actions) {
        const map = {};
        info.position_plan.actions.forEach((act) => {
            map[act.stock_code] = act;
        });
        actionMap.value = map;
    }
});

// 数据刷新（如「触发AI调仓分析」后重新拉取）时，行业饼图跟着重绘
watch(industryDistribution, () => {
    renderIndustryPie();
});

onUnmounted(() => {
    window.removeEventListener('resize', resizeCharts);
    equityChart?.dispose();
    equityChart = null;
    returnChart?.dispose();
    returnChart = null;
    industryChart?.dispose();
    industryChart = null;
});

const items = [
    {
        label: '编辑组合信息',
        icon: 'pi pi-pencil',
        command: () => {
            openEditDialog();
        }
    },
    {
        label: '编辑模型prompt',
        icon: 'pi pi-code',
        command: () => {
            modal_visible.value = true;
        }
    },
    {
        label: '触发AI调仓分析',
        icon: 'pi pi-bolt',
        command: () => {
            triggerAnalysis();
        }
    }
];

// 触发AI调仓分析
const analysisLoading = ref(false);
const triggerAnalysis = async () => {
    if (!profInfo.value) return;
    
    analysisLoading.value = true;
    try {
        await axios.post(`/api/v1/portfolio/${encodeURIComponent(portfolioId)}/analyze`, {
            send_feishu: false
        });
        showSuccess('AI调仓分析完成');
        // 重新加载数据
        const data = await fetchPortfolioInfo(portfolioId);
        enrichAssets(data);
        profInfo.value = data;
    } catch (error) {
        let message = '分析失败，请重试';
        if (error?.response?.data?.msg) {
            message = error.response.data.msg;
        }
        showError(message);
    } finally {
        analysisLoading.value = false;
    }
};

// 打开编辑弹窗
const openEditDialog = () => {
    if (!profInfo.value) return;
    
    editForm.value = {
        name: profInfo.value.name || '',
        strategy_type: profInfo.value.strategy_type ?? 1,
        init_cash: profInfo.value.init_cash || 0,
        desc: profInfo.value.desc || '',
        llm_setting: profInfo.value.llm_setting || {
            model: '',
            platform: 'aliyun'
        }
    };
    editDialogVisible.value = true;
};

// 提交编辑
const submitEdit = async () => {
    const f = editForm.value;
    
    // 校验
    if (!f.name || !String(f.name).trim()) {
        showError('请输入组合名称');
        return;
    }
    if (f.init_cash == null || Number(f.init_cash) <= 0) {
        showError('初始资金必须大于 0');
        return;
    }
    
    // 仅 AI 主观策略需要验证大模型配置
    let llm_setting = null;
    if (f.strategy_type === 1) {
        if (!f.llm_setting.model || !String(f.llm_setting.model).trim()) {
            showError('请输入大模型名称');
            return;
        }
        llm_setting = {
            model: String(f.llm_setting.model || '').trim(),
            platform: f.llm_setting.platform
        };
    }

    editSubmitting.value = true;
    try {
        await axios.put(`/api/v1/portfolio/${encodeURIComponent(portfolioId)}`, {
            name: String(f.name).trim(),
            strategy_type: Number(f.strategy_type),
            init_cash: Number(f.init_cash),
            desc: f.desc,
            llm_setting: llm_setting
        });
        showSuccess('组合信息更新成功');
        editDialogVisible.value = false;
        // 重新加载数据
        const data = await fetchPortfolioInfo(portfolioId);
        enrichAssets(data);
        profInfo.value = data;
    } catch (error) {
        let message = '更新失败，请重试';
        if (error?.response?.data?.msg) {
            message = error.response.data.msg;
        }
        showError(message);
    } finally {
        editSubmitting.value = false;
    }
};

async function updatePortfolioPrompt() {
    try {
        await axios.put(`/api/v1/portfolio/${encodeURIComponent(portfolioId)}`, {
            llm_prompt: code.value,
        });
        showSuccess('编辑模型prompt成功');
    } catch (error) {
        let message = '操作失败，请重试';
        if (axios.isAxiosError(error)) {
            if (error.response) {
                const {status, data} = error.response;
                console.error('HTTP 错误:', status, data);
                if (status === 404) {
                    message = '数据不存在';
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

const showDcfDrawer = function () {
    // 分析数据
    loading.value = true;
    axios.get(`/api/v1/portfolio_quantstat/${portfolioId}`).then(response => {
        loading.value = false;
        portfolio_quantstat.value = response.data;
        dcf_research_report_drawer.value = true;
    }).catch(() => {
        // 401 由全局拦截器处理；其它错误至少别让按钮永远停在 loading 态
        loading.value = false;
        showError('绩效报告加载失败');
    });
}

// 加载失败后的「重新加载」：整页 reload 会把登录态一起清掉重走，代价大；
// 这里只重跑本页的取数动作即可。
const reload = () => window.location.reload();

</script>

<template>

    <Drawer
        v-model:visible="dcf_research_report_drawer"
        header="量化策略绩效报告"
        position="right"
        class="!w-full md:!w-300 lg:!w-[92rem]"
        :footer="false"
        body-class="p-0"
    >
        <!-- iframe 替代 v-html，彻底隔离样式 -->
        <iframe
            v-if="portfolio_quantstat"
            :srcdoc="portfolio_quantstat"
            class="w-full h-full border-0"
            sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
            title="量化报告"
        />
        <!-- 无数据时的占位 -->
        <div v-else class="flex items-center justify-center h-full text-gray-400">
            暂无报告数据
        </div>
    </Drawer>

    <!-- 编辑组合信息弹窗 -->
    <Dialog v-model:visible="editDialogVisible" modal header="编辑组合信息" :style="{ width: '32rem' }">
        <div class="flex flex-col gap-4">
            <div>
                <label for="edit_name" class="font-semibold block mb-1">组合名称 <span class="text-red-500">*</span></label>
                <InputText id="edit_name" v-model="editForm.name" autocomplete="off" placeholder="请输入组合名称" class="w-full" />
            </div>

            <div>
                <label for="edit_desc" class="font-semibold block mb-1">持仓风格 / 描述</label>
                <Textarea id="edit_desc" v-model="editForm.desc" rows="2" autoResize class="w-full" />
            </div>

            <div>
                <label for="edit_strategy_type" class="font-semibold block mb-1">策略类型</label>
                <Dropdown id="edit_strategy_type" v-model="editForm.strategy_type" :options="strategyTypeOptions" optionLabel="label" optionValue="value" class="w-full" />
            </div>

            <div>
                <label for="edit_init_cash" class="font-semibold block mb-1">初始资金 <span class="text-red-500">*</span></label>
                <InputNumber id="edit_init_cash" v-model="editForm.init_cash" mode="currency" currency="CNY" locale="zh-CN" :min="0" class="w-full" />
            </div>

            <!-- 仅 AI 主观策略需要配置大模型 -->
            <template v-if="editForm.strategy_type === 1">
                <div>
                    <label for="edit_platform" class="font-semibold block mb-1">大模型平台</label>
                    <Dropdown id="edit_platform" v-model="editForm.llm_setting.platform" :options="platformOptions" optionLabel="label" optionValue="value" class="w-full" />
                </div>

                <div>
                    <label for="edit_model" class="font-semibold block mb-1">模型名称 <span class="text-red-500">*</span></label>
                    <Dropdown
                        id="edit_model"
                        v-model="editForm.llm_setting.model"
                        :options="modelOptions"
                        :loading="modelsLoading"
                        editable
                        filter
                        placeholder="选择模型，也可手动输入"
                        :empty-message="modelsLoading ? '正在获取模型列表…' : '该平台暂无可用模型，可手动输入'"
                        class="w-full"
                    />
                </div>
            </template>
        </div>

        <template #footer>
            <div class="flex justify-end gap-2">
                <Button type="button" label="取消" severity="secondary" text @click="editDialogVisible = false" :disabled="editSubmitting" />
                <Button type="button" label="保存" :loading="editSubmitting" @click="submitEdit" />
            </div>
        </template>
    </Dialog>

    <Dialog v-model:visible="modal_visible" modal header="编辑模型Prompt" style="width: 950px;">
        <div class="flex items-center gap-4 mb-4">
            <MarkdownEditor
                v-model="code"
                language="markdown"
                theme="vs-dark"
                :options="editorOptions"
                :closable="true"
                :dismissableMask="true"
                @editorDidMount="handleEditorDidMount"
            />
        </div>
        <div class="flex justify-end gap-2">
            <Button type="button" label="取消" severity="secondary" @click="modal_visible=false"></Button>
            <Button type="button" label="保存" @click="modal_visible=false;updatePortfolioPrompt();"></Button>
        </div>
    </Dialog>

    <div class="card mx-auto relative" style="padding-top: 20px;">

        <!-- 右上角操作按钮 -->
        <div class="absolute top-8 right-8">
            <Button label="QuantStat" size="small" class="mr-2" @click="showDcfDrawer()" :loading="loading"></Button>
            <SplitButton label="操作" :model="items" severity="secondary"/>
        </div>

        <!-- 标题 -->
        <h1 class="text-2xl font-bold mb-3 text-gray-800">
            {{ profInfo?.name || '加载中...' }}
        </h1>

        <div class="text-sm text-gray-500 mb-3">
            持仓风格：{{ profInfo?.desc || '加载中...' }}
        </div>

        <div class="text-sm text-gray-500 mb-3" v-if="profInfo?.llm_setting">
            大模型版本：{{ profInfo?.llm_setting.model || '加载中...' }}
        </div>

        <!-- 组合概览卡片 -->
        <div v-if="profInfo" class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">

            <Card>
                <template #title>总资产</template>
                <template #content>
                    <div class="text-xl font-semibold text-blue-700 font-mono">
                        {{ formatCurrency(profInfo.summary?.total_assets) }}
                    </div>
                    <div class="text-xs text-gray-500 mt-1">股票市值 + 现金</div>
                </template>
            </Card>
            <Card>
                <template #title>可用现金</template>
                <template #content>
                    <div class="text-xl font-semibold text-green-700 font-mono">
                        {{ formatCurrency(profInfo.current_cash) }}
                    </div>
                    <div class="text-xs text-gray-500 mt-1">可用于买入的现金资产</div>
                </template>
            </Card>
            <Card>
                <template #title>仓位</template>
                <template #content>
                    <div class="text-xl font-semibold text-purple-700 font-mono">
                        {{ (profInfo.summary?.position_ratio * 100).toFixed(2) }}%
                    </div>
                    <div class="text-xs text-gray-500 mt-1">股票市值 / 总资产</div>
                </template>
            </Card>
            <Card>
                <template #title>浮动盈亏</template>
                <template #content>
                    <div
                        :class="[
              'text-xl font-semibold',
              profInfo.summary?.total_unrealized_pnl < 0
                ? 'text-green-700'
                : 'text-red-500',
            ]"
                    >
                        {{ formatCurrency(profInfo.summary?.total_unrealized_pnl, true) }}
                    </div>
                    <div class="text-xs text-gray-500 mt-1">账面持仓参考盈亏</div>
                </template>
            </Card>
            <Card>
                <template #title>持仓市值</template>
                <template #content>
                    <div class="text-xl font-semibold text-red-400 font-mono">
                        {{ formatCurrency(profInfo.summary?.total_assets - profInfo.current_cash) }}
                    </div>
                    <div class="text-xs text-gray-500 mt-1">持仓股数 * 现价</div>
                </template>
            </Card>
            <Card>
                <template #title>夏普比率</template>
                <template #content>
                    <div class="text-lg font-semibold text-gray-500">
                        {{ profInfo.quantstat_json?.sharpe.toFixed(2) }}
                    </div>
                    <div class="text-xs text-gray-500 mt-1">夏普比率 (Sharpe Ratio)</div>
                </template>
            </Card>
            <Card>
                <template #title>最大回撤</template>
                <template #content>
                    <div class="text-lg font-semibold text-gray-500">
                        {{ (profInfo.quantstat_json?.max_drawdown * 100).toFixed(2) }} %
                    </div>
                    <div class="text-xs text-gray-500 mt-1">最大回撤 (Max Drawdown)</div>
                </template>
            </Card>
            <Card>
                <template #title>复合年均增长率</template>
                <template #content>
                    <div class="text-lg font-semibold text-gray-500">
                        {{ (profInfo.quantstat_json?.cagr * 100).toFixed(2) }} %
                    </div>
                    <div class="text-xs text-gray-500 mt-1">复合年均增长率（CAGR）</div>
                </template>
            </Card>
        </div>

        <!-- 策略说明区域 -->
        <div v-if="profInfo?.position_plan" class="mb-8 space-y-5">

            <Card>
                <template #title><b class="text-lg">市场点评</b></template>
                <template #content>
                    <p class="text-gray-700 text-sm">{{ profInfo.position_plan.market_context }}</p>
                </template>
            </Card>

            <Card>
                <template #title><b class="text-lg">交易复盘</b></template>
                <template #content>
                    <p class="text-gray-700 text-sm">{{ profInfo.position_plan.trading_review }}</p>
                </template>
            </Card>

            <Card>
                <template #title><b class="text-lg">优化建议</b></template>
                <template #content>
                    <p class="text-gray-700 text-sm">{{ profInfo.position_plan.trading_rule_adjust }}</p>
                </template>
            </Card>

            <!--            <Card>-->
            <!--                <template #title><b class="text-lg">收益走势</b></template>-->
            <!--                <template #content>-->
            <!--                    <Chart type="line" :data="lineData" :options="lineOptions" style="height: 300px"></Chart>-->
            <!--                </template>-->
            <!--            </Card>-->

            <Card>
                <template #title>
                    <div class="flex items-center justify-between gap-2 flex-wrap">
                        <b class="text-lg">净资产走势</b>
                        <span v-if="returnStats" class="text-xs font-normal text-gray-500">
                            区间 {{ returnStats.days }} 个交易日
                        </span>
                    </div>
                </template>
                <template #content>
                    <div class="pv-chart-wrap">
                        <div v-if="returnStats" class="pv-chart-side">
                            <div class="pv-side-label">区间累计收益</div>
                            <div
                                class="pv-side-value"
                                :class="returnStats.total >= 0 ? 'text-red-500' : 'text-green-600'"
                            >
                                {{ returnStats.total >= 0 ? '+' : '' }}{{ returnStats.total.toFixed(2) }}%
                            </div>
                            <div class="pv-side-row">
                                <span class="pv-side-k">区间最高</span>
                                <span class="pv-side-v text-red-500">
                                    +{{ returnStats.max.toFixed(2) }}%
                                </span>
                            </div>
                            <div class="pv-side-row">
                                <span class="pv-side-k">区间最低</span>
                                <span class="pv-side-v text-green-600">
                                    {{ returnStats.min.toFixed(2) }}%
                                </span>
                            </div>
                        </div>
                        <div class="pv-chart-main">
                            <div ref="equityChartRef" class="pv-chart"></div>
                        </div>
                    </div>
                </template>
            </Card>

            <Card>
                <template #title>
                    <div class="flex items-center justify-between gap-2 flex-wrap">
                        <b class="text-lg">累计收益率走势</b>
                        <span class="text-xs font-normal text-gray-500">
                            以区间首个交易日净资产为基准（0%）
                        </span>
                    </div>
                </template>
                <template #content>
                    <div v-if="returnStats" class="pv-chart-wrap">
                        <div class="pv-chart-main">
                            <div ref="returnChartRef" class="pv-chart"></div>
                        </div>
                    </div>
                    <div v-else class="pv-empty">交易日不足 2 天，暂无法绘制收益率走势</div>
                </template>
            </Card>

            <!--            <Card>-->
            <!--                <template #title><b class="text-lg">收益日历</b></template>-->
            <!--                <template #content>-->
            <!--                    <div style=" width: 400px;">-->
            <!--                    <ProfitLossCalendar-->
            <!--                      :profit-data="profitData"-->
            <!--                      :initial-date="new Date(2026, 0, 1)"-->
            <!--                    />-->
            <!--                    </div>-->
            <!--                </template>-->
            <!--            </Card>-->

        </div>

        <!-- 操作建议摘要（按动作类型分组）+ 行业分布：桌面端左右并列 -->
        <div class="flex flex-col xl:flex-row gap-6 items-start mb-8">
            <!-- 左：操作建议摘要 -->
            <div v-if="profInfo?.position_plan?.actions" class="w-full xl:flex-1 xl:min-w-0 space-y-6">
            <!-- 买入建议 -->
            <div v-if="buyActions.length > 0">
                <h3 class="text-lg font-semibold text-green-700 mb-2 flex items-center">
                    <i class="pi pi-plus-circle mr-2"></i> 买入计划
                </h3>
                <div class="flex flex-wrap gap-2">
                  <span
                      v-for="action in buyActions"
                      :key="`buy-${action.stock_code}`"
                      class="inline-flex items-center px-3 py-1.5 bg-green-50 border border-green-200 rounded-full text-sm text-green-800"
                  ><!-- ✅ 动态 Badge：根据是否有持仓显示不同文本 -->
                    <Badge
                        :value="action.displayType === 'add' ? '加仓' : '买入'"
                        :severity="action.displayType === 'add' ? 'warning' : 'success'"
                        class="mr-2"
                    />
                    {{ action.stock_name }}（{{ action.quantity }}股）
                    <span v-if="action.reason" class="ml-2 text-xs opacity-80">{{ action.reason }}</span>
                  </span>
                </div>
            </div>

            <!-- 持有建议 -->
            <div v-if="holdActions.length > 0">
                <h3 class="text-lg font-semibold text-blue-700 mb-2 flex items-center">
                    <i class="pi pi-eye mr-2"></i> 继续持有
                </h3>
                <div class="flex flex-wrap gap-2">
                  <span
                      v-for="action in holdActions"
                      :key="`hold-${action.stock_code}`"
                      class="inline-flex items-center px-3 py-1.5 bg-blue-50 border border-blue-200 rounded-full text-sm text-blue-800"
                  >
                    <Badge value="持有" severity="info" class="mr-2"/>
                    {{ action.stock_name }}
                    <span v-if="action.reason" class="ml-2 text-xs opacity-80">{{ action.reason }}</span>
                  </span>
                </div>
            </div>

            <!-- 卖出建议（可选） -->
            <div v-if="sellActions.length > 0">
                <h3 class="text-lg font-semibold text-red-700 mb-2 flex items-center">
                    <i class="pi pi-minus-circle mr-2"></i> 卖出计划
                </h3>
                <div class="flex flex-wrap gap-2">
                  <span
                      v-for="action in sellActions"
                      :key="`sell-${action.stock_code}`"
                      class="inline-flex items-center px-3 py-1.5 bg-red-50 border border-red-200 rounded-full text-sm text-red-800"
                  >
                    <Badge value="卖出" severity="danger" class="mr-2"/>
                    {{ action.stock_name }}（{{ action.quantity }}股）
                    <span v-if="action.reason" class="ml-2 text-xs opacity-80">{{ action.reason }}</span>
                  </span>
                </div>
            </div>
            </div>

            <!-- 右：行业分布饼图（与买卖计划同行，固定宽度，不挤压表格）-->
            <div v-if="industryDistribution && industryDistribution.data.length" class="w-full xl:w-[420px] xl:flex-shrink-0">
                <Card>
                    <template #title>
                        <div class="flex items-center justify-between gap-2 flex-wrap">
                            <b class="text-lg">持仓行业分布</b>
                            <span class="text-xs font-normal text-gray-500">
                                按持仓市值加权 · 共 {{ industryDistribution.data.length }} 个行业
                            </span>
                        </div>
                    </template>
                    <template #content>
                        <div class="pv-industry-chart">
                            <div ref="industryChartRef" class="pv-chart"></div>
                        </div>
                    </template>
                </Card>
            </div>
        </div>

        <!-- 持仓明细表格 -->
        <div v-if="profInfo && profInfo.assets.length > 0">
            <h2 class="text-xl font-semibold mb-4">持仓明细</h2>
            <p class="mb-4 text-gray-500 text-sm">
                每个交易日盘后更新数据，最新数据日期：{{ formatDaysAgo(profInfo.assets[0]['last_update']) }}</p>
            <DataTable
                :value="profInfo.assets"
                :rows="20"
                sortField="positionPct"
                :rowHover="true"
                :showGridlines="false"
                size="medium"
                style="font-size: 11px"
                :sortOrder="-1"
            >
                <Column field="stock_code" header="代码" style="width: 100px">
                    <template #body="slotProps">
                        <a
                            class="text-blue-600 hover:underline font-mono"
                            :href="`https://gushitong.baidu.com/stock/ab-${slotProps.data.stock_code}`"
                            target="_blank"
                        >{{ slotProps.data.stock_code }}</a>
                    </template>
                </Column>

                <Column field="name" header="名称" style="width: 140px">
                    <template #body="slotProps">
                        {{ slotProps.data.name }}
                    </template>
                </Column>

                <Column field="position_size" header="持仓量" style="width: 100px" sortable>
                    <template #body="slotProps">
                        <span>{{ slotProps.data.position_size?.toLocaleString() || '—' }}</span>
                    </template>
                </Column>

                <!-- ✅ 新增：仓位占比 -->
                <Column field="positionPct" header="仓位占比" style="width: 100px" sortable>
                    <template #body="slotProps">
                        <span>{{ slotProps.data.positionPct.toFixed(2) }}%</span>
                    </template>
                </Column>

                <!-- ✅ 新增：持仓市值 -->
                <Column header="持仓市值" style="width: 120px">
                    <template #body="slotProps">
                        <span>{{ formatCurrency(getMarketValue(slotProps.data)) }}</span>
                    </template>
                </Column>

                <Column field="cost_price" header="成本价" style="width: 100px">
                    <template #body="slotProps">
                        <span>{{ slotProps.data.cost_price?.toFixed(3) || '—' }}</span>
                    </template>
                </Column>

                <Column field="position_price" header="收盘价" style="width: 100px">
                    <template #body="slotProps">
                        <span>{{ slotProps.data.position_price?.toFixed(3) || '—' }}</span>
                    </template>
                </Column>

                <Column field="pnl" header="浮动盈亏" style="width: 120px" sortable>
                    <template #body="slotProps">
                  <span

                      :class="{
                      'text-red-500': getUnrealizedPnL(slotProps.data) > 0,
                      'text-green-600': getUnrealizedPnL(slotProps.data) < 0,
                    }"
                  >
                    {{ formatCurrency(getUnrealizedPnL(slotProps.data), true) }}
                  </span>
                    </template>
                </Column>

                <Column header="盈亏%" style="width: 100px">
                    <template #body="slotProps">
                  <span

                      :class="{
                      'text-red-500': getPnLPct(slotProps.data) > 0,
                      'text-green-600': getPnLPct(slotProps.data) < 0,
                    }"
                  >
                    {{ getPnLPct(slotProps.data)?.toFixed(2) || '—' }}%
                  </span>
                    </template>
                </Column>

                <Column header="最新盈亏" style="width: 100px">
                    <template #body="slotProps">
                      <span

                          :class="{
                          'text-red-500': slotProps.data.dailyChange > 0,
                          'text-green-600': slotProps.data.dailyChange < 0,
                        }"
                      >
                        {{ formatCurrency(slotProps.data.dailyChange, true) }}
                      </span>
                    </template>
                </Column>

                <Column header="持仓时长" style="width: 100px">
                    <template #body="slotProps">
                        <span>
                            {{ formatHoldingDuration(slotProps.data.create_time) }}
                        </span>
                    </template>
                </Column>
            </DataTable>
        </div>

        <!-- 交易记录 -->
        <div v-if="profInfo && profInfo.assets.length > 0" class="mt-8">
            <h2 class="text-xl font-semibold mb-4">交易记录</h2>
            <p class="mb-4 text-gray-500 text-sm">
                每个交易日盘后更新数据，最新数据日期：{{ formatDaysAgo(profInfo.assets[0]['last_update']) }}</p>
            <DataTable
                :value="profTransaction"
                :paginator="true"
                :rows="15"
                sortField="positionPct"
                size="medium"
                style="font-size: 11px"
                :rowHover="true"
                :showGridlines="false"
                :sortOrder="-1"
            >
                <Column field="code" header="代码" style="width: 100px">
                    <template #body="slotProps">
                        <a
                            class="text-blue-600 hover:underline font-mono"
                            :href="`https://gushitong.baidu.com/stock/ab-${slotProps.data.code}`"
                            target="_blank"
                        >{{ slotProps.data.code }}</a>
                    </template>
                </Column>

                <Column field="name" header="名称" style="width: 140px">
                    <template #body="slotProps">
                        {{ slotProps.data.name }}
                    </template>
                </Column>

                <Column field="name" header="操作">
                    <template #body="slotProps">
                        {{ slotProps.data.action }}
                    </template>
                </Column>

                <Column field="name" header="成交价">
                    <template #body="slotProps">
                        <span>{{ formatCurrency(slotProps.data.price, false, 3) }}</span>
                    </template>
                </Column>

                <Column field="name" header="数量">
                    <template #body="slotProps">
                        <span>{{ slotProps.data.qty }}</span>
                    </template>
                </Column>

                <Column field="name" header="金额">
                    <template #body="slotProps">
                        <span>{{ formatCurrency(slotProps.data.amount) }}</span>
                    </template>
                </Column>

                <Column field="name" header="实现盈亏">
                    <template #body="slotProps">
                        <span

                            :class="{
                              'text-red-500': slotProps.data.realized_pnl > 0,
                              'text-green-600': slotProps.data.realized_pnl < 0,
                              }"
                        >
                            {{ formatCurrency(slotProps.data.realized_pnl, true) }}
                        </span>
                    </template>
                </Column>

                <Column field="name" header="时间">
                    <template #body="slotProps">
                        {{ formatDaysAgo(slotProps.data.created_at) }}
                    </template>
                </Column>


            </DataTable>
        </div>

        <!-- 加载状态 -->
        <div v-else-if="loading" class="text-center py-10 text-gray-500">
            <i class="pi pi-spin pi-spinner mr-2"></i>加载中...
        </div>

        <!-- 错误状态：明确区分「无权限 / 不存在 / 网络失败」，不再和「加载中」混为一谈 -->
        <div v-else-if="loadError" class="text-center py-10">
            <i class="pi pi-exclamation-circle text-3xl text-red-400 mb-3 block"></i>
            <div class="text-red-500 mb-3">{{ loadError }}</div>
            <Button label="重新加载" size="small" severity="secondary" @click="reload" />
        </div>

        <!-- 兜底 -->
        <div v-else class="text-center py-10 text-gray-500">暂无组合数据</div>


    </div>

</template>

<style scoped>
/* 增强 Card 边框：Aura 主题默认只有极淡阴影、无边框，这里补一条清晰但克制的中性边框 */
.p-card {
    border: 1px solid #dedede;
}
:global(html.app-dark) .p-card {
    border-color: #334155;
}

/* ===== 走势卡片布局（与全站 fear-greed / growth-value 卡片同构：左读数 + 右图）===== */
.pv-chart-wrap {
    display: flex;
    align-items: stretch;
    gap: 16px;
}

.pv-chart-side {
    flex: 0 0 180px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 8px;
    padding-right: 20px;
    border-right: 1px solid #eef1f6;
}

.pv-side-label {
    font-size: 11px;
    color: #94a3b8;
    /* ⚠️ 读数区与图表贴太近时，"区间累计收益" 会被折线压过去（视觉重叠）——
       这里靠 line-height 与 margin 把它和数值成组，和右侧图表拉开呼吸感 */
    line-height: 1.4;
}

.pv-side-value {
    font-size: 26px;
    font-weight: 600;
    line-height: 1.25;
    font-variant-numeric: tabular-nums;
    margin-bottom: 2px;
}

.pv-side-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 11px;
    gap: 8px;
}

.pv-side-k {
    color: #94a3b8;
}

.pv-side-v {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}

.pv-chart-main {
    flex: 1 1 auto;
    min-width: 0;   /* ⚠️ 不加会被 flex 子项的最小内容宽度撑破，图表不随容器收缩 */
}

.pv-chart {
    width: 100%;
    height: 300px;
}

.pv-industry-chart {
    width: 100%;
}

.pv-empty {
    height: 300px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #94a3b8;
    font-size: 12px;
}

/* 深色模式：分隔线换成深色，避免一条亮线特别扎眼 */
:global(html.app-dark) .pv-chart-side {
    border-right-color: #334155;
}

@media (max-width: 768px) {
    .pv-chart-wrap {
        flex-direction: column;
    }

    .pv-chart-side {
        flex: 0 0 auto;
        flex-direction: row;
        flex-wrap: wrap;
        align-items: baseline;
        gap: 4px 16px;
        padding-right: 0;
        padding-bottom: 10px;
        border-right: 0;
        border-bottom: 1px solid #eef1f6;
    }

    .pv-side-value {
        font-size: 22px;
    }

    .pv-chart {
        height: 220px;
    }
}
</style>
