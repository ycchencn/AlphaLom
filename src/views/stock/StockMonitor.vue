<script setup>

import { FilterMatchMode } from '@primevue/core/api';
import { useNotification } from '@/composables/useNotification';
import { computed, onBeforeMount, ref } from 'vue';
import { getMarketByCode, fearGreedToText } from '@/utils/function';
import Dialog from 'primevue/dialog';
import axios from 'axios';
import PriceRange52Week from '@/components/PriceRange52Week.vue';

const stock_list = ref([]);
const filters1 = ref(null);
const loading1 = ref(null);
const modal_visible = ref(false);
const { showSuccess, showError } = useNotification();
const modal_analysis_interval = ref(1)
const filter_market = ref('cn')

// 添加个股弹窗：搜索状态
const searchKeyword = ref('');
const searchResults = ref([]);
const searching = ref(false);
const addingSymbol = ref('');   // 正在添加的 symbol，用于禁用对应按钮
let searchSeq = 0;              // 搜索请求序号，用于丢弃过期响应

// 已在股票池中的代码集合，用于在搜索结果里标记「已添加」
const watchedSymbols = computed(() => new Set(stock_list.value.map(s => String(s.symbol))));

function isWatched(symbol) {
    return watchedSymbols.value.has(String(symbol));
}

function loadStockList(){
    // 获取个股数据
    loading1.value = true;
    return axios.get(`/api/v1/stocks_monitored?page_size=300&page=1&market=${filter_market.value}&v=1.2`).then(response => {
        stock_list.value = response.data.map(item => {
            const ohlc = item.ohlc_last; // 可能为 null 或 undefined
            return {
                ...item,
                fear_greed: item.greed_data?.fear_greed ?? null,
                fear_greed_text: fearGreedToText(item.greed_data?.fear_greed ?? null),
                chg_pct: ohlc?.chg_pct ?? null,
                close: ohlc?.close ?? null,
                open: ohlc?.open ?? null,
                high: ohlc?.high ?? null,
                low: ohlc?.low ?? null,
                market: getMarketByCode(item.symbol) ?? null
            };
        });
        loading1.value = false;
    }).catch(error => {
        console.error('加载股票列表失败:', error);
        loading1.value = false;
        // 可选：显示错误提示
    });
}

onBeforeMount(() => {
    // 获取个股数据
    loadStockList()
    initFilters1();
});

function openAddModal() {
    modal_visible.value = true;
    searchKeyword.value = '';
    searchResults.value = [];
    searchSeq++;   // 丢弃上一次打开时可能仍在途的搜索结果
}

// 输入防抖后调用搜索接口（服务端按关键字过滤，见 StockService.search_stock_catalog）
let searchTimer = null;
function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    const kw = searchKeyword.value.trim();
    if (!kw) {
        searchResults.value = [];
        searching.value = false;
        searchSeq++;   // 让在途请求的结果失效
        return;
    }
    searchTimer = setTimeout(() => doSearch(kw), 300);
}

async function doSearch(kw) {
    const seq = ++searchSeq;
    searching.value = true;
    try {
        const r = await axios.get('/api/v1/stock_search', {params: {keyword: kw, limit: 50}});
        if (seq !== searchSeq) return;   // 已有更新的搜索，丢弃本次结果，避免乱序覆盖
        searchResults.value = Array.isArray(r.data) ? r.data : [];
    } catch (e) {
        if (seq === searchSeq) searchResults.value = [];
    } finally {
        if (seq === searchSeq) searching.value = false;
    }
}

// 在 <script setup> 内部添加：
function getFearGreedClass(greedValue) {
    if (greedValue >= 60) return 'fg-extreme-greed';
    if (greedValue >= 55) return 'fg-greed';
    if (greedValue >= 35) return 'fg-neutral';
    if (greedValue >= 20) return 'fg-fear';
    return 'fg-extreme-fear';
}

/**
 * 把股票加入股票池（PUT /stocks/{symbol}，记录不存在时后端会自动拉取名称并入库）
 * @param {string} symbol - 股票代码（如 '600519'）
 * @returns {Promise<boolean>} 是否添加成功
 */
