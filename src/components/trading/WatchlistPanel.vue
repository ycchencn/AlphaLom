<script setup>
import {computed, onBeforeMount, ref} from 'vue'
import axios from "axios"

const props = defineProps({
    selectedSymbol: {type: String, default: null},
    realtimeQuotes: {type: Object, default: () => ({})}   // 从父组件传入的实时行情
})

const page_size = 150
const activeTab = ref('全部')
const tabs = ['全部', '持仓', '自选', '监控']
const stock_list = ref([])
const sortOrder = ref('desc')   // 排序状态：'asc' | 'desc' | 'none'

function loadStockList() {
    axios.get(`/api/v1/stocks_monitored?page_size=${page_size}&page=1&market=cn&simple=1`)
        .then(response => {
            stock_list.value = response.data.map(item => {
                const ohlc = item.ohlc_last
                return {
                    ...item,
                    chg_pct: ohlc?.chg_pct ?? null,
                    close: ohlc?.close ?? null,
                    open: ohlc?.open ?? null,
                    high: ohlc?.high ?? null,
                    low: ohlc?.low ?? null,
                    lastClose: ohlc?.pre_close ?? ohlc?.lastClose ?? null,   // 昨日收盘价，用于计算实时涨跌幅
                }
            })
        })
        .catch(error => {
            console.error('加载股票列表失败:', error)
        })
}

const sortedStocks = computed(() => {
    const merged = stock_list.value.map(stock => {
        const rt = props.realtimeQuotes[stock.symbol]
        if (!rt) return stock
        let chg_pct = rt.chg_pct ?? null
        // 从行情计算最新的涨跌幅
        if (chg_pct === null && rt.lastClose != null && rt.lastClose !== 0) {
            chg_pct = Number(((rt.lastPrice - rt.lastClose) / rt.lastClose * 100).toFixed(2))
        }
        return {
            ...stock,
            close: rt.lastPrice ?? stock.close,
            chg_pct: chg_pct ?? stock.chg_pct,
            high: rt.high ?? stock.high,
            low: rt.low ?? stock.low,
            open: rt.open ?? stock.open,
        }
    })
    if (sortOrder.value === 'none') return merged
    return [...merged].sort((a, b) => {
        const aVal = a.chg_pct ?? 0
        const bVal = b.chg_pct ?? 0
        return sortOrder.value === 'desc' ? bVal - aVal : aVal - bVal
    })
})

// 点击表头切换排序
function toggleSort() {
    if (sortOrder.value === 'none') sortOrder.value = 'desc'
    else if (sortOrder.value === 'desc') sortOrder.value = 'asc'
    else sortOrder.value = 'none'
}

const emit = defineEmits(['update:symbol'])
const selectStock = (code) => {
    emit('update:symbol', code)
}

onBeforeMount(() => {
    loadStockList()
})
</script>

<template>
    <aside class="w-80 h-full border-r border-gray-800 bg-neutral-900 flex flex-col shrink-0"
           style="height: 96vh; margin-top: 1px;">
        <!-- 头部区域 -->
        <div class="px-3 pt-3 pb-2 border-b border-gray-800 shrink-0">
            <div class="flex gap-1 text-xs mb-2 text-gray-400">
                <button v-for="t in tabs" :key="t" :class="{'!text-white': activeTab === t}" @click="activeTab = t">
                    {{ t }}
                </button>
            </div>
        </div>

        <!-- 表格区域 -->
        <div class="flex-1 overflow-y-auto custom-scrollbar">
            <table class="w-full text-sm">
                <thead>
                <tr class="text-gray-400 text-xs border-b border-gray-800 sticky top-0 bg-neutral-900">
                    <th class="text-left py-2 px-4 font-medium">名称</th>
                    <th class="text-center py-2 px-2 font-medium"></th>
                    <th class="text-right py-2 px-4 font-medium">最新价</th>
                    <th class="text-right py-2 px-4 font-medium cursor-pointer select-none"
                        @click="toggleSort">
                        涨跌幅
                        <span v-if="sortOrder === 'asc'" class="text-blue-400 ml-1">↑</span>
                        <span v-else-if="sortOrder === 'desc'" class="text-blue-400 ml-1">↓</span>
                        <span v-else class="text-gray-600 ml-1">↕</span>
                    </th>
                </tr>
                </thead>
                <tbody>
                <tr v-for="stock in sortedStocks"
                    :key="stock.symbol"
                    :class="{ 'bg-gray-800': selectedSymbol === stock.symbol }"
                    @click="selectStock(stock.symbol)"
                    class="hover:bg-gray-800 cursor-pointer border-b border-gray-800/40 transition-colors">
                    <td class="py-2 px-2">
                        <div style="color: #ffc53f; width: 55px;">{{ stock.name }}</div>
                        <div class="text-[10px] text-gray-500">{{ stock.symbol }}</div>
                    </td>
                    <td class="py-2 px-2 text-right">
                      <span :class="(stock.chg_pct ?? 0) >= 0 ? 'text-red-500' : 'text-green-500'">
                        {{ (stock.chg_pct ?? 0) >= 0 ? '▲' : '▼' }}
                      </span>
                    </td>
                    <td class="py-2 px-2 text-right font-mono text-[10px]" :class="(stock.chg_pct ?? 0) >= 0 ? 'text-red-500' : 'text-green-500'">
                        {{ stock.close?.toFixed(2) ?? '-' }}
                    </td>
                    <td class="py-2 text-center">
                      <span class="inline-block px-2 py-0.5 text-white font-medium text-center text-[10px]" style="width: 52px"
                            :class="(stock.chg_pct ?? 0) >= 0 ? 'bg-red-500' : 'bg-green-500'">
                        {{ (stock.chg_pct ?? 0) >= 0 ? '+' : '' }}{{ stock.chg_pct?.toFixed(2) ?? '0.00' }}%
                      </span>
                    </td>
                </tr>
                </tbody>
            </table>
        </div>
    </aside>
</template>

<style scoped>

.bg-red-500{
    background: var(--app-up);
}

.bg-green-500{
    background: var(--app-down);
}

.custom-scrollbar::-webkit-scrollbar {
    width: 6px;
}

.custom-scrollbar::-webkit-scrollbar-track {
    background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
    background-color: #4b5563;
    border-radius: 3px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
    background-color: #6b7280;
}
</style>