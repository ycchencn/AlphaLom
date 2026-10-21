<script setup>

import { FilterMatchMode, FilterOperator } from '@primevue/core/api';
import { onBeforeMount, reactive, ref } from 'vue';
import axios from 'axios';
import { toneClass } from '@/utils/function';

const customers1 = ref(null);
const filters1 = ref(null);
const loading1 = ref(null);

onBeforeMount(() => {
    axios.get('/api/v1/stocks').then(response => {
        customers1.value = response.data;
        loading1.value = false;
    });
    initFilters1();
});

function initFilters1() {
    filters1.value = {
        global: { value: null, matchMode: FilterMatchMode.CONTAINS },
        stock_code: {
            operator: FilterOperator.AND,
            constraints: [{ value: null, matchMode: FilterMatchMode.STARTS_WITH }]
        }
    };
}

</script>

<template>
    <div class="card">
        <div class="font-semibold text-xl mb-4">股票池（指数成分）</div>
        <DataTable
            tableStyle="font-size:12px"
            :value="customers1"
            :paginator="true"
            :rows="25"
            dataKey="id"
            :rowHover="true"
            filterDisplay="menu"
            :loading="loading1"
            :globalFilterFields="['name']"
            :showGridlines="false"
        >
            <template #header>
                <div class="flex justify-between">
                    <Button type="button" icon="pi pi-filter-slash" label="Clear" outlined @click="clearFilter()" />
                    <IconField>
                        <InputIcon>
                            <i class="pi pi-search" />
                        </InputIcon>
                        <InputText v-model="filters1['global'].value" placeholder="Keyword Search" />
                    </IconField>
                </div>
            </template>
            <template #empty> No data found.</template>
            <template #loading> Loading customers data. Please wait.</template>
            <Column field="stock_code" filterField="stock_code" header="代码">
                <template #body="{ data }">
                    <a :href="'https://data.eastmoney.com/stockdata/' + data.stock_code + '.html'" target="_blank">
                        {{ data.stock_code }}
                    </a>
                </template>
            </Column>
            <Column field="stock_name" filterField="stock_name" header="名称">
                <template #body="{ data }">
                    <a :href="'https://data.eastmoney.com/stockdata/' + data.stock_code + '.html'" target="_blank">
                        {{ data.stock_name }}
                    </a>
                </template>
            </Column>
            <Column field="stock_code" filterField="stock_code" header="最新">
                <template #body="{ data }">
                    <b :class="toneClass(data.daily_data.chg_pct)">
                      {{ data.daily_data.close.toFixed(2) }}
                    </b>
                </template>
            </Column>
            <Column field="stock_code" filterField="stock_code" header="涨跌幅">
                <template #body="{ data }">
                    <b :class="toneClass(data.daily_data.chg_pct)">
                      {{ data.daily_data.chg_pct.toFixed(2) }}%
                    </b>
                </template>
            </Column>
            <Column field="stock_code" filterField="stock_code" header="换手率">
                <template #body="{ data }">
                    <b :class="toneClass(data.daily_data.turnover_rate)">
                      {{ data.daily_data.turnover_rate.toFixed(2) }}%
                    </b>
                </template>
            </Column>
            <Column field="stock_code" filterField="stock_code" header="最新数据日期">
                <template #body="{ data }">
                    {{ data.daily_data.date }}
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
</style>
