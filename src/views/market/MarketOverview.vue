<script setup lang="ts">
import {ref, onMounted, computed} from 'vue'
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import axios from "axios";
import ProgressBar200p from "@/components/ProgressBar200p.vue";

const indices_name = ref({
    '000001': '上证指数',
    '399001': '深证成指',
    '399006': '创业板指',
    '000688': '科创50',
    '000692': '科创200',
    '000300': '沪深300'
})

const index_last_tick = ref([])

// 板块数据
const sectors = ref([])

// ========================
// 两市成交额图（柱状图/面积图）
// ========================
const turnoverData = ref({
    labels: ['12/02', '12/03', '12/04', '12/05', '12/06', '12/09', '12/10'],
    datasets: [
        {
            label: '成交额（亿元）',
            data: [18542, 19021, 17896, 21034, 19875, 20321, 21560],
            backgroundColor: 'rgba(59,130,246,0.6)',
            borderColor: '#3b82f6',
            borderWidth: 1,
            borderRadius: 4
        }
    ]
})

const turnoverOptions = ref({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {display: false},
        tooltip: {mode: 'index'}
    },
    scales: {
        x: {grid: {display: false}},
        y: {beginAtZero: false, grid: {color: '#e5e7eb'}}
    }
})

// ========================
// 沪深涨跌分布（柱状图） - 修改为专业柱状图
// ========================
const distributionData = ref({
    labels: ['<-5%', '-5%~-3%', '-3%~-1%', '-1%~0%', '0%~1%', '1%~3%', '3%~5%', '>5%'],
    datasets: [
        {
            label: '家数',
            data: [80, 200, 500, 1000, 1200, 600, 300, 120],
            // 下跌区间（前4个）用绿色系，上涨区间（后4个）用红色系
            backgroundColor: [
                '#14532d', // <-5%
                '#166534', // -5%~-3%
                '#22c55e', // -3%~-1%
                '#4ade80', // -1%~0%
                '#fca5a5', // 0%~1%
                '#ef4444', // 1%~3%
                '#dc2626', // 3%~5%
                '#b91c1c'  // >5%
            ],
            borderRadius: 4,
            borderSkipped: false
        }
    ]
})

const distributionOptions = ref({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            display: false // 单条数据，不显示图例更简洁
        },
        tooltip: {
            callbacks: {
                label: (context: any) => {
                    const total = context.dataset.data.reduce((a: number, b: number) => a + b, 0)
                    const value = context.parsed.y
                    const percent = ((value / total) * 100).toFixed(1)
                    return `${context.label}: ${value} 家 (${percent}%)`
                }
            }
        }
    },
    scales: {
        x: {
            grid: {display: false},
            ticks: {
                font: {size: 11},
                maxRotation: 45
            }
        },
        y: {
            beginAtZero: true,
            grid: {color: '#e5e7eb'},
            title: {
                display: true,
                text: '家数'
            }
        }
    }
})

// ========================
// 辅助函数
// ========================
const getChangeColor = (val: number) => val >= 0 ? '#ef4444' : '#10b981'
const formatSign = (val: number) => val > 0 ? `+${val.toFixed(2)}` : val.toFixed(2)

// ================= 生命周期 =================
onMounted(async () => {
    const res = await axios.get('/api/v1/market/sectors', {
        params: {sector_type: 'sw2'}
    });
    sectors.value = res.data;
    // 获取指数行情
    const res2 = await axios.get('/api/v1/index/last_tick');
    index_last_tick.value = res2.data;
    index_last_tick.value.forEach((item, idx) => {
        // 对每个项做自定义处理，比如格式化时间、加字段
        item.formatTime = new Date(item.tick_time).toLocaleString()
        item.change = item.lastPrice - item.lastClose
        item.changePercent = item.change / item.lastClose * 100
    })
});

// 工具方法
const getPctColorClass = (value: number) => {
    if (value > 0) return 'text-up'
    if (value < 0) return 'text-down'
    return 'text-flat'
}

</script>

