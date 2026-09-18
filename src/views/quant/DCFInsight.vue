<script setup>

import {FilterMatchMode, FilterOperator} from '@primevue/core/api';
import {onBeforeMount, ref} from 'vue';
import {formatPercentage} from '@/utils/function';
import axios from 'axios';

const stock_list = ref([]);
const filters1 = ref(null);
const loading1 = ref(null);
const dt1 = ref(null);

function loadStockList() {
    // 获取个股数据
    axios.get(`/api/v1/quant/stock/get_dcf_report_snap?v=1.2`).then(response => {
        stock_list.value = response.data.map(item => {
            return {
                ...item
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

// 2. 修改 initFilters1 函数，添加 main_force_behavior_phase 的配置
function initFilters1() {
    filters1.value = {
        global: {value: null, matchMode: FilterMatchMode.CONTAINS},
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

</script>

<template>
    <Toast/>
    <div class="card">
        <DataTable
            ref="dt1"
            :value="stock_list"
            :paginator="true"
            :rows="50"
            dataKey="symbol"
            :rowHover="true"
            filterDisplay="menu"
            :loading="loading1"
            :filters="filters1"
            :globalFilterFields="['symbol', 'name', 'concepts']"
            :showGridlines="false"
            size="medium"
            style="font-size: 11px"
            sortField="opt_space"
            sortOrder="-1"
        >
            <template #header>
                <div class="flex flex-col md:flex-row items-center justify-between gap-3 w-full">
                    <!-- 左侧：下拉框 -->
                    <div class="w-full md:w-auto">
                        <span class="font-semibold">DCF估值信息汇总 - 每周更新</span>
                    </div>
                    <!-- 右侧：按钮 + 搜索框 -->
                    <div class="flex flex-wrap items-center gap-2 w-full md:w-auto justify-end md:justify-start">
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
            <template #empty> No data found.</template>
            <template #loading> Loading customers data. Please wait.</template>
            <Column field="symbol" filterField="symbol" header="代码">
                <template #body="{ data }">
                    <router-link class="text-blue-500"
                                 :to="{ name: 'stock-detail', params: { symbol: data.symbol } }">{{data.symbol}}
                    </router-link>
                </template>
            </Column>
            <Column field="name" filterField="name" header="名称">
                <template #body="{ data }">
                    {{ data.name }}
                </template>
            </Column>
            <Column field="current_price" filterField="current_price" header="最新" sortable>
                <template #body="{ data }">
                    {{ data.current_price != null ? data.current_price.toFixed(2) : '--' }}
                </template>
            </Column>
            <Column field="opt_valuation" filterField="opt_valuation" header="乐观估值" sortable>
                <template #body="{ data }">
                    {{ data.opt_valuation != null ? data.opt_valuation.toFixed(2) : '--' }}
                </template>
            </Column>
            <Column field="opt_space" filterField="opt_space" header="乐观空间" sortable>
                <template #body="{ data }">
                    <span :style="{ color: data.opt_space > 0 ? 'red' : 'green' }">
                        {{ data.opt_space != null ? (data.opt_space * 100).toFixed(2) : '--' }}%
                    </span>
                </template>
            </Column>
            <Column field="mid_valuation" filterField="mid_valuation" header="中性估值" sortable>
                <template #body="{ data }">
                    {{ data.mid_valuation != null ? data.mid_valuation.toFixed(2) : '--' }}
                </template>
            </Column>
            <Column field="mid_space" filterField="mid_space" header="中性空间" sortable>
                <template #body="{ data }">
                    <span :style="{ color: data.mid_space > 0 ? 'red' : 'green' }">
                        {{ data.mid_space != null ? (data.mid_space * 100).toFixed(2) + '%' : '--' }}
                    </span>
                </template>
            </Column>
            <Column field="cons_valuation" filterField="cons_valuation" header="保守估值" sortable>
                <template #body="{ data }">
                    {{ data.cons_valuation != null ? data.cons_valuation.toFixed(2) : '--' }}
                </template>
            </Column>
            <Column field="cons_space" filterField="cons_space" header="保守空间" sortable>
                <template #body="{ data }">
                    <span :style="{ color: data.cons_space > 0 ? 'red' : 'green' }">
                        {{ data.cons_space != null ? (data.cons_space * 100).toFixed(2) + '%' : '--' }}
                    </span>
                </template>
            </Column>
            <Column field="update_time" filterField="update_time" header="更新时间">
                <template #body="{ data }">
                    {{ data.update_time }}
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
