<script setup>
import Dialog from 'primevue/dialog';
import ConfirmDialog from 'primevue/confirmdialog';
import { computed, onBeforeMount, ref, watch } from 'vue';
import axios from 'axios';
import { formatCurrency } from '@/utils/function';
import { useNotification } from '@/composables/useNotification';

const portfolios = ref([]); // 初始化为空数组，避免 v-for 报错
const loading1 = ref(false);
const { showSuccess, showError } = useNotification();

// ---- 新增投资组合相关 ----
const createDialogVisible = ref(false);
const submitting = ref(false);
const createForm = ref({
    name: '',
    strategy_type: 1,
    init_cash: 1000000,
    current_cash: 1000000,
    total_position_pct: 80,
    base_currency: 'CNY',
    llm_setting: {
        model: '',
        platform: 'aliyun'
    }
});

// 策略类型选项（与下方 PHASE_CONFIG 对齐）
const strategyTypeOptions = [
    { label: '技术面', value: 0 },
    { label: 'AI主观', value: 1 },
];

// 基准货币选项
const currencyOptions = [
    { label: '人民币 CNY', value: 'CNY' },
    { label: '美元 USD', value: 'USD' },
    { label: '港币 HKD', value: 'HKD' },
];

// 大模型平台选项（对应 llms/__init__.py get_model_by_setting 的 platform 分发）
const platformOptions = [
    { label: '阿里云百炼', value: 'aliyun' },
    { label: 'DeepSeek', value: 'deepseek' },
    { label: '火山引擎', value: 'volcengine' },
    { label: 'SiliconFlow', value: 'siliconflow' },
    { label: '智谱', value: 'zhipu' },
];

// ---- 模型列表（后端 GET /api/v1/llm/models?platform=xx，实时调各平台 /models 接口）----
// 与平台下拉联动：切换平台后拉取该平台可用模型（客户端按平台缓存，切回不重复请求）；
// 接口失败时退化为可手动输入，不阻塞创建流程
const modelOptionsByPlatform = ref({});
const modelsLoading = ref(false);
const loadLlmModels = (platform) => {
    if (!platform || modelOptionsByPlatform.value[platform]) return; // 已有缓存
    modelsLoading.value = true;
    axios.get('/api/v1/llm/models', { params: { platform } })
        .then(response => {
            const info = (response.data || {})[platform];
            modelOptionsByPlatform.value[platform] = info?.models || [];
            if (info?.error) {
                showError(`获取 ${platform} 模型列表失败，可手动输入模型名称`);
            }
        })
        .catch(err => {
            console.error('模型列表加载失败', err);
            modelOptionsByPlatform.value[platform] = [];
            showError('获取模型列表失败，可手动输入模型名称');
        })
        .finally(() => {
            modelsLoading.value = false;
        });
};

// 当前平台下的可选模型
const modelOptions = computed(() => modelOptionsByPlatform.value[createForm.value.llm_setting.platform] || []);

// 平台切换联动：拉取新平台的模型列表；当前模型不在新平台选项里时，自动切到首个模型（没有则清空）
watch(() => createForm.value.llm_setting.platform, (platform) => {
    loadLlmModels(platform);
    if (createForm.value.llm_setting.model && !modelOptions.value.includes(createForm.value.llm_setting.model)) {
        createForm.value.llm_setting.model = modelOptions.value[0] || '';
    }
});

// 打开弹窗即拉当前默认平台的模型列表
watch(createDialogVisible, (visible) => {
    if (visible) loadLlmModels(createForm.value.llm_setting.platform);
});

// 辅助函数：安全计算累计收益率
const calculateCumulativeReturn = (item) => {

    // 1. 防御性编程：检查对象层级是否存在
    const summary = item.summary || {};
    const totalAssets = Number(summary.total_assets);
    const initCash = Number(item.init_cash);

    // 2. 边界值判断：如果总资产或初始资金无效（如 null, undefined, NaN），返回 0 或 '-'
    if (!totalAssets || !initCash) {
        item.summary.total_assets = initCash;
        return 0;
    }

    // 3. 计算公式：(总资产 - 本金) / 本金 * 100
    const ratio = (totalAssets - initCash) / initCash;

    // 4. 格式化：保留两位小数 + %
    return ratio * 100;
};

// 加载投资组合列表（可复用，新增后刷新用）
const loadPortfolios = () => {
    loading1.value = true;
    axios.get('/api/v1/investment_portfolios')
        .then(response => {
            const rawData = response.data || [];
            portfolios.value = rawData.map(item => {
                // 防御：新组合可能暂无 daily summary，补全字段避免 toFixed / 运算报错
                const summary = item.summary || {};
                item.summary = {
                    total_unrealized_pnl: summary.total_unrealized_pnl ?? 0,
                    total_assets: summary.total_assets ?? 0,
                    daily_pnl_change: summary.daily_pnl_change ?? 0,
                    position_ratio: summary.position_ratio ?? 0,
                };
                // 仓位比例后端为 0~1 小数，转成 0~100 供 ProgressBar 显示，保留2位小数
                item.summary.position_ratio = Math.round(item.summary.position_ratio * 10000) / 100;
                item.calculated_return_rate = calculateCumulativeReturn(item);
                return item;
            });
        })
        .catch(err => {
            console.error("数据加载失败", err);
            showError('投资组合列表加载失败');
        })
        .finally(() => {
            loading1.value = false;
        });
};

