<script setup>
import { ref, onMounted, computed } from 'vue';
import { useRoute } from 'vue-router';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Card from 'primevue/card';
import Badge from 'primevue/badge';
import { useNotification } from '@/composables/useNotification';
import {
    fetchPortfolioInfo,
    setColorOptions,
    formatCurrency,
    formatHoldingDuration,
    formatDaysAgo,
    fetchPortfolioSummaryDaily,
    fetchPortfolioTransaction, fetchPortfolioQuantStat
} from '@/utils/function.js';
import axios from 'axios';
import Dialog from 'primevue/dialog';
import MarkdownEditor from '@/components/MarkdownEditor.vue';
const { showSuccess, showError } = useNotification();

// 状态
const route = useRoute();
const portfolioId = route.params.portfolio_id;
const profInfo = ref(null);
const profSummary = ref(null);
const profTransaction = ref(null);
const loading = ref(true);
const lineData = ref(null);
const lineDataAssets = ref(null);
const lineOptions = ref(null);
const modal_visible = ref(false);
const code = ref(``);
// 盈亏日历数据
const profitData = ref({});
const portfolio_quantstat = ref(null);
const dcf_research_report_drawer = ref(false)

// 编辑器选项对象
const editorOptions = {
  minimap: { enabled: false }, // 启用缩略图
  fontSize: 12,
  scrollBeyondLastLine: false,
  automaticLayout: true
};

// 处理编辑器挂载完成事件
const handleEditorDidMount = (editor) => {
  // console.log('Editor mounted!', editor);
  // editorInstance = editor;
  // 你可以在 editorInstance 上调用任何 Monaco Editor API
  // 例如: editor.addAction(...)
};

// 在获取 profInfo 后，为每个 asset 添加 positionPct 和 marketValue
const enrichAssets = (info) => {
    if (!info?.assets || !Array.isArray(info.assets)) return;

    // 优先使用 summary.total_assets（最准确）
    const totalAssets = info.summary?.total_assets;

    if (typeof totalAssets !== 'number' || totalAssets <= 0) {
        // 如果没有 total_assets，回退到手动计算：股票市值 + 现金
        const totalPositionValue = info.assets.reduce((sum, asset) => {
            return sum + ((asset.position_size || 0) * (asset.position_price || 0));
        }, 0);
        const cash = info.current_cash || 0;
        info._fallbackTotalAssets = totalPositionValue + cash;
    }

    // 1. 首先确保 daily_pnl 是按日期排序的（最新的在最后或最前）
    // 假设数据是按时间倒序排列的（最新的在索引0），如果不是，请先排序
    const sortedPnL = [...info.daily_pnl].sort((a, b) => new Date(b.date) - new Date(a.date));

    // 2. 创建一个映射表，存储“昨天”的数据，用于快速查找
    // 键为 stock_code，值为昨天的 market_value
    const yesterdayDataMap = new Map();
    const todayDataMap = new Map();

    if (sortedPnL.length > 1) {
        // 获取昨天的数据组（索引为1，因为0是今天）
        // 注意：这里假设 sortedPnL[0] 是今天，sortedPnL[1] 是昨天
        const yesterdayDate = profSummary.value[profSummary.value.length - 2].date;
        const yesterdayGroup = sortedPnL.filter(record => record.date === yesterdayDate);
        yesterdayGroup.forEach(record => {
            yesterdayDataMap.set(record.stock_code, {
                unrealized_pnl: record.unrealized_pnl
            });
        });
        const todayDate = profSummary.value[profSummary.value.length - 1].date;
        const todayGroup = sortedPnL.filter(record => record.date === todayDate);
        todayGroup.forEach(record => {
            todayDataMap.set(record.stock_code, {
                unrealized_pnl: record.unrealized_pnl
            });
        });
    }

    // 3. 遍历今天的资产列表 (info.assets)，计算日变动
    info.assets.forEach(asset => {
        const todayMV = todayDataMap.unrealized_pnl;
        asset.marketValue = todayMV;

        // 计算占总资产比例 (保持原有逻辑)
        const denominator = typeof totalAssets === 'number' && totalAssets > 0
            ? totalAssets
            : (info._fallbackTotalAssets || 1);
        asset.positionPct = (todayMV / denominator) * 100;

        // --- 关键：计算日变动 ---
        const todayInfo = todayDataMap.get(asset.stock_code);
        const yesterdayInfo = yesterdayDataMap.get(asset.stock_code);

        if (yesterdayInfo && todayInfo) {
            // 如果昨天持有该股票
            // 注意：这里直接用市值相减，已经自动包含了价格波动和分红等所有因素
            asset.dailyChange = todayInfo.unrealized_pnl - yesterdayInfo.unrealized_pnl;
        } else {
            // 如果昨天没有持有（新买入），通常日变动设为 0
            // 或者如果你想显示“买入当天的盈亏”，可以计算 (现价-成本)*数量
            // 这里遵循“相对昨天”的定义，设为 0
            asset.dailyChange = 0;
            asset.dailyChangePct = 0;
        }
    });

    // 为每个 asset 添加计算字段
    info.assets.forEach(asset => {
        const mv = (asset.position_size || 0) * (asset.position_price || 0);
        asset.marketValue = mv;
        const denominator = typeof totalAssets === 'number' && totalAssets > 0
            ? totalAssets
            : (info._fallbackTotalAssets || 1); // 避免除零
        asset.positionPct = (mv / denominator) * 100;
    });
};

