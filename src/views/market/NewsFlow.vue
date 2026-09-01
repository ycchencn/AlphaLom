<script setup>
import {ref, reactive, onMounted} from 'vue';
import axios from 'axios';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Dialog from 'primevue/dialog';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import BullishBearishIndicator from '@/components/BullishBearishIndicator.vue';
import {formatDaysAgo} from '@/utils/function.js';

// ================= 状态管理 =================
const news = ref([]);
const loading1 = ref(false);

// 话题相关状态
const topics = ref([]);
const activeTopic = ref('');
const showTopicDialog = ref(false);
const topicForm = reactive({id: null, name: '', oldName: ''});
const isEditing = ref(false);

// 🟢 MOCK 测试数据（对接后端前请保持开启）
const MOCK_TOPICS = [
    {id: 1, name: '全部新闻'},
    {id: 2, name: '特朗普'},
    {id: 3, name: '马斯克'},
    {id: 4, name: '美联储'},
    {id: 5, name: '央行'},
    {id: 6, name: '证监会'},
    {id: 7, name: '货币政策'},
    {id: 8, name: '业绩披露'},
    {id: 9, name: '商业航天'},
    {id: 15, name: '半导体'},
    {id: 10, name: '机器人'},
    {id: 11, name: 'CPO'},
    {id: 12, name: 'PCB'},
    {id: 13, name: '芯片'},
    {id: 14, name: '创新药'},
    {id: 15, name: '黄金'},
];

// ================= 数据加载 =================
const loadTopics = async () => {
    // ⬇️ 此处使用 Mock 数据，切换真实接口时注释掉下一行即可
    topics.value = MOCK_TOPICS;

    /* 🔵 真实接口示例（开发完成后可取消注释）
    try {
      const res = await axios.get('/api/v1/market/topics');
      topics.value = res.data || [];
    } catch (e) {
      console.error('加载话题列表失败:', e);
      // 失败可降级使用 Mock
      // topics.value = MOCK_TOPICS;
    }
    */

    // 如果未选中任何话题，自动选中第一个
    if (topics.value.length > 0 && !activeTopic.value) {
        activeTopic.value = topics.value[0].name;
    }
};

const loadNewsData = async () => {
    if (!activeTopic.value) {
        news.value = [];
        loading1.value = false;
        return;
    }
    loading1.value = true;
    try {
        const keyword = activeTopic.value === '全部新闻' ? '' : activeTopic.value;
        const res = await axios.get('/api/v1/market/search_news', {
            params: {page: 1, page_size: 200, keyword}
        });
        news.value = res.data?.items || [];
    } catch (e) {
        news.value = [];
    } finally {
        loading1.value = false;
    }
};

// 监听话题切换，自动刷新右侧表格
import {watch} from 'vue';

watch(activeTopic, () => {
    loadNewsData();
});

// ================= 话题 CRUD =================
const openAddDialog = () => {
    isEditing.value = false;
    topicForm.id = null;
    topicForm.name = '';
    topicForm.oldName = '';
    showTopicDialog.value = true;
};

const openEditDialog = (topic) => {
    isEditing.value = true;
    topicForm.id = topic.id;
    topicForm.name = topic.name;
    topicForm.oldName = topic.name;
    showTopicDialog.value = true;
};

const saveTopic = async () => {
    if (!topicForm.name.trim()) {
        alert('话题名称不能为空');
        return;
    }

    try {
        if (isEditing.value) {
            // 模拟 PUT 请求（实际对接时取消注释 axios.put）
            // await axios.put(`/api/v1/market/topics/${topicForm.id}`, { name: topicForm.name });
            const idx = topics.value.findIndex(t => t.id === topicForm.id);
            if (idx !== -1) {
                topics.value[idx].name = topicForm.name;
                if (activeTopic.value === topicForm.oldName) activeTopic.value = topicForm.name;
            }
        } else {
            // 模拟 POST 请求
            // const res = await axios.post('/api/v1/market/topics', { name: topicForm.name });
            // const newTopic = res.data;
            const newId = Math.max(...topics.value.map(t => t.id), 0) + 1;
            const newTopic = {id: newId, name: topicForm.name};
            topics.value.push(newTopic);
            if (!activeTopic.value) activeTopic.value = newTopic.name;
        }
        showTopicDialog.value = false;
    } catch (e) {
        alert('保存失败');
    }
};

const deleteTopic = async (topic) => {
    if (!confirm(`确定要删除话题「${topic.name}」吗？该操作不可恢复。`)) return;

    try {
        // await axios.delete(`/api/v1/market/topics/${topic.id}`);
        const newTopics = topics.value.filter(t => t.id !== topic.id);
        topics.value = newTopics;

        if (activeTopic.value === topic.name) {
            activeTopic.value = newTopics.length > 0 ? newTopics[0].name : '';
        }
    } catch (e) {
        alert('删除失败');
    }
};

