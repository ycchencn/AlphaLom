<script setup>

import {computed, onBeforeMount, ref} from 'vue';
import axios from 'axios';
import {useNotification} from '@/composables/useNotification';
import {invalidateTimezone} from '@/composables/useTimezone.js';

// ⚠️ 不要 `import Select from 'primevue/select'`：本项目用
//    `Components({resolvers: [PrimeVueResolver()]})` 自动导入 PrimeVue 组件，
//    显式 import 会让 resolver 跳过它、组件反而渲染不出来（页面上只剩相邻按钮）。
//    其它页面（如 FactorScreen.vue）的 <Select> 也是靠自动导入的。

/**
 * 系统设置 · 通用设置
 *
 * 目前只有一项：**展示时区**。它决定页面上显示的时间按哪个时区解释。
 * 配置存在后端 system_setting 表（分组 general_setting），保存后立即生效、无需重启；
 * 点「恢复默认」= 删掉表里那一行，回落到代码默认值（Asia/Shanghai）。
 *
 * ⚠️ 作用范围 —— 页面里必须讲清楚，否则用户会以为改时区能改任务触发时刻：
 *    时区**只影响展示**。定时任务（新闻采集、速览生成、日更）固定按 A 股业务时区
 *    （Asia/Shanghai）触发，改这里不会把任务挪点 —— 那属于市场规则而非用户偏好。
 */
const {showSuccess, showError} = useNotification();

const loading = ref(false);
const saving = ref(false);

const timezone = ref('');
const defaultValue = ref('Asia/Shanghai');
const customized = ref(false);
const currentTime = ref('');
const utcOffset = ref('');
const serverLocalTimezone = ref('');
const serverLocalOffset = ref('');
const aShareTimezone = ref('Asia/Shanghai');

/** 下拉数据源（分组结构：常用 / 全部时区）。 */
const timezoneOptions = ref([]);

const errorText = ref('');

/**
 * 服务器本地时区是否与展示时区「偏移不同」。
 *
 * ⚠️ 必须比 UTC 偏移，**不能比时区名字**：
 *    `serverLocalTimezone` 是给人看的显示串（形如 "中国标准时间 (UTC+08:00)"），
 *    `timezone` 是 IANA 名（"Asia/Shanghai"），两者永远不相等 ——
 *    拿名字比会让告警无条件常亮（哪怕两边都是 UTC+8）。
 *    真正要提示的是「机器时区与展示时区差了几个小时」（历史 naive 数据可能因此错位）。
 */
const offsetDiffers = computed(() => {
    const a = normalizeOffset(utcOffset.value);
    const b = normalizeOffset(serverLocalOffset.value);
    if (a === null || b === null) return false;  // 缺数据时不误报
    return a !== b;
});

/** 把 "UTC+08:00" / "+08:00" / "UTC+8" 归一成分钟数；解析不出返回 null。 */
function normalizeOffset(s) {
    if (!s) return null;
    const m = String(s).replace('UTC', '').trim().match(/^([+-])(\d{1,2})(?::?(\d{2}))?$/);
    if (!m) return null;
    const sign = m[1] === '-' ? -1 : 1;
    return sign * (Number(m[2]) * 60 + Number(m[3] || 0));
}

function loadSettings() {
    loading.value = true;
    errorText.value = '';
    return axios.get('/api/v1/settings/general')
        .then((response) => {
            const d = response.data?.data || response.data || {};
            timezone.value = d.timezone || 'Asia/Shanghai';
            defaultValue.value = d.default || 'Asia/Shanghai';
            customized.value = !!d.customized;
            currentTime.value = d.current_time || '';
            utcOffset.value = d.utc_offset || '';
            serverLocalTimezone.value = d.server_local_timezone || '';
            serverLocalOffset.value = d.server_local_offset || '';
            aShareTimezone.value = d.a_share_timezone || 'Asia/Shanghai';
            timezoneOptions.value = buildGroupedOptions(d.common || [], timezone.value);
        })
        .catch((e) => {
            errorText.value = describeError(e);
            showError(errorText.value);
        })
        .finally(() => {
            loading.value = false;
        });
}

