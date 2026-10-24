<script setup>

/**
 * 投资组合 → 公司公告
 *
 * 数据来源：后端本地副本 `stock_announcements`（由定时任务从巨潮资讯网经 DataBull
 * 增量拉取），范围 = **当前用户的股票池**。
 *
 * 三个需要保持的口径：
 * 1. 分类标签是后端按标题关键词推断的，**不是巨潮原始 category 码**（码表不可得），
 *    所以不要在前端再写码→中文的映射。
 * 2. 上游覆盖不完整（部分 A 股恒为 0 条），「空」不等于「失败」：
 *    后端用 empty_reason / coverage 区分，这里按不同文案展示。
 * 3. 分类标签上的数字由后端在「忽略 category 筛选」的条件下算，点选分类后其它标签
 *    仍然可用 —— 前端不要自己在前端重算，否则数字会和列表条数打架。
 */

import { computed, onMounted, ref, watch } from 'vue';
import axios from 'axios';
import { useNotification } from '@/composables/useNotification';
import AnnouncementAiDrawer from '@/components/announcement/AnnouncementAiDrawer.vue';
import AnnouncementPdfDrawer from '@/components/announcement/AnnouncementPdfDrawer.vue';

defineOptions({ name: 'CompanyAnnouncements' });

const { showSuccess, showError } = useNotification();

const loading = ref(false);
const items = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(25);

// 筛选条件
const activeCategory = ref('');     // '' = 全部
const keyword = ref('');
const symbolFilter = ref('');
const days = ref(30);               // 0 = 不限
const dateRange = ref(null);        // [Date, Date] | null

// 后端返回的统计数据
const categories = ref([]);
const categoryCounts = ref({});
const coverage = ref({ pool_total: 0, non_a_share: 0, a_share_total: 0, with_data: 0, without_data: 0 });
const dataAsOf = ref(null);
const syncInfo = ref({ synced: 0, never_synced: 0, failed: 0, last_sync_time: null, errors: [] });
const emptyReason = ref('');
// 今天发布的公告条数（后端按 CURDATE 统计）。⚠️ 口径与分类标签数字一致：
// 忽略分类与日期区间筛选，只跟随关键词/单只票，所以**不等于当前列表条数**。
const todayCount = ref(0);

// 股票池（筛选下拉）
const symbolOptions = ref([]);

const syncing = ref(false);

// ---- AI 解读抽屉 ----
// 抽屉自己管流式请求与多轮对话，列表只负责「打开哪一条」和「打开后标记已解读」。
const aiVisible = ref(false);
const aiTarget = ref(null);

function openAiDrawer(row) {
    aiTarget.value = row;
    aiVisible.value = true;
}

// 抽屉完成首轮解读后回传 id，只改这一行的标记（不整页重拉，避免打断阅读）
function onAiInterpreted(id) {
    const row = items.value.find((it) => it.id === id);
    if (row) row.has_ai_summary = true;
}

// ---- 原文阅读抽屉 ----
// 点标题或「阅读」都在抽屉里看 PDF（同源代理，不再是新开标签页去巨潮）。
// 抽屉自己负责拉流、进度、失败态与 blob 释放，列表只传当前行。
const pdfVisible = ref(false);
const pdfTarget = ref(null);

function openPdfDrawer(row) {
    if (!row?.pdf_url) return;
    pdfTarget.value = row;
    pdfVisible.value = true;
}

const dayOptions = [
    { label: '近 7 天', value: 7 },
    { label: '近 30 天', value: 30 },
    { label: '近 90 天', value: 90 },
    { label: '不限', value: 0 },
];

