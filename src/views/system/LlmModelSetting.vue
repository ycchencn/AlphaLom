<script setup>

import {useNotification} from '@/composables/useNotification';
import {onBeforeMount, reactive, ref} from 'vue';
import axios from 'axios';

/**
 * 系统设置 · 大模型配置
 *
 * 每个业务场景（深度研报 / 技术分析 / 新闻分析 …）在这里选一个「平台 + 模型」。
 * 配置存在后端 system_setting 表里，保存后**立即生效、无需重启**（服务每次调用都实时读表）；
 * 点「恢复默认」= 删掉表里那一行，回落到 config.py 的默认值。
 */
const {showSuccess, showError} = useNotification();

const loading = ref(false);
const scenes = ref([]);
const platforms = ref([]);

// 每个场景一份可编辑表单：{ 场景名: {platform, model} }
const forms = reactive({});
const savingScene = ref('');
const resettingScene = ref('');

// 平台 → 模型列表（后端实时调各平台 /models 接口，改变低频，进程内缓存一份）
const modelOptionsByPlatform = ref({});
const modelsLoading = reactive({});

function normalizeModel(model) {
    // 后端的 model 允许字符串（单选）或列表（多候选，config 里 news_analysis 的默认值就是列表）。
    // 设置页按单选处理，列表只取第一个作为初始值。
    if (Array.isArray(model)) return model[0] || '';
    return model || '';
}

const modelOptions = (platform) => modelOptionsByPlatform.value[platform] || [];

function loadLlmModels(platform) {
    if (!platform || modelOptionsByPlatform.value[platform]) return Promise.resolve();
    modelsLoading[platform] = true;
    return axios.get('/api/v1/llm/models', {params: {platform}})
        .then((response) => {
            const info = (response.data || {})[platform];
            modelOptionsByPlatform.value[platform] = info?.models || [];
            if (info?.error) {
                showError(`获取 ${platform} 模型列表失败：${info.error}`);
            }
        })
        .catch(() => {
            modelOptionsByPlatform.value[platform] = [];
            showError(`获取 ${platform} 模型列表失败，可手动输入模型名称`);
        })
        .finally(() => {
            modelsLoading[platform] = false;
        });
}

function syncForms() {
    scenes.value.forEach((scene) => {
        forms[scene.name] = {
            platform: scene.platform || '',
            model: normalizeModel(scene.model),
        };
        if (scene.platform) loadLlmModels(scene.platform);
    });
}

function loadSettings() {
    loading.value = true;
    return axios.get('/api/v1/settings/llm_models')
        .then((response) => {
            const data = response.data || {};
            scenes.value = data.scenes || [];
            platforms.value = data.platforms || [];
            syncForms();
        })
        .catch(() => {
            scenes.value = [];
            showError('读取大模型配置失败');
        })
        .finally(() => {
            loading.value = false;
        });
}

// 切换平台：拉该平台的模型列表，并清掉在新平台上不存在的旧模型，避免存下一个无效组合
function onPlatformChange(scene) {
    const form = forms[scene.name];
    loadLlmModels(form.platform);
    const options = modelOptions(form.platform);
    if (form.model && options.length && !options.includes(form.model)) {
        form.model = options[0];
    }
}

function saveScene(scene) {
    const form = forms[scene.name];
    if (!form.platform) {
        showError('请先选择平台');
        return;
    }
    if (!String(form.model || '').trim()) {
        showError('请选择或输入模型名称');
        return;
    }
    savingScene.value = scene.name;
    axios.put(`/api/v1/settings/llm_models/${encodeURIComponent(scene.name)}`, {
        platform: form.platform,
        model: String(form.model).trim(),
    })
        .then((response) => {
            const updated = response.data?.data;
            // 用后端回传的生效值刷新该行（含 customized 状态与默认值）
            if (updated) Object.assign(scene, updated);
            showSuccess(`已保存 ${scene.label}`);
        })
        .catch((e) => {
            showError(e.response?.data?.detail || '保存失败，请重试');
        })
        .finally(() => {
            savingScene.value = '';
        });
}

