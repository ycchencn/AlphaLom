<script setup>

import {FilterMatchMode} from '@primevue/core/api';
import {useNotification} from '@/composables/useNotification';
import {computed, onBeforeMount, ref} from 'vue';
import axios from 'axios';
import PriceRange52Week from '@/components/PriceRange52Week.vue';
import EtfSearchDialog from '@/components/EtfSearchDialog.vue';
import EtfRotation from '@/views/etf/EtfRotation.vue';
import {
    formatStockTradeAmount,
} from '@/utils/function.js';

const etfList = ref([]);
const filters1 = ref(null);
const loading1 = ref(false);
const {showSuccess, showError} = useNotification();

// 页签：监控列表 / 轮动分析。
// ⚠️ 轮动分析用 v-if 懒挂载，不用 v-show：它一挂载就会请求轮动接口（池内每只都要拉
// 3 年日线，是重活），v-show 会让用户只是打开「ETF 洞察」就白跑一次分析。
const activeTab = ref('list');

// 添加 ETF 弹窗状态（弹窗本体是共用组件 EtfSearchDialog，这里只管提交与刷新列表）
const modalVisible = ref(false);
const addingSymbol = ref('');   // 正在添加的 symbol，用于禁用对应按钮
const searchDialog = ref(null);

// 已在监控列表中的代码列表，用于在搜索结果里标记「已添加」
const watchedSymbols = computed(() => etfList.value.map(e => String(e.symbol)));

function loadETFList() {
    loading1.value = true;
    return axios.get(`/api/v1/etfs`).then(response => {
        etfList.value = response.data;
    }).catch(() => {
        etfList.value = [];
    }).finally(() => {
        loading1.value = false;
    });
}

function openAddModal() {
    modalVisible.value = true;
    searchDialog.value?.reset();
}

// ⚠️ 搜索联想（300ms 防抖 + 请求序号丢弃过期响应 + 按代码直接添加的兜底）已下沉到
// 共用组件 EtfSearchDialog —— 轮动池需要完全一样的行为，两处各写一份必然漂移。

// 提交来自 EtfSearchDialog 的添加请求：{symbol, name, byCode}
async function addEtf({symbol, name}) {
    addingSymbol.value = symbol;
    try {
        await axios.post('/api/v1/etf', {symbol, name: name || null});
        showSuccess(`已添加 ${name || symbol}`);
        // 刷新监控列表，该条目会自动变成「已添加」状态
        await loadETFList();
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
    <!-- 添加 ETF 弹窗：共用组件（监控列表与轮动池用同一套搜索联想） -->
    <EtfSearchDialog
        ref="searchDialog"
        v-model:visible="modalVisible"
        title="添加 ETF"
        :watched="watchedSymbols"
        :adding="addingSymbol"
        @submit="addEtf"
    />

    <div class="card">
        <!-- 页签：监控列表 / 轮动分析 -->
        <div class="etf-tabs">
            <button
                type="button"
                class="etf-tab"
                :class="{ 'etf-tab--active': activeTab === 'list' }"
                @click="activeTab = 'list'"
            >
                <i class="pi pi-list"/>监控列表
                <span class="etf-tab-count">{{ etfList.length }}</span>
            </button>
            <button
                type="button"
                class="etf-tab"
                :class="{ 'etf-tab--active': activeTab === 'rotation' }"
                @click="activeTab = 'rotation'"
            >
                <i class="pi pi-chart-line"/>轮动分析
            </button>
        </div>

        <DataTable
            v-show="activeTab === 'list'"
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

    <!-- 轮动分析页签：v-if 懒挂载（接口要拉全池日线，用 v-show 会让打开页面就白跑一次分析） -->
    <EtfRotation v-if="activeTab === 'rotation'"/>

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

/* 页签：文字 + 下划线。刻意不用 PrimeVue 的 Tabs 组件 —— 本页只需要两个静态页签，
   引一个组件进来反而要多一层样式覆盖。 */
.etf-tabs {
    display: flex;
    gap: 24px;
    border-bottom: 1px solid #eef1f6;
    margin-bottom: 16px;
}

.etf-tab {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 2px 10px;
    border: none;
    border-bottom: 2px solid transparent;
    background: transparent;
    color: #64748b;
    font-size: 13px;
    cursor: pointer;
    margin-bottom: -1px;

    &:hover {
        color: #1f2937;
    }

    &.etf-tab--active {
        color: #1f2937;
        font-weight: 500;
        border-bottom-color: #1f2937;
    }
}

.etf-tab-count {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    border-radius: 9px;
    background: #f1f5f9;
    color: #64748b;
    font-size: 11px;
}

</style>
