<script setup>
import {computed, onBeforeUnmount, onMounted, ref, watch} from 'vue';
import axios from 'axios';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Tag from 'primevue/tag';
import {useToast} from 'primevue/usetoast';
import BullishBearishIndicator from '@/components/BullishBearishIndicator.vue';
import {formatDaysAgo} from '@/utils/function.js';
import NavSidePanel from '@/components/NavSidePanel.vue';
import {store} from '@/store';

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

// 左侧话题导航面板（与股票池分组共用 NavSidePanel 组件，保证视觉一致）
const topicItems = computed(() => FIXED_TOPICS.map((t) => ({ key: t, label: t })));
function onTopicSelect(key) {
    activeTopic.value = key;
}

// ================= AI 速览（置顶卡片） =================
// 数据来自后端 job_news_digest：每小时把窗口内的新闻交给大模型，压成「前三条头条」。
// 前端只负责展示与轮询：**不自己算刷新时间、不自己传窗口**，
// 一律用后端给的 next_refresh_at —— 两边各写一份 cron 迟早会对不上。
const digest = ref(null);
const digestLoading = ref(false);
const digestRefreshing = ref(false);
const nextRefreshAt = ref(null);       // Date | null
const showHighlights = ref(false);     // 「更多」展开次要要点

const isAdmin = computed(() => store.getters.isAdmin);

// 兜底轮询上限：即便 next_refresh_at 算歪了，卡片也不会一直停在旧数据上
const DIGEST_MAX_POLL_MS = 5 * 60 * 1000;
let digestTimer = null;
let alive = true;

const loadDigest = async () => {
    // 只有首次进页面（还没有任何数据）时才显示占位，轮询刷新不闪
    digestLoading.value = digest.value === null;
    try {
        const res = await axios.get('/api/v1/market/news_digest');
        const data = res.data || {};
        digest.value = data.digest || null;
        nextRefreshAt.value = toDate(data.next_refresh_at);
    } catch (e) {
        // 速览是锦上添花：拉不到就静默保持空态，绝不弹错挡住下面的新闻流
        console.warn('新闻速览加载失败', e);
    } finally {
        digestLoading.value = false;
    }
};

// 下一次拉取时刻：优先「本轮刷新时间 + 1 分钟」（新速览刚落库就去取），
// 但不快于 1 分钟、不慢于 DIGEST_MAX_POLL_MS（防止时间口径出错导致不再刷新）。
const scheduleDigestPoll = () => {
    if (!alive) return;
    if (digestTimer) clearTimeout(digestTimer);

    let delay = DIGEST_MAX_POLL_MS;
    if (nextRefreshAt.value) {
        const untilNew = nextRefreshAt.value.getTime() + 60 * 1000 - Date.now();
        delay = untilNew > 0 ? Math.min(Math.max(untilNew, 60 * 1000), DIGEST_MAX_POLL_MS) : 60 * 1000;
    }
    digestTimer = setTimeout(async () => {
        await loadDigest();
        scheduleDigestPoll();
    }, delay);
};

// 手动重新生成（仅管理员可见）：后端有 2 分钟冷却，超频会返回 429
const refreshDigest = async () => {
    if (digestRefreshing.value) return;
    digestRefreshing.value = true;
    try {
        const res = await axios.post('/api/v1/market/news_digest/refresh');
        const data = res.data || {};
        if (data.digest) digest.value = data.digest;
        if (data.next_refresh_at) nextRefreshAt.value = toDate(data.next_refresh_at);
        toast.add({severity: 'success', summary: '已重新生成', detail: '速览已更新', life: 2500});
        scheduleDigestPoll();
    } catch (e) {
        toast.add({
            severity: 'warn',
            summary: '刷新失败',
            detail: e?.response?.data?.detail || '生成失败，请稍后再试',
            life: 4000,
        });
    } finally {
        digestRefreshing.value = false;
    }
};

// 点速览里的关键词 → 直接筛选下方新闻流（复用现成的话题筛选通道）
const filterByKeyword = (keyword) => {
    if (keyword) activeTopic.value = keyword;
};
// 「速览筛选」= 当前话题不在左侧固定清单里（说明是从关键词点进来的），给一个可清除的提示
const isDigestFilter = computed(() => !FIXED_TOPICS.includes(activeTopic.value));
const clearDigestFilter = () => {
    activeTopic.value = ALL_NEWS_TOPIC;
};

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
// 后端给的时间是 ISO 串（2026-09-29T15:30:00，北京时间无时区后缀）或已经是 Date，
// 统一收敛成 Date；解析失败返回 null，让调用方走空态而不是渲染 "Invalid Date"。
const toDate = (raw) => {
    if (!raw) return null;
    const d = raw instanceof Date ? raw : new Date(String(raw).replace(' ', 'T'));
    return Number.isNaN(d.getTime()) ? null : d;
};