// YYYY-MM-DD（用本地日期拼，不能走 toISOString —— 会按 UTC 偏移一天）
function fmtDate(d) {
    if (!d) return '';
    const date = d instanceof Date ? d : new Date(d);
    if (Number.isNaN(date.getTime())) return '';
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

function formatPdfSize(kb) {
    const n = Number(kb);
    if (!n || n <= 0) return '';
    return n >= 1024 ? `${(n / 1024).toFixed(1)} MB` : `${n} KB`;
}

// 「今天发布的公告」判定。announce_date 是 YYYY-MM-DD 字符串（后端 date 字段），
// 所以直接按本地日期拼出来的当天字符串比较 —— 不能用 Date 对象比较，
// new Date('2026-10-24') 会按 UTC 解析，在 UTC+8 下算出来是前一天。
// ⚠️ 每次调用现算而不是缓存成常量：页面可能跨零点一直开着（盘中开着到第二天），
//    常量会让新公告在刷新前始终不显示标记。
function isNewToday(row) {
    return !!row?.announce_date && row.announce_date === fmtDate(new Date());
}

// 行级高亮：给「今天」的行加左侧竖线，扫视时不用逐行读徽章
function rowClass(row) {
    return isNewToday(row) ? 'ann-row-new' : '';
}

// 分类 → 配色梯度。⚠️ 绝不用 --app-up/--app-down：那会把「风险提示」读成看跌。
function catClass(category) {
    switch (category) {
        case '定期报告':
        case '重大事项':
            return 'cat-strong';
        case '风险提示':
            return 'cat-warn';
        case '公司治理':
        case '融资事项':
        case '回购增持':
        case '股权激励':
        case '股东变动':
            return 'cat-mid';
        default:
            return 'cat-base';
    }
}

const hasFilter = computed(() =>
    !!(activeCategory.value || keyword.value.trim() || symbolFilter.value || dateRange.value?.length)
);

// 「全部」按钮上的数字 = 各分类计数之和（后端已按关键词/日期/单只票收窄，只是忽略
// 分类本身，所以求和即为当前范围下的总条数，不会与表格的分页总数打架）。
const allCount = computed(() =>
    Object.values(categoryCounts.value || {}).reduce((sum, n) => sum + (Number(n) || 0), 0)
);

async function loadAnnouncements(resetPage = false) {
    if (resetPage) page.value = 1;
    loading.value = true;
    try {
        const params = { page: page.value, page_size: pageSize.value };
        if (activeCategory.value) params.category = activeCategory.value;
        if (keyword.value.trim()) params.keyword = keyword.value.trim();
        if (symbolFilter.value) params.symbol = symbolFilter.value;

        // 显式日期区间优先于「近 N 天」；两者同时存在时后端也以后者为准
        if (dateRange.value && dateRange.value[0]) {
            params.date_from = fmtDate(dateRange.value[0]);
            if (dateRange.value[1]) params.date_to = fmtDate(dateRange.value[1]);
            params.days = 0;
        } else if (days.value) {
            params.days = days.value;
        }

        const { data } = await axios.get('/api/v1/announcements', { params });
        items.value = Array.isArray(data?.items) ? data.items : [];
        total.value = data?.total ?? 0;
        categories.value = data?.categories || [];
        categoryCounts.value = data?.category_counts || {};
        todayCount.value = Number(data?.today_count ?? 0);
        coverage.value = data?.coverage || { pool_total: 0, non_a_share: 0, a_share_total: 0, with_data: 0, without_data: 0 };
        dataAsOf.value = data?.data_as_of || null;
        syncInfo.value = data?.sync || syncInfo.value;
        emptyReason.value = data?.empty_reason || '';
    } catch (e) {
        console.error('加载公司公告失败:', e);
        showError(e?.response?.data?.detail || '加载公司公告失败');
        items.value = [];
        total.value = 0;
        todayCount.value = 0;
    } finally {
        loading.value = false;
    }
}

async function loadPoolSymbols() {
    try {
        const { data } = await axios.get('/api/v1/stocks_monitored', {
            params: { page: 1, page_size: 1000, simple: 1 },
        });
        const list = Array.isArray(data) ? data : [];
        symbolOptions.value = list
            .filter(s => s?.symbol)
            .map(s => ({ label: `${s.name || '--'} ${s.symbol}`, value: String(s.symbol) }));
    } catch (e) {
        console.error('加载股票池失败:', e);
    }
}

async function triggerSync() {
    syncing.value = true;
    try {
        const { data } = await axios.post('/api/v1/announcements/sync', {});
        if (data?.queued) {
            showSuccess(data.message || '已提交同步任务');
        } else {
            showError(data?.message || '同步任务未提交');
        }
    } catch (e) {
        showError(e?.response?.data?.detail || '提交同步任务失败');
    } finally {
        syncing.value = false;
    }
}

function onPage(event) {
    page.value = event.page + 1;
    loadAnnouncements();
}

function selectCategory(cat) {
    activeCategory.value = activeCategory.value === cat ? '' : cat;
    loadAnnouncements(true);
}

function resetFilters() {
    activeCategory.value = '';
    keyword.value = '';
    symbolFilter.value = '';
    days.value = 30;
    dateRange.value = null;
    loadAnnouncements(true);
}

// 关键词输入防抖：后端是 LIKE 查询，逐字符打请求既慢也没意义
let keywordTimer = null;
watch(keyword, () => {
    clearTimeout(keywordTimer);
    keywordTimer = setTimeout(() => loadAnnouncements(true), 400);
});

// 其余筛选（单只票 / 快捷天数 / 自定义区间）用 60ms 去重：
// 「快捷天数」与「日期区间」互斥（选一个就清另一个），互相赋值必然触发两次 watch，
// 去重后只发一次请求 —— 否则每次切换筛选都会打两遍后端。
let filterTimer = null;
function scheduleReload() {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => loadAnnouncements(true), 60);
}

