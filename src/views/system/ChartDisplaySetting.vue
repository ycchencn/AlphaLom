<script setup>

import {onBeforeMount, ref} from 'vue';
import axios from 'axios';
import ToggleSwitch from 'primevue/toggleswitch';
import {useNotification} from '@/composables/useNotification';
import {invalidateChartDisplay} from '@/composables/useChartDisplay.js';

/**
 * 系统设置 · 图表显示
 *
 * 控制详情页（个股 / ETF）各图表区块的显隐。配置存在后端 system_setting 表
 * （分组 chart_display），**保存后立即生效、无需重启服务**；
 * 点「恢复默认」= 删掉表里那一行，回落到代码里的默认值。
 *
 * ⚠️ 页面全部按后端返回的 items 动态渲染，加新开关只需改后端 _CHART_DISPLAY_SPEC，
 * 前端不用动 —— 避免「后端加了配置、前端忘了加控件」这类漂移。
 */
const {showSuccess, showError} = useNotification();

const loading = ref(false);
const saving = ref('');
const items = ref([]);

function loadSettings() {
    loading.value = true;
    return axios.get('/api/v1/settings/chart_display')
        .then((response) => {
            items.value = response.data?.items || [];
        })
        .catch(() => {
            items.value = [];
            showError('加载图表显示配置失败');
        })
        .finally(() => {
            loading.value = false;
        });
}

/**
 * 保存单项。value 由控件直接给出布尔。
 * @param {{name:string, label:string}} item
 * @param {boolean} value
 */
function saveItem(item, value) {
    saving.value = item.name;
    axios.put(`/api/v1/settings/chart_display/${encodeURIComponent(item.name)}`, {value})
        .then((response) => {
            items.value = response.data?.data?.items || items.value;
            // 失效 composable 缓存 → 详情页下次进入就能拿到新值
            invalidateChartDisplay();
            showSuccess(`「${item.label}」已${value ? '开启' : '关闭'}`);
        })
        .catch((e) => {
            showError(e?.response?.data?.detail || '保存失败');
            // 保存失败 → 重新拉取，让控件回到与后端一致的状态（避免界面骗人）
            loadSettings();
        })
        .finally(() => {
            saving.value = '';
        });
}

/** 恢复默认 = 删配置行，回落到代码默认值 */
function resetItem(item) {
    saving.value = item.name;
    axios.delete(`/api/v1/settings/chart_display/${encodeURIComponent(item.name)}`)
        .then((response) => {
            items.value = response.data?.data?.items || items.value;
            invalidateChartDisplay();
            showSuccess(`「${item.label}」已恢复默认值`);
        })
        .catch((e) => {
            showError(e?.response?.data?.detail || '恢复默认失败');
            loadSettings();
        })
        .finally(() => {
            saving.value = '';
        });
}

onBeforeMount(loadSettings);

</script>

<template>

    <Toast/>

    <div class="card">
        <div class="flex flex-col gap-2 w-full mb-4">
            <div class="flex flex-col md:flex-row items-center justify-between gap-3 w-full">
                <div class="text-gray-500 text-sm">
                    图表显示配置 · 共 {{ items.length }} 项
                </div>
                <Button
                    icon="pi pi-refresh"
                    label="刷新"
                    size="small"
                    severity="secondary"
                    outlined
                    :loading="loading"
                    @click="loadSettings"
                />
            </div>
            <div class="text-xs text-gray-500">
                开关存放在数据库里，<b>保存后立即生效、无需重启服务</b>。
                「恢复默认」= 删除库里的配置行，回到代码中的默认值。
            </div>
        </div>

        <div v-if="loading && !items.length" class="text-gray-400 text-sm py-6 text-center">
            <i class="pi pi-spin pi-spinner"></i> 加载中...
        </div>

        <div v-else-if="!items.length" class="text-gray-400 text-sm py-6 text-center">
            暂无可配置项
        </div>

        <div v-else class="chart-setting-list">
            <div class="chart-setting-row" v-for="item in items" :key="item.name">
                <div class="chart-setting-main">
                    <div class="chart-setting-label">
                        {{ item.label }}
                        <Tag v-if="item.customized" value="已自定义" severity="warn" class="ml-2"/>
                    </div>
                    <div class="chart-setting-desc">{{ item.description }}</div>
                    <div class="chart-setting-meta">
                        生效值：<b>{{ item.value ? '开启' : '关闭' }}</b>
                        · 代码默认：{{ item.default ? '开启' : '关闭' }}
                        · 键名：<code>{{ item.name }}</code>
                    </div>
                </div>

                <div class="chart-setting-action">
                    <ToggleSwitch
                        :modelValue="item.value"
                        @update:modelValue="(val) => saveItem(item, val)"
                        :disabled="saving === item.name"
                    />
                    <Button
                        label="恢复默认"
                        size="small"
                        severity="secondary"
                        text
                        :disabled="!item.customized || saving === item.name"
                        @click="resetItem(item)"
                    />
                </div>
            </div>
        </div>
    </div>

</template>

<style scoped lang="scss">
.chart-setting-list {
    display: flex;
    flex-direction: column;
}

.chart-setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    padding: 1rem 0.25rem;
    border-bottom: 1px solid #f1f5f9;

    &:last-child {
        border-bottom: none;
    }
}

.chart-setting-main {
    min-width: 0;

    .chart-setting-label {
        font-size: 0.95rem;
        font-weight: 600;
        color: #1e293b;
        display: flex;
        align-items: center;
    }

    .chart-setting-desc {
        font-size: 0.8rem;
        color: #64748b;
        margin-top: 0.2rem;
    }

    .chart-setting-meta {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-top: 0.3rem;

        code {
            background: #f1f5f9;
            border-radius: 3px;
            padding: 0 4px;
        }
    }
}

.chart-setting-action {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-shrink: 0;
}

@media (max-width: 768px) {
    .chart-setting-row {
        flex-direction: column;
        align-items: flex-start;
        gap: 0.75rem;
    }
}
</style>
