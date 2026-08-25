<script setup>

import { FilterMatchMode, FilterOperator } from '@primevue/core/api';
import { useNotification } from '@/composables/useNotification';
import { onBeforeMount, reactive, ref } from 'vue';
import { getMarketByCode, fearGreedToText } from '@/utils/function';
import Dialog from 'primevue/dialog';
import axios from 'axios';
import PriceRange52Week from '@/components/PriceRange52Week.vue';

const stock_list = ref([]);
const filters1 = ref(null);
const loading1 = ref(null);
const modal_visible = ref(false);
const modal_stock_code = ref(null);
const { showSuccess, showError } = useNotification();
const dt1 = ref(null);
const modal_analysis_interval = ref(1)
const filter_market = ref('cn')

function loadStockList(){
    // 获取个股数据
    axios.get(`/api/v1/stocks_monitored?page_size=300&page=1&market=${filter_market.value}&v=1.2`).then(response => {
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

// 在 <script setup> 内部添加：
function getFearGreedClass(greedValue) {
    if (greedValue >= 60) return 'fg-extreme-greed';
    if (greedValue >= 55) return 'fg-greed';
    if (greedValue >= 35) return 'fg-neutral';
    if (greedValue >= 20) return 'fg-fear';
    return 'fg-extreme-fear';
}

/**
 * 添加股票到监控列表
 * @param {string} stockCode - 股票代码（如 '600519', 'AAPL', '00700.HK' 等）
 */
async function addStockMonitor(stockCode) {
    // === 1. 前置校验：stockCode 合法性 ===
    if (!stockCode) {
        showError('请输入股票代码');
        return;
    }

    // 去除首尾空白
    const trimmedCode = stockCode.trim();
    if (trimmedCode.length === 0) {
        showError('股票代码不能为空');
        return;
    }

    // 可选：限制长度（例如最多20字符，覆盖 A股、港股、美股等）
    if (trimmedCode.length > 20) {
        showError('股票代码过长');
        return;
    }

    // 可选：基础格式校验（允许字母、数字、点号、连字符，常见于全球股票代码）
    const stockCodeRegex = /^[a-zA-Z0-9\.\-]+$/;
    if (!stockCodeRegex.test(trimmedCode)) {
        showError('股票代码包含非法字符');
        return;
    }

    // === 2. 发起请求 ===
    try {
        await axios.put(`/api/v1/stocks/${encodeURIComponent(trimmedCode)}`, {
            llm_analysis_interval: modal_analysis_interval.value,
            monitoring: 1,
            monitor_by: 'guest'
        });
        showSuccess('个股添加成功，数据已提交后台任务，请稍后查看');
        modal_stock_code.value = ""
    } catch (error) {
        let message = '操作失败，请重试';
        if (axios.isAxiosError(error)) {
            if (error.response) {
                const { status, data } = error.response;
                message = data.message;
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
    <Dialog v-model:visible="modal_visible" modal header="添加个股监控" :style="{ width: '25rem' }">
      <div class="flex flex-col gap-4">
        <!-- 股票代码 -->
        <div>
          <label for="stock_code" class="font-semibold block mb-1">股票代码</label>
          <InputText
            id="stock_code"
            v-model="modal_stock_code"
            autocomplete="off"
            placeholder="填写股票代码"
            @keyup.enter="modal_visible=false; addStockMonitor(modal_stock_code);"
            class="w-full mt-3"
          />
        </div>

        <!-- 分析周期 -->
        <div>
          <div class="flex justify-between items-center mb-1">
            <label for="analysis_interval" class="font-semibold">分析周期（天）</label>
          </div>
            <Dropdown
              v-model="modal_analysis_interval"
              :options="stockIntervalOptions"
              optionLabel="label"
              optionValue="value"
              placeholder="选择分析周期"
              class="w-full mt-3"
              @change="() => {}"
            />
        </div>
      </div>

      <!-- 操作按钮 -->
      <template #footer>
        <div class="flex justify-end gap-2">
          <Button
            type="button"
            label="取消"
            severity="secondary"
            @click="modal_visible = false"
          />
          <Button
            type="button"
            label="确认"
            @click="modal_visible=false; addStockMonitor(modal_stock_code);"
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
                            @click="modal_visible = true"
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
                    <router-link class="text-blue-500"
                                 target="_blank"
                                 :to="{ name: 'stock-detail', params: { symbol: data.symbol } }">查看
                    </router-link>
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
