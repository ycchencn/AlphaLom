<script setup>
import { ref, onMounted, computed } from 'vue';
import axios from 'axios';

const logs = ref([]);
const loading = ref(false);
const totalRecords = ref(0);
const currentPage = ref(1);
const pageSize = ref(50);

// 筛选条件
const filters = ref({
    level: null,
    module: null,
    keyword: '',
    start_time: null,
    end_time: null
});

// 可选项
const levelOptions = ref([]);
const moduleOptions = ref([]);

// 日期范围
const dateRange = ref(null);

// 加载日志数据
const loadLogs = async () => {
    loading.value = true;
    try {
        const params = {
            page: currentPage.value,
            page_size: pageSize.value
        };
        
        if (filters.value.level) {
            params.level = filters.value.level;
        }
        if (filters.value.module) {
            params.module = filters.value.module;
        }
        if (filters.value.keyword) {
            params.keyword = filters.value.keyword;
        }
        if (dateRange.value && dateRange.value[0]) {
            params.start_time = dateRange.value[0].toISOString().split('T')[0] + ' 00:00:00';
        }
        if (dateRange.value && dateRange.value[1]) {
            params.end_time = dateRange.value[1].toISOString().split('T')[0] + ' 23:59:59';
        }
        
        const response = await axios.get('/api/v1/app_logs', { params });
        if (response.data.code === 200) {
            logs.value = response.data.data.logs;
            totalRecords.value = response.data.data.total;
        }
    } catch (error) {
        console.error('加载日志失败:', error);
    } finally {
        loading.value = false;
    }
};

// 加载筛选选项
const loadFilterOptions = async () => {
    try {
        const [levelsRes, modulesRes] = await Promise.all([
            axios.get('/api/v1/app_logs/levels'),
            axios.get('/api/v1/app_logs/modules')
        ]);
        
        if (levelsRes.data.code === 200) {
            levelOptions.value = levelsRes.data.data.map(level => ({
                label: level,
                value: level
            }));
        }
        if (modulesRes.data.code === 200) {
            moduleOptions.value = modulesRes.data.data.map(module => ({
                label: module,
                value: module
            }));
        }
    } catch (error) {
        console.error('加载筛选选项失败:', error);
    }
};

// 分页变化
const onPage = (event) => {
    currentPage.value = event.page + 1;
    loadLogs();
};

// 筛选
const onFilter = () => {
    currentPage.value = 1;
    loadLogs();
};

// 重置筛选
const resetFilters = () => {
    filters.value = {
        level: null,
        module: null,
        keyword: '',
        start_time: null,
        end_time: null
    };
    dateRange.value = null;
    currentPage.value = 1;
    loadLogs();
};

// 获取日志级别颜色
const getLevelSeverity = (level) => {
    const severityMap = {
        'DEBUG': 'info',
        'INFO': 'success',
        'WARNING': 'warn',
        'WARN': 'warn',
        'ERROR': 'danger',
        'CRITICAL': 'danger'
    };
    return severityMap[level] || 'info';
};

// 格式化消息（截断过长内容）
const formatMessage = (message) => {
    if (!message) return '';
    return message.length > 100 ? message.substring(0, 100) + '...' : message;
};

onMounted(() => {
    loadLogs();
    loadFilterOptions();
});
</script>

<template>
    <div class="card mt-5">
        <div class="font-semibold text-xl mb-4">系统日志</div>
        
        <!-- 筛选区域 -->
        <div class="mb-4 flex flex-wrap gap-2 align-items-center">
            <Dropdown 
                v-model="filters.level" 
                :options="levelOptions" 
                optionLabel="label"
                optionValue="value"
                placeholder="日志级别"
                showClear
            />
            <Dropdown 
                v-model="filters.module" 
                :options="moduleOptions" 
                optionLabel="label"
                optionValue="value"
                placeholder="模块"
                showClear
            />
            <Calendar 
                v-model="dateRange" 
                selectionMode="range" 
                :manualInput="false"
                dateFormat="yy-mm-dd"
                placeholder="时间范围"
            />
            <IconField>
                <InputIcon>
                    <i class="pi pi-search" />
                </InputIcon>
                <InputText 
                    v-model="filters.keyword" 
                    placeholder="搜索日志内容"
                />
            </IconField>
            <Button label="筛选" icon="pi pi-filter" @click="onFilter" size="small" />
            <Button label="重置" icon="pi pi-filter-slash" @click="resetFilters" outlined size="small" />
        </div>
        
        <!-- 数据表格 -->
        <DataTable 
            :value="logs" 
            :loading="loading"
            :paginator="true"
            :rows="pageSize"
            :totalRecords="totalRecords"
            :lazy="true"
            @page="onPage"
            :rowsPerPageOptions="[20, 50, 100]"
            stripedRows
            showGridlines
            tableStyle="font-size: 13px"
        >
            <Column field="timestamp" header="时间" style="min-width: 180px">
                <template #body="{ data }">
                    <span class="text-color-secondary">{{ data.timestamp }}</span>
                </template>
            </Column>
            <Column field="level" header="级别" style="min-width: 100px">
                <template #body="{ data }">
                    <Tag :value="data.level" :severity="getLevelSeverity(data.level)" />
                </template>
            </Column>
            <Column field="module" header="模块" style="min-width: 150px">
                <template #body="{ data }">
                    <span class="font-medium">{{ data.module || '-' }}</span>
                </template>
            </Column>
            <Column field="func" header="函数" style="min-width: 120px">
                <template #body="{ data }">
                    <span class="text-color-secondary">{{ data.func || '-' }}</span>
                </template>
            </Column>
            <Column field="line" header="行号" style="min-width: 80px">
                <template #body="{ data }">
                    <span class="text-color-secondary">{{ data.line || '-' }}</span>
                </template>
            </Column>
            <Column field="message" header="消息" style="min-width: 400px">
                <template #body="{ data }">
                    <span :title="data.message">{{ formatMessage(data.message) }}</span>
                </template>
            </Column>
            <template #empty>
                <div class="text-center p-5">暂无日志数据</div>
            </template>
        </DataTable>
    </div>
</template>

<style scoped>
:deep(.p-datatable .p-datatable-thead > tr > th) {
    background-color: var(--surface-50);
}
</style>