// ================= 生命周期 =================
onMounted(async () => {
    await loadTopics();
    loadNewsData(); // 主动触发一次数据加载，解决 watch 不触发初次渲染的问题
});
</script>

<template>
    <div class="flex bg-gray-50 overflow-hidden">
        <!-- 左侧：话题导航面板 -->
        <div class="min-w-56 border-r border-gray-200 bg-white flex flex-col shadow-sm z-10">
            <div class="p-4 border-b border-gray-200 flex justify-between items-center bg-gray-50">
                <h3 class="font-semibold text-base text-gray-700">话题列表</h3>
                <Button icon="pi pi-plus" @click="openAddDialog" rounded text severity="primary" aria-label="Add Topic"/>
            </div>

            <div class="flex-1 overflow-y-auto p-2 space-y-1">
                <div
                    v-for="topic in topics"
                    :key="topic.id"
                    class="px-3 py-2.5 rounded-md cursor-pointer flex justify-between items-center transition-all duration-200 hover:bg-blue-50 group"
                    :class="{ 'bg-blue-50 text-blue-700 font-semibold border-l-4 border-blue-500': activeTopic === topic.name }"
                    @click="activeTopic = topic.name"
                >
                    <span class="truncate">{{ topic.name }}</span>

                    <!-- 悬停显示的操作按钮 -->
                    <div class="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button
                            icon="pi pi-pencil"
                            size="small"
                            text
                            severity="secondary"
                            @click.stop="openEditDialog(topic)"
                            class="!p-1 !min-w-0 !h-6"
                        />
                        <Button
                            icon="pi pi-trash"
                            size="small"
                            text
                            severity="danger"
                            @click.stop="deleteTopic(topic)"
                            class="!p-1 !min-w-0 !h-6"
                        />
                    </div>
                </div>

                <div v-if="topics.length === 0" class="text-center text-gray-400 text-sm py-8">
                    暂无话题<br/>点击右上角 "+" 添加
                </div>
            </div>
        </div>

        <!-- 右侧：新闻数据表格 -->
        <div class="flex-1 p-4 overflow-y-auto flex flex-col bg-white">

            <DataTable
                tableStyle="width: 100%; border-collapse: separate; border-spacing: 0;font-size:11px"
                :value="news"
                :paginator="true"
                :rows="50"
                dataKey="id"
                :rowHover="true"
                :loading="loading1"
                :showGridlines="false"
                paginatorPosition="bottom"
                paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
                currentPageReportTemplate="当前 {currentPage} / {totalPages} 页，每页 {rows} 条"
            >
                <Column field="stock_name" header="新闻详情">
                    <template #body="{ data }">
                        <div class="news-item">
                            <p class="news-digest leading-relaxed">{{ data.digest }}</p>

                            <div class="news-time text-gray-500 text-xs mb-1">
                                {{ formatDaysAgo(data.news_time) }}
                                <a v-if="data.url" :href="data.url" target="_blank" class="text-blue-500 hover:underline ml-2">{{data.url}}</a>
                            </div>

                            <div v-if="data.relations_stocks?.length" class="mt-2 text-sm">
                                <strong class="text-gray-600">关联股票：</strong>
                                <span class="ml-1 inline-flex flex-wrap gap-x-2">
                                  <a
                                      v-for="(stock, i) in data.relations_stocks"
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
            </DataTable>
        </div>

        <!-- 新增/编辑话题弹窗 -->
        <Dialog
            v-model:visible="showTopicDialog"
            modal
            header="话题设置"
            :style="{ width: '320px' }"
            :breakpoints="{ '500px': '90vw' }"
        >
            <div class="flex flex-col gap-3 pt-2">
                <label for="topicName" class="text-sm font-medium text-gray-700">话题名称</label>
                <InputText
                    id="topicName"
                    v-model="topicForm.name"
                    placeholder="例如：美联储降息、芯片国产替代"
                    autofocus
                    class="w-full"
                    @keyup.enter="saveTopic"
                />
                <p class="text-xs text-gray-500 mt-1">
                    {{ isEditing ? '修改后若正在查看该话题，将自动刷新内容' : '新话题创建后将自动选中并加载数据' }}
                </p>
            </div>
            <template #footer>
                <Button label="取消" text @click="showTopicDialog = false" class="mr-2"/>
                <Button label="保存" @click="saveTopic"/>
            </template>
        </Dialog>
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

/* 覆盖 PrimeVue 按钮默认样式以适配紧凑布局 */
::v-deep(.p-button.p-button-text.p-button-small) {
    padding: 0.25rem;
    min-width: 1.5rem;
    height: 1.5rem;
}
</style>