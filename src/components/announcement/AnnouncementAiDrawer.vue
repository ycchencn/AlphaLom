<script setup>

/**
 * 公司公告「AI 解读」抽屉。
 *
 * 数据流：POST /api/v1/announcements/{id}/ai/stream（NDJSON 流式）
 *   首轮：不带 question → 后端先抽 PDF 正文（可能 1~2 秒，期间推 status 事件），
 *         再流式返回解读，并落库到 stock_announcements.ai_summary。
 *   再看：同一公告已有 ai_summary → 后端直接回放缓存（meta.cached=true），不花模型调用。
 *   追问：带 question + history（history[0] 是首轮解读）→ 后端把材料只注入一次，
 *         之后接 history，最后接本次问题。
 *
 * 三个不能在前端"美化"的事实：
 * 1. 正文可能抽不出来（扫描件 / 自定义字体乱码）。后端会在 meta.content_status 里说明，
 *    这里必须如实提示「未取到正文」，否则用户会以为下面的推断都有原文依据。
 * 2. 解读是流式的，出错时流已经开了，只能以 error 事件回传 → 统一渲染在消息气泡里。
 * 3. 首轮解读在 history 里，追问时不能再把公告正文重贴一遍（后端已处理，前端只传问答）。
 */

import { computed, ref, watch, nextTick } from 'vue';
import axios from 'axios';
import { store } from '@/store';
import MarkdownRenderer from '@/components/MarkdownRenderer.vue';

const props = defineProps({
    visible: { type: Boolean, default: false },
    announcement: { type: Object, default: null },
});

// 首轮解读生成完之后，通知父组件刷新列表上的「已解读」标记。
// ⚠️ 不直接改 props.announcement.has_ai_summary：那是父组件列表里的行对象，
//    子组件改 props 数据属于反向写，后续若列表改成不可变数据流就会静默失效。
const emit = defineEmits(['update:visible', 'interpreted']);

const messages = ref([]);   // {id, role: 'assistant'|'user', content, isLoading, error}
const meta = ref(null);     // {cached, content_status, content_chars, model, ai_update_time}
const statusText = ref('');
const inputMessage = ref('');
const loading = ref(false);
const scrollAnchor = ref(null);
// 当前这次流式请求的控制器：关闭抽屉时要中止，否则「关掉再开」会看到空白且永远转圈
// （上一轮 loading 还是 true，run() 直接早退，新请求根本发不出去）。
let controller = null;

const genId = () => `ai_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

const open = computed({
    get: () => props.visible,
    set: (v) => emit('update:visible', v),
});

const ann = computed(() => props.announcement || {});

// 正文状态 → 提示文案。'ok' 时不提示（正常态不需要解释）。
const contentNotice = computed(() => {
    const s = meta.value?.content_status;
    if (!s || s === 'ok') return '';
    if (s === 'unsupported') return '这份 PDF 的字体编码无法解析（抽取结果是乱码，已丢弃），以下解读仅基于标题与公司背景推断。';
    if (s === 'empty') return '这份 PDF 是扫描件、没有文字层，以下解读仅基于标题与公司背景推断。';
    if (s === 'failed') return '公告正文下载失败，以下解读仅基于标题与公司背景推断。可稍后点「重新生成」再试。';
    return '';
});

// 建议追问：覆盖「影响 → 风险 → 待确认」三个方向，避免用户面对空输入框没话说
const SUGGESTIONS = [
    '这次披露对业绩的实际影响有多大？',
    '有哪些条款或前置条件需要再确认？',
    '和同行业公司同类事项相比算正常吗？',
];

function scrollToBottom() {
    nextTick(() => scrollAnchor.value?.scrollIntoView({ behavior: 'smooth', block: 'end' }));
}

/**
 * 发起一次流式请求。
 * @param {string|null} question 追问内容；null = 首轮解读
 * @param {boolean} regenerate   强制忽略缓存重新生成首轮解读
 */
async function run(question = null, regenerate = false) {
    if (!ann.value?.id || loading.value) return;
    loading.value = true;
    statusText.value = '';
    meta.value = null;

    // 追问时把「当前已展示的问答」作为 history 带上；首轮时为空。
    // ⚠️ 只取已完成的消息，别把本轮的空占位气泡发给后端。
    const history = question
        ? messages.value
            .filter((m) => !m.isLoading && !m.error && (m.content || '').trim())
            .map((m) => ({ role: m.role, content: m.content }))
        : [];

    if (question) {
        messages.value.push({ id: genId(), role: 'user', content: question });
    }
    const replyId = genId();
    messages.value.push({ id: replyId, role: 'assistant', content: '', isLoading: true });
    scrollToBottom();

    const replyOf = () => messages.value.find((m) => m.id === replyId);

    try {
        const token = store.state.token;
        controller = new AbortController();
        const response = await fetch(`/api/v1/announcements/${ann.value.id}/ai/stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ question, history, regenerate }),
            signal: controller.signal,
        });
        if (!response.ok) {
            // 404 = 不在股票池/公告不存在（后端刻意不区分，避免探测别人持仓）
            const detail = response.status === 404 ? '这条公告不在当前股票池范围内' : `请求失败（${response.status}）`;
            throw new Error(detail);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let nl;
            while ((nl = buffer.indexOf('\n')) >= 0) {
                const line = buffer.slice(0, nl);
                buffer = buffer.slice(nl + 1);
                if (!line.trim()) continue;
                let evt;
                try {
                    evt = JSON.parse(line);
                } catch (e) {
                    console.warn('解析解读事件失败:', line, e);
                    continue;
                }
                if (evt.type === 'status') {
                    statusText.value = evt.data || '';
                } else if (evt.type === 'meta') {
                    meta.value = evt;
                    statusText.value = '';
                } else if (evt.type === 'text') {
                    const target = replyOf();
                    if (target) target.content += evt.data || '';
                    scrollToBottom();
                } else if (evt.type === 'error') {
                    const target = replyOf();
                    if (target) {
                        target.content += (target.content ? '\n\n' : '') + (evt.data || '解读失败');
                        target.error = true;
                    }
                }
            }
        }
        const target = replyOf();
        if (target && !target.content.trim()) {
            target.content = '（模型没有返回内容，请稍后点「重新生成」再试）';
            target.error = true;
        }
        // 首轮解读生成完之后，通知父组件更新列表上的「已解读」标记
        if (!question && target && !target.error) {
            emit('interpreted', ann.value.id);
        }
    } catch (e) {
        if (e.name === 'AbortError') return;   // 主动关闭抽屉，不是错误
        const target = replyOf();
        if (target) {
            target.content = target.content || `出错了：${e.message || '网络异常'}`;
            target.error = true;
        }
    } finally {
        messages.value.forEach((m) => { if (m.isLoading) m.isLoading = false; });
        statusText.value = '';
        loading.value = false;
        scrollToBottom();
    }
}