// 在 script setup 内部，ref 之后
// 👇 替换原有的 buyActions computed
const buyActions = computed(() => {
    // 如果数据未加载，返回空数组
    if (!profInfo.value?.position_plan?.actions || !profInfo.value?.assets) {
        return [];
    }
    // 提取当前所有的持仓股票代码，用于快速查找
    const heldStockCodes = new Set(profInfo.value.assets.map(asset => asset.stock_code));
    // 过滤出买入动作，并标记是“买入”还是“加仓”
    return profInfo.value.position_plan.actions
        .filter(a => a.action === 'buy')
        .map(action => {
            // 检查当前持仓中是否包含这只股票
            const isHeld = heldStockCodes.has(action.stock_code);
            // 给对象添加一个新属性，用于模板显示
            return {
                ...action,
                displayType: isHeld ? 'add' : 'buy' // 'add'代表加仓, 'buy'代表新建仓
            };
        });
});
const holdActions = computed(() =>
    profInfo.value?.position_plan?.actions?.filter(a => a.action === 'hold') || []
);
const sellActions = computed(() =>
    profInfo.value?.position_plan?.actions?.filter(a => a.action === 'sell') || []
);

// 获取单个股票的持仓市值
const getMarketValue = (asset) => {
    return (asset.position_size || 0) * (asset.position_price || 0);
};

const getUnrealizedPnL = (asset) => {
    if (!asset.cost_price || !asset.position_price || !asset.position_size) return 0;
    return (asset.position_price - asset.cost_price) * asset.position_size;
};

const getPnLPct = (asset) => {
    if (!asset.cost_price || asset.cost_price === 0) return 0;
    return ((asset.position_price / asset.cost_price) - 1) * 100;
};

