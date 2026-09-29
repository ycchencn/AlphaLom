<script setup>
import { onBeforeMount, onMounted, ref } from 'vue';
import axios from 'axios';
import FinPaasProgressBar from '@/components/FinPaasProgressBar.vue';
import ProgressBar200p from '@/components/ProgressBar200p.vue';
import { fetchMarketTempData, fetchIndexMarketData } from '@/utils/function.js';
import MarkdownRenderer from '@/components/MarkdownRenderer.vue';
const lineData = ref(null);
const pieData = ref(null);
const polarData = ref(null);
const barData = ref(null);
const radarData = ref(null);
const lineOptions = ref(null);
const pieOptions = ref(null);
const polarOptions = ref(null);
const barOptions = ref(null);
const radarOptions = ref(null);
const market_weights_list = ref(null);
const market_temp_data_last_date = ref(null);
const market_temp_data_last = ref({
    temperature: 0,
    ai_suggestion: ""
});

const fetchTurnOverRatesData = async () => {
    try {
        const response = await fetch(`/api/v1/market_turnover_rates`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

const fetchBackTestCount = async (last_signal_trade_type) => {
    try {
        const response = await fetch(`/api/v1/backtest_signals_count?last_signal_trade_type=` + last_signal_trade_type);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

onBeforeMount(() => {
    axios.get('/api/v1/market/market_weights_list').then(response => {
        market_weights_list.value = response.data;
        market_temp_data_last_date.value = response.data[0]['created_at']
    });
});

onMounted(async () => {

    setColorOptions();

    const documentStyle = getComputedStyle(document.documentElement);
    const backtest_signals_count_sell = await fetchBackTestCount('sell');
    const backtest_signals_count_buy = await fetchBackTestCount('buy');
    const _labels = backtest_signals_count_buy.map(item => item.last_signal_date);
    const _values = backtest_signals_count_buy.map(item => item._count);
    const _values_sell = backtest_signals_count_sell.map(item => item._count);

    barData.value = {
        labels: _labels,
        datasets: [
            {
                label: '买入',
                backgroundColor: 'rgba(255, 71, 87, 0.8)',
                borderColor: documentStyle.getPropertyValue('--p-primary-500'),
                data: _values
            },
            {
                label: '卖出',
                backgroundColor: 'rgba(46, 204, 113, 0.8)',
                borderColor: documentStyle.getPropertyValue('--p-primary-500'),
                data: _values_sell
            }
        ]
    };

    const trd = await fetchTurnOverRatesData();
    // const sz001 = await fetchIndexMarketData('sh000001');
    const market_temp_data = await fetchMarketTempData();

    const updateChartData = (trdData, market_temp_data) => {

        if (!Array.isArray(trdData) || !Array.isArray(market_temp_data)) {
            console.error('Expected arrays but got:', trdData, market_temp_data);
            return;
        }

        // 创建 trdData 和 market_temp_data 的可修改副本
        const sortedTrdData = [...trdData].sort((a, b) => new Date(a.date) - new Date(b.date));
        const sortedMarketData = [...market_temp_data].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

        // 构建 market_temp_data 的日期到温度映射表，统一处理为 "YYYY-MM-DD" 格式
        const temperatureMap = new Map();
        for (const item of sortedMarketData) {
            const dateObj = new Date(item.created_at);
            const formattedDate = dateObj.toISOString().split('T')[0]; // "YYYY-MM-DD"
            temperatureMap.set(formattedDate, item.temperature);
        }
        // 生成标签（来自 trdData 的 date）
        const labels = sortedTrdData.map(item => {
            const date = new Date(item.date);
            return date.toISOString().split('T')[0]; // 保证格式为 "YYYY-MM-DD"
        });
        // 从 trdData 构造加权换手率数据
        const turnoverRatios = sortedTrdData.map(item => item.weighted_turnover_ratios);
        // 从 trdData 构造温度数据（取 market_temp_data 的对应值，或 null）
        const temperatures = sortedTrdData.map((item) => {
            const date = new Date(item.date);
            const dateStr = date.toISOString().split('T')[0]; // 使用一致日期格式
            return temperatureMap.has(dateStr) ? temperatureMap.get(dateStr) : null;
        });

        market_temp_data_last.value = sortedMarketData[sortedMarketData.length - 1];

        // 更新 lineData.value
        lineData.value = {
            labels: labels,
            datasets: [
                {
                    label: '市场温度',
                    data: temperatures,
                    fill: false,
                    backgroundColor: 'rgba(255, 71, 87, 0.8)',
                    borderColor: 'rgba(255, 71, 87, 0.8)',
                    tension: 0.4,
                    yAxisID: 'y-axis-1', // 指定使用第一个 y 轴
                }
            ]
        };
    };

    // 调用更新函数
    updateChartData(trd, market_temp_data);

});

function setColorOptions() {

    const documentStyle = getComputedStyle(document.documentElement);
    const textColor = documentStyle.getPropertyValue('--text-color');
    const textColorSecondary = documentStyle.getPropertyValue('--text-color-secondary');
    const surfaceBorder = documentStyle.getPropertyValue('--surface-border');

    barOptions.value = {
        plugins: {
            legend: {
                labels: {
                    fontColor: textColor
                }
            }
        },
        scales: {
            x: {
                ticks: {
                    color: textColorSecondary,
                    font: {
                        weight: 500
                    }
                },
                grid: {
                    display: false,
                    drawBorder: false
                }
            },
            y: {
                ticks: {
                    color: textColorSecondary
                },
                grid: {
                    color: surfaceBorder,
                    drawBorder: false
                }
            }
        }
    };

    pieData.value = {
        labels: ['A', 'B', 'C'],
        datasets: [
            {
                data: [540, 325, 702],
                backgroundColor: [documentStyle.getPropertyValue('--p-indigo-500'), documentStyle.getPropertyValue('--p-purple-500'), documentStyle.getPropertyValue('--p-teal-500')],
                hoverBackgroundColor: [documentStyle.getPropertyValue('--p-indigo-400'), documentStyle.getPropertyValue('--p-purple-400'), documentStyle.getPropertyValue('--p-teal-400')]
            }
        ]
    };

    pieOptions.value = {
        plugins: {
            legend: {
                labels: {
                    usePointStyle: true,
                    color: textColor
                }
            }
        }
    };

    lineOptions.value = {
        plugins: {
            legend: {
                labels: {
                    fontColor: textColor
                }
            }
        },
        scales: {
            x: {
                ticks: {
                    color: textColorSecondary
                },
                grid: {
                    color: surfaceBorder,
                    drawBorder: false
                }
            },
            y: {
                ticks: {
                    color: textColorSecondary
                },
                grid: {
                    color: surfaceBorder,
                    drawBorder: false
                }
            }
        }
    };

    polarData.value = {
        datasets: [
            {
                data: [11, 16, 7, 3],
                backgroundColor: [documentStyle.getPropertyValue('--p-indigo-500'), documentStyle.getPropertyValue('--p-purple-500'), documentStyle.getPropertyValue('--p-teal-500'), documentStyle.getPropertyValue('--p-orange-500')],
                label: 'My dataset'
            }
        ],
        labels: ['Indigo', 'Purple', 'Teal', 'Orange']
    };

    polarOptions.value = {
        plugins: {
            legend: {
                labels: {
                    color: textColor
                }
            }
        },
        scales: {
            r: {
                grid: {
                    color: surfaceBorder
                }
            }
        }
    };

    radarData.value = {
        labels: ['Eating', 'Drinking', 'Sleeping', 'Designing', 'Coding', 'Cycling', 'Running'],
        datasets: [
            {
                label: 'My First dataset',
                borderColor: documentStyle.getPropertyValue('--p-indigo-400'),
                pointBackgroundColor: documentStyle.getPropertyValue('--p-indigo-400'),
                pointBorderColor: documentStyle.getPropertyValue('--p-indigo-400'),
                pointHoverBackgroundColor: textColor,
                pointHoverBorderColor: documentStyle.getPropertyValue('--p-indigo-400'),
                data: [65, 59, 90, 81, 56, 55, 40]
            },
            {
                label: 'My Second dataset',
                borderColor: documentStyle.getPropertyValue('--p-purple-400'),
                pointBackgroundColor: documentStyle.getPropertyValue('--p-purple-400'),
                pointBorderColor: documentStyle.getPropertyValue('--p-purple-400'),
                pointHoverBackgroundColor: textColor,
                pointHoverBorderColor: documentStyle.getPropertyValue('--p-purple-400'),
                data: [28, 48, 40, 19, 96, 27, 100]
            }
        ]
    };

    radarOptions.value = {
        plugins: {
            legend: {
                labels: {
                    fontColor: textColor
                }
            }
        },
        scales: {
            r: {
                grid: {
                    color: textColorSecondary
                }
            }
        }
    };
}

</script>

<template>
    <Fluid class="grid grid-cols-12 gap-8 mt-root">
        <div class="col-span-12 xl:col-span-6">
            <div class="card">
                <div class="font-semibold text-xl mb-4">沪深+港股 市场温度指标</div>
                <Chart type="line" :data="lineData" :options="lineOptions"></Chart>
            </div>
        </div>
        <div class="col-span-12 xl:col-span-6">
            <div class="card">
                <div class="font-semibold text-xl mb-4">每日量化信号量</div>
                <Chart type="bar" :data="barData" :options="barOptions"></Chart>
            </div>
        </div>
    </Fluid>
</template>

<style scoped lang="scss">
/* 页面外边距对齐全站约定：横向 2rem（=24px），与 .card 页内容左边缘一致（204）。
   原先无 style 块，grid 直接顶到内容区左边缘。注意 gap-8 是栅格列间距，
   不等于页面外边距，两者都需要。 */
.mt-root {
    padding: 2rem;
}
</style>