function send() {
    const text = inputMessage.value.trim();
    if (!text || loading.value) return;
    inputMessage.value = '';
    run(text);
}

function regenerate() {
    if (loading.value) return;
    messages.value = [];
    run(null, true);
}

// 每次打开（或切换到另一条公告）都重新拉：首轮会命中后端缓存，几乎零耗时
watch(
    () => [props.visible, ann.value?.id],
    ([visible]) => {
        if (!visible) {
            // 关闭：中止在途请求并复位，否则下次打开会被上一轮的 loading 卡住
            controller?.abort();
            controller = null;
            loading.value = false;
            statusText.value = '';
            return;
        }
        if (!ann.value?.id) return;
        messages.value = [];
        inputMessage.value = '';
        meta.value = null;
        run(null, false);
    },
    { immediate: true }
);

defineExpose({ regenerate });
</script>

<template>
    <Drawer
        v-model:visible="open"
        position="right"
        :footer="false"
        body-class="p-0"
        class="!w-full md:!w-[42rem] lg:!w-[50rem]"
    >
        <template #header>
            <div class="ai-head">
                <div class="ai-head-title">
                    <i class="pi pi-sparkles"></i>
                    <span>AI 解读</span>
                    <span v-if="ann.symbol" class="ai-head-symbol">{{ ann.symbol }}</span>
                </div>
                <div class="ai-head-sub" :title="ann.title">{{ ann.title || '' }}</div>
            </div>
        </template>

        <div class="ai-body">
            <!-- 公告元信息：让解读始终有「在读哪一条」的锚点 -->
            <div class="ai-meta-bar">
                <span>{{ ann.announce_date || '--' }}</span>
                <span v-if="ann.category" class="ai-cat">{{ ann.category }}</span>
                <span v-if="ann.column_name">{{ ann.column_name }}</span>
                <a v-if="ann.pdf_url" :href="ann.pdf_url" target="_blank" rel="noopener" class="ai-pdf">
                    <i class="pi pi-file-pdf"></i> 原文 PDF
                </a>
                <span class="ai-meta-spacer"></span>
                <span v-if="meta?.cached && meta.ai_update_time" class="ai-cached">
                    缓存于 {{ meta.ai_update_time }}
                </span>
                <Button
                    label="重新生成"
                    icon="pi pi-refresh"
                    size="small"
                    text
                    severity="secondary"
                    :disabled="loading"
                    @click="regenerate"
                />
            </div>

            <!-- 正文缺失提示：必须显眼，否则用户会以为推断都有原文依据 -->
            <Message v-if="contentNotice" severity="warn" :closable="false" class="ai-notice">
                {{ contentNotice }}
            </Message>

            <div class="ai-messages">
                <div v-for="msg in messages" :key="msg.id" class="ai-msg" :class="`is-${msg.role}`">
                    <template v-if="msg.role === 'user'">
                        <div class="ai-bubble-user">{{ msg.content }}</div>
                    </template>
                    <template v-else>
                        <div class="ai-answer" :class="{ 'is-error': msg.error }">
                            <MarkdownRenderer fontSize="12px" :markdown="msg.content || ''" />
                            <span v-if="msg.isLoading && !msg.content" class="ai-thinking">
                                {{ statusText || '正在生成解读…' }}
                            </span>
                        </div>
                    </template>
                </div>

                <!-- 首轮还在读正文时给个骨架，避免一片空白像卡死 -->
                <div v-if="loading && !messages.length" class="ai-answer">
                    <span class="ai-thinking">{{ statusText || '正在读取公告并生成解读…' }}</span>
                </div>

                <div ref="scrollAnchor"></div>
            </div>

            <!-- 追问建议：只在首轮生成完之后出现，避免抢在解读前干扰阅读 -->
            <div
                v-if="!loading && messages.length && !messages[messages.length - 1].isLoading"
                class="ai-suggest"
            >
                <button
                    v-for="s in SUGGESTIONS"
                    :key="s"
                    type="button"
                    class="ai-suggest-item"
                    @click="inputMessage = s; send()"
                >
                    {{ s }}
                </button>
            </div>

            <div class="ai-input">
                <InputText
                    v-model="inputMessage"
                    placeholder="就这条公告继续追问，例如：这个事项还需要股东大会通过吗？"
                    class="flex-1"
                    :disabled="loading"
                    @keyup.enter="send"
                />
                <Button
                    icon="pi pi-send"
                    label="发送"
                    size="small"
                    :disabled="!inputMessage.trim() || loading"
                    @click="send"
                />
            </div>
        </div>
    </Drawer>