/**
 * 组装分组下拉数据：`[{label:'常用', items:[{label,value}...]}, {label:'全部时区', items:[...]}]`。
 *
 * 走 PrimeVue Select 的分组模式（`optionGroupLabel` + `optionGroupChildren`），
 * 它要求 options 是「组数组、每组带 items」，**不能**给每个选项塞 group 字段。
 *
 * 全量时区用 `Intl.supportedValuesOf('timeZone')` 拿（浏览器原生，不必后端再传一份）；
 * 老浏览器没有这个 API 时只给常用清单（降级但可用）。
 */
function buildGroupedOptions(commonList, currentValue) {
    const seen = new Set();
    const commonItems = [];

    for (const item of commonList) {
        if (seen.has(item.value)) continue;
        seen.add(item.value);
        commonItems.push({label: item.label, value: item.value});
    }

    let all = [];
    try {
        all = Intl.supportedValuesOf('timeZone') || [];
    } catch (e) {
        all = [];
    }
    const otherItems = [];
    for (const tz of all) {
        if (seen.has(tz)) continue;
        seen.add(tz);
        otherItems.push({label: tz, value: tz});
    }

    // 当前值不在清单里（后端配了个浏览器不认识的名字）→ 补进常用组，避免控件显示空
    if (currentValue && !seen.has(currentValue)) {
        commonItems.unshift({label: `${currentValue}（当前配置）`, value: currentValue});
    }

    const groups = [{label: '常用时区', items: commonItems}];
    if (otherItems.length) groups.push({label: '全部时区', items: otherItems});
    return groups;
}

/** 把 axios 错误转成可读文案（区分 SPA 兜底 / 403 / 401 / 其它）。 */
function describeError(e) {
    if (e?.isSpaFallback) {
        return '后端服务缺少该接口 —— 服务端还没部署本次更新，请重启后端服务后重试。';
    }
    const status = e?.response?.status;
    if (status === 403) return '当前账号不是管理员，无权查看/修改系统设置。';
    if (status === 401) return '登录已失效，请重新登录。';
    if (status) return `读取失败（HTTP ${status}）：${e?.response?.data?.detail || '未知错误'}`;
    return '读取设置失败，请检查网络或后端服务。';
}

