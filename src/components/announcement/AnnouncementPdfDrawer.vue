<script setup>

/**
 * 公司公告「原文阅读」抽屉：在右侧抽屉里用 iframe 直接看 PDF。
 *
 * 数据来源：GET /api/v1/announcements/{id}/pdf（后端同源代理巨潮原文）。
 * ⚠️ 不把 iframe 直接指向上游 pdf_url，三个原因：
 *   1. 上游给的是 **http://** 直链，生产页面是 https → 被「混合内容」拦截，抽屉一片空白；
 *   2. 上游 CORS 只放行自家域名，前端 fetch 成 blob 也读不出来；
 *   3. 直链会绕过鉴权 —— 走代理则「不在股票池就 404」这条口径依然成立。
 *
 * 为什么用 blob 而不是 iframe src 直接指向代理 URL：
 *   iframe 无法带 Bearer 头，只能把 token 拼进 query（会进历史记录/访问日志）。
 *   这里先用 fetch + Authorization 取回二进制，再造一个 blob URL 给 iframe，
 *   token 不出现在 URL 里；顺带还能显示下载进度、把失败态渲染成可读文案。
 *
 * ⚠️ blob URL 必须显式 revoke：关闭抽屉、切换到另一条公告、组件卸载三处都要收，
 *    否则每看一条公告就多占一份内存（大 PDF 几百 KB~几 MB，看几十条就明显了）。
 */

import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { store } from '@/store';

const props = defineProps({
    visible: { type: Boolean, default: false },
    announcement: { type: Object, default: null },
});

const emit = defineEmits(['update:visible']);

const open = computed({
    get: () => props.visible,
    set: (v) => emit('update:visible', v),
});

const ann = computed(() => props.announcement || {});

const loading = ref(false);
const progress = ref(0);      // 0~100；拿不到 content-length 时一直停在 0（用不定态骨架）
const errorTitle = ref('');
const errorDetail = ref('');
const pdfUrl = ref('');       // blob: URL
const pdfBytes = ref(0);

// 正在进行的请求控制器：关闭抽屉要中止，否则关掉再开会看到旧的进度条在跑
let controller = null;
// 一轮请求的序号：快速连点两条公告时，先发的响应可能后到，用序号丢弃过期结果
let seq = 0;

const proxyUrl = computed(() => (ann.value?.id ? `/api/v1/announcements/${ann.value.id}/pdf` : ''));

// 「新窗口打开」用代理 URL + query token：同源、走 https，且后端支持 Range
// （浏览器内置阅读器会按需分段取，比 blob 更适合大文件）。
const openInNewTabUrl = computed(() => {
    if (!proxyUrl.value) return '';
    const token = store.state.token;
    return token ? `${proxyUrl.value}?token=${encodeURIComponent(token)}` : proxyUrl.value;
});

const sizeText = computed(() => {
    const n = pdfBytes.value;
    if (!n) return '';
    return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
});

function releaseBlob() {
    if (pdfUrl.value) {
        URL.revokeObjectURL(pdfUrl.value);
        pdfUrl.value = '';
    }
    pdfBytes.value = 0;
}

function abortCurrent() {
    if (controller) {
        controller.abort();
        controller = null;
    }
}

function downloadName() {
    const raw = [
        ann.value.stock_name || ann.value.symbol || '公告',
        ann.value.announce_date || '',
        ann.value.title || '',
    ].filter(Boolean).join('-');
    // 文件名里不能出现的字符统一换成下划线（Windows 比 POSIX 严格，按 Windows 来）
    return `${raw.replace(/[\\/:*?"<>|]/g, '_').slice(0, 120)}.pdf`;
}

function download() {
    if (pdfUrl.value) {
        const a = document.createElement('a');
        a.href = pdfUrl.value;
        a.download = downloadName();
        document.body.appendChild(a);
        a.click();
        a.remove();
        return;
    }
    // 没有 blob（加载失败）时退到「新窗口打开」，让用户自己另存
    openInNewTab();
}

// ⚠️ 模板里不能直接写 window.open（Vue 模板作用域没有 window，会解析成 undefined），
//    而且 window.open 必须在用户手势的同步调用栈里，否则被弹窗拦截。
function openInNewTab() {
    if (openInNewTabUrl.value) window.open(openInNewTabUrl.value, '_blank', 'noopener');
}