</template>

<style scoped lang="scss">
.ai-head {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
}

.ai-head-title {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--app-text-primary);
}

.ai-head-title i {
    color: var(--app-link);
}

.ai-head-symbol {
    font-size: 0.85rem;
    font-weight: 400;
    color: var(--app-text-muted);
    font-variant-numeric: tabular-nums;
}

.ai-head-sub {
    color: var(--app-text-secondary);
    font-size: 0.95rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ai-body {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--app-bg-page);
}

.ai-meta-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    padding: 0.5rem 1rem;
    border-bottom: 1px solid var(--app-border-base);
    background: var(--app-bg-card);
    color: var(--app-text-secondary);
    font-size: 0.95rem;
}

.ai-cat {
    padding: 0 6px;
    border-radius: 3px;
    border: 1px solid var(--app-border-strong);
    color: var(--app-text-secondary);
}

.ai-pdf {
    color: var(--app-link);
    text-decoration: none;
}

.ai-pdf:hover {
    text-decoration: underline;
}

.ai-meta-spacer {
    flex: 1 1 auto;
}

.ai-cached {
    color: var(--app-text-muted);
    font-size: 0.9rem;
}

.ai-notice {
    margin: 0.5rem 1rem 0;
    padding: 0.35rem 0.6rem;
    font-size: 0.95rem;
    /* 覆盖 PrimeVue 默认的警告色：默认那套是浅黄底 + 琥珀字，暗色下会亮得像一张贴纸。
       走语义层（--app-warn-*），明暗两套主题都跟着底色走。 */
    background: var(--app-warn-bg);
    color: var(--app-warn-text);
    border: 1px solid var(--app-warn-border);
}

.ai-messages {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
}

.ai-msg.is-user {
    display: flex;
    justify-content: flex-end;
}

.ai-bubble-user {
    max-width: 85%;
    padding: 0.45rem 0.75rem;
    border-radius: 8px 8px 2px 8px;
    background: var(--app-select-bg);
    color: var(--app-select-text);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.ai-answer {
    background: var(--app-bg-card);
    border: 1px solid var(--app-border-base);
    border-radius: 8px;
    padding: 0.6rem 0.8rem;
}

.ai-answer.is-error {
    border-color: var(--app-error-border);
    background: var(--app-error-bg);
    color: var(--app-error-text);
}

.ai-thinking {
    display: inline-block;
    color: var(--app-text-muted);
    font-size: 0.95rem;
}

.ai-suggest {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 0 1rem 0.5rem;
}

.ai-suggest-item {
    padding: 0.25rem 0.6rem;
    border-radius: 999px;
    border: 1px dashed var(--app-border-strong);
    background: transparent;
    color: var(--app-text-secondary);
    font-size: 0.92rem;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
}

.ai-suggest-item:hover {
    background: var(--app-bg-hover);
    color: var(--app-text-primary);
}

.ai-input {
    display: flex;
    gap: 0.5rem;
    padding: 0.6rem 1rem;
    border-top: 1px solid var(--app-border-base);
    background: var(--app-bg-card);
}
</style>