const pad2 = (n) => String(n).padStart(2, '0');

// 速览生成时间，形如 09.29 15:30
const digestGeneratedText = computed(() => {
    const d = toDate(digest.value?.generated_at);
    if (!d) return '';
    return `${pad2(d.getMonth() + 1)}.${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
});

// 下一轮自动生成时间，形如 16:30（跨天时前缀「明日」）
const nextRefreshText = computed(() => {
    const d = nextRefreshAt.value;
    if (!d) return '';
    const now = new Date();
    const sameDay = d.getDate() === now.getDate() && d.getMonth() === now.getMonth();
    return `${sameDay ? '' : '明日 '}${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
});

// search() 现在只返回本页条数 + has_more（不再为拿总数多跑一次 COUNT 全表统计）。
// 因此总条数用「已加载页数 + 是否还有更多」估算，只用于分页器显示。
const estimatedTotal = computed(() => {
    if (!totalRecords.value && !news.value.length) return 0;
    const loaded = (page.value - 1) * pageSize.value + news.value.length;
    return loaded + (news.value.length >= pageSize.value ? pageSize.value : 0);
});

// ================= 生命周期 =================
onMounted(() => {
    loadNewsData();
    loadDigest();
    scheduleDigestPoll();
});

onBeforeUnmount(() => {
    // 卸载后到达的响应不应再写状态
    requestSeq++;
    // 停掉速览轮询，否则离开页面后定时器还会一直打接口
    alive = false;
    if (digestTimer) {
        clearTimeout(digestTimer);
        digestTimer = null;
    }
});
</script>

<template>
    <div class="flex bg-gray-50 overflow-hidden">
        <!-- 左侧：固定话题导航面板（与股票池分组共用 NavSidePanel 组件） -->
        <NavSidePanel
            title="话题列表"
            subtitle="固定筛选词，按摘要匹配"
            :items="topicItems"
            :activeKey="activeTopic"
            :responsive="false"
            @select="onTopicSelect"
        />

        <!-- 右侧：新闻数据表格 -->
        <div class="flex-1 p-4 overflow-y-auto flex flex-col bg-white">

            <!-- AI 速览：置顶展示前三条自动总结（后端每小时滚动生成） -->
            <div class="ai-digest">
                <div class="ai-digest-head">
                    <span class="ai-spark">AI</span>
                    <span class="ai-digest-title">AI 推荐</span>
                    <span class="ai-digest-sub">
                        {{ digest?.title || '新闻流速览' }}<template v-if="digestGeneratedText">（{{ digestGeneratedText }}）</template>
                    </span>
                    <span class="ai-digest-actions">
                        <span v-if="nextRefreshText" class="ai-next">下一轮 {{ nextRefreshText }}</span>
                        <button
                            v-if="digest?.highlights?.length"
                            class="ai-btn ai-btn-plain"
                            @click="showHighlights = !showHighlights"
                        >
                            {{ showHighlights ? '收起' : '更多' }}
                            <i :class="showHighlights ? 'pi pi-angle-up' : 'pi pi-angle-down'"></i>
                        </button>
                        <button
                            v-if="isAdmin"
                            class="ai-btn"
                            :disabled="digestRefreshing"
                            :title="digestRefreshing ? '生成中…' : '立即重新生成（会消耗大模型额度）'"
                            @click="refreshDigest"
                        >
                            <i :class="digestRefreshing ? 'pi pi-spin pi-spinner' : 'pi pi-refresh'"></i>
                            {{ digestRefreshing ? '生成中' : '刷新' }}
                        </button>
                    </span>
                </div>

                <div v-if="digestLoading" class="ai-empty">正在生成速览…</div>

                <template v-else-if="digest">
                    <div v-for="(h, hi) in digest.headlines" :key="hi" class="ai-row">
                        <span class="ai-topic">{{ h.topic }}</span>
                        <div class="ai-body">
                            <div class="ai-keywords">
                                <template v-for="(kw, ki) in h.keywords" :key="kw + ki">
                                    <span v-if="ki" class="ai-sep">；</span>
                                    <button class="ai-kw" :title="'筛选含「' + kw + '」的新闻'" @click="filterByKeyword(kw)">{{ kw }}</button>
                                </template>
                                <span v-if="!h.keywords?.length" class="ai-kw-empty">—</span>
                            </div>
                            <div v-if="h.summary" class="ai-summary">{{ h.summary }}</div>
                        </div>
                    </div>

                    <div v-if="showHighlights && digest.highlights?.length" class="ai-highlights">
                        <div v-for="(item, i) in digest.highlights" :key="i" class="ai-highlight">
                            <span class="ai-dot"></span>{{ item }}
                        </div>
                    </div>

                    <div class="ai-foot">
                        基于近 {{ digest.news_count }} 条新闻自动生成
                        <template v-if="digest.model"> · {{ digest.model }}</template>
                        <template v-if="digest.trigger_type === 'manual'"> · 手动刷新</template>
                    </div>
                </template>

                <div v-else class="ai-empty">
                    暂无速览<template v-if="nextRefreshText">，下一轮 {{ nextRefreshText }} 自动生成</template>
                </div>
            </div>

            <!-- 从速览关键词点进来的筛选态：左侧固定话题里没有这个词，给一个可清除的提示 -->
            <div v-if="isDigestFilter" class="ai-filter-bar">
                <span>速览筛选：<b>{{ activeTopic }}</b></span>
                <button class="ai-btn ai-btn-plain" @click="clearDigestFilter">
                    清除<i class="pi pi-times"></i>
                </button>
            </div>

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

/* ================= AI 速览置顶卡片 =================
   配色沿用站内「暖色提示」基调（与恐惧贪婪卡片的暖底一致），
   刻意不加阴影和圆角放大，避免它抢走下面新闻流的注意力。 */
.ai-digest {
    border: 1px solid #f0e2d8;
    background: linear-gradient(180deg, #fffaf5 0%, #ffffff 65%);
    border-radius: 10px;
    padding: 10px 12px 8px;
    margin-bottom: 12px;
}

.ai-digest-head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    padding-bottom: 8px;
    border-bottom: 1px dashed #f3e4d8;
}

.ai-spark {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 18px;
    padding: 0 6px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: #fff;
    background: linear-gradient(135deg, #ff7a45, #f5222d);
}

.ai-digest-title {
    font-size: 1rem;
    font-weight: 700;
    color: #1f2937;
}

.ai-digest-sub {
    font-size: 0.85rem;
    color: #8c8c8c;
}

.ai-digest-actions {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
}

.ai-next {
    font-size: 0.75rem;
    color: #bfbfbf;
}

.ai-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    border: 1px solid #ffd8bf;
    border-radius: 4px;
    background: #fff7f0;
    color: #d4380d;
    font-size: 0.75rem;
    line-height: 18px;
    cursor: pointer;
}

.ai-btn:hover:not(:disabled) {
    background: #fff1e6;
}

.ai-btn:disabled {
    opacity: 0.6;
    cursor: default;
}

.ai-btn-plain {
    border-color: #e5e7eb;
    background: #fff;
    color: #6b7280;
}

.ai-btn-plain:hover {
    background: #f9fafb;
}

.ai-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 6px 0;
}

