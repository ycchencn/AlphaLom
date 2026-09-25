<script setup>
import { ref, onMounted } from 'vue';
import axios from 'axios';

const summary = ref(null);
const loadingSummary = ref(false);
const records = ref([]);
const loadingRecords = ref(false);
const totalRecords = ref(0);
const currentPage = ref(1);
const pageSize = ref(20);

const dateRange = ref(null);
const filterModel = ref(null);
const filterScene = ref(null);
const modelOptions = ref([]);
const sceneOptions = ref([]);

const expandedRows = ref({});

const fmt = (n) => (n == null ? 0 : n);

const fmtDate = (d) => {
    const dt = new Date(d);
    return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0');
};

const buildParams = () => {
    const p = {};
    if (filterModel.value) p.model = filterModel.value;
    if (filterScene.value) p.scene = filterScene.value;
    if (dateRange.value && dateRange.value[0]) p.start_date = fmtDate(dateRange.value[0]);
    if (dateRange.value && dateRange.value[1]) p.end_date = fmtDate(dateRange.value[1]);
    return p;
};

const loadSummary = async () => {
    loadingSummary.value = true;
    try {
        const r = await axios.get('/api/v1/token_usage/summary', { params: buildParams() });
        if (r.data.code === 200) {
            summary.value = r.data.data;
            modelOptions.value = (summary.value.by_model || []).map((m) => ({ label: m.model, value: m.model }));
            sceneOptions.value = (summary.value.by_scene || []).map((s) => ({ label: s.scene, value: s.scene }));
        }
    } catch (e) {
        console.error('加载统计失败', e);
    } finally {
        loadingSummary.value = false;
    }
};

const loadRecords = async () => {
    loadingRecords.value = true;
    try {
        const params = { page: currentPage.value, page_size: pageSize.value, ...buildParams() };
        const r = await axios.get('/api/v1/token_usage/records', { params });
        if (r.data.code === 200) {
            records.value = r.data.data.records;
            totalRecords.value = r.data.data.total;
        }
    } catch (e) {
        console.error('加载明细失败', e);
    } finally {
        loadingRecords.value = false;
    }
};

const onPage = (e) => {
    currentPage.value = e.page + 1;
    loadRecords();
};

const onFilter = () => {
    currentPage.value = 1;
    loadSummary();
    loadRecords();
};

const onReset = () => {
    filterModel.value = null;
    filterScene.value = null;
    dateRange.value = null;
    currentPage.value = 1;
    loadSummary();
    loadRecords();
};

onMounted(() => {
    loadSummary();
    loadRecords();
});
</script>

<template>
    <div class="card mt-5">
        <div class="font-semibold text-xl mb-4">Token 使用量统计</div>

        <!-- 汇总卡片 -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div class="p-3 border-round surface-card">
                <div class="text-color-secondary text-sm">总调用次数</div>
                <div class="text-2xl font-bold">{{ fmt(summary?.total_calls) }}</div>
            </div>
            <div class="p-3 border-round surface-card">
                <div class="text-color-secondary text-sm">总 Token</div>
                <div class="text-2xl font-bold">{{ fmt(summary?.total_tokens) }}</div>
            </div>
            <div class="p-3 border-round surface-card">
                <div class="text-color-secondary text-sm">输入 Token</div>
                <div class="text-2xl font-bold">{{ fmt(summary?.total_prompt_tokens) }}</div>
            </div>
            <div class="p-3 border-round surface-card">
                <div class="text-color-secondary text-sm">输出 Token</div>
                <div class="text-2xl font-bold">{{ fmt(summary?.total_completion_tokens) }}</div>
            </div>
        </div>

        <!-- 筛选 -->
        <div class="mb-4 flex flex-wrap gap-2 align-items-center">
            <Dropdown v-model="filterModel" :options="modelOptions" optionLabel="label" optionValue="value" placeholder="模型" showClear />
            <Dropdown v-model="filterScene" :options="sceneOptions" optionLabel="label" optionValue="value" placeholder="场景" showClear />
            <Calendar v-model="dateRange" selectionMode="range" :manualInput="false" dateFormat="yy-mm-dd" placeholder="时间范围" />
            <Button label="筛选" icon="pi pi-filter" @click="onFilter" size="small" />
            <Button label="重置" icon="pi pi-filter-slash" @click="onReset" outlined size="small" />
        </div>

        <!-- 按模型聚合 -->
        <div class="font-semibold mb-2">按模型</div>
        <DataTable :value="summary?.by_model || []" stripedRows showGridlines class="mb-4" style="font-size: 11px">
            <Column field="model" header="模型" />
            <Column field="calls" header="调用次数" />
            <Column field="prompt_tokens" header="输入 Token" />
            <Column field="completion_tokens" header="输出 Token" />
            <Column field="total_tokens" header="总计 Token" />
            <template #empty>暂无数据</template>
        </DataTable>

        <!-- 按场景聚合 -->
        <div class="font-semibold mb-2">按场景</div>
        <DataTable :value="summary?.by_scene || []" stripedRows showGridlines class="mb-4" style="font-size: 11px">
            <Column field="scene" header="场景" />
            <Column field="calls" header="调用次数" />
            <Column field="total_tokens" header="总计 Token" />
            <template #empty>暂无数据</template>
        </DataTable>

        <!-- 日期趋势 -->
        <div class="font-semibold mb-2">日期趋势</div>
        <DataTable :value="summary?.daily || []" stripedRows showGridlines class="mb-4" style="font-size: 11px">
            <Column field="date" header="日期" />
            <Column field="calls" header="调用次数" />
            <Column field="total_tokens" header="总计 Token" />
            <template #empty>暂无数据</template>
        </DataTable>

        <!-- 调用明细 -->
        <div class="font-semibold mb-2">调用明细</div>
        <DataTable
            :value="records" :loading="loadingRecords" lazy paginator :rows="pageSize"
            :totalRecords="totalRecords" @page="onPage"
            :rowsPerPageOptions="[20, 50, 100]" stripedRows showGridlines
            v-model:expandedRows="expandedRows" dataKey="id" style="font-size: 11px">
            <Column expander style="width: 2rem" />
            <Column field="created_at" header="时间" />
            <Column field="user_id" header="用户ID" />
            <Column field="scene" header="场景" />
            <Column field="platform" header="平台" />
            <Column field="model" header="模型" />
            <Column field="prompt_tokens" header="输入" />
            <Column field="completion_tokens" header="输出" />
            <Column field="total_tokens" header="总计" />
            <template #expansion="slotProps">
                <div class="p-3">
                    <div class="font-semibold mb-1">输入</div>
                    <pre class="whitespace-pre-wrap text-sm" style="max-height: 300px; overflow: auto">{{ slotProps.data.input_text }}</pre>
                    <div class="font-semibold mt-3 mb-1">输出</div>
                    <pre class="whitespace-pre-wrap text-sm" style="max-height: 300px; overflow: auto">{{ slotProps.data.output_text }}</pre>
                </div>
            </template>
            <template #empty>暂无数据</template>
        </DataTable>
    </div>
</template>

<style scoped>
:deep(.p-datatable .p-datatable-thead > tr > th) {
    background-color: var(--surface-50);
}
pre {
    white-space: pre-wrap;
    word-break: break-word;
}
</style>