async function load() {
    releaseBlob();
    abortCurrent();

    const id = ann.value?.id;
    if (!id) return;

    const mine = ++seq;
    controller = new AbortController();
    loading.value = true;
    progress.value = 0;
    errorTitle.value = '';
    errorDetail.value = '';

    try {
        const token = store.state.token;
        const resp = await fetch(proxyUrl.value, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            signal: controller.signal,
        });

        if (!resp.ok) {
            let detail = '';
            try {
                const data = await resp.json();
                detail = data?.detail || '';
            } catch (e) {
                // 上游返回的是非 JSON（例如网关错误页），下面按状态码给通用文案
            }
            if (mine !== seq) return;
            errorTitle.value = resp.status === 404 ? '原文不可用' : '原文加载失败';
            errorDetail.value = detail
                || (resp.status === 404 ? '这条公告没有原文附件，或已不在当前股票池范围内。' : `请求失败（${resp.status}）`);
            return;
        }

        const total = Number(resp.headers.get('content-length') || 0);
        const type = (resp.headers.get('content-type') || '').toLowerCase();
        if (!type.includes('pdf')) {
            if (mine !== seq) return;
            errorTitle.value = '原文加载失败';
            errorDetail.value = '服务端返回的不是 PDF 文件。';
            return;
        }

        // 手动读流：为了显示进度（几百 KB 在代理链路上可能要等一下），
        // 也让关闭抽屉能立刻中止，不必等整包下完。
        const reader = resp.body?.getReader();
        if (!reader) {
            const blob = await resp.blob();
            if (mine !== seq) return;
            pdfUrl.value = URL.createObjectURL(blob);
            pdfBytes.value = blob.size;
            return;
        }

        const chunks = [];
        let received = 0;
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            if (mine !== seq) return;   // 已切到别的公告，别把旧数据拼进来
            chunks.push(value);
            received += value.length;
            if (total) progress.value = Math.min(99, Math.round((received / total) * 100));
        }
        if (mine !== seq) return;

        const blob = new Blob(chunks, { type: 'application/pdf' });
        pdfUrl.value = URL.createObjectURL(blob);
        pdfBytes.value = blob.size;
        progress.value = 100;
    } catch (e) {
        if (e?.name === 'AbortError') return;   // 主动中止，不是错误
        if (mine !== seq) return;
        errorTitle.value = '原文加载失败';
        // fetch 的网络层错误是英文的（"Failed to fetch" / "Load failed"），
        // 直接甩给用户既看不懂也帮不上忙，统一换成可操作的中文提示。
        const msg = String(e?.message || '');
        errorDetail.value = /fetch|network|load failed/i.test(msg) || e instanceof TypeError
            ? '网络异常或请求被拦截，请稍后重试；也可以直接打开巨潮原文查看。'
            : (msg || '网络异常，请稍后重试');
    } finally {
        if (mine === seq) loading.value = false;
    }
}

// 打开或切换公告时加载；关闭时中止并释放 blob
watch(
    () => [props.visible, ann.value?.id],
    ([visible]) => {
        if (!visible) {
            abortCurrent();
            releaseBlob();
            return;
        }
        if (ann.value?.id) load();
    },
    { immediate: true }
);

onBeforeUnmount(() => {
    abortCurrent();
    releaseBlob();
});

function retry() {
    load();
}
</script>

<template>
    <!-- ⚠️ 抽屉内容区的 padding/overflow 必须走 pt 的内联 style：
         PrimeVue 4 没有 body-class（v3 的 API），而且 Drawer 是 Teleport 出去的，
         整条 DOM 都不带本组件的 data-v 属性，scoped 里的 :deep(.p-drawer-content)
         一个也匹配不到（编译成 [data-v-xxx] .p-drawer-content，祖先上没这个属性）。
         内联样式没有这个问题，也不依赖选择器优先级。 -->
    <Drawer
        v-model:visible="open"
        position="right"
        :footer="false"
        :pt="{
            content: {
                class: 'pdf-drawer-content',
                style: { padding: '0', overflow: 'hidden' },
            },
        }"
        class="!w-full md:!w-[88vw] lg:!w-[76rem]"
    >
        <template #header>
            <div class="pdf-head">
                <div class="pdf-head-title">
                    <i class="pi pi-file-pdf"></i>
                    <span>公告原文</span>
                    <span v-if="ann.symbol" class="pdf-head-symbol">{{ ann.symbol }}</span>
                    <span v-if="sizeText" class="pdf-head-size">{{ sizeText }}</span>
                </div>
                <div class="pdf-head-sub" :title="ann.title">{{ ann.title || '' }}</div>
            </div>
        </template>

        <!-- ⚠️ 这一层 wrapper 是必须的：Drawer 的 .p-drawer-content 是 overflow-y:auto
             + height:100%，页面里如果有「固定高工具栏 + height:100% 的正文」两个兄弟，
             两者相加必然超过内容区高度 → 抽屉内凭空多出一整条外层滚动条（正文区域
             自己还要滚）。这里让 wrapper 独占 100%，内部用 flex 分配，工具栏不收缩、
             正文吃掉剩余高度，内容区的滚动被 :deep 关掉。 -->
        <div class="pdf-root">
            <!-- 顶栏：元信息 + 操作。单独一行，避免和 Drawer 自带的关闭按钮挤在一起 -->
            <div class="pdf-toolbar">
                <div class="pdf-meta">
                    <span>{{ ann.announce_date || '--' }}</span>
                    <span v-if="ann.stock_name" class="pdf-meta-strong">{{ ann.stock_name }}</span>
                    <span v-if="ann.category" class="pdf-tag">{{ ann.category }}</span>
                </div>
                <div class="pdf-actions">
                    <Button
                        type="button"
                        icon="pi pi-external-link"
                        label="新窗口"
                        size="small"
                        text
                        severity="secondary"
                        :disabled="!openInNewTabUrl"
                        title="在浏览器新标签页打开（同源代理，支持分页加载）"
                        @click="openInNewTab"
                    />
                    <Button
                        type="button"
                        icon="pi pi-download"
                        label="下载"
                        size="small"
                        text
                        severity="secondary"
                        title="下载这份 PDF"
                        @click="download"
                    />
                </div>
            </div>

            <div class="pdf-body">
                <!-- 加载中：给百分比。拿不到总长（无 content-length）时显示不定态 -->
                <div v-if="loading" class="pdf-state">
                    <i class="pi pi-spin pi-spinner pdf-state-icon"></i>
                    <div class="pdf-state-title">正在加载公告原文…</div>
                    <div v-if="progress > 0" class="pdf-state-bar">
                        <div class="pdf-state-bar-inner" :style="{ width: `${progress}%` }"></div>
                    </div>
                    <div v-if="progress > 0" class="pdf-state-hint">{{ progress }}%</div>
                </div>

                <!-- 失败：说清原因，并给「新窗口」这条退路（代理挂了但直链可能仍可打开） -->
                <div v-else-if="errorTitle" class="pdf-state">
                    <i class="pi pi-exclamation-circle pdf-state-icon pdf-state-icon-warn"></i>
                    <div class="pdf-state-title">{{ errorTitle }}</div>
                    <div class="pdf-state-hint">{{ errorDetail }}</div>
                    <div class="pdf-state-actions">
                        <Button type="button" label="重试" size="small" severity="secondary" @click="retry" />
                        <a
                            v-if="ann.pdf_url"
                            :href="ann.pdf_url"
                            target="_blank"
                            rel="noopener"
                            class="pdf-fallback-link"
                        >直接打开巨潮原文</a>
                    </div>
                </div>

                <!-- 正常：iframe 铺满。PDF 由浏览器内置阅读器渲染（白底文档，暗色主题下也是白底，属正常） -->
                <iframe
                    v-else-if="pdfUrl"
                    :src="pdfUrl"
                    :title="ann.title || '公告原文'"
                    class="pdf-frame"
                ></iframe>
            </div>
        </div>
    </Drawer>
