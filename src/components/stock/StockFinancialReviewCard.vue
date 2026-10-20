<script setup>
import {ref, onMounted, watch} from 'vue'
import {store} from '@/store'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import {useNotification} from '@/composables/useNotification'

const props = defineProps({
    stockCode: {type: String, required: true},
    stockName: {type: String, default: ''},
})

const {showError} = useNotification()

const reviewText = ref('')          // 展示中的点评正文（来自每日生成结果或手动流式生成）
const storedMeta = ref(null)        // 已存点评元信息 {review_date, report_date, update_time, model}
const loading = ref(false)          // 重新生成（流式）中
const loadingStored = ref(false)    // 拉取每日生成结果中
const errorMsg = ref('')            // 错误提示
const abortController = ref(null)

async function loadStored() {
    loadingStored.value = true
    errorMsg.value = ''
    try {
        const token = store.state.token
        const response = await fetch(`/api/v1/stock/financial_review/${props.stockCode}`, {
            headers: {
                ...(token ? {'Authorization': `Bearer ${token}`} : {}),
            },
        })
        const ctype = String(response.headers.get('content-type') || '')
        if (response.status === 200 && ctype.includes('text/html')) {
            // 后端没这个接口时 SPA 兜底会返回 index.html（200），原样渲染会一团糟
            throw new Error('后端未提供财务点评接口（服务端版本可能落后于前端），请重新部署/重启后端后重试。')
        }
        if (!response.ok) {
            const text = await response.text().catch(() => '')
            throw new Error(text || `请求失败: ${response.status}`)
        }
        const data = await response.json()
        const review = data.review
        if (review && review.content) {
            reviewText.value = review.content
            storedMeta.value = {
                review_date: review.review_date,
                report_date: review.report_date,
                update_time: review.update_time,
                model: review.model,
            }
        } else {
            // 该票尚无每日生成结果：清空，等待用户手动生成（不报错）
            reviewText.value = ''
            storedMeta.value = null
        }
    } catch (e) {
        // 拉取失败不阻塞：保留已有正文（若有），降级为空状态由用户手动生成
        storedMeta.value = null
        if (e.name !== 'AbortError') {
            errorMsg.value = e.message || '加载点评失败'
        }
    } finally {
        loadingStored.value = false
    }
}

