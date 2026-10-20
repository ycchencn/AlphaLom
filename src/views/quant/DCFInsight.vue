<script setup>

import {FilterMatchMode, FilterOperator} from '@primevue/core/api';
import {computed, onBeforeMount, ref} from 'vue';
import {formatPercentage, toneClass} from '@/utils/function';
import ToggleSwitch from 'primevue/toggleswitch';
import axios from 'axios';
import {useNotification} from '@/composables/useNotification';

const {showSuccess, showError} = useNotification();

const stock_list = ref([]);
const filters1 = ref(null);
const loading1 = ref(null);
const dt1 = ref(null);
// 正在关闭监控的行 symbol（按钮 loading 态，避免连点）
const closing_symbol = ref('');

// ==================== 关闭监控 ====================
// DCF 汇总表是全局缓存（所有被监控的标的一起算），「关闭监控」只把这只票
// 移出**当前用户**的股票池（调 DELETE /stocks/{symbol}，与个股监控页一致）：
// 不影响其他用户、也不删除公共行情数据。成功后从当前列表移除该行并提示。
async function closeMonitoring(row) {
    if (closing_symbol.value) return;                    // 已有请求在飞，防连点
    if (!window.confirm(`确定将 ${row.symbol} ${row.name || ''} 移出监控列表？\n（仅移除你的监控，其他用户与该股票基础数据不受影响。）`)) return;
    closing_symbol.value = row.symbol;
    try {
        await axios.delete(`/api/v1/stocks/${encodeURIComponent(row.symbol)}`);
        showSuccess(`已移出监控：${row.symbol}`);
        // 当前列表是全局快照，移除后直接剔掉本行即可（不必整表重拉）
        stock_list.value = stock_list.value.filter((it) => it.symbol !== row.symbol);
    } catch (error) {
        const detail = error.response?.data?.detail;
        showError(detail ? `移出监控失败：${detail}` : '移出监控失败，请重试');
    } finally {
        closing_symbol.value = '';
    }
}


// ==================== 赔率过滤 ====================
// 「赔率低」的判定口径：**保守情景空间 <= 0**。
// 即哪怕按 DCF 最悲观的一档估值，价格也已经没有上行空间（估值 >= 现价），
// 这种票风险收益比很差。
//
// 为什么不看「中性空间」：中性情景偏乐观，很多票中性为正、保守为负，
// 也就是说「合理估值下能涨，但一旦基本面走弱就要亏」，这恰恰是低赔率的典型特征。
const MIN_ODDS_SPACE = 0;

// 默认**不**隐藏低赔率（2026-10-20 用户要求：默认展示全量）。
// ⚠️ 之前默认是 true（当时要求「赔率很低的不要显示」），后来发现默认过滤会让
// 用户以为这些票不存在，且看不到它们的保守空间到底差多少 —— 低赔率本身就是
// 有价值的信息（说明下行风险大于上行空间），不该被静默藏起来。
// 开关保留：需要聚焦赔率合格的标的时可一键打开。
const hideLowOdds = ref(false);

// 判定单条记录是否属于「低赔率」。
// ⚠️ cons_space 缺失（null）时**不算**低赔率 —— 缺数据不等于赔率差，
// 直接隐藏会让用户以为这只票不存在；宁可显示出来由用户判断。
function isLowOdds(item) {
    const v = item?.cons_space;
    if (v === null || v === undefined) return false;
    return Number(v) <= MIN_ODDS_SPACE;
}

// 低赔率条目数（用于表头提示与开关文案）
const lowOddsCount = computed(() => stock_list.value.filter(isLowOdds).length);

// 实际渲染的数据：关闭过滤时给全量，开启时剔除低赔率
const visibleList = computed(() =>
    hideLowOdds.value ? stock_list.value.filter((it) => !isLowOdds(it)) : stock_list.value
);

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
            :value="visibleList"
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
                    <!-- 左侧：标题 + 计数 + 赔率过滤开关 -->
                    <div class="w-full md:w-auto flex flex-wrap items-center gap-3">
                        <span class="font-semibold">DCF估值信息汇总 - 每日更新</span>
                        <span class="dcf-count">
                            显示 {{ visibleList.length }} / {{ stock_list.length }}
                        </span>
                        <label class="dcf-toggle" :title="`隐藏「保守空间 ≤ ${MIN_ODDS_SPACE * 100}%」的低赔率个股`">
                            <ToggleSwitch v-model="hideLowOdds" size="small"/>
                            <span>隐藏低赔率</span>
                            <span v-if="hideLowOdds && lowOddsCount > 0" class="dcf-hint">
                                （已隐藏 {{ lowOddsCount }} 只）
                            </span>
                        </label>
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
            <template #empty>
                <span v-if="hideLowOdds && stock_list.length">
                    当前条件下没有赔率合格的个股（已隐藏 {{ lowOddsCount }} 只低赔率标的），
                    可关闭「隐藏低赔率」查看全部。
                </span>
                <span v-else>No data found.</span>
            </template>
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
                    <span :class="toneClass(data.opt_space)">
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
                    <span :class="toneClass(data.mid_space)">
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
                    <span :class="toneClass(data.cons_space)">
                        {{ data.cons_space != null ? (data.cons_space * 100).toFixed(2) + '%' : '--' }}
                    </span>
                </template>
            </Column>            <Column field="update_time" filterField="update_time" header="更新时间">
                <template #body="{ data }">
                    {{ data.update_time }}
                </template>
            </Column>
            <Column field="__actions" header="操作" :exportable="false" style="min-width: 110px">
                <template #body="{ data }">
                    <Button
                        size="small"
                        severity="danger"
                        text
                        :loading="closing_symbol === data.symbol"
                        :disabled="closing_symbol !== '' && closing_symbol !== data.symbol"
                        @click="closeMonitoring(data)"
                    >
                        <i class="pi pi-times mr-1"></i>关闭监控
                    </Button>
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
    background: var(--app-up-soft) !important; /* 贪婪 - 浅红 */
}

:deep(.fg-extreme-greed .p-progressbar-value) {
    background: var(--app-up) !important; /* 极度贪婪 - 红 */
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
    background-color: var(--app-down);
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

/* ==================== 赔率过滤控件 ==================== */
.dcf-count {
    font-size: 11px;
    color: #8a8a8a;
    font-variant-numeric: tabular-nums;
}

.dcf-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 400;
    color: #4a4a4a;
    cursor: pointer;
    white-space: nowrap;
}

.dcf-hint {
    font-size: 11px;
    color: #b0752a;
}

</style>