function resetScene(scene) {
    resettingScene.value = scene.name;
    axios.delete(`/api/v1/settings/llm_models/${encodeURIComponent(scene.name)}`)
        .then((response) => {
            const updated = response.data?.data;
            if (updated) Object.assign(scene, updated);
            forms[scene.name] = {
                platform: scene.platform || '',
                model: normalizeModel(scene.model),
            };
            if (scene.platform) loadLlmModels(scene.platform);
            showSuccess(response.data?.deleted ? `已恢复默认 ${scene.label}` : `${scene.label} 本来就是默认值`);
        })
        .catch((e) => {
            showError(e.response?.data?.detail || '恢复默认失败，请重试');
        })
        .finally(() => {
            resettingScene.value = '';
        });
}

function formatModel(model) {
    if (Array.isArray(model)) return model.join(' / ');
    return model || '--';
}

onBeforeMount(() => {
    loadSettings();
});

</script>

<template>
    <Toast/>
    <div class="card">
        <DataTable
            :value="scenes"
            dataKey="name"
            :loading="loading"
            :rowHover="true"
            :showGridlines="false"
            size="medium"
        >
            <template #header>
                <div class="flex flex-col gap-2 w-full">
                    <div class="flex flex-col md:flex-row items-center justify-between gap-3 w-full">
                        <div class="text-gray-500 text-sm">
                            大模型配置 · 共 {{ scenes.length }} 个业务场景
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
                        配置保存在数据库里，<b>保存后立即生效、无需重启服务</b>。
                        「恢复默认」= 删除库里的配置行，回到代码中的默认值。
                    </div>
                </div>
            </template>

            <template #empty> 暂无可用场景 </template>
            <template #loading> 正在读取配置… </template>

            <Column header="业务场景" :style="{ minWidth: '18rem' }">
                <template #body="{ data }">
                    <div class="font-semibold">{{ data.label }}</div>
                    <div class="text-xs text-gray-500">{{ data.name }}</div>
                    <div class="text-xs text-gray-400 mt-1">{{ data.description }}</div>
                </template>
            </Column>

            <Column header="状态" :style="{ width: '9rem' }">
                <template #body="{ data }">
                    <div class="flex flex-col gap-1 items-start">
                        <Tag v-if="data.customized" value="已自定义" severity="success"/>
                        <Tag v-else value="使用默认" severity="secondary"/>
                        <Tag v-if="data.in_use === false" value="暂未接入" severity="warn"/>
                    </div>
                </template>
            </Column>

            <Column header="平台" :style="{ width: '12rem' }">
                <template #body="{ data }">
                    <Dropdown
                        v-model="forms[data.name].platform"
                        :options="platforms"
                        optionLabel="label"
                        optionValue="value"
                        placeholder="选择平台"
                        class="w-full"
                        @change="onPlatformChange(data)"
                    />
                </template>
            </Column>

            <Column header="模型" :style="{ minWidth: '16rem' }">
                <template #body="{ data }">
                    <Dropdown
                        v-model="forms[data.name].model"
                        :options="modelOptions(forms[data.name].platform)"
                        :loading="modelsLoading[forms[data.name].platform]"
                        editable
                        filter
                        placeholder="选择模型，也可手动输入"
                        :empty-message="modelsLoading[forms[data.name].platform] ? '正在获取模型列表…' : '该平台暂无可用模型，可手动输入'"
                        class="w-full"
                    />
                </template>
            </Column>

            <Column header="代码默认值" :style="{ minWidth: '14rem' }">
                <template #body="{ data }">
                    <div class="text-xs text-gray-600">
                        <div>{{ data.default_platform || '--' }}</div>
                        <div class="text-gray-400 break-all">{{ formatModel(data.default_model) }}</div>
                    </div>
                </template>
            </Column>

            <Column header="操作" :style="{ width: '12rem' }">
                <template #body="{ data }">
                    <!-- 必须 nowrap：这两个按钮在 flex 容器里会被压缩，标签会折成竖排的「保/存」 -->
                    <div class="flex gap-1 items-center whitespace-nowrap">
                        <Button
                            icon="pi pi-check"
                            label="保存"
                            size="small"
                            class="whitespace-nowrap"
                            :loading="savingScene === data.name"
                            @click="saveScene(data)"
                        />
                        <Button
                            icon="pi pi-undo"
                            size="small"
                            severity="secondary"
                            text
                            rounded
                            v-tooltip.top="'恢复默认'"
                            :disabled="!data.customized"
                            :loading="resettingScene === data.name"
                            @click="resetScene(data)"
                        />
                    </div>
                </template>
            </Column>
        </DataTable>
    </div>
</template>

<style scoped lang="scss">
:deep(.p-datatable) {
    font-size: 12px;
}
</style>
