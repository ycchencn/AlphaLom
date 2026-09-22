<script setup>
import {computed, onBeforeUnmount, onMounted, ref, watch} from 'vue';
import axios from 'axios';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Tag from 'primevue/tag';
import {useToast} from 'primevue/usetoast';
import BullishBearishIndicator from '@/components/BullishBearishIndicator.vue';
import {formatDaysAgo} from '@/utils/function.js';

// ================= 固定话题 =================
// 话题即搜索关键词，作为**代码内的固定配置**维护，不在页面上增删改。
// 第一个是「全部新闻」哨兵（不带 keyword 查询），其余按顺序展示。
// ⚠️ 旧实现把这份清单写成 MOCK_TOPICS 并允许前端增删改，但没有任何后端接口承接，
//    刷新即丢；且其中两个话题共用了 id=15，:key 冲突会导致编辑/删除串行。现已移除。
const ALL_NEWS_TOPIC = '全部新闻';
const FIXED_TOPICS = [
    ALL_NEWS_TOPIC,
    '特朗普',
    '马斯克',
    '美联储',
    '央行',
    '证监会',
    '货币政策',
    '业绩披露',
    '商业航天',
    '半导体',
    '机器人',
    'CPO',
    'PCB',
    '芯片',
    '创新药',
    '黄金',
];

// ================= 状态管理 =================
const news = ref([]);
const loading = ref(false);
const activeTopic = ref(ALL_NEWS_TOPIC);

// 服务端分页状态：DataTable 的 lazy 模式由这些字段驱动
const page = ref(1);
const pageSize = ref(20);
const totalRecords = ref(0);

const toast = useToast();

// 请求竞态保护：快速切换话题时，先发出的请求可能后返回并把新列表覆盖掉。
// 每次发起请求自增一个序号，只有序号最新的响应才允许写入。
let requestSeq = 0;

// ================= 数据加载 =================
const loadNewsData = async () => {
    const seq = ++requestSeq;
    loading.value = true;
    try {
        const params = {
            page: page.value,
            page_size: pageSize.value,
        };
        // 「全部新闻」不带 keyword，但仍要显式关闭「只取已关联」过滤：
        // 否则 relation_level 为 0 / NULL 的新闻会被静默丢弃，与话题名不符。
        if (activeTopic.value !== ALL_NEWS_TOPIC) {
            params.keyword = activeTopic.value;
        }
        params.relation_level_only = false;

        const res = await axios.get('/api/v1/market/search_news', {params});
        if (seq !== requestSeq) return;   // 已有更新的请求发出，丢弃本次结果

        const data = res.data || {};
        news.value = data.items || [];
        totalRecords.value = data.total || 0;
    } catch (e) {
        if (seq !== requestSeq) return;
        news.value = [];
        totalRecords.value = 0;
        toast.add({
            severity: 'error',
            summary: '加载失败',
            detail: '新闻数据获取失败，请稍后重试',
            life: 3000,
        });
    } finally {
        if (seq === requestSeq) loading.value = false;
    }
};

// 切换话题：回到第一页再加载
watch(activeTopic, () => {
    page.value = 1;
    loadNewsData();
});

// 翻页 / 改每页条数：DataTable lazy 模式的事件回传
const onPage = (event) => {
    page.value = event.page + 1;        // PrimeVue 的 page 从 0 开始
    pageSize.value = event.rows;
    loadNewsData();
};

// ================= 派生 =================
// search() 现在只返回本页条数 + has_more（不再为拿总数多跑一次 COUNT 全表统计）。
// 因此总条数用「已加载页数 + 是否还有更多」估算，只用于分页器显示。
const estimatedTotal = computed(() => {
    if (!totalRecords.value && !news.value.length) return 0;
    const loaded = (page.value - 1) * pageSize.value + news.value.length;
    return loaded + (news.value.length >= pageSize.value ? pageSize.value : 0);
});

// ================= 生命周期 =================
onMounted(loadNewsData);

onBeforeUnmount(() => {
    // 卸载后到达的响应不应再写状态
    requestSeq++;
});
</script>