<template>
    <div class="dashboard-container">
        <!-- 顶部标题栏 -->
        <div class="header">
            <h1 class="title">沪深大盘监控</h1>
            <span class="update-time">最后更新: {{ new Date().toLocaleTimeString() }}</span>
        </div>

        <!-- 指数卡片行 (6个，自动折行) -->
        <div class="indices-row">
            <Card v-for="item in index_last_tick" :key="item.code" class="index-card">
                <template #content>
                    <div class="card-content">
                        <div class="index-name">{{ indices_name[item.index_code] }}</div>
                        <div class="index-code">{{ item.index_code }}</div>
                        <div class="index-price">{{ item.lastPrice.toFixed(2) }}</div>
                        <div class="index-change" :style="{ color: getChangeColor(item.change) }">
                            <span>{{ formatSign(item.change) }}</span>
                            <span class="change-percent">{{ formatSign(item.changePercent) }}%</span>
                        </div>
                    </div>
                </template>
            </Card>
        </div>

        <!-- {"avg_turnover": 0.0, "bottom_stock": "浦发银行", "bottom_stock_pct": -0.89, "change_pct": 0.17, "down_count": 18, "flat_count": 4, "sector_name": "银行", "stock_count": 42, "top_stock": "重庆银行", "top_stock_pct": 3.71, "total_market_cap": 0.0, "total_trade_amount": 241.22, "up_count": 20, "up_down_ratio": 1.11} -->
        <Card class="chart-card sector-card-custom">
            <template #title> 板块涨跌幅</template>
            <template #content>
                <DataTable
                    :value="sectors"
                    stripedRows
                    size="small"
                    class="sector-table"
                    :sortField="'change_pct'"
                    :sortOrder="-1"
                    sortMode="single"
                    removableSort
                    :rowHover="true"
                >
                    <!-- 板块名称列 -->
                    <Column field="sector_name" header="板块" :filter="true" filterPlaceholder="搜索板块"/>
                    <!-- 领涨股列 -->
                    <Column field="top_stock" header="领涨股">
                        <template #body="{ data }">
                            <span class="text-up">
                              {{ data.top_stock || '--' }}
                              <span class="text-sm">({{ data.top_stock_pct?.toFixed(2) }}%)</span>
                            </span>
                        </template>
                    </Column>
                    <!-- 领跌股列（新增） -->
                    <Column field="bottom_stock" header="领跌股">
                        <template #body="{ data }">
                            <span class="text-down">
                              {{ data.bottom_stock || '--' }}
                              <span class="text-sm">({{ data.bottom_stock_pct?.toFixed(2) }}%)</span>
                            </span>
                        </template>
                    </Column>
                    <!-- 涨跌幅列（带进度条+箭头） -->
                    <Column field="change_pct" header="涨跌幅" style="min-width: 120px;" sortable>
                        <template #body="{ data }">
                            <ProgressBar200p :barHeight="20" :value="data.change_pct.toFixed(2)" :times="10" readonly/>
                        </template>
                    </Column>
                    <!-- 涨跌家数列（新增） -->
                    <Column field="up_count" header="上涨/平盘/下跌" sortable>
                        <template #body="{ data }">
                            <span class="text-up">{{ data.up_count }}</span> /
                            <span class="text-flat">{{ data.flat_count }}</span> /
                            <span class="text-down">{{ data.down_count }}</span>
                        </template>
                    </Column>
                    <!-- 总成交额列（新增） -->
                    <Column
                        field="total_trade_amount"
                        header="总成交额"
                        sortable
                        style="min-width: 100px"
                    >
                        <template #body="{ data }">
                            {{ data.total_trade_amount ? `${data.total_trade_amount.toFixed(1)} 亿` : '--' }}
                        </template>
                    </Column>
                    <!-- 涨跌比列（新增，小屏幕可隐藏） -->
                    <Column
                        field="up_down_ratio"
                        header="涨跌比"
                        sortable
                        class="hidden md:table-cell"
                    >
                        <template #body="{ data }">
                            <span :class="getPctColorClass(data.up_down_ratio - 1)">
                              {{ data.up_down_ratio?.toFixed(2) || '--' }}
                            </span>
                        </template>
                    </Column>
                    <!-- 空状态 -->
                    <template #empty>
                        <div class="py-8 text-center text-gray-500">暂无板块数据</div>
                    </template>
                </DataTable>
            </template>
        </Card>

        <!-- 图表行2：板块涨跌幅 + 两市成交额 -->
        <!--        <div class="grid-row">-->

        <!--            <Card class="chart-card">-->
        <!--                <template #title> 两市成交额</template>-->
        <!--                <template #content>-->
        <!--                    <div class="chart-wrapper">-->
        <!--                        <Chart type="bar" :data="turnoverData" :options="turnoverOptions"/>-->
        <!--                    </div>-->
        <!--                </template>-->
        <!--            </Card>-->

        <!--        </div>-->

    </div>
