<script setup>

import {FilterMatchMode} from '@primevue/core/api';
import {useNotification} from '@/composables/useNotification';
import {onBeforeMount, ref} from 'vue';
import Dialog from 'primevue/dialog';
import axios from 'axios';
import PriceRange52Week from '@/components/PriceRange52Week.vue';
import {
    formatStockTradeAmount,
} from '@/utils/function.js';

const etfList = ref([]);
const filters1 = ref(null);
const loading1 = ref(false);
const {showSuccess, showError} = useNotification();

// 添加 ETF 弹窗状态
const modalVisible = ref(false);
const searchKeyword = ref('');
const searchResults = ref([]);
const searching = ref(false);
const addingSymbol = ref('');   // 正在添加的 symbol，用于禁用对应按钮

function loadETFList() {
    loading1.value = true;
    axios.get(`/api/v1/etfs`).then(response => {
        etfList.value = response.data;
    }).catch(() => {
        etfList.value = [];
    }).finally(() => {
        loading1.value = false;
    });
}

function openAddModal() {
    modalVisible.value = true;
    searchKeyword.value = '';
    searchResults.value = [];
}

// 输入防抖后调用搜索接口
let searchTimer = null;
function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    const kw = searchKeyword.value.trim();
    if (!kw) {
        searchResults.value = [];
        return;
    }
    searchTimer = setTimeout(() => doSearch(kw), 300);
}

async function doSearch(kw) {
    searching.value = true;
    try {
        const r = await axios.get('/api/v1/etf_search', {params: {keyword: kw, limit: 50}});
        searchResults.value = Array.isArray(r.data) ? r.data : [];
    } catch (e) {
        searchResults.value = [];
    } finally {
        searching.value = false;
    }
}

async function addEtf(row) {
    const symbol = row.symbol;
    addingSymbol.value = symbol;
    try {
        await axios.post('/api/v1/etf', {symbol, name: row.name || null});
        showSuccess(`已添加 ${row.name || symbol}`);
        // 从搜索结果里移除，避免重复添加
        searchResults.value = searchResults.value.filter(x => x.symbol !== symbol);
        loadETFList();
    } catch (e) {
        let msg = '添加失败，请重试';
        if (e.response && e.response.data && e.response.data.detail) msg = e.response.data.detail;
        else if (e.response && e.response.data && e.response.data.message) msg = e.response.data.message;
        showError(msg);
    } finally {
        addingSymbol.value = '';
    }
}

async function deleteEtf(symbol) {
    try {
        await axios.delete(`/api/v1/etf/${encodeURIComponent(symbol)}`);
        showSuccess(`已删除 ${symbol}`);
        loadETFList();
    } catch (e) {
        let msg = '删除失败，请重试';
        if (e.response && e.response.data && e.response.data.detail) msg = e.response.data.detail;
        showError(msg);
    }
}

// 按代码直接添加（搜索无结果时的兜底）
async function addBySymbol(symbol) {
    const sym = (symbol || '').trim();
    if (!sym) return;
    addingSymbol.value = sym;
    try {
        await axios.post('/api/v1/etf', {symbol: sym, name: null});
        showSuccess(`已添加 ${sym}`);
        searchKeyword.value = '';
        searchResults.value = [];
        loadETFList();
    } catch (e) {
        let msg = '添加失败，请重试';
        if (e.response && e.response.data && e.response.data.detail) msg = e.response.data.detail;
        else if (e.response && e.response.data && e.response.data.message) msg = e.response.data.message;
        showError(msg);
    } finally {
        addingSymbol.value = '';
    }
}

function initFilters1() {
    filters1.value = {
        global: {value: null, matchMode: FilterMatchMode.CONTAINS},
    };
}

onBeforeMount(() => {
    loadETFList();
    initFilters1();
});

</script>

