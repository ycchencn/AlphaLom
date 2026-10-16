<script setup>

import {computed, onBeforeMount, ref} from 'vue';
import axios from 'axios';
import {useNotification} from '@/composables/useNotification';

/**
 * 系统设置 · 网站统计代码
 *
 * 站长粘贴的第三方统计代码（百度统计 / CNZZ / Google Analytics / umami 等），
 * 整段原文存后端 system_setting 表（分组 general_setting，键 analytics_code），
 * 由后端在渲染 index.html（SPA 兜底）时注入 </body> 之前，对所有访客（含未登录）生效。
 *
 * ⚠️ 「保存」≠ 立即注入：统计代码由后端在**每次页面加载**时从配置读取并写进 HTML，
 *    所以保存 / 清除后要**刷新页面**才看得到效果 —— 这也是统计平台的通用行为
 *    （重复注入同一段代码会导致数据重复计数，后端注入保证了每个页面只注入一次）。
 * ⚠️ 注入是**全站**的：对所有访客生效，不是只对管理员。
 */
const {showSuccess, showError} = useNotification();

const loading = ref(false);
const saving = ref(false);
const code = ref('');
const customized = ref(false);
const errorText = ref('');

/** 字符数提示：主流统计代码都在几 KB 量级，64KB 上限（与后端一致）。 */
const MAX_LEN = 64 * 1024;

// 必须是 computed：写成普通函数在模板里传的是「函数引用」，恒为真值 ——
// 会把保存按钮永久禁用（`saving || tooLong` 里 tooLong 永远是 truthy）。
const tooLong = computed(() => code.value.length > MAX_LEN);

function loadSettings() {
    loading.value = true;
    errorText.value = '';
    return axios.get('/api/v1/settings/general/analytics')
        .then((response) => {
            const d = response.data?.data || {};
            code.value = typeof d.code === 'string' ? d.code : '';
            customized.value = !!d.customized;
        })
        .catch((e) => {
            code.value = '';
            customized.value = false;
            errorText.value = e?.isSpaFallback
                ? '后端服务缺少该接口 —— 服务端还没部署本次更新，请重启后端服务后重试。'
                : '读取统计代码失败，请重试。';
        })
        .finally(() => {
            loading.value = false;
        });
}

/** 保存。空串 = 清除（后端特判为删行）。 */
function save() {
    saving.value = true;
    axios.put('/api/v1/settings/general/analytics', {code: code.value})
        .then((response) => {
            const d = response.data?.data || {};
            code.value = typeof d.code === 'string' ? d.code : '';
            customized.value = !!d.customized;
            if (code.value.trim()) {
                showSuccess('统计代码已保存，刷新页面后开始生效');
            } else {
                showSuccess('已清除统计代码，刷新页面后停止统计');
            }
        })
        .catch((e) => {
            showError(e?.response?.data?.detail || '保存失败');
            // 保存失败 → 重新拉取，让控件回到与后端一致的状态（避免界面骗人）
            loadSettings();
        })
        .finally(() => {
            saving.value = false;
        });
}

/** 清除 = 删配置行，回到「不注入任何统计代码」。 */
function clearCode() {
    saving.value = true;
    axios.delete('/api/v1/settings/general/analytics')
        .then((response) => {
            const d = response.data?.data || {};
            code.value = typeof d.code === 'string' ? d.code : '';
            customized.value = !!d.customized;
            showSuccess('已清除统计代码，刷新页面后停止统计');
        })
        .catch((e) => {
            showError(e?.response?.data?.detail || '清除失败');
            loadSettings();
        })
        .finally(() => {
            saving.value = false;
        });
}

onBeforeMount(loadSettings);

</script>

<template>

    <!-- ⚠️ 不挂自己的 <Toast/>：通知统一走 AppLayout 的全局 Toast（避免合并进通用设置页后被渲染成多条重复提示） -->
    <div class="card">
        <div class="flex flex-col gap-2 w-full mb-4">
            <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-3 w-full">
                <div class="text-gray-500 text-sm">
                    网站统计代码
                    <Tag v-if="customized" value="已自定义" severity="warn" class="ml-2"/>
                    <Tag v-else value="未配置" severity="secondary" class="ml-2"/>
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
                粘贴统计平台提供的代码片段（整段，含 <code>&lt;script&gt;</code> 标签），
                <b>保存后刷新页面即生效、无需重启服务</b>；对所有已登录用户全站生效。
                「清除」= 删除库里的配置行，回到不注入任何统计代码。
            </div>
        </div>

        <div v-if="loading && !customized && !code" class="text-gray-400 text-sm py-6 text-center">
            <i class="pi pi-spin pi-spinner"></i> 加载中...
        </div>

        <div v-else-if="errorText" class="text-red-500 text-sm py-6 text-center">
            {{ errorText }}
        </div>

        <div v-else class="flex flex-col gap-3">
            <Textarea
                v-model="code"
                rows="10"
                class="analytics-code-input"
                placeholder="<script> var _hmt = _hmt || []; ... </script>"
                :disabled="saving"
            />
            <div class="flex items-center justify-between gap-3 flex-wrap">
                <div class="text-xs text-gray-400">
                    当前 {{ code.length }} 字符（上限 {{ MAX_LEN }}）
                    <span v-if="tooLong" class="text-red-500">· 已超出上限，无法保存</span>
                </div>
                <div class="flex items-center gap-2">
                    <Button
                        label="保存"
                        size="small"
                        :loading="saving"
                        :disabled="saving || tooLong"
                        @click="save"
                    />
                    <Button
                        label="清除"
                        size="small"
                        severity="secondary"
                        outlined
                        :loading="saving"
                        :disabled="!customized || saving"
                        @click="clearCode"
                    />
                </div>
            </div>
            <div class="analytics-note">
                <i class="pi pi-info-circle"></i>
                <div>
                    <b>支持任意统计平台</b>：百度统计、CNZZ、Google Analytics、umami、
                    Matomo 等，只要它给的是可粘贴的 <code>&lt;script&gt;</code> 片段即可。
                    代码只在页面加载时执行一次；保存后请<b>刷新页面</b>再验证效果。
                    若粘贴后页面无数据，请检查代码是否完整（有些平台会拆成两段，需一起粘贴）。
                </div>
            </div>
        </div>
    </div>

</template>

<style scoped lang="scss">
/* 代码输入框：等宽字体 + 字号不低于 10px（统计代码是要逐字看的），
   取消横向 resize（长代码会撑破卡片），只允许纵向拖高 */
.analytics-code-input {
    width: 100%;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.9rem;
    line-height: 1.6;
    resize: vertical;
}

.analytics-note {
    display: flex;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border: 1px solid #e0e7ff;
    border-radius: 6px;
    background: #f6f8ff;
    font-size: 0.78rem;
    line-height: 1.7;
    color: #4b5563;

    i {
        flex: none;
        margin-top: 0.15rem;
        color: #6366f1;
    }

    code {
        background: #eef2ff;
        border-radius: 3px;
        padding: 0 4px;
    }
}
</style>