onBeforeMount(() => {
    loadPortfolios();
});

// 打开新增弹窗（重置表单为默认值）
const openCreateDialog = () => {
    createForm.value = {
        name: '',
        strategy_type: 1,
        init_cash: 1000000,
        current_cash: 1000000,
        total_position_pct: 80,
        base_currency: 'CNY',
        llm_setting: {
            model: '',
            platform: 'aliyun'
        }
    };
    createDialogVisible.value = true;
};

// 提交新增投资组合
const submitCreate = async () => {
    const f = createForm.value;

    // 前置校验
    if (!f.name || !String(f.name).trim()) {
        showError('请输入策略名称');
        return;
    }
    if (f.init_cash == null || Number(f.init_cash) <= 0) {
        showError('初始资金必须大于 0');
        return;
    }
    if (f.current_cash == null || Number(f.current_cash) < 0) {
        showError('当前资金不能为负数');
        return;
    }
    if (f.total_position_pct == null || Number(f.total_position_pct) < 0 || Number(f.total_position_pct) > 100) {
        showError('总仓位需在 0~100 之间');
        return;
    }
    if (!f.llm_setting.model || !String(f.llm_setting.model).trim()) {
        showError('请输入大模型名称');
        return;
    }

    submitting.value = true;
    try {
        await axios.post('/api/v1/investment_portfolios', {
            name: String(f.name).trim(),
            strategy_type: Number(f.strategy_type),
            init_cash: Number(f.init_cash),
            current_cash: Number(f.current_cash),
            total_position_pct: Number(f.total_position_pct),
            base_currency: f.base_currency,
            llm_setting: {
                model: String(f.llm_setting.model || '').trim(),
                platform: f.llm_setting.platform
            }
        });
        showSuccess('策略创建成功');
        createDialogVisible.value = false;
        loadPortfolios();
    } catch (error) {
        let message = '创建失败，请重试';
        if (error?.response?.data?.msg) {
            message = error.response.data.msg;
        }
        showError(message);
    } finally {
        submitting.value = false;
    }
};

// 辅助函数：安全计算今日收益百分比（分母为 0 时返回 0，避免 NaN）
const calculateDailyPct = (summary) => {
    const change = Number(summary?.daily_pnl_change ?? 0);
    const totalAssets = Number(summary?.total_assets ?? 0);
    if (!totalAssets) return '0.00';
    return ((change / totalAssets) * 100).toFixed(2);
};

// 1. 阶段映射配置
const PHASE_CONFIG = {
    0: { label: '技术面', type: 'unknown', severity: 'secondary' },
    1: { label: 'AI主观', type: 'accumulate', severity: 'info' },
};

const formatType = (phaseInt) => {
    return PHASE_CONFIG[phaseInt]?.label || PHASE_CONFIG[0].label;
};

</script>