<template>
    <Toast/>
    <!-- 添加 ETF 弹窗：支持按代码/名称搜索 databull 全市场 ETF 目录 -->
    <Dialog v-model:visible="modalVisible" modal header="添加 ETF" :style="{ width: '30rem' }">
        <div class="flex flex-col gap-3">
            <IconField>
                <InputIcon>
                    <i class="pi pi-search"/>
                </InputIcon>
                <InputText
                    v-model="searchKeyword"
                    @input="onSearchInput"
                    placeholder="输入代码或名称搜索"
                    class="w-full"
                    autocomplete="off"
                />
            </IconField>

            <div v-if="searching" class="text-center text-gray-500 py-4">
                <i class="pi pi-spin pi-spinner"/>
            </div>
            <div v-else-if="searchKeyword.trim() && searchResults.length === 0" class="text-center text-gray-400 py-4">
                未找到匹配的 ETF
            </div>
            <div v-else class="flex flex-col gap-2 max-h-80 overflow-auto">
                <div v-for="item in searchResults" :key="item.symbol"
                     class="flex items-center justify-between border rounded p-2">
                    <div class="min-w-0">
                        <div class="font-semibold truncate">{{ item.symbol }}</div>
                        <div class="text-xs text-gray-500 truncate">{{ item.name }}</div>
                    </div>
                    <Button
                        icon="pi pi-plus"
                        label="添加"
                        size="small"
                        :loading="addingSymbol === item.symbol"
                        @click="addEtf(item)"
                    />
                </div>
            </div>

            <!-- 搜索无结果时，支持按代码直接添加（不依赖目录接口可用性） -->
            <div v-if="searchKeyword.trim() && !searching" class="pt-1 border-t mt-2">
                <Button
                    label="按代码直接添加"
                    severity="secondary"
                    size="small"
                    text
                    :loading="addingSymbol === searchKeyword.trim()"
                    @click="addBySymbol(searchKeyword.trim())"
                />
                <span class="text-xs text-gray-400 ml-2">未搜到？可直接用代码（如 159901）添加</span>
            </div>
        </div>
    </Dialog>

    <div class="card">
        <DataTable
            ref="dt1"
            :value="etfList"
            :paginator="true"
            :rows="25"
            dataKey="symbol"
            :rowHover="true"
            filterDisplay="menu"
            :loading="loading1"
            :filters="filters1"
            :globalFilterFields="['symbol', 'name']"
            :showGridlines="false"
            style="font-size: 11px"
            size="medium"
            sortField="fear_greed"
            sortOrder="-1"
        >
            <template #header>
                <div class="flex flex-col md:flex-row items-center justify-between gap-3 w-full">
                    <!-- 左侧：说明 -->
                    <div class="w-full md:w-auto text-gray-500 text-sm">
                        共 {{ etfList.length }} 只监控 ETF
                    </div>
                    <!-- 右侧：按钮 + 搜索框 -->
                    <div class="flex flex-wrap items-center gap-2 w-full md:w-auto justify-end md:justify-start">
                        <Button
                            type="button"
                            icon="pi pi-plus"
                            size="small"
                            label="添加ETF"
                            @click="openAddModal"
                            class="whitespace-nowrap"
                        />
                        <IconField>
                            <InputIcon>
                                <i class="pi pi-search"/>
                            </InputIcon>
                            <InputText
                                size="small"
                                v-model="filters1.global.value"
                                placeholder="Keyword Search"
                                class="w-full md:w-64"
                            />
                        </IconField>
                    </div>
                </div>
            </template>
            <template #empty> 暂无监控 ETF，点击右上角「添加ETF」搜索加入 </template>
            <template #loading> Loading ETF data. Please wait.</template>
            <Column field="name" filterField="name" header="名称">
                <template #body="{ data }">
                    <router-link class="text-blue-500"
                                 :to="{ name: 'etf-detail', params: { symbol: data.symbol } }">{{ data.symbol }}
                    </router-link>
                    <br/>{{ data.name }}
                </template>
            </Column>
            <Column field="close" filterField="close" header="最新净值" sortable>
                <template #body="{ data }">
                    <b :style="{ color: data.ohlc_last.chg_pct > 0 ? 'red' : 'green' }">
                        {{ data.ohlc_last.lastPrice != null ? data.ohlc_last.lastPrice.toFixed(3) : '--' }}
                    </b>
                </template>
            </Column>
            <Column field="chg_pct" filterField="chg_pct" header="涨跌幅" sortable>
                <template #body="{ data }">
                    <b :style="{ color: data.ohlc_last.chg_pct > 0 ? 'red' : 'green' }">
                        {{ data.ohlc_last.chg_pct != null ? data.ohlc_last.chg_pct.toFixed(2) + '%' : '--' }}
                    </b>
                </template>
            </Column>
            <Column field="amount" filterField="amount" header="成交">
                <template #body="{ data }">
                    {{ formatStockTradeAmount(data.ohlc_last.amount) }}
                </template>
            </Column>
            <Column header="52周价格范围">
                <template #body="{ data }">
                    <PriceRange52Week
                        :low52w="data['52week_low']"
                        :high52w="data['52week_high']"
                        :currentPrice="data.ohlc_last.lastPrice"
                        style="width: 100px;"
                    />
                </template>
            </Column>
            <Column header="操作" :style="{ width: '5rem' }">
                <template #body="{ data }">
                    <Button
                        icon="pi pi-trash"
                        severity="danger"
                        text
                        rounded
                        v-tooltip.top="'移除'"
                        @click="deleteEtf(data.symbol)"
                    />
                </template>
            </Column>
        </DataTable>
    </div>

</template>

<style scoped lang="scss">

:deep(.p-datatable-frozen-tbody) {
    font-weight: bold;
}

:deep(.p-datatable-scrollable .p-frozen-column) {
    font-weight: bold;
}

:deep(.fg-extreme-fear .p-progressbar-value) {
    background: #bebebe !important; /* 极度恐惧 - 柔和红 */
}

:deep(.fg-fear .p-progressbar-value) {
    background: #bebebe !important; /* 恐惧 - 深橙 */
}

:deep(.fg-neutral .p-progressbar-value) {
    background: #9ccc65 !important; /* 中性 - 金黄 */
}

:deep(.fg-greed .p-progressbar-value) {
    background: #ef5350 !important; /* 贪婪 - 浅绿 */
}

:deep(.fg-extreme-greed .p-progressbar-value) {
    background: #ef5350 !important; /* 极度贪婪 - 绿 */
}

:deep(.p-progressbar) {
    border-radius: 8px;
    overflow: hidden;
}

:deep(.p-progressbar-value) {
    border-radius: 8px;
}

.phase-tag {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: bold;
    color: white;
    text-align: center;
}

/* 不同阶段的颜色定义 */
.phase-tag--accumulate {
    background-color: #1890ff;
}

/* 蓝色 - 吸筹 */
.phase-tag--wash {
    background-color: #531dab;
}

/* 靛紫色 - 洗盘 */
.phase-tag--rise {
    background-color: #389e0d;
}

/* 绿色 - 拉升 */
.phase-tag--distribute {
    background-color: #d46b08;
}

/* 橙色 - 出货 */
.phase-tag--unknown {
    background-color: #bfbfbf;
}

/* 浅灰 - 未知 */

</style>
