<script setup>

import { onMounted, onUnmounted } from 'vue';
import { init, dispose } from 'klinecharts';

import { ref } from 'vue';
import { useRoute } from 'vue-router';
import { chartConfigs } from '@/utils/constants.js';
import axios from 'axios';
import { fetchStockMarketData, fetchStockInfo } from '@/utils/function.js';

const route = useRoute();
const backtest_id = route.params.id;
const stock_code = route.params.stock_code;
const stock_info = ref({ name: '' });

const fetchBackTestTrade = async (backtest_id) => {
    try {
        // ⚠️ 必须用 axios：backtest 路由有 router 级 get_current_user 依赖，
        // 原生 fetch 不带 Authorization → 401。
        const response = await axios.get(`/api/v1/get_backtest_trades/` + backtest_id);
        return response.data;
    } catch (error) {
        console.error('Error fetching stock data:', error?.response?.status || error.message);
        return [];
    }
};

onMounted(async () => {
    const chart = init('chart');
    const stock_data = await fetchStockMarketData(stock_code);
    const backtest_trades = await fetchBackTestTrade(backtest_id)
    stock_info.value = await fetchStockInfo(stock_code)
    let style = {
        text: {
            color: 'white',
            backgroundColor: '#2DC08E'
        }
    };
    if (stock_data.length === 0) {
        console.warn('No stock data received.');
        return;
    } else {
        chart.applyNewData(stock_data);
        chart.setStyles(chartConfigs);
    }

    chart.createIndicator('VOL');
    chart.createIndicator('BOLL', false, { id: 'candle_pane' });

    for(const i in backtest_trades){
        // 创建一个新的 Date 对象
        const date = new Date(backtest_trades[i].created_at);
        // 获取时间戳，单位为毫秒
        backtest_trades[i].timestamp = date.getTime();
        if (backtest_trades[i].trade_type === 'sell') {
            backtest_trades[i].trade_type = 'S'
            style = {
                text: {
                    color: '#2DC08E'
                },
            }
        } else {
            backtest_trades[i].trade_type = 'B'
            style = {
                text: {
                    color: '#F92855'
                },
            }
        }
        chart.createOverlay({
            name: 'simpleAnnotation',
            points: [
                {
                    timestamp: backtest_trades[i].timestamp,
                    value: backtest_trades[i].price,
                    mode: 'strong_magnet'
                }
            ],
            extendData: backtest_trades[i].trade_type + ' ' + Math.abs(backtest_trades[i].size),
            styles: style
        });
    }
});

onUnmounted(() => {
    dispose('chart');
});

</script>

<template>
    <div class="card">
        <div class="font-semibold text-xl mb-4">{{ stock_info.name }} ({{ stock_code }}) 回测记录</div>
        <div id="chart" style="width: 100%; height: 600px;"></div>
    </div>
    <Fluid class="grid grid-cols-12 gap-8">
        <div class="col-span-12 xl:col-span-8">
            <div class="card">
                <div class="font-semibold text-xl mb-4">回测交易明细</div>
                <Chart type="line" :data="lineData" :options="lineOptions"></Chart>
            </div>
        </div>
        <div class="col-span-12 xl:col-span-4">
            <div class="card">
                <div class="font-semibold text-xl mb-4">市场涨跌停对比</div>
                <Chart type="bar" :data="barData" :options="barOptions"></Chart>
            </div>
        </div>
    </Fluid>
</template>

<style scoped lang="scss">
:deep(.p-datatable-frozen-tbody) {
    font-weight: bold;
}

:deep(.p-datatable-scrollable .p-frozen-column) {
    font-weight: bold;
}
</style>
