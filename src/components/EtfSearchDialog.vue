<script setup>
/**
 * ETF 搜索添加弹窗（「监控列表」与「轮动池」共用）。
 *
 * 抽出来的原因：这段搜索联想逻辑原本内嵌在 ETFInsight.vue 里，而轮动池需要
 * **一模一样**的行为（300ms 防抖 + 请求序号丢弃过期响应 + 搜索无结果时按代码直接
 * 添加的兜底 + 已添加标记）。复制第二份的话，两处必然会漂移（改一处的防抖时间、
 * 忘了另一处的序号保护）。
 *
 * ⚠️ 职责边界：组件只负责「搜到什么、用户选了哪个」，**不调业务接口** ——
 * 两个清单的提交接口不同（POST /etf 与 POST /etf_rotation_pool），
 * 提交、toast、刷新列表都由父组件处理（见父组件的 @submit）。
 */
import {computed, ref, watch} from 'vue';
import Dialog from 'primevue/dialog';
import axios from 'axios';

const props = defineProps({
    // 由父组件 v-model:visible 控制
    visible: {type: Boolean, default: false},
    title: {type: String, default: '添加 ETF'},
    // 已在目标清单中的代码，用于把搜索结果标记成「已添加」并替换添加按钮
    watched: {type: Array, default: () => []},
    // 正在提交的代码（父组件在请求期间传入，用于禁用/loading 对应按钮）
    adding: {type: String, default: ''},
    hint: {type: String, default: '输入 ETF 代码或名称，从全市场 ETF 目录中搜索'},
    // 搜索无结果时的兜底提示语，两个清单的措辞不同
    fallbackHint: {type: String, default: '未搜到？可直接用代码（如 159901）添加'},
});

const emit = defineEmits(['update:visible', 'submit']);

const searchKeyword = ref('');
const searchResults = ref([]);
const searching = ref(false);
let searchSeq = 0;      // 搜索请求序号，用于丢弃过期响应（乱序返回时不能覆盖新结果）
let searchTimer = null;

const watchedSet = computed(() => new Set((props.watched || []).map(s => String(s))));

function isWatched(symbol) {
    return watchedSet.value.has(String(symbol));
}

function reset() {
    searchKeyword.value = '';
    searchResults.value = [];
    searching.value = false;
    searchSeq++;        // 让在途请求的结果失效，避免重开弹窗后旧结果闪一下
    if (searchTimer) {
        clearTimeout(searchTimer);
        searchTimer = null;
    }
}

// 打开时重置；关闭时也重置（下次打开是干净的）
watch(() => props.visible, (val) => {
    if (val) reset();
});

function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    const kw = searchKeyword.value.trim();
    if (!kw) {
        searchResults.value = [];
        searching.value = false;
        searchSeq++;
        return;
    }
    searchTimer = setTimeout(() => doSearch(kw), 300);
}

async function doSearch(kw) {
    const seq = ++searchSeq;
    searching.value = true;
    try {
        const r = await axios.get('/api/v1/etf_search', {params: {keyword: kw, limit: 50}});
        if (seq !== searchSeq) return;   // 已有更新的搜索，丢弃本次结果
        searchResults.value = Array.isArray(r.data) ? r.data : [];
    } catch (e) {
        if (seq === searchSeq) searchResults.value = [];
    } finally {
        if (seq === searchSeq) searching.value = false;
    }
}

function pick(item) {
    emit('submit', {symbol: item.symbol, name: item.name || null, byCode: false});
}

function addByCode() {
    const sym = searchKeyword.value.trim();
    if (!sym) return;
    emit('submit', {symbol: sym, name: null, byCode: true});
}

// 父组件提交成功后调这个把弹窗内容清空（弹窗本身由父组件关闭）
defineExpose({reset});
</script>

<template>
    <Dialog
        :visible="visible"
        @update:visible="v => emit('update:visible', v)"
        modal
        :header="title"
        :style="{ width: '30rem' }"
    >
        <div class="flex flex-col gap-3">
            <IconField>
                <InputIcon>
                    <i class="pi pi-search"/>
                </InputIcon>
                <InputText
                    v-model="searchKeyword"
                    @input="onSearchInput"
                    placeholder="输入代码或名称搜索"
                    class="w-full"
                    autocomplete="off"
                />
            </IconField>

            <div v-if="searching" class="text-center text-gray-500 py-4">
                <i class="pi pi-spin pi-spinner"/>
            </div>
            <div v-else-if="!searchKeyword.trim()" class="text-center text-gray-400 py-4 text-sm">
                {{ hint }}
            </div>
            <div v-else-if="searchResults.length === 0" class="text-center text-gray-400 py-4 text-sm">
                未找到匹配的 ETF
            </div>
            <div v-else class="flex flex-col gap-2">
                <div class="text-xs text-gray-400">共 {{ searchResults.length }} 条匹配</div>
                <div class="flex flex-col gap-2 max-h-80 overflow-auto">
                    <div v-for="item in searchResults" :key="item.symbol"
                         class="flex items-center justify-between gap-2 border rounded p-2">
                        <div class="min-w-0">
                            <div class="font-semibold truncate">{{ item.symbol }}</div>
                            <div class="text-xs text-gray-500 truncate">{{ item.name }}</div>
                        </div>
                        <Tag v-if="isWatched(item.symbol)" value="已添加" severity="secondary" class="shrink-0"/>
                        <Button
                            v-else
                            icon="pi pi-plus"
                            label="添加"
                            size="small"
                            class="shrink-0"
                            :loading="adding === item.symbol"
                            @click="pick(item)"
                        />
                    </div>
                </div>
            </div>

            <!-- 搜索无结果时，支持按代码直接添加（不依赖目录接口可用性） -->
            <div v-if="searchKeyword.trim() && !searching && searchResults.length === 0" class="pt-1 border-t mt-2">
                <Button
                    label="按代码直接添加"
                    severity="secondary"
                    size="small"
                    text
                    :loading="adding === searchKeyword.trim()"
                    @click="addByCode"
                />
                <span class="text-xs text-gray-400 ml-2">{{ fallbackHint }}</span>
            </div>
        </div>
    </Dialog>
</template>