onMounted(async () => {

    try {

        // 获取统计数据
        profSummary.value = await fetchPortfolioSummaryDaily(portfolioId);

        // 获取统计数据
        profTransaction.value = await fetchPortfolioTransaction(portfolioId);

        // 获取分析html
        // portfolio_quantstat.value = await fetchPortfolioQuantStat(portfolioId);

        // 获取策略信息
        const data = await fetchPortfolioInfo(portfolioId);
        enrichAssets(data); // 👈 关键：注入计算字段
        profInfo.value = data;
        code.value = profInfo.value.llm_prompt;
        /**
         * [
         *   {
         *     "cash_balance": 707772.5,
         *     "created_at": "2026-01-15T23:59:58",
         *     "cumulative_realized_pnl": 0.0,
         *     "daily_pnl_change": 0.0,
         *     "date": "2026-01-15",
         *     "id": 22,
         *     "portfolio_id": "1",
         *     "position_ratio": 0.6221,
         *     "total_assets": 1872931.0,
         *     "total_pnl_pct": 0.0,
         *     "total_unrealized_pnl": 0.0,
         *     "updated_at": "2026-01-15T23:59:58"
         *   },
         *
         * **/

        // 👇 2. 遍历并安全赋值
        profSummary.value.forEach(item => {
          // 确保 item 存在，且包含必要的字段
          if (item && item.date) {
            // 使用 || 0 确保如果 daily_pnl_change 为 null/undefined 时，默认为 0
            profitData.value[item.date] = item.daily_pnl_change || 0;
          }
        });

        lineOptions.value = setColorOptions();

        // 按 date 排序（确保时间顺序）
        const sortedData = [...profSummary.value].sort(
        (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
        );
        const labels = sortedData.map(item => item.date);
        const assets = sortedData.map(item => item.total_unrealized_pnl);
        const total_assets = sortedData.map(item => item.total_assets);
        const daily_pnl_change = sortedData.map(item => item.daily_pnl_change);

        // 更新 lineData.value
        lineData.value = {
            labels: labels,
            datasets: [
                {
                    label: '当日盈亏',
                    data: daily_pnl_change,
                    pointRadius: 1,
                    borderWidth: 1,
                    tension: 0.3,
                },
            ]
        };

        lineDataAssets.value = {
            labels: labels,
            datasets: [
                {
                    label: '净资产',
                    data: total_assets,
                    backgroundColor: 'rgba(255, 71, 87, 0.8)',
                    borderColor: 'rgba(255, 71, 87, 0.8)',
                    pointRadius: 1,
                    borderWidth: 2,
                    tension: 0.3,
                }
            ]
        };

    } catch (err) {
        console.error('Failed to load portfolio:', err);
    } finally {
        loading.value = false;
    }
});

// 获取操作建议（按 stock_code 索引）
const actionMap = ref({});
onMounted(() => {
    if (profInfo.value?.position_plan?.actions) {
        const map = {};
        profInfo.value.position_plan.actions.forEach((act) => {
            map[act.stock_code] = act;
        });
        actionMap.value = map;
    }
});

const items = [
    {
        label: '编辑模型prompt',
        command: () => {
            modal_visible.value = true;
        }
    }
];

async function updatePortfolioPrompt() {
    try {
        await axios.put(`/api/v1/portfolio/${encodeURIComponent(portfolioId)}`, {
            llm_prompt: code.value,
        });
        showSuccess('编辑模型prompt成功');
    } catch (error) {
        let message = '操作失败，请重试';
        if (axios.isAxiosError(error)) {
            if (error.response) {
                const { status, data } = error.response;
                console.error('HTTP 错误:', status, data);
                if (status === 404) {
                    message = '数据不存在';
                }
                // 可继续扩展其他业务状态码
            } else if (error.request) {
                message = '网络连接失败，请检查网络后重试';
            } else {
                console.error('请求配置错误:', error.message);
                message = '请求出错，请联系管理员';
            }
        } else {
            console.error('未知错误:', error);
            message = '发生未知错误';
        }
        showError(message);
    }

}

const showDcfDrawer = function () {
    // 分析数据
    loading.value = true;
    axios.get(`/api/v1/portfolio_quantstat/${portfolioId}`).then(response => {
        loading.value = false;
        portfolio_quantstat.value = response.data;
        dcf_research_report_drawer.value = true;
    });
}

</script>

<template>

    <Drawer
        v-model:visible="dcf_research_report_drawer"
        header="量化策略绩效报告"
        position="right"
        class="!w-full md:!w-300 lg:!w-[89rem]"
        :footer="false"
        body-class="p-0"
    >
        <!-- iframe 替代 v-html，彻底隔离样式 -->
        <iframe
            v-if="portfolio_quantstat"
            :srcdoc="portfolio_quantstat"
            class="w-full h-full border-0"
            sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
            title="量化报告"
        />
        <!-- 无数据时的占位 -->
        <div v-else class="flex items-center justify-center h-full text-gray-400">
            暂无报告数据
        </div>
    </Drawer>

    <Dialog v-model:visible="modal_visible" modal header="编辑模型Prompt" style="width: 950px;">
        <div class="flex items-center gap-4 mb-4">
            <MarkdownEditor
              v-model="code"
              language="markdown"
              theme="vs-dark"
              :options="editorOptions"
              :closable="true"
              :dismissableMask="true"
              @editorDidMount="handleEditorDidMount"
            />
        </div>
        <div class="flex justify-end gap-2">
            <Button type="button" label="取消" severity="secondary" @click="modal_visible=false"></Button>
            <Button type="button" label="保存" @click="modal_visible=false;updatePortfolioPrompt();"></Button>
        </div>
    </Dialog>

    <div class="card mx-auto relative" style="padding-top: 20px;">

        <!-- 右上角操作按钮 -->
        <div class="absolute top-8 right-8">
            <Button label="QuantStat" size="small" class="mr-2" @click="showDcfDrawer()" :loading="loading"></Button>
            <SplitButton label="操作" :model="items" severity="secondary" />
        </div>

        <!-- 标题 -->
        <h1 class="text-2xl font-bold mb-3 text-gray-800">
            {{ profInfo?.name || '加载中...' }}
        </h1>

        <div class="text-sm text-gray-500 mb-3">
            持仓风格：{{ profInfo?.desc || '加载中...' }}
        </div>

        <div class="text-sm text-gray-500 mb-3" v-if="profInfo?.llm_setting">大模型版本：{{ profInfo?.llm_setting.model || '加载中...' }}</div>

        <!-- 组合概览卡片 -->
        <div v-if="profInfo" class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">

            <Card>
                <template #title>总资产</template>
                <template #content >
                    <div class="text-xl font-semibold text-blue-700 font-mono">
                        {{ formatCurrency(profInfo.summary?.total_assets) }}
                    </div>
                    <div class="text-xs text-gray-500 mt-1">股票市值 + 现金</div>
                </template>
            </Card>
            <Card>
                <template #title>可用现金</template>
                <template #content>
                    <div class="text-xl font-semibold text-green-700 font-mono">
                        {{ formatCurrency(profInfo.current_cash) }}
                    </div>
                    <div class="text-xs text-gray-500 mt-1">可用于买入的现金资产</div>
                </template>
            </Card>
            <Card>
              <template #title>仓位</template>
              <template #content>
                <div class="text-xl font-semibold text-purple-700 font-mono">
                  {{ (profInfo.summary?.position_ratio * 100).toFixed(2) }}%
                </div>
                <div class="text-xs text-gray-500 mt-1">股票市值 / 总资产</div>
              </template>
            </Card>
            <Card>
                <template #title>浮动盈亏</template>
                <template #content>
                    <div
                        :class="[
              'text-xl font-semibold',
              profInfo.summary?.total_unrealized_pnl < 0
                ? 'text-green-700'
                : 'text-red-500',
            ]"
                    >
                        {{ formatCurrency(profInfo.summary?.total_unrealized_pnl, true) }}
                    </div>
                    <div class="text-xs text-gray-500 mt-1">账面持仓参考盈亏</div>
                </template>
            </Card>
            <Card>
              <template #title>持仓市值</template>
              <template #content>
                <div class="text-xl font-semibold text-red-400 font-mono">
                    {{ formatCurrency(profInfo.summary?.total_assets - profInfo.current_cash) }}
                </div>
                <div class="text-xs text-gray-500 mt-1">持仓股数 * 现价</div>
              </template>
            </Card>
            <Card>
              <template #title>夏普比率</template>
              <template #content>
                <div class="text-lg font-semibold text-gray-500">
                    暂无数据
                </div>
              </template>
            </Card>
            <Card>
              <template #title>最大回撤</template>
              <template #content>
                <div class="text-lg font-semibold text-gray-500">
                    暂无数据
                </div>
              </template>
            </Card>
            <Card>
              <template #title>年化收益率</template>
              <template #content>
                <div class="text-lg font-semibold text-gray-500">
                    暂无数据
                </div>
              </template>
            </Card>
        </div>

        <!-- 策略说明区域 -->
        <div v-if="profInfo?.position_plan" class="mb-8 space-y-5">

            <Card>
                <template #title><b class="text-lg">市场点评</b></template>
                <template #content>
                    <p class="text-gray-700 text-sm">{{ profInfo.position_plan.market_context }}</p>
                </template>
            </Card>

            <Card>
                <template #title><b class="text-lg">交易复盘</b></template>
                <template #content>
                    <p class="text-gray-700 text-sm">{{ profInfo.position_plan.trading_review }}</p>
                </template>
            </Card>

            <Card>
                <template #title><b class="text-lg">优化建议</b></template>
                <template #content>
                    <p class="text-gray-700 text-sm">{{ profInfo.position_plan.trading_rule_adjust }}</p>
                </template>
            </Card>