.ai-topic {
    flex: none;
    margin-top: 1px;
    padding: 0 5px;
    border: 1px solid #ffccc7;
    border-radius: 3px;
    background: #fff2f0;
    color: #cf1322;
    font-size: 0.75rem;
    font-weight: 600;
    line-height: 18px;
}

.ai-body {
    flex: 1;
    min-width: 0;
}

.ai-keywords {
    font-size: 1rem;
    line-height: 20px;
    color: #1f2937;
}

.ai-sep {
    margin: 0 1px;
    color: #d9d9d9;
}

/* 关键词可点：点一下筛选下方新闻流，故用链接色区分于普通正文 */
.ai-kw {
    padding: 0;
    border: none;
    background: none;
    color: #2563eb;
    font-size: 1rem;
    cursor: pointer;
}

.ai-kw:hover {
    color: #f5222d;
    text-decoration: underline;
}

.ai-kw-empty {
    color: #d9d9d9;
}

.ai-summary {
    margin-top: 2px;
    font-size: 0.85rem;
    line-height: 18px;
    color: #8c8c8c;
}

.ai-highlights {
    margin-top: 4px;
    padding-top: 6px;
    border-top: 1px dashed #f3e4d8;
}

.ai-highlight {
    display: flex;
    gap: 6px;
    font-size: 0.85rem;
    line-height: 20px;
    color: #595959;
}

.ai-dot {
    flex: none;
    width: 4px;
    height: 4px;
    margin-top: 8px;
    border-radius: 50%;
    background: #ffbb96;
}

.ai-foot {
    margin-top: 6px;
    font-size: 0.75rem;
    color: #bfbfbf;
}

.ai-empty {
    padding: 10px 0 6px;
    font-size: 0.85rem;
    color: #bfbfbf;
}

.ai-filter-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    padding: 4px 8px;
    border: 1px solid #e0e7ff;
    border-radius: 4px;
    background: #f6f8ff;
    font-size: 0.85rem;
    color: #4b5563;
}
</style>
