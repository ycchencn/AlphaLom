<script setup>
import {ref, computed, onMounted, watch, nextTick} from 'vue'
import axios from 'axios'
import {store} from '@/store'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import {useNotification} from '@/composables/useNotification'

const props = defineProps({
    stockCode: {type: String, required: true},
    stockName: {type: String, default: ''},
})

const {showError} = useNotification()

// ---------- 智能体列表 ----------
const agents = ref([])
const agentsLoading = ref(false)
const currentAgentId = ref(null)

function fetchAgents() {
    agentsLoading.value = true
    return axios.get('/api/v1/agents')
        .then((r) => {
            agents.value = r.data?.data || []
            if (currentAgentId.value === null && agents.value.length > 0) {
                currentAgentId.value = agents.value[0].id
            }
        })
        .catch(() => {
            agents.value = []
            showError('加载智能体列表失败')
        })
        .finally(() => {
            agentsLoading.value = false
        })
}

const currentAgent = computed(() => agents.value.find(a => a.id === currentAgentId.value) || null)

// 输入框占位符（避免在模板属性里写复杂表达式）
const placeholderText = computed(() =>
    '向智能体提问关于 ' + props.stockCode + ' ' + (props.stockName || '') + ' 的问题…')

// ---------- 会话 / 消息 ----------
const messages = ref([])  // {id, role: user|assistant|tool, content, isLoading, name?, args?, summary?}
const inputMessage = ref('')
const isLoading = ref(false)
// Agent 模式开关。默认值不是写死的 true —— 后端 MCP_HOST 未配置时会静默降级为纯文本，
// 此时开关若仍显示为开启，用户会以为在用工具，实际拿到的是纯模型回答。
// 所以先问后端「这台部署到底有没有 MCP」，再决定默认值和可用性。
const useTools = ref(false)
const mcpEnabled = ref(true)
function fetchMcpStatus() {
    return axios.get('/api/v1/chat/mcp_status')
        .then((r) => {
            const on = !!r.data?.data?.mcp_enabled
            mcpEnabled.value = on
            useTools.value = on
        })
        .catch(() => {
            // 拿不到状态时保守处理：按不可用处理，避免又出现「以为在用工具」
            mcpEnabled.value = false
            useTools.value = false
        })
}
const scrollAnchor = ref(null)
const abortController = ref(new AbortController())

const genId = () => `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`

function scrollToBottom() {
    nextTick(() => scrollAnchor.value?.scrollIntoView({behavior: 'smooth'}))
}

watch(() => messages.value, () => scrollToBottom(), {deep: true})

// 从后端（Redis）拉取该股票 + 该智能体的历史对话
function loadAgentSession(agentId) {
    if (!agentId) {
        messages.value = []
        return Promise.resolve()
    }
    return axios.get('/api/v1/chat/agent_session', {
        params: {agent_id: agentId, stock_code: props.stockCode},
    })
        .then((r) => {
            const hist = r.data?.data || []
            // 后端只存 user/assistant 纯文本，工具步骤不持久化
            messages.value = hist.map(h => ({
                id: genId(),
                role: h.role,
                content: h.content || '',
                isLoading: false,
            }))
        })
        .catch(() => {
            messages.value = []
        })
}

// 清空会话
function clearSession() {
    if (!currentAgentId.value) return
    axios.post('/api/v1/chat/clear_session', {
        agent_id: currentAgentId.value,
        stock_code: props.stockCode,
    })
        .then(() => {
            messages.value = []
        })
        .catch(() => showError('清空会话失败'))
}

function selectAgent(agentId) {
    if (currentAgentId.value === agentId) return
    currentAgentId.value = agentId
    abortController.value.abort()
    abortController.value = new AbortController()
    loadAgentSession(agentId)
    scrollToBottom()
}

// ---------- 发送（NDJSON 流式） ----------
let currentAssistantId = null