<template>
    <div class="flex bg-gray-50 overflow-hidden">
        <!-- 左侧：固定话题导航面板 -->
        <div class="min-w-56 border-r border-gray-200 bg-white flex flex-col shadow-sm z-10">
            <div class="p-4 border-b border-gray-200 bg-gray-50">
                <h3 class="font-semibold text-base text-gray-700">话题列表</h3>
                <p class="text-xs text-gray-400 mt-1 leading-snug">固定筛选词，按摘要匹配</p>
            </div>

            <div class="flex-1 overflow-y-auto p-2 space-y-1">
                <div
                    v-for="topic in FIXED_TOPICS"
                    :key="topic"
                    class="px-3 py-2.5 rounded-md cursor-pointer truncate transition-all duration-200 hover:bg-blue-50"
                    :class="{ 'bg-blue-50 text-blue-700 font-semibold border-l-4 border-blue-500': activeTopic === topic }"
                    @click="activeTopic = topic"
                >
                    {{ topic }}
                </div>
            </div>
        </div>

        <!-- 右侧：新闻数据表格 -->
        <div class="flex-1 p-4 overflow-y-auto flex flex-col bg-white">

            <DataTable
                :value="news"
                dataKey="id"
                lazy
                :paginator="true"
                :rows="pageSize"
                :totalRecords="estimatedTotal"
                :first="(page - 1) * pageSize"
                :rowHover="true"
                :loading="loading"
                :showGridlines="false"
                paginatorPosition="bottom"
                paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
                :rowsPerPageOptions="[10, 20, 50]"
                currentPageReportTemplate="第 {first} - {last} 条"
                @page="onPage"
            >
                <Column field="digest" header="新闻详情">
                    <template #body="{ data }">
                        <div class="news-item">
                            <p class="news-digest leading-relaxed">
                                <Tag v-if="data.news_type === 'report'" severity="danger" class="mr-1">研</Tag>{{ data.digest }}
                            </p>

                            <div class="news-time text-gray-500 text-xs mb-1">
                                {{ formatDaysAgo(data.news_time) }}
                                <a v-if="data.url" :href="data.url" target="_blank"
                                   class="text-blue-500 hover:underline ml-2">{{ data.url }}</a>
                            </div>

                            <div v-if="data.relations_stocks?.length" class="mt-2 text-sm">
                                <strong class="text-gray-600">关联股票：</strong>
                                <span class="ml-1 inline-flex flex-wrap gap-x-2">
                                  <a
                                      v-for="stock in data.relations_stocks"
                                      :key="stock.code"
                                      class="text-blue-600 hover:underline cursor-pointer"
                                      :href="'https://gushitong.baidu.com/stock/ab-' + stock.code"
                                      target="_blank"
                                  >
                                    {{ stock.code }}({{ stock.name }})
                                  </a>
                                </span>
                            </div>

                            <div v-if="data.tags?.length" class="mt-1.5 text-sm">
                                <strong class="text-gray-600">标签：</strong>
                                <span v-for="tag in data.tags" :key="tag" class="tag-badge ml-1">{{ tag }}</span>
                            </div>

                            <div v-if="data.bullish_level !== 0" class="mt-2">
                                <BullishBearishIndicator :value="data.bullish_level" :max-segments="10"/>
                            </div>
                        </div>
                    </template>
                </Column>

                <template #empty>
                    <div class="py-8 text-center text-gray-400">
                        {{ loading ? '加载中…' : '该话题下暂无新闻' }}
                    </div>
                </template>
            </DataTable>
        </div>
    </div>
</template>

<style scoped>
.news-item {
    padding: 4px 0;
    border-bottom: 1px dashed #f3f4f6;
}

.news-item:last-child {
    border-bottom: none;
}

.news-time {
    color: #6b7280;
    font-weight: 500;
}

.news-digest {
    margin: 4px 0;
    color: #1f2937;
    /* 摘要通常较长，限制为两行，避免单条新闻撑高整页 */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.tag-badge {
    display: inline-block;
    background-color: #f3f4f6;
    border: 1px solid #e5e7eb;
    border-radius: 9999px;
    padding: 1px 8px;
    font-size: 0.75rem;
    color: #374151;
    margin-right: 4px;
}
</style>