<template>
    <Toast />
    <ConfirmDialog></ConfirmDialog>

    <!-- 新增投资组合弹窗 -->
    <Dialog v-model:visible="createDialogVisible" modal header="新增投资组合" :style="{ width: '28rem' }">
        <div class="flex flex-col gap-4">
            <div>
                <label for="pf_name" class="font-semibold block mb-1">策略名称 <span class="text-red-500">*</span></label>
                <InputText id="pf_name" v-model="createForm.name" autocomplete="off" placeholder="请输入策略名称" class="w-full" />
            </div>

            <div>
                <label for="pf_strategy_type" class="font-semibold block mb-1">策略类型</label>
                <Dropdown id="pf_strategy_type" v-model="createForm.strategy_type" :options="strategyTypeOptions" optionLabel="label" optionValue="value" class="w-full" />
            </div>

            <div>
                <label for="pf_init_cash" class="font-semibold block mb-1">初始资金 <span class="text-red-500">*</span></label>
                <InputNumber id="pf_init_cash" v-model="createForm.init_cash" mode="currency" currency="CNY" locale="zh-CN" :min="0" class="w-full" />
            </div>

            <div>
                <label for="pf_current_cash" class="font-semibold block mb-1">当前资金 <span class="text-red-500">*</span></label>
                <InputNumber id="pf_current_cash" v-model="createForm.current_cash" mode="currency" currency="CNY" locale="zh-CN" :min="0" class="w-full" />
            </div>

            <div>
                <label for="pf_position_pct" class="font-semibold block mb-1">总仓位（%） <span class="text-red-500">*</span></label>
                <InputNumber id="pf_position_pct" v-model="createForm.total_position_pct" :min="0" :max="100" suffix=" %" class="w-full" />
            </div>

            <div>
                <label for="pf_currency" class="font-semibold block mb-1">基准货币</label>
                <Dropdown id="pf_currency" v-model="createForm.base_currency" :options="currencyOptions" optionLabel="label" optionValue="value" class="w-full" />
            </div>

            <div>
                <label for="pf_platform" class="font-semibold block mb-1">大模型平台</label>
                <Dropdown id="pf_platform" v-model="createForm.llm_setting.platform" :options="platformOptions" optionLabel="label" optionValue="value" class="w-full" />
            </div>

            <div>
                <label for="pf_model" class="font-semibold block mb-1">模型名称 <span class="text-red-500">*</span></label>
                <Dropdown
                    id="pf_model"
                    v-model="createForm.llm_setting.model"
                    :options="modelOptions"
                    :loading="modelsLoading"
                    editable
                    filter
                    placeholder="选择模型，也可手动输入"
                    :empty-message="modelsLoading ? '正在获取模型列表…' : '该平台暂无可用模型，可手动输入'"
                    class="w-full"
                />
            </div>
        </div>

        <template #footer>
            <div class="flex justify-end gap-2">
                <Button type="button" label="取消" severity="secondary" text @click="createDialogVisible = false" :disabled="submitting" />
                <Button type="button" label="创建" :loading="submitting" @click="submitCreate" />
            </div>
        </template>
    </Dialog>

    <div class="card">
        <DataTable
            :value="portfolios"
            :rows="25"
            dataKey="id"
            :showGridlines="false"
            :rowHover="true"
            filterDisplay="menu"
            :loading="loading1"
            :globalFilterFields="['name']"
            style="font-size: 11px"
            size="medium"
            showGridlines
        >
            <template #header>
                <div class="flex flex-col md:flex-row items-center justify-between gap-3 w-full">
                    <!-- 左侧：下拉框 -->
                    <div class="w-full md:w-auto">
                        <span class="font-semibold">AI 量化策略</span>
                    </div>
                    <!-- 右侧：按钮 + 搜索框 -->
                    <div class="flex flex-wrap items-center gap-2 w-full md:w-auto justify-end md:justify-start">
                        <Button
                            type="button"
                            icon="pi pi-plus"
                            size="small"
                            label="添加策略"
                            class="whitespace-nowrap"
                            @click="openCreateDialog"
                        />
                    </div>
                </div>
            </template>
            <template #empty> No data found.</template>
            <template #loading> Loading customers data. Please wait.</template>

            <Column field="name" filterField="name" header="策略名">
                <template #body="{ data }">
                    {{ data.name }}
                </template>
            </Column>

            <Column field="name" filterField="name" header="策略类型">
                <template #body="{ data }">
                    {{ formatType(data.strategy_type) }}
                </template>
            </Column>

            <Column field="name" filterField="name" header="仓位" style="min-width: 8rem">
                <template #body="{ data }">
                    <ProgressBar :value="data.summary?.position_ratio"></ProgressBar>
                </template>
            </Column>

            <Column field="name" filterField="name" header="今日收益">
                <template #body="{ data }">
                    <span
                      :class="{
                      'text-red-600': data.summary.daily_pnl_change > 0,
                      'text-green-600': data.summary.daily_pnl_change < 0,
                    }">
                        {{ formatCurrency(data.summary.daily_pnl_change, true) }}
                        ({{ calculateDailyPct(data.summary) }}%)
                    </span>
                </template>
            </Column>

            <!-- 修改后的累计收益列 -->
            <Column field="calculated_return_rate" header="累计收益">
                <template #body="{ data }">
                    <!-- 直接使用预处理好的字段，简单且无运行时错误风险 -->
                    <span :class="{
                        'text-red-600': parseFloat(data.calculated_return_rate) > 0,
                        'text-green-600': parseFloat(data.calculated_return_rate) < 0,
                    }">
                        {{ formatCurrency(data.summary.total_assets - data.init_cash, true) }}
                        ({{ data.calculated_return_rate.toFixed(2) }}%)
                    </span>
                </template>
            </Column>

            <Column field="name" filterField="name" header="浮动盈亏">
                <template #body="{ data }">
                    <span
                      :class="{
                      'text-red-600': data.summary.total_unrealized_pnl > 0,
                      'text-green-600': data.summary.total_unrealized_pnl < 0,
                    }">{{ formatCurrency(data.summary.total_unrealized_pnl, true) }}
                    </span>
                </template>
            </Column>

            <Column field="name" filterField="name" header="持仓个股">
                <template #body="{ data }">
                    {{ (data.assets || []).length }}
                </template>
            </Column>

            <Column field="name" filterField="name" header="操作">
                <template #body="{ data }">
                    <router-link
                        class="text-blue-500"
                        :to="{ name: 'portfolio_view', params: { portfolio_id: data.portfolio_id } }">查看
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
</style>
