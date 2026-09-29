<script setup>

import {computed, onBeforeMount, reactive, ref} from 'vue';
import axios from 'axios';
import ToggleSwitch from 'primevue/toggleswitch';
import Dialog from 'primevue/dialog';
import {useNotification} from '@/composables/useNotification';

/**
 * 系统设置 · 大模型配置
 *
 * 两个区块：
 *   1. 平台管理 —— 每个平台的「启用 / 关闭」+ API Key + Base URL。
 *      API Key **加密存在库里**（主密钥在 .env: ALPHALOM_SECRET_KEY），页面只回显掩码；
 *      留空 = 不改动现有 key，「恢复默认」= 删掉表里那一行，完全回落到 .env 的配置。
 *   2. 业务场景 —— 每个场景选一个「平台 + 模型」。
 *
 * 两处配置都**保存后立即生效、无需重启服务**（服务每次调用都实时读表）。
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

// ==================== 平台管理 ====================

const platformRows = ref([]);          // 后端返回的平台列表（含掩码）
const secretKeyConfigured = ref(true); // 加密主密钥是否已配置（未配置则不能保存 key）
const platformForms = reactive({});    // { 平台: {enabled, api_key, base_url} }
const savingPlatform = ref('');
const resettingPlatform = ref('');
const testingPlatform = ref('');

// ⚠️ 读平台列表失败时**不能只把列表清空** —— 那样页面显示「共 0 个平台」，
// 看起来像「平台被删光了」，实际是请求 403/网络失败。这里单独记错误文案，
// 由模板显式渲染出来（含 403 的「需要管理员权限」）。
const platformError = ref('');

// 正在编辑 key 的平台（弹窗）；选弹窗而不是行内输入框，避免掩码与输入互相干扰
const keyDialogVisible = ref(false);
const keyDialogPlatform = ref('');
const keyDialogValue = ref('');
const keyDialogSaving = ref(false);

const platformOptions = computed(() => platforms.value);

function syncPlatformForms() {
    platformRows.value.forEach((row) => {
        platformForms[row.platform] = {
            enabled: !!row.enabled,
            api_key: '',                       // 永远留空，只在用户主动输入时才回传
            base_url: row.base_url || '',
            customized: !!row.customized,
        };
    });
}

function loadPlatforms() {
    return axios.get('/api/v1/settings/llm_platforms')
        .then((response) => {
            const data = response.data?.data || {};
            platformRows.value = data.platforms || [];
            secretKeyConfigured.value = data.secret_key_configured !== false;
            platformError.value = '';
            syncPlatformForms();
        })
        .catch((e) => {
            platformRows.value = [];
            const status = e.response?.status;
            if (e.isSpaFallback) {
                // 后端没有 /settings/llm_platforms 这个接口（服务端版本落后于前端）：
                // 静态兜底返回了 index.html，见 main.js 的响应拦截器。
                platformError.value = '后端服务缺少「大模型平台配置」接口 —— 服务端还没部署本次更新。'
                    + '请重新部署/重启后端服务后再刷新本页。';
            } else if (status === 403) {
                platformError.value = '当前账号不是管理员，无权查看平台配置。请用管理员账号登录后重试。';
            } else if (status === 401) {
                platformError.value = '登录已失效，请重新登录后重试。';
            } else {
                platformError.value = e.response?.data?.detail
                    || e.message
                    || `读取平台配置失败${status ? `（HTTP ${status}）` : ''}，请点「刷新」重试。`;
            }
            showError(platformError.value);
        });
}

function keySourceLabel(row) {
    if (row.key_source === 'database') return '后台配置';
    if (row.key_source === 'env') return '.env';
    return '未配置';
}

// 保存一行的「开关 + base_url」（不含 key —— key 走弹窗单独保存）
function savePlatform(row) {
    const form = platformForms[row.platform];
    savingPlatform.value = row.platform;
    axios.put(`/api/v1/settings/llm_platforms/${encodeURIComponent(row.platform)}`, {
        enabled: form.enabled,
        base_url: form.base_url || '',
    })
        .then((response) => {
            applyPlatformResponse(response);
            showSuccess(`已保存 ${row.label}`);
        })
        .catch((e) => {
            showError(e.response?.data?.detail || '保存失败，请重试');
        })
        .finally(() => {
            savingPlatform.value = '';
        });
}

// 删除该平台的全部后台配置 = 完全回到 .env / 代码默认值（key、base_url、开关一起回退）
function resetPlatform(row) {
    resettingPlatform.value = row.platform;
    axios.delete(`/api/v1/settings/llm_platforms/${encodeURIComponent(row.platform)}`)
        .then((response) => {
            applyPlatformResponse(response);
            showSuccess(response.data?.deleted
                ? `已恢复默认 ${row.label}（改为使用 .env 中的配置）`
                : `${row.label} 本来就是默认配置`);
        })
        .catch((e) => {
            showError(e.response?.data?.detail || '恢复默认失败，请重试');
        })
        .finally(() => {
            resettingPlatform.value = '';
        });
}

function applyPlatformResponse(response) {
    const data = response.data?.data || {};
    platformRows.value = data.platforms || [];
    secretKeyConfigured.value = data.secret_key_configured !== false;
    syncPlatformForms();
}

function openKeyDialog(row) {
    keyDialogPlatform.value = row.platform;
    keyDialogValue.value = '';
    keyDialogVisible.value = true;
}

function savePlatformKey() {
    const plain = String(keyDialogValue.value || '').trim();
    if (!plain) {
        showError('请输入 API Key');
        return;
    }
    keyDialogSaving.value = true;
    axios.put(`/api/v1/settings/llm_platforms/${encodeURIComponent(keyDialogPlatform.value)}`, {
        api_key: plain,
    })
        .then((response) => {
            applyPlatformResponse(response);
            keyDialogVisible.value = false;
            keyDialogValue.value = '';
            showSuccess('API Key 已加密保存');
        })
        .catch((e) => {
            showError(e.response?.data?.detail || '保存失败，请重试');
        })
        .finally(() => {
            keyDialogSaving.value = false;
        });
}

// 连通性自测：用当前生效配置调一次上游 /models
function testPlatform(row) {
    testingPlatform.value = row.platform;
    axios.post(`/api/v1/settings/llm_platforms/${encodeURIComponent(row.platform)}/test`)
        .then((response) => {
            const data = response.data || {};
            if (data.ok) showSuccess(`${row.label}：${data.message}`);
            else showError(`${row.label}：${data.message}`);
        })
        .catch((e) => {
            showError(e.response?.data?.detail || '测试失败，请重试');
        })
        .finally(() => {
            testingPlatform.value = '';
        });
}

// ==================== 业务场景 ====================

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

function refreshAll() {
    loading.value = true;
    Promise.all([loadPlatforms(), loadSettings()]).finally(() => {
        loading.value = false;
    });
}

onBeforeMount(() => {
    refreshAll();
});

</script>

<template>
    <Toast/>
    <div class="llm-setting-page flex flex-col gap-4">
        <!-- ==================== 平台管理 ==================== -->
        <div class="card">
            <DataTable
                :value="platformRows"
                dataKey="platform"
                :rowHover="true"
                :showGridlines="false"
                size="medium"
            >
                <template #header>
                    <div class="flex flex-col gap-2 w-full">
                        <div class="flex flex-col md:flex-row items-center justify-between gap-3 w-full">
                            <div class="text-gray-500 text-sm">
                                平台管理 · 共 {{ platformRows.length }} 个大模型平台
                            </div>
                            <Button
                                icon="pi pi-refresh"
                                label="刷新"
                                size="small"
                                severity="secondary"
                                outlined
                                :loading="loading"
                                @click="refreshAll"
                            />
                        </div>
                        <div class="text-xs text-gray-500">
                            这里配置各平台的<b>启用开关、API Key、Base URL</b>，
                            API Key <b>加密存库</b>、页面只显示掩码，<b>保存后立即生效、无需重启</b>。
                            留空表示沿用 .env 中的配置；「恢复默认」= 删除库里的配置行，完全回到 .env。
                        </div>
                        <div class="text-xs text-gray-400">
                            平台清单来自代码里已注册的平台实现（<code>llms/PLATFORM_META</code>），
                            这里只能<b>启用/配置</b>它们，<b>不能新增或删除平台</b>
                            —— 接入新平台需要在 <code>llms/</code> 下实现一个 LLMBase 子类并注册。
                        </div>
                        <div v-if="platformError" class="text-xs text-red-500 flex items-center gap-1">
                            <i class="pi pi-exclamation-triangle"></i>
                            <span>{{ platformError }}</span>
                            <Button
                                label="重试"
                                size="small"
                                severity="danger"
                                text
                                class="ml-1"
                                @click="loadPlatforms"
                            />
                        </div>
                        <div v-if="!secretKeyConfigured" class="text-xs text-red-500">
                            未配置加解密主密钥 <code>ALPHALOM_SECRET_KEY</code>，无法在后台保存 API Key。
                            请在 .env 中设置一段随机口令并重启服务。
                        </div>
                    </div>
                </template>

                <template #empty>
                    <!-- 平台清单是代码注册的，正常永远有 5 个；走到这里说明请求没成功 -->
                    <div class="flex flex-col items-center gap-1 py-4">
                        <i class="pi pi-exclamation-circle text-2xl text-gray-400"></i>
                        <div class="text-sm text-gray-500">没有读到平台列表</div>
                        <div class="text-xs text-gray-400">
                            {{ platformError || '平台清单由后端代码注册，正常应显示 5 个。请点「刷新」重试。' }}
                        </div>
                    </div>
                </template>

                <Column header="平台" :style="{ minWidth: '12rem' }">
                    <template #body="{ data }">
                        <div class="font-semibold">{{ data.label }}</div>
                        <div class="text-xs text-gray-500">{{ data.platform }}</div>
                    </template>
                </Column>

                <Column header="启用" :style="{ width: '7rem' }">
                    <template #body="{ data }">
                        <div class="flex flex-col items-start gap-1">
                            <ToggleSwitch v-model="platformForms[data.platform].enabled" size="small"/>
                            <Tag v-if="data.customized" value="已自定义" severity="success"/>
                            <Tag v-else value="使用默认" severity="secondary"/>
                        </div>
                    </template>
                </Column>

                <Column header="API Key" :style="{ minWidth: '16rem' }">
                    <template #body="{ data }">
                        <div class="flex items-center gap-2 flex-nowrap">
                            <span class="text-xs font-mono break-all">
                                {{ data.api_key_masked || '未配置' }}
                            </span>
                            <Tag
                                :value="keySourceLabel(data)"
                                :severity="data.key_source === 'database' ? 'success' : (data.key_source === 'env' ? 'info' : 'danger')"
                            />
                        </div>
                        <div class="text-xs text-gray-400 mt-1">
                            .env 变量：<code>{{ data.env_key_name }}</code>
                        </div>
                    </template>
                </Column>

                <Column header="Base URL" :style="{ minWidth: '20rem' }">
                    <template #body="{ data }">
                        <InputText
                            v-model="platformForms[data.platform].base_url"
                            :placeholder="data.default_base_url"
                            class="w-full"
                        />
                        <div class="text-xs text-gray-400 mt-1 break-all">
                            默认：{{ data.default_base_url }}
                        </div>
                    </template>
                </Column>

                <Column header="操作" :style="{ minWidth: '20rem' }">
                    <template #body="{ data }">
                        <!-- 必须 nowrap：这些按钮在 flex 容器里会被压缩，标签会折成竖排的「保/存」 -->
                        <div class="flex gap-1 items-center whitespace-nowrap">
                            <Button
                                icon="pi pi-key"
                                label="设置 Key"
                                size="small"
                                severity="secondary"
                                outlined
                                class="whitespace-nowrap"
                                @click="openKeyDialog(data)"
                            />
                            <Button
                                icon="pi pi-check"
                                label="保存"
                                size="small"
                                class="whitespace-nowrap"
                                :loading="savingPlatform === data.platform"
                                @click="savePlatform(data)"
                            />
                            <Button
                                icon="pi pi-bolt"
                                size="small"
                                severity="info"
                                text
                                rounded
                                v-tooltip.top="'连通性测试'"
                                :loading="testingPlatform === data.platform"
                                @click="testPlatform(data)"
                            />
                            <Button
                                icon="pi pi-undo"
                                size="small"
                                severity="secondary"
                                text
                                rounded
                                v-tooltip.top="'恢复默认（回到 .env 配置）'"
                                :disabled="!data.customized"
                                :loading="resettingPlatform === data.platform"
                                @click="resetPlatform(data)"
                            />
                        </div>
                    </template>
                </Column>
            </DataTable>
        </div>

        <!-- ==================== 业务场景 ==================== -->
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
                        <div class="text-gray-500 text-sm">
                            业务场景模型路由 · 共 {{ scenes.length }} 个业务场景
                        </div>
                        <div class="text-xs text-gray-500">
                            每个业务场景在这里选一个「平台 + 模型」。配置同样存在数据库里，
                            <b>保存后立即生效、无需重启服务</b>。
                            「恢复默认」= 删除库里的配置行，回到代码中的默认值。
                            <span v-if="platformOptions.length" class="text-gray-400">
                                可选平台：{{ platformOptions.map(p => p.label).join(' / ') }}。
                            </span>
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

        <!-- ==================== 设置 API Key 弹窗 ==================== -->
        <Dialog
            v-model:visible="keyDialogVisible"
            modal
            header="设置 API Key"
            :style="{ width: '34rem', maxWidth: '92vw' }"
            :draggable="false"
        >
            <div class="flex flex-col gap-3">
                <div class="text-sm text-gray-600">
                    为平台设置新的 API Key。保存后<b>加密存储</b>，不会以明文出现在页面上。
                </div>
                <div class="flex flex-col gap-1">
                    <label class="text-xs text-gray-500">API Key</label>
                    <InputText
                        v-model="keyDialogValue"
                        type="password"
                        class="w-full"
                        autocomplete="new-password"
                        placeholder="粘贴新的 API Key"
                        @keyup.enter="savePlatformKey"
                    />
                </div>
                <div class="text-xs text-gray-400">
                    留空并保存不会改动现有 key。「恢复默认」可让该平台回到 .env 中的配置。
                </div>
                <div v-if="!secretKeyConfigured" class="text-xs text-red-500">
                    未配置 <code>ALPHALOM_SECRET_KEY</code>，无法保存。
                </div>
            </div>
            <template #footer>
                <div class="flex justify-end gap-2">
                    <Button label="取消" size="small" severity="secondary" text @click="keyDialogVisible = false"/>
                    <Button
                        label="保存"
                        size="small"
                        icon="pi pi-check"
                        :loading="keyDialogSaving"
                        :disabled="!secretKeyConfigured"
                        @click="savePlatformKey"
                    />
                </div>
            </template>
        </Dialog>
    </div>
</template>

<style scoped lang="scss">
:deep(.p-datatable) {
    font-size: 12px;
}
</style>
