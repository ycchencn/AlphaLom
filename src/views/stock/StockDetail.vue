<script setup>

import {computed, onMounted, onUnmounted, watch} from 'vue';
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
    getLineChartOptions,
    formatCurrency,
    formatPercentage,
    calcDcfScore,
    parseNumber
} from '@/utils/function.js';
import MarkdownRenderer from '@/components/MarkdownRenderer.vue';
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
const news = ref(null);
const greed_data = ref([]);
const ohlc_data = ref([]);
const ohlc_last = ref({})
const lineData = ref(null);
const loading = ref(false);
const lineOptions = ref(null);
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

const echart1 = ref(null)

function render() {
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
                            fundamental_scores.value['cash_quality_score'],
                            score.finalScore,
                            fundamental_scores.value['debt_ratio_score'],
                            fundamental_scores.value['profit_growth_score'],
                            fundamental_scores.value['roe_score']
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

    lineOptions.value = getLineChartOptions();
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

    // 加载新闻关联数据
    axios.get('/api/v1/market/search_news?c=1&stock_code=' + stock_code).then(response => {
        news.value = response.data.items;
    });

    // 获取技术分析报告
    axios.get(`/api/v1/stock/tech_analysis_report/${stock_code}`).then(response => {
        tech_report.value = response.data
    });

    // 获取DCF分析报告
    axios.get(`/api/v1/stock/dcf_research_report/${stock_code}`).then(response => {
        loading.value = false;
        dcf_research_report.value = response.data
        neutral.value = parseNumber(dcf_research_report.value.content_json?.每股内在价值?.中性情景)
        optimistic.value = parseNumber(dcf_research_report.value.content_json?.每股内在价值?.乐观情景)
        conservative.value = parseNumber(dcf_research_report.value.content_json?.每股内在价值?.保守情景)

        // 获取基本面评分数据
        axios.get(`/api/v1/stock/fundamental_scores/${stock_code}`).then(response => {
            loading.value = false;
            fundamental_scores.value = response.data

            let chartDom = document.getElementById('el');
            echart1.value = echarts.init(chartDom)
            render()

        });
    });

    // 贪婪与恐惧数据
    axios.get('/api/v1/stock/greed_data/' + stock_code).then(response => {

        greed_data.value = response.data

        // 按 date 排序（确保时间顺序）
        const sortedData = [...greed_data.value].sort(
            (a, b) => new Date(a.trade_date).getTime() - new Date(b.trade_date).getTime()
        );

        const labels = sortedData.map(item => item.trade_date);
        const assets = sortedData.map(item => item.fear_greed);
        // const history_close = sortedData.map(item => item.close);

        // 更新 lineData.value
        lineData.value = {
            labels: labels,
            datasets: [
                {
                    label: '恐惧&贪婪指标',
                    data: assets,
                    backgroundColor: 'rgba(255, 71, 87, 0.8)',
                    borderColor: 'rgba(255, 71, 87, 0.8)',
                    pointRadius: 1,
                    borderWidth: 2,
                    tension: 0.3,
                }
            ]
        };

    });

    // 加载研报列表
    axios.get(`/api/v1/stock/research_reports/${stock_code}`).then(response => {
        research_reports.value = response.data || [];
    });

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

const getRatingSeverity = function (rating) {
    if (!rating) return 'secondary';
    const r = rating.toLowerCase();
    if (r.includes('买入') || r.includes('buy') || r.includes('强推')) return 'success';
    if (r.includes('增持') || r.includes('推荐')) return 'success';
    if (r.includes('中性') || r.includes('持有')) return 'warning';
    if (r.includes('卖出') || r.includes('减持')) return 'danger';
    return 'secondary';
}


onUnmounted(() => {
    dispose('chart');
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
        class="!w-full md:!w-200 lg:!w-[75rem]"
        :footer="false"
        body-class="p-0"
    >
        <div class="flex flex-col h-full" v-if="selected_report">
            <!-- 滚动区域 -->
            <div class="flex-1 overflow-y-auto">
                <div class="p-6">
                    <div class="mb-4">
                        <h2 class="text-2xl font-bold mb-2">{{ selected_report.title }}</h2>
                        <div class="flex gap-4 text-sm text-gray-500 mb-4">
                            <span><i class="pi pi-building"></i> {{ selected_report.broker_name }}</span>
                            <span><i class="pi pi-user"></i> {{ selected_report.analyst_name || '-' }}</span>
                            <span><i class="pi pi-calendar"></i> {{ formatDaysAgo(selected_report.publish_time) }}</span>
                        </div>
                    </div>

                    <Divider/>

                    <div v-if="selected_report.summary" class="mb-6">
                        <h3 class="text-lg font-semibold mb-2">摘要</h3>
                        <div class="text-gray-700">{{ selected_report.summary }}</div>
                    </div>

                    <Divider/>

                    <div class="mb-6">
                        <h3 class="text-lg font-semibold mb-2">正文内容</h3>
                        <iframe
                            v-if="selected_report.content_text"
                            :srcdoc="selected_report.content_text"
                            class="w-full border-0"
                            style="height: 600px;"
                            sandbox="allow-same-origin"
                        />
                        <div v-else class="text-gray-400">暂无内容</div>
                    </div>

                    <div class="h-4"></div>
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

        <div class="absolute top-8 right-8">
            <Button label="AI 估值分析" size="small" class="mr-2" @click="showDcfDrawer()" :loading="loading"></Button>
            <!-- <Button :label="watched ? '已关注' : '关注'" size="small" class="mr-2" @click="toggleLike()" :severity="watched ? '' : 'secondary'"></Button>-->
            <SplitButton label="操作" :model="items" size="small" severity="secondary"/>
        </div>
    </div>

    <Tabs value="tab1">
        <TabList style="border-top: 1px solid #eee;">
            <Tab value="tab1">技术面分析</Tab>
            <Tab value="tab2">基本面分析</Tab>
            <Tab value="tab3">新闻动态</Tab>
            <Tab value="tab4">财务分析</Tab>
            <Tab value="tab5">研报数据</Tab>
        </TabList>
        <TabPanels>
            <TabPanel value="tab1">

                <div class="mt-5">
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

                <div class="mt-5 flex flex-col md:flex-row gap-6">

                    <div class="w-full md:w-1/2 flex flex-col min-h-0">
                        <div class="font-semibold text-lg">
                            <i class="pi pi-sun text-orange-500"></i> 恐惧&贪婪指标
                            <span v-if="greed_data.length > 0">
                                【{{ fearGreedToText(greed_data?.[0]['fear_greed'])['advice'] }}】
                            </span>
                        </div>
                        <Divider/>
                        <div class="overflow-y-auto flex-1" v-if="greed_data">
                            <Chart type="line" :data="lineData" :options="lineOptions" style="height: 200px"></Chart>
                        </div>
                    </div>

                    <div class="w-full md:w-1/2 flex flex-col min-h-0" v-if="tech_report">
                        <div class="font-semibold text-lg">
                            <i class="pi pi-chart-line text-green-500"></i> 技术面深度诊断
                        </div>
                        <Divider/>
                        <div class="overflow-y-auto flex-1" v-if="greed_data">
                            <MarkdownRenderer
                                fontSize="11px"
                                :markdown="dictToMarkdownRecursive(tech_report.content_json['技术面深度诊断'])">
                            </MarkdownRenderer>
                        </div>
                    </div>

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
                    :paginator="true"
                    :rows="5"
                    dataKey="id"
                    :rowHover="true"
                    filterDisplay="menu"
                    :globalFilterFields="['stock_code']"
                    :showGridlines="false"
                >
                    <template #empty> No data found.</template>
                    <template #loading> Loading customers data. Please wait.</template>
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
                        :loading="report_loading"
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

</style>