async function generate() {
    if (loading.value) return
    reviewText.value = ''
    errorMsg.value = ''
    storedMeta.value = null
    loading.value = true

    abortController.value = new AbortController()
    const wasAborted = () => abortController.value?.signal.aborted
    try {
        const token = store.state.token
        const response = await fetch(`/api/v1/stock/financial_review/${props.stockCode}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token ? {'Authorization': `Bearer ${token}`} : {}),
            },
            body: JSON.stringify({stock_name: props.stockName || '', periods: 12}),
            signal: abortController.value.signal,
        })

        const ctype = String(response.headers.get('content-type') || '')
        if (response.status === 200 && ctype.includes('text/html')) {
            throw new Error('后端未提供财务点评接口（服务端版本可能落后于前端），请重新部署/重启后端后重试。')
        }
        if (!response.ok) {
            const text = await response.text().catch(() => '')
            throw new Error(text || `请求失败: ${response.status}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        while (true) {
            const {done, value} = await reader.read()
            if (done) break
            reviewText.value += decoder.decode(value, {stream: true})
        }
    } catch (e) {
        if (e.name !== 'AbortError') {
            errorMsg.value = e.message || '生成失败，请稍后重试'
            showError(errorMsg.value)
        }
    } finally {
        loading.value = false
        // 重新生成后回拉已存记录，刷新元信息（财务期 / 生成日期），失败则保留流式正文
        if (!wasAborted()) {
            await loadStored()
        }
    }
}

function regenerate() {
    generate()
}

function stop() {
    abortController.value?.abort()
    loading.value = false
}

onMounted(loadStored)
// 切换股票时重新拉取该票的每日生成结果（tab4 用 v-show，组件常驻）
watch(() => props.stockCode, (nv, ov) => {
    if (nv && nv !== ov) {
        abortController.value?.abort()
        reviewText.value = ''
        storedMeta.value = null
        loadStored()
    }
})
</script>

<template>
    <Card class="buffett-card">
        <!-- 头部：巴菲特品牌标识 -->
        <template #header>
            <div class="buffett-head">
                <div class="buffett-avatar">🎩</div>
                <div class="buffett-title">
                    <div class="buffett-title__main">
                        巴菲特视角的财务点评
                        <Tag value="每日盘后自动生成" class="buffett-tag" severity="warn"/>
                    </div>
                    <div class="buffett-title__sub">由系统智能体基于最新财务数据生成，以价值投资视角点评这门生意</div>
                </div>
            </div>
        </template>

        <!-- 生成中（手动流式） -->
        <div v-if="loading" class="buffett-loading">
            <div class="buffett-loading__bar">
                <i class="pi pi-spin pi-spinner buffett-spinner"></i>
                <span>巴菲特正在研读财报…</span>
                <Button label="停止" icon="pi pi-stop" severity="secondary" text size="small" class="ml-auto" @click="stop"/>
            </div>
            <div v-if="reviewText" class="buffett-stream">
                <MarkdownRenderer fontSize="12px" :markdown="reviewText"/>
                <span class="buffett-cursor"></span>
            </div>
            <div v-else class="buffett-loading__hint">正在拉取财务数据并组织点评…</div>
        </div>

        <!-- 结果态（每日生成结果 / 手动生成结果） -->
        <div v-else-if="reviewText" class="buffett-result">
            <div v-if="errorMsg" class="buffett-error">
                <Message severity="error" :closable="false">{{ errorMsg }}</Message>
            </div>
            <div v-if="storedMeta" class="buffett-meta">
                <span>基于 <strong>{{ storedMeta.report_date || '最新' }}</strong> 财报</span>
                <span class="buffett-meta__dot">·</span>
                <span>生成于 {{ storedMeta.review_date }}</span>
            </div>
            <MarkdownRenderer fontSize="12px" :markdown="reviewText"/>
            <div class="buffett-actions">
                <Button label="重新生成" icon="pi pi-refresh" severity="warning" outlined @click="regenerate"/>
            </div>
        </div>

        <!-- 拉取每日结果中 -->
        <div v-else-if="loadingStored" class="buffett-loading">
            <div class="buffett-loading__bar">
                <i class="pi pi-spin pi-spinner buffett-spinner"></i>
                <span>正在读取已生成的财务点评…</span>
            </div>
        </div>

        <!-- 空状态：尚无每日生成结果 -->
        <div v-else class="buffett-empty">
            <p class="buffett-empty__text">
                让系统智能体以巴菲特的视角，读一遍这家公司的财报，
                从<strong>护城河、盈利质量、负债、自由现金流、估值安全边际</strong>几个维度给出点评。
                <br/>（该标的暂无预生成的财务点评，可手动触发一次。）
            </p>
            <Button
                label="生成巴菲特视角点评"
                icon="pi pi-sparkles"
                severity="warning"
                @click="generate"
            />
        </div>
    </Card>
</template>

<style scoped lang="scss">
.buffett-card {
    margin-bottom: 1.25rem;
}

.buffett-head {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.9rem 1.1rem;
    border-bottom: 1px solid var(--p-content-border-color, #e5e7eb);
}

.buffett-avatar {
    width: 2.75rem;
    height: 2.75rem;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.4rem;
    flex-shrink: 0;
    background: linear-gradient(135deg, #f7d774 0%, #c8951f 100%);
    box-shadow: 0 2px 6px rgba(200, 149, 31, 0.35);
}

.buffett-title__main {
    font-weight: 600;
    font-size: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
}

.buffett-tag {
    font-size: 0.7rem;
}

.buffett-title__sub {
    font-size: 0.78rem;
    color: var(--p-text-muted-color, #6b7280);
    margin-top: 0.15rem;
}

.buffett-empty {
    padding: 1.25rem 1.1rem;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
}

.buffett-empty__text {
    margin: 0;
    font-size: 0.85rem;
    line-height: 1.6;
    color: var(--p-text-color, #374151);
}

.buffett-loading {
    padding: 1rem 1.1rem;
}

.buffett-loading__bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    color: var(--p-text-muted-color, #6b7280);
    margin-bottom: 0.75rem;
}

.buffett-spinner {
    font-size: 1rem;
    color: #c8951f;
}

.buffett-loading__hint {
    font-size: 0.82rem;
    color: var(--p-text-muted-color, #6b7280);
}

.buffett-stream {
    font-size: 0.85rem;
}

.buffett-cursor {
    display: inline-block;
    width: 0.5rem;
    height: 1rem;
    margin-left: 2px;
    vertical-align: text-bottom;
    background: #c8951f;
    animation: buffett-blink 1s step-start infinite;
}

@keyframes buffett-blink {
    50% {
        opacity: 0;
    }
}

.buffett-result {
    padding: 1rem 1.1rem;
}

.buffett-meta {
    font-size: 0.76rem;
    color: var(--p-text-muted-color, #6b7280);
    margin-bottom: 0.75rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;

    &__dot {
        opacity: 0.6;
    }

    strong {
        color: var(--p-text-color, #374151);
        font-weight: 600;
    }
}

.buffett-error {
    margin-bottom: 0.75rem;
}

.buffett-actions {
    margin-top: 1rem;
    display: flex;
    justify-content: flex-end;
}
</style>