</template>

<style scoped lang="scss">
.pdf-head {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
}

.pdf-head-title {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--app-text-primary);
}

.pdf-head-title i {
    color: var(--app-link);
}

.pdf-head-symbol {
    padding: 1px 6px;
    border-radius: 3px;
    background: var(--app-bg-active);
    color: var(--app-text-secondary);
    font-size: 0.85rem;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
}

.pdf-head-size {
    color: var(--app-text-muted);
    font-size: 0.85rem;
    font-weight: 400;
}

.pdf-head-sub {
    color: var(--app-text-secondary);
    font-size: 0.92rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* 内容区的 padding/overflow 在 <Drawer :pt> 里用内联 style 处理（原因见模板注释：
   Drawer 是 Teleport 出去的，整条 DOM 不带本组件的 data-v，:deep 匹配不到）。 */

/* 撑满内容区。100% 只在这里算一次，内层全部按 flex 分配，不做百分比高度相加 */
.pdf-root {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--app-bg-page);
}

.pdf-body {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--app-bg-page);
}

.pdf-toolbar {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
    padding: 0.4rem 1rem;
    border-bottom: 1px solid var(--app-border-base);
    background: var(--app-bg-card);
}

.pdf-meta {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    color: var(--app-text-secondary);
    font-variant-numeric: tabular-nums;
}

.pdf-meta-strong {
    color: var(--app-text-primary);
    font-weight: 500;
}

.pdf-tag {
    padding: 1px 7px;
    border-radius: 3px;
    border: 1px solid var(--app-border-strong);
    background: var(--app-bg-active);
    color: var(--app-text-secondary);
    font-size: 11px;
    line-height: 18px;
}

.pdf-actions {
    display: flex;
    align-items: center;
    gap: 0.25rem;
}

/* iframe 必须 flex:1 + min-height:0，否则在 flex 容器里会被内容高度顶开而不是滚动 */
.pdf-frame {
    flex: 1 1 auto;
    width: 100%;
    min-height: 0;
    border: 0;
    background: var(--app-bg-card);
}

.pdf-state {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 2rem;
    text-align: center;
}

.pdf-state-icon {
    font-size: 1.8rem;
    color: var(--app-link);
}

.pdf-state-icon-warn {
    color: var(--app-warn-text);
}

.pdf-state-title {
    color: var(--app-text-primary);
    font-size: 1rem;
    font-weight: 500;
}

.pdf-state-hint {
    color: var(--app-text-muted);
    max-width: 30rem;
    line-height: 1.5;
}

.pdf-state-bar {
    width: 12rem;
    height: 4px;
    border-radius: 2px;
    overflow: hidden;
    background: var(--app-bg-active);
}

.pdf-state-bar-inner {
    height: 100%;
    background: var(--app-link);
    transition: width 0.15s ease;
}

.pdf-state-actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.25rem;
}

.pdf-fallback-link {
    color: var(--app-link);
    font-size: 0.92rem;
    text-decoration: none;
}

.pdf-fallback-link:hover {
    text-decoration: underline;
}
</style>