function saveTimezone() {
    if (!timezone.value) return;
    saving.value = true;
    axios.put('/api/v1/settings/general/timezone', {timezone: timezone.value})
        .then((response) => {
            const d = response.data?.data || {};
            timezone.value = d.timezone || timezone.value;
            defaultValue.value = d.default || defaultValue.value;
            customized.value = !!d.customized;
            currentTime.value = d.current_time || '';
            utcOffset.value = d.utc_offset || '';
            // 失效 composable 缓存 → 各页下次读能拿到新时区
            invalidateTimezone();
            showSuccess(`展示时区已切换为 ${timezone.value}`);
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

/** 恢复默认 = 删配置行，回落到代码默认时区 */
function resetTimezone() {
    saving.value = true;
    axios.delete('/api/v1/settings/general/timezone')
        .then((response) => {
            const d = response.data?.data || {};
            timezone.value = d.timezone || defaultValue.value;
            customized.value = !!d.customized;
            currentTime.value = d.current_time || '';
            utcOffset.value = d.utc_offset || '';
            invalidateTimezone();
            showSuccess(`已恢复默认时区（${timezone.value}）`);
        })
        .catch((e) => {
            showError(e?.response?.data?.detail || '恢复默认失败');
            loadSettings();
        })
        .finally(() => {
            saving.value = false;
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
                    通用设置 · 全站展示口径
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
                设置存放在数据库里，<b>保存后立即生效、无需重启服务</b>。
                「恢复默认」= 删除库里的配置行，回到代码中的默认值。
            </div>
        </div>

        <div v-if="loading" class="text-gray-400 text-sm py-6 text-center">
            <i class="pi pi-spin pi-spinner"></i> 加载中...
        </div>

        <div v-else-if="errorText" class="text-red-500 text-sm py-6 text-center">
            {{ errorText }}
        </div>

        <div v-else class="gs-list">
            <!-- 时区 -->
            <div class="gs-row">
                <div class="gs-main">
                    <div class="gs-label">
                        展示时区
                        <Tag v-if="customized" value="已自定义" severity="warn" class="ml-2"/>
                        <Tag v-else value="代码默认" severity="secondary" class="ml-2"/>
                    </div>
                    <div class="gs-desc">
                        页面上显示的时间按这个时区解释。影响速览卡片、新闻时间等所有时间展示。
                    </div>
                    <div class="gs-meta">
                        生效值：<b>{{ timezone }}</b>
                        · <span v-if="utcOffset">{{ utcOffset }}</span>
                        · 该时区此刻：<b>{{ currentTime }}</b>
                        <template v-if="serverLocalTimezone">
                            <br/>服务器本地时区：{{ serverLocalTimezone }}
                            <span v-if="offsetDiffers" class="gs-warn">
                                （与展示时区不同，历史数据可能因此有偏移）
                            </span>
                        </template>
                    </div>
                </div>
            </div>

            <!-- 操作区 -->
            <div class="gs-actions">
                <Select
                    v-model="timezone"
                    :options="timezoneOptions"
                    optionLabel="label"
                    optionValue="value"
                    optionGroupLabel="label"
                    optionGroupChildren="items"
                    filter
                    filterBy="label"
                    class="gs-select"
                    placeholder="选择时区"
                    :disabled="saving"
                />
                <Button
                    label="保存"
                    size="small"
                    :loading="saving"
                    :disabled="saving"
                    @click="saveTimezone"
                />
                <Button
                    label="恢复默认"
                    size="small"
                    severity="secondary"
                    outlined
                    :disabled="!customized || saving"
                    @click="resetTimezone"
                />
            </div>

            <!-- 作用范围说明：必须写清楚，否则用户以为改这里能改任务时刻 -->
            <div class="gs-note">
                <i class="pi pi-info-circle"></i>
                <div>
                    <b>时区只影响展示，不影响定时任务。</b>
                    新闻采集、速览生成、行情日更等任务固定按 <b>{{ aShareTimezone }}</b>
                    （A 股业务时区）触发 —— 「15:00 收盘」「交易日」属于市场规则而非个人偏好，
                    跟着展示时区变会让任务在错误时刻运行并产生错误数据。
                </div>
            </div>
        </div>
    </div>

</template>

<style scoped lang="scss">
.gs-list {
    display: flex;
    flex-direction: column;
}

.gs-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    padding: 1rem 0.25rem 0.75rem;
    border-bottom: 1px solid #f1f5f9;
}

.gs-main {
    min-width: 0;

    .gs-label {
        font-size: 0.95rem;
        font-weight: 600;
        color: #1e293b;
        display: flex;
        align-items: center;
    }

    .gs-desc {
        font-size: 0.8rem;
        color: #64748b;
        margin-top: 0.2rem;
    }

    .gs-meta {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-top: 0.3rem;
        line-height: 1.6;

        .gs-warn {
            color: #d97706;
        }
    }
}

.gs-actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 1rem 0.25rem 0.5rem;

    .gs-select {
        min-width: 20rem;
    }
}

.gs-note {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.5rem;
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
}

@media (max-width: 768px) {
    .gs-row {
        flex-direction: column;
        align-items: flex-start;
        gap: 0.75rem;
    }

    .gs-actions {
        flex-wrap: wrap;

        .gs-select {
            min-width: 100%;
        }
    }
}
</style>