async function putStockMonitoring(symbol) {
    try {
        const res = await axios.put(`/api/v1/stocks/${encodeURIComponent(symbol)}`, {
            monitoring: 1,
            monitor_by: 'guest',
            securities_type: 'stock'
        });
        // 后端对「刚入池」的票会顺带投递一次个股分析（恐惧贪婪 / 因子 / DCF / 报价）。
        // 任务队列串行消费，跑完需要一段时间，所以提示里要说清「稍后刷新」——
        // 刚加完就来查列表只会看到名称和代码，其余列是空的。
        if (res.data && res.data.analysis_triggered) {
            showSuccess(`已添加监控：${symbol}，正在后台分析数据，稍后点「刷新」查看`);
        } else {
            showSuccess(`已添加监控：${symbol}`);
        }
        await loadStockList();
        return true;
    } catch (error) {
        let message = '操作失败，请重试';
        if (axios.isAxiosError(error)) {
            if (error.response) {
                const { data } = error.response;
                message = (data && (data.message || data.detail)) || message;
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
        return false;
    }
}

/**
 * 从搜索结果添加（保持弹窗打开，该条结果会自动变为「已添加」状态）
 */
async function addFromSearch(row) {
    const symbol = row.symbol;
    addingSymbol.value = symbol;
    try {
        await putStockMonitoring(symbol);
    } finally {
        addingSymbol.value = '';
    }
}

/**
 * 按代码直接添加（搜索无结果时的兜底，不依赖目录接口可用性）
 */
async function addByCode(stockCode) {
    const trimmedCode = (stockCode || '').trim();
    if (!trimmedCode) {
        showError('请输入股票代码');
        return;
    }
    if (trimmedCode.length > 20) {
        showError('股票代码过长');
        return;
    }
    // 允许字母、数字、点号、连字符（覆盖 A股 / 港股 / 美股等代码格式）
    if (!/^[a-zA-Z0-9.\-]+$/.test(trimmedCode)) {
        showError('股票代码包含非法字符');
        return;
    }
    addingSymbol.value = trimmedCode;
    try {
        const ok = await putStockMonitoring(trimmedCode);
        if (ok) {
            searchKeyword.value = '';
            searchResults.value = [];
        }
    } finally {
        addingSymbol.value = '';
    }
}

// 1. 阶段映射配置 (保持不变)
const PHASE_CONFIG = {
    0: { label: '未知阶段', type: 'unknown', severity: 'secondary' },
    1: { label: '吸筹阶段', type: 'accumulate', severity: 'info' },
    2: { label: '洗盘阶段', type: 'wash', severity: 'help' },
    3: { label: '拉升阶段', type: 'rise', severity: 'success' },
    5: { label: '出货阶段', type: 'distribute', severity: 'warn' },
    6: { label: '出货阶段', type: 'distribute', severity: 'danger' }
};

// 将对象转换为 [{ label: '吸筹阶段', value: '1' }, ...] 格式
const phaseFilterOptions = Object.entries(PHASE_CONFIG)
    .filter(([key, config]) => key !== '0') // 过滤掉 key 为 '0' 的项
    .map(([key, config]) => ({
    label: config.label,
    value: key // 使用字符串作为 value，兼容性更好
}));

const stockIntervalOptions = [
    { label: '每天', value: 1 },
    { label: '每3天', value: 3 },
];

const marketFilterOptions = [
    { label: 'A股', value: 'cn' },
    { label: '美股', value: 'us' },
    { label: '港股', value: 'hk' },
];

// 2. 修改 initFilters1 函数，添加 main_force_behavior_phase 的配置
function initFilters1() {
    filters1.value = {
        global: { value: null, matchMode: FilterMatchMode.CONTAINS },
        // 添加这一行配置
        main_force_behavior_phase: {
            value: null,
            matchMode: FilterMatchMode.CONTAINS
        },
        // 新增：市场筛选配置
        market: {
            value: null,
            matchMode: FilterMatchMode.EQUALS
        }
    };
}

// 格式化数字为文本
const formatPhase = (phaseInt) => {
    const num = Number(phaseInt);
    return PHASE_CONFIG[num]?.label || PHASE_CONFIG[0].label;
};

// 获取 Severity (PrimeVue 的预设颜色等级)
const getPhaseSeverity = (phaseInt) => {
    const num = Number(phaseInt);
    return PHASE_CONFIG[num]?.severity || PHASE_CONFIG[0].severity;
};

</script>

<template>
    <Toast />
    <!-- 添加个股弹窗：支持按代码/名称搜索 databull 全市场股票目录 -->
    <Dialog v-model:visible="modal_visible" modal header="添加个股监控" :style="{ width: '30rem' }">
      <div class="flex flex-col gap-3">
        <IconField>
          <InputIcon>
            <i class="pi pi-search" />
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
          <i class="pi pi-spin pi-spinner" />
        </div>
        <div v-else-if="!searchKeyword.trim()" class="text-center text-gray-400 py-4 text-sm">
          输入股票代码或名称，从全市场股票目录中搜索
        </div>
        <div v-else-if="searchResults.length === 0" class="text-center text-gray-400 py-4 text-sm">
          未找到匹配的股票
        </div>
        <div v-else class="flex flex-col gap-2">
          <div class="text-xs text-gray-400">共 {{ searchResults.length }} 条匹配</div>
          <div class="flex flex-col gap-2 max-h-80 overflow-auto">
            <div v-for="item in searchResults" :key="item.symbol"
                 class="flex items-center justify-between gap-2 border rounded p-2">
              <div class="min-w-0">
                <div class="font-semibold truncate">{{ item.symbol }}</div>
                <div class="text-xs text-gray-500 truncate">{{ item.name }}</div>
              </div>
              <Tag v-if="isWatched(item.symbol)" value="已添加" severity="secondary" class="shrink-0" />
              <Button
                v-else
                icon="pi pi-plus"
                label="添加"
                size="small"
                class="shrink-0"
                :loading="addingSymbol === item.symbol"
                @click="addFromSearch(item)"
              />
            </div>
          </div>
        </div>

        <!-- 搜索无结果时，支持按代码直接添加（不依赖目录接口可用性） -->
        <div v-if="searchKeyword.trim() && !searching && searchResults.length === 0" class="pt-1 border-t mt-2">
          <Button
            label="按代码直接添加"
            severity="secondary"
            size="small"
            text
            :loading="addingSymbol === searchKeyword.trim()"
            @click="addByCode(searchKeyword.trim())"
          />
          <span class="text-xs text-gray-400 ml-2">未搜到？可直接用代码（如 600519）添加</span>
        </div>

        <!-- 分析周期 -->
        <div class="pt-2 border-t">
          <label for="analysis_interval" class="font-semibold block mb-1">分析周期（天）</label>
          <Dropdown
            v-model="modal_analysis_interval"
            :options="stockIntervalOptions"
            optionLabel="label"
            optionValue="value"
            placeholder="选择分析周期"
            class="w-full"
            @change="() => {}"
          />
        </div>
      </div>

      <!-- 操作按钮 -->
      <template #footer>
        <div class="flex justify-end gap-2">
          <Button
            type="button"
            label="关闭"
            severity="secondary"
            @click="modal_visible = false"
          />
        </div>
      </template>
    </Dialog>
    <div class="card">
        <DataTable
            ref="dt1"
            :value="stock_list"
            :paginator="true"
            :rows="25"
            dataKey="symbol"
            :rowHover="true"
            filterDisplay="menu"
            :loading="loading1"
            :filters="filters1"
            :globalFilterFields="['symbol', 'name', 'concepts']"
            :showGridlines="false"
            size="medium"
            style="font-size: 11px"
            sortField="fear_greed"
            sortOrder="-1"
        >
            <template #header>
                <div class="flex flex-col md:flex-row items-center justify-between gap-3 w-full">
                  <!-- 左侧：下拉框 -->
                  <div class="w-full md:w-auto">
                    <Dropdown
                      v-model="filters1.main_force_behavior_phase.value"
                      :options="phaseFilterOptions"
                      optionLabel="label"
                      optionValue="value"
                      placeholder="筛选阶段"
                      size="small"
                      class="mr-3"
                      :showClear="true"
                      @change="() => {}"
                    />
                    <Dropdown
                      v-model="filter_market"
                      :options="marketFilterOptions"
                      optionLabel="label"
                      optionValue="value"
                      placeholder="筛选市场"
                      size="small"
                      :showClear="true"
                      @change="loadStockList"
                    />
                  </div>
                    <!-- 右侧：按钮 + 搜索框 -->
                    <div class="flex flex-wrap items-center gap-2 w-full md:w-auto justify-end md:justify-start">
                        <Button
                            type="button"
                            icon="pi pi-plus"
                            size="small"
                            label="添加个股"
                            @click="openAddModal"
                            class="whitespace-nowrap"
                        />
                        <Button
                            type="button"
                            icon="pi pi-refresh"
                            size="small"
                            label="刷新"
                            severity="secondary"
                            :loading="loading1"
                            @click="loadStockList"
                            class="whitespace-nowrap"
                        />
                        <IconField>
                            <InputIcon>
                                <i class="pi pi-search" />
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
            <template #empty> No data found.</template>
            <template #loading> Loading customers data. Please wait.</template>
            <Column field="name" filterField="name" header="名称">
                <template #body="{ data }">
                    <router-link class="text-blue-500"
                                 :to="{ name: 'stock-detail', params: { symbol: data.symbol } }">{{ data.symbol }}
                    </router-link><br/>{{ data.name }}
                </template>
            </Column>
            <Column field="close" filterField="close" header="最新" sortable>
                <template #body="{ data }">
                    <span :style="{ color: data.chg_pct > 0 ? 'red' : 'green' }">
                        {{ data.close != null ? data.close.toFixed(2) : '--' }}
                    </span>
                </template>
            </Column>
            <Column field="chg_pct" filterField="chg_pct" header="涨跌幅" sortable>
                <template #body="{ data }">
                    <span :style="{ color: data.chg_pct > 0 ? 'red' : 'green' }">
                        {{ data.chg_pct != null ? data.chg_pct.toFixed(2) + '%' : '--' }}
                    </span>
                </template>
            </Column>
            <Column field="main_force_behavior_phase" filterField="main_force_behavior_phase" header="主力行为">
                <template #body="{ data }">
                    <Tag
                      :value="formatPhase(parseInt(data.main_force_behavior_phase))"
                      :severity="getPhaseSeverity(parseInt(data.main_force_behavior_phase))"
                    />
                </template>
            </Column>
            <Column field="concepts" filterField="concepts" header="概念题材" style="max-width: 300px">
                <template #body="{ data }">
                    <span class="block whitespace-nowrap overflow-hidden text-ellipsis w-full">{{ data.concepts }}</span>
                </template>
            </Column>
            <Column header="52周价格范围">
                <template #body="{ data }">
                    <PriceRange52Week
                      :low52w="data['52week_low']"
                      :high52w="data['52week_high']"
                      :currentPrice="data.close"
                      style="width: 100px;"
                    />
                </template>
            </Column>
            <Column field="fear_greed" filterField="fear_greed" header="贪婪&恐惧指标" sortable>
                <template #body="{ data }">
                    <ProgressBar
                        :mode="indeterminate"
                        :class="getFearGreedClass(data.greed_data?.fear_greed)"
                        :value="data.greed_data?.fear_greed"
                        :showValue="false"
                        style="height: 8px; width: 100px"
                    />
                </template>
            </Column>
            <Column field="verified" header="操作" dataType="boolean" bodyClass="text-center">
                <template #body="{ data }">
                    <router-link class="text-blue-500" :to="{ name: 'stock-detail', params: { symbol: data.symbol } }">查看</router-link>
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
  font-weight: bold;
  color: white;
  text-align: center;
}

/* 不同阶段的颜色定义 */
.phase-tag--accumulate { background-color: #1890ff; } /* 蓝色 - 吸筹 */
.phase-tag--wash { background-color: #531dab; }       /* 靛紫色 - 洗盘 */
.phase-tag--rise { background-color: #389e0d; }       /* 绿色 - 拉升 */
.phase-tag--distribute { background-color: #d46b08; } /* 橙色 - 出货 */
.phase-tag--unknown { background-color: #bfbfbf; }    /* 浅灰 - 未知 */

</style>