function handleEvent(evt) {
    if (evt.type === 'text') {
        let idx = messages.value.findIndex(m => m.id === currentAssistantId)
        if (idx === -1) {
            const id = genId()
            messages.value.push({id, role: 'assistant', content: '', isLoading: true})
            currentAssistantId = id
            idx = messages.value.length - 1
        }
        messages.value[idx].content += evt.data
    } else if (evt.type === 'tool') {
        // 工具步骤作为独立可折叠卡片插入；之后若有文本则新开一条 assistant
        messages.value.push({
            id: genId(),
            role: 'tool',
            name: evt.name,
            args: evt.args || {},
            summary: evt.summary || '',
            isLoading: false,
        })
        currentAssistantId = null
    } else if (evt.type === 'error') {
        const idx = messages.value.findIndex(m => m.id === currentAssistantId)
        if (idx !== -1) {
            messages.value[idx].content += '\n\n' + (evt.data || '出错了')
            messages.value[idx].isLoading = false
        }
    }
}

const sendMessage = async () => {
    if (!inputMessage.value.trim() || isLoading.value || !currentAgentId.value) return

    const text = inputMessage.value.trim()
    messages.value.push({id: genId(), role: 'user', content: text})
    inputMessage.value = ''

    const aiId = genId()
    messages.value.push({id: aiId, role: 'assistant', content: '', isLoading: true})
    currentAssistantId = aiId
    scrollToBottom()
    isLoading.value = true

    abortController.value.abort()
    abortController.value = new AbortController()

    try {
        const token = store.state.token
        const response = await fetch('/api/v1/chat/agent_stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token ? {'Authorization': `Bearer ${token}`} : {}),
            },
            body: JSON.stringify({
                message: text,
                agent_id: currentAgentId.value,
                stock_code: props.stockCode,
                stock_name: props.stockName,
                use_tools: useTools.value,
            }),
            signal: abortController.value.signal,
        })
        if (!response.ok) throw new Error(`请求失败: ${response.status}`)

        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''
        while (true) {
            const {done, value} = await reader.read()
            if (done) break
            buffer += decoder.decode(value, {stream: true})
            let nl
            while ((nl = buffer.indexOf('\n')) >= 0) {
                const line = buffer.slice(0, nl)
                buffer = buffer.slice(nl + 1)
                if (!line.trim()) continue
                try {
                    handleEvent(JSON.parse(line))
                } catch (e) {
                    // 单行解析失败忽略，继续后续
                    console.warn('解析流式事件失败:', line, e)
                }
            }
        }
    } catch (error) {
        if (error.name !== 'AbortError') {
            const idx = messages.value.findIndex(m => m.id === currentAssistantId)
            if (idx !== -1) {
                messages.value[idx].content += `\n\n出错了：${error.message || '网络异常'}`
            }
            console.error('发送失败:', error)
        }
    } finally {
        // 统一结束所有 loading 态
        messages.value.forEach(m => {
            if (m.role === 'assistant') m.isLoading = false
        })
        currentAssistantId = null
        isLoading.value = false
    }
}

onMounted(async () => {
    await Promise.all([fetchAgents(), fetchMcpStatus()])
    if (currentAgentId.value !== null) {
        await loadAgentSession(currentAgentId.value)
    }
    scrollToBottom()
})
</script>

