<script setup>

import {FilterMatchMode} from '@primevue/core/api';
import {useNotification} from '@/composables/useNotification';
import {computed, onBeforeMount, ref} from 'vue';
import axios from 'axios';
import PriceRange52Week from '@/components/PriceRange52Week.vue';
import EtfTrendSparkline from '@/components/EtfTrendSparkline.vue';
import EtfSearchDialog from '@/components/EtfSearchDialog.vue';
import EtfRotation from '@/views/etf/EtfRotation.vue';
import {
    formatStockTradeAmount,
    fearGreedLevel,
} from '@/utils/function.js';

// 组件名与 AppLayout <KeepAlive :include> 名单一致（列表页缓存，返回不重建）
defineOptions({name: 'EtfInsight'});

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

// 贪婪恐惧进度条的着色 class（与股票列表 StockMonitor 一致，全站唯一分档入口 fearGreedLevel）
const FG_LEVEL_CLASS = {
    '极度恐惧': 'fg-extreme-fear',
    '恐惧': 'fg-fear',
    '中性': 'fg-neutral',
    '贪婪': 'fg-greed',
    '极度贪婪': 'fg-extreme-greed',
};

function getFearGreedClass(value) {
    return FG_LEVEL_CLASS[fearGreedLevel(value).text] || 'fg-neutral';
}

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

    <div class="card" style="padding-top: 2rem">
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
            sortField="ohlc_last.chg_pct"
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
            <Column header="近60日走势" :style="{ width: '15rem' }">
                <template #body="{ data }">
                    <EtfTrendSparkline :symbol="data.symbol" :days="60"/>
                </template>
            </Column>
            <Column field="ohlc_last.chg_pct" filterField="ohlc_last.chg_pct" header="涨跌幅" sortable dataType="numeric">
                <template #body="{ data }">
                    <b :style="{ color: data.ohlc_last.chg_pct > 0 ? 'red' : 'green' }">
                        {{ data.ohlc_last.chg_pct != null ? data.ohlc_last.chg_pct.toFixed(2) + '%' : '--' }}
                    </b>
                </template>
            </Column>
            <Column field="ohlc_last.lastPrice" filterField="ohlc_last.lastPrice" header="最新净值" sortable dataType="numeric">
                <template #body="{ data }">
                    <b :style="{ color: data.ohlc_last.chg_pct > 0 ? 'red' : 'green' }">
                        {{ data.ohlc_last.lastPrice != null ? data.ohlc_last.lastPrice.toFixed(3) : '--' }}
                    </b>
                </template>
            </Column>
            <Column field="ohlc_last.amount" filterField="ohlc_last.amount" header="成交" dataType="numeric">
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
            <Column field="fear_greed" filterField="fear_greed" header="贪婪&恐惧指标" sortable>
                <template #body="{ data }">
                    <ProgressBar
                        v-if="data.fear_greed != null"
                        :class="getFearGreedClass(data.fear_greed)"
                        :value="data.fear_greed"
                        :showValue="false"
                        style="height: 8px; width: 100px"
                    />
                    <span v-else class="etf-fg-empty">—</span>
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

/* 恐惧贪婪进度条配色（与股票列表 StockMonitor 一致，对应 utils/function.js 的
   FEAR_GREED_LEVELS，A 股口径：恐惧绿、贪婪红）。改这里务必同步那个常量。 */
:deep(.fg-extreme-fear .p-progressbar-value) {
    background: var(--app-down) !important; /* 极度恐惧 - 深绿 */
}

:deep(.fg-fear .p-progressbar-value) {
    background: var(--app-down-soft) !important; /* 恐惧 - 浅绿 */
}

:deep(.fg-neutral .p-progressbar-value) {
    background: var(--app-flat) !important; /* 中性 - 灰 */
}

:deep(.fg-greed .p-progressbar-value) {
    background: var(--app-up-soft) !important; /* 贪婪 - 浅红 */
}

:deep(.fg-extreme-greed .p-progressbar-value) {
    background: var(--app-up) !important; /* 极度贪婪 - 红 */
}

.etf-fg-empty {
    font-size: 11px;
    color: var(--app-text-muted);
}

:deep(.p-progressbar) {
    border-radius: 8px;
    overflow: hidden;
}

:deep(.p-progressbar-value) {
    border-radius: 8px;
}

/* 以下 .phase-tag 整块在本页**没有引用点**（模板/脚本都搜不到 phase-tag）——
   「主力行为阶段」是个股因子，ETF 的因子表里没有这一项，这里是从个股页拷来的死代码
   （`views/quant/DCFInsight.vue` 有另一份同样的拷贝，同样是死的）。
   故保持原样不迁移：等哪天在本页真的用起来，改用 `COLORS.phase1/2/3/5/6/Unknown`
   （FactorPanel 用的就是那套，两套色板不能各写一份）。
   顺带记一笔：这里的注释已经和类名错位了 —— 「蓝色 - 吸筹」写在 --accumulate
   之后，读起来像在描述 --wash。 */
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
    background-color: var(--app-down);
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
    border-bottom: 1px solid var(--app-border-base);
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
    /* ⚠️ 这里原先写死 #64748b（未选中）/ #1f2937（hover + 选中 + 下划线）。
       #1f2937 是近黑的 slate-800 —— 暗色下就是「黑字压在深底上」，正是页签看不清的原因。 */
    color: var(--app-text-secondary);
    font-size: 13px;
    cursor: pointer;
    margin-bottom: -1px;

    &:hover {
        color: var(--app-text-primary);
    }

    &.etf-tab--active {
        color: var(--app-text-primary);
        font-weight: 500;
        border-bottom-color: var(--app-text-primary);
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
    background: var(--app-bg-active);
    color: var(--app-text-secondary);
    font-size: 11px;
}

</style>