watch(days, (value) => {
    if (value !== 0 && dateRange.value?.length) dateRange.value = null;
    scheduleReload();
});

watch(dateRange, (value) => {
    if (value && value[0]) days.value = 0;
    scheduleReload();
});

watch(symbolFilter, scheduleReload);

onMounted(() => {
    loadPoolSymbols();
    loadAnnouncements();
});

</script>

<template>
    <Toast />
    <div class="ann-page">
        <!-- 顶部：标题 + 数据状态 + 操作 -->
        <div class="ann-header">
            <div class="ann-header-main">
                <div class="ann-title">
                    <i class="pi pi-megaphone"></i>
                    <span>公司公告</span>
                </div>
                <div class="ann-sub">
                    股票池内上市公司的公告清单（巨潮资讯网原文，每日盘后自动同步）
                </div>
            </div>
            <div class="ann-header-actions">
                <!-- 今日新增：后端按 CURDATE 统计（忽略分类/日期区间）。0 条时不占位，
                     避免每天都挂一个「0」把注意力吸走。放在头部状态区而不是分类条，
                     是因为它属于「数据状态」而非「筛选维度」—— 混进分类行会让
                     用户以为点它能筛出今天。 -->
                <span
                    v-if="todayCount > 0"
                    class="ann-today"
                    :title="`今天发布的公告共 ${todayCount} 条（不受分类与日期区间筛选影响）`"
                >
                    <i class="pi pi-bolt"></i>今日新增 {{ todayCount }}
                </span>
                <span v-if="syncInfo.last_sync_time" class="ann-meta">
                    最近同步 {{ syncInfo.last_sync_time }}
                </span>
                <span v-if="dataAsOf" class="ann-meta">数据截至 {{ dataAsOf }}</span>
                <Button
                    type="button"
                    icon="pi pi-cloud-download"
                    size="small"
                    label="立即同步"
                    severity="secondary"
                    :loading="syncing"
                    @click="triggerSync"
                />
                <Button
                    type="button"
                    icon="pi pi-refresh"
                    size="small"
                    label="刷新"
                    severity="secondary"
                    :loading="loading"
                    @click="loadAnnouncements()"
                />
            </div>
        </div>

        <!-- 分类标签条：数字来自后端统计（忽略 category 自身筛选） -->
        <div class="ann-cats">
            <button
                type="button"
                class="ann-cat-btn"
                :class="{ 'is-active': activeCategory === '' }"
                @click="selectCategory('')"
            >
                全部<span class="ann-cat-count">{{ allCount }}</span>
            </button>
            <button
                v-for="cat in categories"
                :key="cat"
                type="button"
                class="ann-cat-btn"
                :class="{ 'is-active': activeCategory === cat }"
                @click="selectCategory(cat)"
            >
                {{ cat }}<span class="ann-cat-count">{{ categoryCounts[cat] ?? 0 }}</span>
            </button>
        </div>

        <!-- 筛选行 -->
        <div class="ann-filters">
            <Dropdown
                v-model="symbolFilter"
                :options="symbolOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="全部股票"
                filter
                showClear
                size="small"
                class="ann-filter-symbol"
            />
            <SelectButton
                v-model="days"
                :options="dayOptions"
                optionLabel="label"
                optionValue="value"
                :allowEmpty="false"
                size="small"
            />
            <DatePicker
                v-model="dateRange"
                selectionMode="range"
                dateFormat="yy-mm-dd"
                placeholder="自定义日期区间"
                showIcon
                showButtonBar
                size="small"
                class="ann-filter-date"
            />
            <IconField class="ann-filter-search">
                <InputIcon>
                    <i class="pi pi-search" />
                </InputIcon>
                <InputText v-model="keyword" size="small" placeholder="搜索公告标题 / 公司名" class="w-full" />
            </IconField>
            <Button
                v-if="hasFilter"
                type="button"
                label="重置"
                size="small"
                text
                severity="secondary"
                @click="resetFilters"
            />
        </div>

        <!-- 覆盖提示：把「上游未收录」与「非 A 股不在范围内」分开说，别让用户以为接口坏了 -->
        <Message
            v-if="!loading && coverage.pool_total > 0
                  && (coverage.without_data > 0 || coverage.non_a_share > 0)"
            severity="info"
            :closable="false"
            class="ann-notice"
        >
            股票池共 {{ coverage.pool_total }} 只：
            <template v-if="coverage.a_share_total">A 股 {{ coverage.a_share_total }} 只，已收录公告 {{ coverage.with_data }} 只<template
                v-if="coverage.without_data">（{{ coverage.without_data }} 只暂未被巨潮收录）</template>
            </template>
            <template v-if="coverage.non_a_share">；非 A 股 {{ coverage.non_a_share }} 只（上游只覆盖 A 股，不展示公告）</template>
            。
        </Message>

        <div class="ann-table-wrap card">
            <DataTable
                :value="items"
                :loading="loading"
                :paginator="total > pageSize"
                :rows="pageSize"
                :first="(page - 1) * pageSize"
                :totalRecords="total"
                lazy
                dataKey="id"
                :rowHover="true"
                :rowClass="rowClass"
                :showGridlines="false"
                tableStyle="font-size: 12px"
                @page="onPage"
            >
                <template #empty>
                    <div class="ann-empty">
                        <template v-if="coverage.pool_total === 0">
                            股票池还是空的 —— 先在「投资组合 → 股票池」加入个股，这里会展示它们的公告。
                        </template>
                        <template v-else-if="emptyReason === 'no_a_share'">
                            股票池里没有 A 股标的 —— 公司公告接口只覆盖 A 股（沪深京），港股/美股暂不提供。
                        </template>
                        <template v-else-if="emptyReason === 'never_synced'">
                            还没有同步过公告数据。点击右上角「立即同步」拉取，或等今晚的定时任务自动执行。
                        </template>
                        <template v-else>
                            当前筛选条件下没有公告。
                        </template>
                    </div>
                </template>
                <template #loading>公告加载中，请稍候...</template>

                <Column header="公告日期" style="width: 110px">
                    <template #body="{ data }">
                        <span class="ann-date">{{ data.announce_date || '--' }}</span>
                    </template>
                </Column>

                <Column header="股票" style="width: 150px">
                    <template #body="{ data }">
                        <router-link
                            class="ann-symbol"
                            :title="data.symbol"
                            :to="{ name: 'stock-detail', params: { symbol: data.symbol } }"
                        >{{ data.symbol }}</router-link>
                        <span class="ann-name" :title="data.stock_name">{{ data.stock_name || '--' }}</span>
                    </template>
                </Column>

                <Column header="分类" style="width: 100px">
                    <template #body="{ data }">
                        <span class="ann-cat" :class="catClass(data.category)">
                            {{ data.category || '其他公告' }}
                        </span>
                    </template>
                </Column>

                <Column header="公告标题">
                    <template #body="{ data }">
                        <div class="ann-title-cell">
                            <span
                                v-if="isNewToday(data)"
                                class="ann-new"
                                title="今天发布的公告"
                            >NEW</span>
                            <button
                                v-if="data.pdf_url"
                                type="button"
                                class="ann-link"
                                :title="`在抽屉中阅读原文：${data.title}`"
                                @click="openPdfDrawer(data)"
                            >{{ data.title }}</button>
                            <span v-else class="ann-text" :title="data.title">{{ data.title }}</span>
                            <span v-if="data.column_name" class="ann-col">{{ data.column_name }}</span>
                        </div>
                    </template>
                </Column>

                <Column header="原文" style="width: 120px">
                    <template #body="{ data }">
                        <button
                            v-if="data.pdf_url"
                            type="button"
                            class="ann-pdf"
                            title="在抽屉中阅读原文"
                            @click="openPdfDrawer(data)"
                        >
                            <i class="pi pi-file-pdf"></i> 阅读
                            <span v-if="formatPdfSize(data.pdf_size_kb)" class="ann-size">
                                {{ formatPdfSize(data.pdf_size_kb) }}
                            </span>
                        </button>
                        <span v-else class="ann-none">--</span>
                    </template>
                </Column>

                <!-- AI 解读入口：每行一个，点开抽屉做「这条公告说明什么」的多轮追问 -->
                <Column header="AI" style="width: 84px">
                    <template #body="{ data }">
                        <Button
                            type="button"
                            icon="pi pi-sparkles"
                            label="解读"
                            size="small"
                            text
                            severity="secondary"
                            class="ann-ai-btn"
                            :title="data.has_ai_summary ? '已解读过，点击查看（会直接显示上次结果）' : 'AI 解读这条公告'"
                            @click="openAiDrawer(data)"
                        />
                    </template>
                </Column>
            </DataTable>
        </div>

        <!-- AI 解读抽屉：传当前行，抽屉内部负责流式请求与多轮追问 -->
        <AnnouncementAiDrawer
            v-model:visible="aiVisible"
            :announcement="aiTarget"
            @interpreted="onAiInterpreted"
        />

        <!-- 原文阅读抽屉：iframe + blob，同源代理取 PDF -->
        <AnnouncementPdfDrawer v-model:visible="pdfVisible" :announcement="pdfTarget" />
    </div>