<!--            <Card>-->
<!--                <template #title><b class="text-lg">收益走势</b></template>-->
<!--                <template #content>-->
<!--                    <Chart type="line" :data="lineData" :options="lineOptions" style="height: 300px"></Chart>-->
<!--                </template>-->
<!--            </Card>-->

            <Card>
                <template #title><b class="text-lg">净资产走势</b></template>
                <template #content>
                    <Chart type="line" :data="lineDataAssets" :options="lineOptions" style="height: 300px"></Chart>
                </template>
            </Card>

<!--            <Card>-->
<!--                <template #title><b class="text-lg">收益日历</b></template>-->
<!--                <template #content>-->
<!--                    <div style=" width: 400px;">-->
<!--                    <ProfitLossCalendar-->
<!--                      :profit-data="profitData"-->
<!--                      :initial-date="new Date(2026, 0, 1)"-->
<!--                    />-->
<!--                    </div>-->
<!--                </template>-->
<!--            </Card>-->

        </div>

        <!-- 操作建议摘要（按动作类型分组） -->
        <div v-if="profInfo?.position_plan?.actions" class="mb-8 space-y-6">
            <!-- 买入建议 -->
            <div v-if="buyActions.length > 0">
                <h3 class="text-lg font-semibold text-green-700 mb-2 flex items-center">
                    <i class="pi pi-plus-circle mr-2"></i> 买入计划
                </h3>
                <div class="flex flex-wrap gap-2">
                  <span
                      v-for="action in buyActions"
                      :key="`buy-${action.stock_code}`"
                      class="inline-flex items-center px-3 py-1.5 bg-green-50 border border-green-200 rounded-full text-sm text-green-800"
                  ><!-- ✅ 动态 Badge：根据是否有持仓显示不同文本 -->
                    <Badge
                        :value="action.displayType === 'add' ? '加仓' : '买入'"
                        :severity="action.displayType === 'add' ? 'warning' : 'success'"
                        class="mr-2"
                    />
                    {{ action.stock_name }}（{{ action.quantity }}股）
                    <span v-if="action.reason" class="ml-2 text-xs opacity-80">{{ action.reason }}</span>
                  </span>
                </div>
            </div>

            <!-- 持有建议 -->
            <div v-if="holdActions.length > 0">
                <h3 class="text-lg font-semibold text-blue-700 mb-2 flex items-center">
                    <i class="pi pi-eye mr-2"></i> 继续持有
                </h3>
                <div class="flex flex-wrap gap-2">
                  <span
                      v-for="action in holdActions"
                      :key="`hold-${action.stock_code}`"
                      class="inline-flex items-center px-3 py-1.5 bg-blue-50 border border-blue-200 rounded-full text-sm text-blue-800"
                  >
                    <Badge value="持有" severity="info" class="mr-2" />
                    {{ action.stock_name }}
                    <span v-if="action.reason" class="ml-2 text-xs opacity-80">{{ action.reason }}</span>
                  </span>
                </div>
            </div>

            <!-- 卖出建议（可选） -->
            <div v-if="sellActions.length > 0">
                <h3 class="text-lg font-semibold text-red-700 mb-2 flex items-center">
                    <i class="pi pi-minus-circle mr-2"></i> 卖出计划
                </h3>
                <div class="flex flex-wrap gap-2">
                  <span
                      v-for="action in sellActions"
                      :key="`sell-${action.stock_code}`"
                      class="inline-flex items-center px-3 py-1.5 bg-red-50 border border-red-200 rounded-full text-sm text-red-800"
                  >
                    <Badge value="卖出" severity="danger" class="mr-2" />
                    {{ action.stock_name }}（{{ action.quantity }}股）
                    <span v-if="action.reason" class="ml-2 text-xs opacity-80">{{ action.reason }}</span>
                  </span>
                </div>
            </div>
        </div>

        <!-- 持仓明细表格 -->
        <div v-if="profInfo && profInfo.assets.length > 0">
            <h2 class="text-xl font-semibold mb-4">持仓明细</h2>
            <p class="mb-4 text-gray-500 text-sm">每个交易日盘后更新数据，最新数据日期：{{ formatDaysAgo(profInfo.assets[0]['last_update']) }}</p>
            <DataTable
                :value="profInfo.assets"
                :rows="20"
                sortField="positionPct"
                :rowHover="true"
                :showGridlines="false"
                size="medium"
                style="font-size: 11px"
                :sortOrder="-1"
            >
                <Column field="stock_code" header="代码" style="width: 100px">
                    <template #body="slotProps">
                        <a
                            class="text-blue-600 hover:underline font-mono"
                            :href="`https://gushitong.baidu.com/stock/ab-${slotProps.data.stock_code}`"
                            target="_blank"
                        >{{ slotProps.data.stock_code }}</a>
                    </template>
                </Column>

                <Column field="name" header="名称" style="width: 140px">
                    <template #body="slotProps">
                        {{ slotProps.data.name }}
                    </template>
                </Column>

                <Column field="position_size" header="持仓量" style="width: 100px" sortable>
                    <template #body="slotProps">
                        <span>{{ slotProps.data.position_size?.toLocaleString() || '—' }}</span>
                    </template>
                </Column>

                <!-- ✅ 新增：仓位占比 -->
                <Column field="positionPct" header="仓位占比" style="width: 100px" sortable>
                    <template #body="slotProps">
                        <span>{{ slotProps.data.positionPct.toFixed(2) }}%</span>
                    </template>
                </Column>

                <!-- ✅ 新增：持仓市值 -->
                <Column header="持仓市值" style="width: 120px">
                    <template #body="slotProps">
                        <span>{{ formatCurrency(getMarketValue(slotProps.data)) }}</span>
                    </template>
                </Column>

                <Column field="cost_price" header="成本价" style="width: 100px">
                    <template #body="slotProps">
                        <span>{{ slotProps.data.cost_price?.toFixed(3) || '—' }}</span>
                    </template>
                </Column>

                <Column field="position_price" header="收盘价" style="width: 100px">
                    <template #body="slotProps">
                        <span>{{ slotProps.data.position_price?.toFixed(3) || '—' }}</span>
                    </template>
                </Column>

                <Column field="pnl" header="浮动盈亏" style="width: 120px" sortable>
                    <template #body="slotProps">
                  <span
                     
                      :class="{
                      'text-red-500': getUnrealizedPnL(slotProps.data) > 0,
                      'text-green-600': getUnrealizedPnL(slotProps.data) < 0,
                    }"
                  >
                    {{ formatCurrency(getUnrealizedPnL(slotProps.data), true) }}
                  </span>
                    </template>
                </Column>

                <Column header="盈亏%" style="width: 100px">
                    <template #body="slotProps">
                  <span
                     
                      :class="{
                      'text-red-500': getPnLPct(slotProps.data) > 0,
                      'text-green-600': getPnLPct(slotProps.data) < 0,
                    }"
                  >
                    {{ getPnLPct(slotProps.data)?.toFixed(2) || '—' }}%
                  </span>
                    </template>
                </Column>

                <Column header="最新盈亏" style="width: 100px">
                    <template #body="slotProps">
                      <span
                         
                          :class="{
                          'text-red-500': slotProps.data.dailyChange > 0,
                          'text-green-600': slotProps.data.dailyChange < 0,
                        }"
                      >
                        {{ formatCurrency(slotProps.data.dailyChange, true) }}
                      </span>
                    </template>
                </Column>

                <Column header="持仓时长" style="width: 100px">
                    <template #body="slotProps">
                        <span>
                            {{ formatHoldingDuration(slotProps.data.create_time) }}
                        </span>
                    </template>
                </Column>
            </DataTable>
        </div>

        <!-- 交易记录 -->
        <div v-if="profInfo && profInfo.assets.length > 0" class="mt-8">
            <h2 class="text-xl font-semibold mb-4">交易记录</h2>
            <p class="mb-4 text-gray-500 text-sm">每个交易日盘后更新数据，最新数据日期：{{ formatDaysAgo(profInfo.assets[0]['last_update']) }}</p>
            <DataTable
                :value="profTransaction"
                :paginator="true"
                :rows="15"
                sortField="positionPct"
                size="medium"
                style="font-size: 11px"
                :rowHover="true"
                :showGridlines="false"
                :sortOrder="-1"
            >
                <Column field="code" header="代码" style="width: 100px">
                    <template #body="slotProps">
                        <a
                            class="text-blue-600 hover:underline font-mono"
                            :href="`https://gushitong.baidu.com/stock/ab-${slotProps.data.code}`"
                            target="_blank"
                        >{{ slotProps.data.code }}</a>
                    </template>
                </Column>

                <Column field="name" header="名称" style="width: 140px">
                    <template #body="slotProps">
                        {{ slotProps.data.name }}
                    </template>
                </Column>

                <Column field="name" header="操作">
                    <template #body="slotProps">
                        {{ slotProps.data.action }}
                    </template>
                </Column>

                <Column field="name" header="成交价">
                    <template #body="slotProps">
                        <span>{{ formatCurrency(slotProps.data.price, false, 3) }}</span>
                    </template>
                </Column>

                <Column field="name" header="数量">
                    <template #body="slotProps">
                        <span>{{ slotProps.data.qty }}</span>
                    </template>
                </Column>

                <Column field="name" header="金额">
                    <template #body="slotProps">
                        <span>{{ formatCurrency(slotProps.data.amount) }}</span>
                    </template>
                </Column>

                <Column field="name" header="实现盈亏">
                    <template #body="slotProps">
                        <span
                           
                            :class="{
                              'text-red-500': slotProps.data.realized_pnl > 0,
                              'text-green-600': slotProps.data.realized_pnl < 0,
                              }"
                        >
                            {{ formatCurrency(slotProps.data.realized_pnl, true) }}
                        </span>
                    </template>
                </Column>

                <Column field="name" header="时间">
                    <template #body="slotProps">
                        {{ formatDaysAgo(slotProps.data.created_at) }}
                    </template>
                </Column>


            </DataTable>
        </div>

        <!-- 加载状态 -->
        <div v-else-if="loading" class="text-center py-10 text-gray-500">加载中...</div>

        <!-- 错误状态 -->
        <div v-else class="text-center py-10 text-red-500">组合数据加载失败</div>


    </div>

</template>

<style scoped>

</style>