<template>
    <div class="flex flex-col h-full bg-gray-50">

        <!-- 顶部操作栏：智能体选择 + agent 模式开关 + 清空 -->
        <div class="flex items-center gap-2 p-3 bg-white border-b border-gray-200 shrink-0 flex-wrap">
            <span class="text-xs text-gray-500 whitespace-nowrap">智能体</span>
            <select
                v-model="currentAgentId"
                :disabled="agentsLoading"
                @change="selectAgent(currentAgentId)"
                class="text-sm border border-gray-300 rounded px-2 py-1 bg-white max-w-[12rem]"
            >
                <option :value="null" disabled>请选择智能体</option>
                <option v-for="a in agents" :key="a.id" :value="a.id">
                    {{ a.emoji || '🤖' }} {{ a.name }}
                </option>
            </select>

            <label
                class="flex items-center gap-1 text-xs ml-1"
                :class="mcpEnabled ? 'text-gray-600 cursor-pointer' : 'text-gray-400 cursor-not-allowed'"
                :title="mcpEnabled ? '调用本系统 MCP 工具获取行情/财务/新闻' : '当前部署未配置 MCP_HOST，Agent 模式不可用'"
            >
                <input type="checkbox" v-model="useTools" :disabled="!mcpEnabled"/>
                Agent 模式（调用本系统数据）
            </label>

            <Button
                label="清空"
                icon="pi pi-trash"
                severity="secondary"
                text
                size="small"
                class="ml-auto"
                :disabled="!currentAgentId || isLoading"
                @click="clearSession"
            />
        </div>

        <!-- 消息区 -->
        <div class="flex-1 overflow-auto p-4 bg-gray-50" ref="messageContainer">
            <div v-if="!currentAgent" class="flex items-center justify-center h-full text-gray-400 text-sm">
                请先在上方选择一个智能体
            </div>
            <template v-else>
                <div v-for="msg in messages" :key="msg.id" class="mb-3">
                    <!-- 用户消息 -->
                    <div v-if="msg.role === 'user'" class="flex justify-end">
                        <div class="solid-primary rounded-lg px-4 py-2 max-w-[85%] whitespace-pre-wrap break-words">
                            {{ msg.content }}
                        </div>
                    </div>
                    <!-- 工具步骤卡片（可折叠） -->
                    <div v-else-if="msg.role === 'tool'">
                        <details class="rounded-lg border p-0 text-sm tool-step">
                            <summary class="cursor-pointer px-3 py-2 tool-step-title">
                                🔧 调用工具：{{ msg.name }}
                            </summary>
                            <div class="px-3 pb-3 text-gray-700 space-y-1">
                                <div><span class="text-gray-400">参数：</span>
                                    <pre class="text-xs bg-white rounded p-2 overflow-auto mt-1">{{ JSON.stringify(msg.args, null, 2) }}</pre>
                                </div>
                                <div><span class="text-gray-400">结果摘要：</span>{{ msg.summary }}</div>
                            </div>
                        </details>
                    </div>
                    <!-- AI 消息 -->
                    <div v-else class="flex justify-start">
                        <div class="px-1 py-1 w-[92%]">
                            <MarkdownRenderer fontSize="11px" :markdown="msg.content || ''"/>
                            <Skeleton v-if="msg.isLoading && !msg.content" style="width: 12px" class="inline-block"/>
                        </div>
                    </div>
                </div>
            </template>
            <div ref="scrollAnchor"></div>
        </div>

        <!-- 输入区 -->
        <div class="p-3 bg-white border-t border-gray-200 shrink-0">
            <div class="flex gap-2">
                <InputText
                    v-model="inputMessage"
                    :placeholder="placeholderText"
                    @keyup.enter="sendMessage"
                    class="flex-1"
                    :disabled="isLoading || !currentAgent"
                />
                <Button
                    label="发送"
                    icon="pi pi-send"
                    @click="sendMessage"
                    :disabled="!inputMessage.trim() || isLoading || !currentAgent"
                    severity="primary"
                />
            </div>
        </div>
    </div>
</template>

<style scoped lang="scss">
::-webkit-scrollbar {
    width: 6px;
}
::-webkit-scrollbar-track {
    background: var(--app-bg-subtle);
}
::-webkit-scrollbar-thumb {
    background: var(--app-text-muted);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--app-text-secondary);
}

/* 工具调用步骤卡片：原本写的是 border-blue-200 / bg-blue-50/60 / text-blue-700，
   暗色下 bg-blue-50/60 是一层浅蓝白雾、和白字叠在一起读不清。
   走 --app-info-* 语义层（浅色淡蓝底 / 暗色深靛底），并显式声明 color ——
   summary 在部分浏览器里不继承 details 的 color。 */
.tool-step {
    background: var(--app-info-bg);
    border-color: var(--app-info-border);
    color: var(--app-text-primary);
}

.tool-step-title {
    color: var(--app-icon-info);
}
</style>