</template>

<style scoped lang="scss">
/* 页面间距沿用全站口径（左 204 / 右 24 由布局层控制，这里只管内部间距） */
.ann-page {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 2rem;
}

.ann-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
}

.ann-header-main {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    min-width: 0;
}

.ann-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1.15rem;
    font-weight: 600;
    color: var(--app-text-primary);
}

.ann-title i {
    color: var(--app-link);
}

.ann-sub {
    color: var(--app-text-secondary);
}

.ann-header-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.ann-meta {
    color: var(--app-text-muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}

/* ---------------- 分类标签条 ---------------- */
.ann-cats {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
}

.ann-cat-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.25rem 0.6rem;
    border-radius: 999px;
    border: 1px solid var(--app-border-base);
    background: var(--app-bg-card);
    color: var(--app-text-secondary);
    font-size: 0.92rem;
    line-height: 1.4;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.ann-cat-btn:hover {
    background: var(--app-bg-hover);
    color: var(--app-text-primary);
}

.ann-cat-btn.is-active {
    background: var(--app-select-bg);
    border-color: var(--app-select-border);
    color: var(--app-select-text);
    font-weight: 600;
}

.ann-cat-count {
    font-variant-numeric: tabular-nums;
    opacity: 0.75;
}

/* 「今日新增 N」：头部状态区的强调项，放在「最近同步 / 数据截至」这组旁边 ——
   它是数据状态，不是筛选维度。
   配色与行内 NEW 徽章同族（红）：两者讲的是同一件事（今天发的公告），
   一个说「共几条」、一个标「哪几条」，颜色不一致会让人以为是两种提示。 */
.ann-today {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.1rem 0.55rem;
    border-radius: 999px;
    border: 1px solid var(--app-up-soft);
    background: var(--app-up-wash);
    color: var(--app-up);
    font-size: 0.92rem;
    line-height: 1.5;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}

.ann-today i {
    font-size: 0.85em;
}

/* ---------------- 今日公告标记 ---------------- */
/* 红色（用户指定）。A 股语境下红绿本属涨跌语义，这里是「时间强调」而非「价格方向」：
   徽章只压在标题首部、尺寸小、不与任何数值并列，误读风险可控。 */
.ann-new {
    flex: 0 0 auto;
    align-self: center;
    padding: 0 3px;
    border-radius: 2px;
    /* ⚠️ 实心块固定 #dc2626，不用 var(--app-up)：暗色下 --app-up 是 #f87171（红-400），
       白字压上去对比度只有 2.4:1，小字直接糊掉。
       压在实心色块上的底色/文字都不参与明暗语义 —— 两套主题同值，
       与全站涨红（--app-up 浅色档）同色相，观感统一。 */
    background: #dc2626;
    color: #fff;
    /* 只是「有更新」的角标，不该和标题抢视线：9px / 行高 11px（块高 11px），
       宽度靠 3px 内边距收到 ~26px。再小就压不住 #dc2626 上的白字了。 */
    font-size: 9px;
    font-weight: 700;
    line-height: 11px;
    letter-spacing: 0.02em;
}

/* 行首竖线：扫视时不用逐行找徽章就能定位「今天的那几条」。
   ⚠️ 竖线画在第一个 td 的 ::before 上（tr 上的 box-shadow 在表格行上不可靠），
   需要 td 自身 position:relative 作为定位参照。 */
:deep(tr.ann-row-new > td:first-child) {
    position: relative;
}

:deep(tr.ann-row-new > td:first-child::before) {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
    /* 竖线是「细线」不是「色块」：暗色下 --app-up 的 #f87171 反而更清楚，
       所以这里用变量、和徽章实心块不同值 —— 不是不一致，是两种载体的正确取色。 */
    background: var(--app-up);
}

/* ---------------- 筛选行 ---------------- */
.ann-filters {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.ann-filter-symbol {
    min-width: 11rem;
}

.ann-filter-date {
    min-width: 13rem;
}

.ann-filter-search {
    flex: 1 1 12rem;
    max-width: 20rem;
}

.ann-notice {
    padding: 0.35rem 0.6rem;
    font-size: 0.95rem;
}

/* ---------------- 表格 ---------------- */
.ann-table-wrap {
    padding: 0.5rem 0.6rem 0.25rem;
    border-radius: 5px;
}

.ann-date {
    color: var(--app-text-secondary);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}

.ann-symbol {
    display: block;
    color: var(--app-link);
    text-decoration: none;
    white-space: nowrap;
}

.ann-symbol:hover {
    text-decoration: underline;
}

.ann-name {
    display: block;
    color: var(--app-text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.ann-cat {
    display: inline-block;
    padding: 1px 7px;
    border-radius: 3px;
    font-size: 11px;
    line-height: 18px;
    white-space: nowrap;
    border: 1px solid transparent;
}

.ann-cat.cat-strong {
    background: var(--app-select-bg);
    color: var(--app-select-text);
    border-color: var(--app-select-border);
}

.ann-cat.cat-warn {
    background: var(--app-warn-bg);
    color: var(--app-warn-text);
    border-color: var(--app-warn-border);
}

.ann-cat.cat-mid {
    background: var(--app-info-bg);
    color: var(--app-select-text);
    border-color: var(--app-info-border);
}

.ann-cat.cat-base {
    background: var(--app-bg-active);
    color: var(--app-text-secondary);
    border-color: var(--app-border-strong);
}

.ann-title-cell {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    min-width: 0;
}

/* 标题与「阅读」都是**按钮**（点开抽屉），不是链接 —— 需要把 button 的默认外观清掉，
   否则会出现浏览器默认的灰底和居中文本，与右侧的 PDF 大小标签对不齐。 */
.ann-link {
    display: block;
    min-width: 0;
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    color: var(--app-link);
    text-align: left;
    cursor: pointer;
    overflow-wrap: anywhere;
}

.ann-link:hover {
    text-decoration: underline;
}

.ann-text {
    color: var(--app-text-primary);
    overflow-wrap: anywhere;
}

.ann-col {
    flex: 0 0 auto;
    color: var(--app-text-muted);
    font-size: 11px;
    white-space: nowrap;
}

.ann-pdf {
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    color: var(--app-link);
    white-space: nowrap;
    cursor: pointer;
}

.ann-pdf:hover {
    text-decoration: underline;
}

.ann-size {
    color: var(--app-text-muted);
    margin-left: 0.25rem;
}

.ann-none {
    color: var(--app-text-muted);
}

/* AI 解读按钮：默认低调（每行都有，不该抢标题的注意力），已解读过的行用一点主色提示 */
.ann-ai-btn {
    padding: 0 0.35rem !important;
    font-size: 0.92rem !important;
}

.ann-empty {
    padding: 1.5rem 0;
    color: var(--app-text-secondary);
    text-align: center;
}
</style>