</template>

<style scoped lang="scss">

// 全局容器
.dashboard-container {
    padding: 1.5rem;
    background: #f5f7fb;
    min-height: 100vh;
}

// 头部
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;

    .title {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1e293b;
        margin: 0;
    }

    .update-time {
        color: #64748b;
        font-size: 0.9rem;
    }
}

// 指数卡片行（使用flex-wrap让六个卡片自动折行）
.indices-row {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 1.5rem;

    .index-card {
        flex: 1 1 calc(16.66% - 1rem); // 6个一行，留出间距
        min-width: 160px;
        transition: all 0.2s ease;

        &:hover {
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }
    }
}

.card-content {
    display: flex;
    flex-direction: column;
    align-items: center;

    .index-name {
        font-size: 1rem;
        color: #475569;
        font-weight: 600;
        white-space: nowrap;
    }

    .index-code {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-top: 0.2rem;
    }

    .index-price {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0f172a;
        margin: 0.5rem 0;
        line-height: 1;
    }

    .index-change {
        display: flex;
        gap: 0.5rem;
        font-size: 0.95rem;

        .change-percent {
            color: inherit;
        }
    }
}

// 图表行（两栏布局）
.grid-row {
    display: flex;
    gap: 1.5rem;
    align-items: stretch; /* 保持主轴拉伸 */

    // 统一接管所有图表卡片的尺寸流
    .chart-card,
    .distribution-card,
    .stocks-card,
    .sector-card-custom {
        flex: 1;
        height: 100%; // 关键：允许父级 align-items: stretch 锁定实际高度
        border-radius: 5px;

        // 覆盖 PrimeVue Card 默认盒模型，让内容区参与垂直分配
        .p-card-body {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden; // 防止内容溢出导致卡片撑破
        }

        // 图表包装器：占满剩余空间，并提供保底高度防止加载期抖动
        .chart-wrapper {
            flex: 1;
            min-height: 195px;
            height: 100%;
            position: relative;
        }
    }
}

// 图表容器
.chart-wrapper {
    position: relative;
}

// 涨跌分布卡片 - 柱状图样式（无需额外改动，继承父类即可）
.distribution-card {
    background: #fff;
    margin-bottom: 1.5rem;
}

// 板块表格
.sector-table {
    ::v-deep(.p-datatable-wrapper) {
        max-height: 280px;
        overflow-y: auto;
    }

    td, th {
        padding: 0.4rem 0.5rem;
        font-size: 0.9rem;
    }
}

// 个股表格卡片
.stocks-card {
    .stocks-table {
        td, th {
            padding: 0.4rem 0.5rem;
            font-size: 0.9rem;
        }
    }
}

@media (max-width: 1200px) {
    .grid-row {
        flex-direction: column;

        & > :first-child {
            order: -1;
        }

        /* 可选：让图表始终置顶 */
    }
}

@media (max-width: 768px) {
    .indices-row .index-card {
        flex: 1 1 calc(50% - 1rem);
    }
}

.sector-table :deep(.p-datatable-header) {
    background: var(--header-bg);
    border-bottom: 1px solid var(--border-color);
    font-weight: 600;
}

.sector-table :deep(.p-column-header) {
    text-align: left;
    padding: 10px 8px;
    background: var(--header-bg);
}

.sector-table :deep(.p-datatable-tbody > tr > td) {
    padding: 10px 8px;
    border-bottom: 1px solid var(--border-color);
}

/* 涨跌幅进度条样式 */
.pct-bar {
    width: 60px;
    height: 4px;
    background: #eee;
    display: inline-block;
    vertical-align: middle;
    position: relative;
    border-radius: 2px;
    overflow: hidden;
}

.pct-bar-inner {
    position: absolute;
    top: 0;
    height: 100%;
    border-radius: 2px;
}

.pct-bar-inner.up {
    left: 50%;
    background: var(--color-up);
}

.pct-bar-inner.down {
    right: 50%;
    background: var(--color-down);
}

/* 颜色工具类 */
.text-up {
    color: var(--color-up);
}

.text-down {
    color: var(--color-down);
}

.text-flat {
    color: var(--color-flat);
}

</style>