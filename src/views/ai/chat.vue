<script setup>

import {useNotification} from '@/composables/useNotification';
import {onMounted, onUnmounted, ref, computed, reactive, watch, nextTick} from 'vue';
import axios from 'axios';
import {store} from '@/store';
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import {useToast} from 'primevue/usetoast'

const toast = useToast()
const {showSuccess, showError} = useNotification();

// ---------- 智能体列表（后端驱动） ----------

const agents = ref([]);
const loadingAgents = ref(false);
const currentAgentId = ref(null);

// 平台下拉 + 模型联动（与 LLM 设置页同模式）
const platforms = ref([]);
const modelOptionsByPlatform = ref({});
const modelsLoading = reactive({});

function normalizeModel(model) {
    if (Array.isArray(model)) return model[0] || '';
    return model || '';
}

const modelOptions = (platform) => modelOptionsByPlatform.value[platform] || [];

function loadLlmModels(platform) {
    if (!platform || modelOptionsByPlatform.value[platform]) return Promise.resolve();
    modelsLoading[platform] = true;
    return axios.get('/api/v1/llm/models', {params: {platform}})
        .then((response) => {
            const info = (response.data || {})[platform];
            modelOptionsByPlatform.value[platform] = info?.models || [];
            if (info?.error) {
                showError(`获取 ${platform} 模型列表失败：${info.error}`);
            }
        })
        .catch(() => {
            modelOptionsByPlatform.value[platform] = [];
            showError(`获取 ${platform} 模型列表失败，可手动输入模型名称`);
        })
        .finally(() => {
            modelsLoading[platform] = false;
        });
}

function fetchAgents() {
    loadingAgents.value = true;
    return axios.get('/api/v1/agents')
        .then((response) => {
            const data = response.data?.data || [];
            // 后端只存配置字段，messages 是前端运行时的对话状态，需初始化
            agents.value = data.map(a => ({...a, messages: a.messages || []}));
            // 如果当前没有选中任何智能体，自动选第一个
            if (currentAgentId.value === null && data.length > 0) {
                currentAgentId.value = data[0].id;
            }
        })
        .catch(() => {
            agents.value = [];
            showError('加载智能体列表失败');
        })
        .finally(() => {
            loadingAgents.value = false;
        });
}

function fetchPlatforms() {
    return axios.get('/api/v1/settings/llm_models')
        .then((response) => {
            platforms.value = response.data?.platforms || [];
        })
        .catch(() => {
            platforms.value = [];
        });
}

// 从后端（Redis）拉取指定智能体的历史对话，刷新/切换后恢复界面
function loadSession(agentId) {
    if (!agentId) return Promise.resolve();
    return axios.get('/api/v1/chat/session', {params: {agent_id: agentId}})
        .then((response) => {
            const history = response.data?.data || [];
            const agent = agents.value.find(a => a.id === agentId);
            if (agent) {
                // 后端存的是 {role, content} 纯数据，前端需补上 id / isLoading 运行态字段
                agent.messages = history.map(h => ({
                    id: generateMsgId(),
                    role: h.role,
                    content: h.content || '',
                    isLoading: false,
                }));
            }
        })
        .catch(() => {
            // 拉取失败不影响当前对话（保持空即可）
        });
}

// ---------- 计算属性 ----------

const currentAgent = computed(() => {
    return agents.value.find(a => a.id === currentAgentId.value) || null;
});

// ---------- 发送消息 ----------

const inputMessage = ref('')
const isLoading = ref(false)
const scrollAnchor = ref(null)
const abortController = ref(new AbortController())
const sessionId = ref('')

// 每个智能体独立 session（以 agent.id 生成）
function getAgentSessionId(agentId) {
    return `session_agent_${agentId}`
}

const scrollToBottom = () => {
    nextTick(() => {
        scrollAnchor.value?.scrollIntoView({behavior: 'smooth'})
    })
}

// 监听消息变化自动滚动
watch(
    () => currentAgent.value?.messages,
    () => scrollToBottom(),
    {deep: true}
)

const generateMsgId = () => `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`

// 发送消息
const sendMessage = async () => {
    if (!inputMessage.value.trim() || isLoading.value || !currentAgent.value) return

    const userMsg = {
        id: generateMsgId(),
        role: 'user',
        content: inputMessage.value.trim()
    }
    currentAgent.value.messages.push(userMsg)
    inputMessage.value = ''
    scrollToBottom()

    const aiMsgId = generateMsgId()
    const loadingMsg = {
        id: aiMsgId,
        role: 'assistant',
        content: '',
        isLoading: true
    }
    currentAgent.value.messages.push(loadingMsg)
    scrollToBottom()
    isLoading.value = true

    abortController.value.abort()
    abortController.value = new AbortController()

    try {
        // ⚠️ 原生 fetch 不经过 axios 拦截器，必须手工带令牌，否则 401
        const token = store.state.token
        const response = await fetch('/api/v1/chat/stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(token ? {'Authorization': `Bearer ${token}`} : {}),
            },
            body: JSON.stringify({
                message: userMsg.content,
                session_id: getAgentSessionId(currentAgentId.value),
                agent_id: currentAgentId.value,
            }),
            signal: abortController.value.signal
        })

        if (!response.ok) throw new Error(`请求失败: ${response.status}`)

        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let aiMsgIndex = currentAgent.value.messages.findIndex(m => m.id === aiMsgId)

        while (true) {
            const {done, value} = await reader.read()
            if (done) break
            const chunk = decoder.decode(value, {stream: true})
            if (aiMsgIndex !== -1) {
                currentAgent.value.messages[aiMsgIndex].content += chunk
            }
        }

        currentAgent.value.messages[aiMsgIndex].isLoading = false
    } catch (error) {
        if (error.name !== 'AbortError') {
            const aiMsgIndex = currentAgent.value.messages.findIndex(m => m.id === aiMsgId)
            currentAgent.value.messages[aiMsgIndex].content = `出错了：${error.message || '网络异常'}`
            currentAgent.value.messages[aiMsgIndex].isLoading = false
            console.error('发送失败:', error)
        }
    } finally {
        isLoading.value = false
    }
}

// ---------- 切换智能体 ----------

function selectAgent(agentId) {
    if (currentAgentId.value === agentId) return
    currentAgentId.value = agentId
    loadSession(agentId)
    scrollToBottom()
}

// ---------- 编辑相关 ----------

const showEditDialog = ref(false)
const editingAgent = ref({}) // 编辑中的智能体副本
const savingAgent = ref('') // 正在保存的 agent id

function editAgent(agentId) {
    const agent = agents.value.find(a => a.id === agentId)
    if (agent) {
        editingAgent.value = {...agent} // 浅拷贝足够（全是简单类型）
        showEditDialog.value = true
    }
}

function cancelEdit() {
    showEditDialog.value = false
    editingAgent.value = {}
}

// 切换平台：拉该平台的模型列表，并清掉在新平台上不存在的旧模型
function onPlatformChange() {
    const form = editingAgent.value;
    loadLlmModels(form.platform);
    const options = modelOptions(form.platform);
    if (form.model && options.length && !options.includes(form.model)) {
        form.model = options[0];
    }
}

function saveAgent() {
    const form = editingAgent.value;
    if (!form.name || !form.name.trim()) {
        showError('名称不能为空');
        return;
    }
    if (!form.platform) {
        showError('请先选择平台');
        return;
    }
    if (!String(form.model || '').trim()) {
        showError('请选择或输入模型名称');
        return;
    }
    savingAgent.value = form.id || 'new';

    const payload = {
        name: form.name.trim(),
        emoji: form.emoji || '🤖',
        platform: form.platform,
        model: String(form.model).trim(),
        system_prompt: form.system_prompt || '',
    };

    const isEdit = form.id !== undefined && form.id !== null;
    const request = isEdit
        ? axios.put(`/api/v1/agents/${form.id}`, payload)
        : axios.post('/api/v1/agents', payload);

    request
        .then((response) => {
            const saved = response.data?.data;
            if (isEdit) {
                const index = agents.value.findIndex(a => a.id === form.id);
                // 后端 to_dict 不含 messages，必须补齐，且编辑时保留已有对话
                if (index !== -1) {
                    agents.value[index] = {...saved, messages: agents.value[index].messages || []};
                }
            } else {
                // 新建：后端返回没有 messages 字段，补上空数组，否则 sendMessage 会 undefined.push 报错
                agents.value.push({...saved, messages: []});
                currentAgentId.value = saved.id;
            }
            showSuccess(isEdit ? '智能体已更新' : `智能体"${saved.name}"已创建`, 2000);
            showEditDialog.value = false;
            editingAgent.value = {};
        })
        .catch((e) => {
            showError(e.response?.data?.detail || e.response?.data?.message || '操作失败');
        })
        .finally(() => {
            savingAgent.value = '';
        });
}

// ---------- 新建智能体 ----------

function addAgent() {
    const template = {
        id: null,
        name: '新智能体',
        emoji: '🧠',
        model: '',
        systemPrompt: '',
        messages: [],
        platform: '',
        system_prompt: '',
    };
    editingAgent.value = {...template};
    showEditDialog.value = true;
}

// ---------- 删除智能体 ----------

function deleteAgent(agentId) {
    if (!confirm('确认删除此智能体？')) return;
    axios.delete(`/api/v1/agents/${agentId}`)
        .then(() => {
            agents.value = agents.value.filter(a => a.id !== agentId);
            if (currentAgentId.value === agentId) {
                currentAgentId.value = agents.value.length > 0 ? agents.value[0].id : null;
            }
            showSuccess('智能体已删除', 2000);
        })
        .catch((e) => {
            showError(e.response?.data?.detail || '删除失败');
        });
}

// ---------- 初始化 ----------

onMounted(async () => {
    sessionId.value = generateMsgId(); // 兜底全局 session
    fetchPlatforms();
    await fetchAgents();
    // 进入页面后恢复当前智能体的历史对话（避免刷新即丢）
    if (currentAgentId.value !== null) {
        await loadSession(currentAgentId.value);
    }
    scrollToBottom();
});

onUnmounted(() => {
    abortController.value.abort();
});

</script>

<template>
    <Toast/>
    <div class="flex h-full w-full bg-gray-50">

        <!-- 左侧智能体列表区域 -->
        <div class="w-72 bg-white border-r border-gray-200 flex flex-col overflow-hidden">

            <!-- 智能体列表 -->
            <div class="flex-1 overflow-y-auto p-2">
              <div
                v-for="agent in agents"
                :key="agent.id"
                @click="selectAgent(agent.id)"
                :class="[
                  'agent-item p-3 rounded-lg cursor-pointer mb-2 transition-colors',
                  currentAgentId === agent.id
                    ? 'bg-primary-50 border border-primary-200'
                    : 'hover:bg-gray-100 border border-transparent'
                ]"
              >
                <div class="flex items-center gap-3">
                  <div
                    class="w-10 h-10 rounded-full bg-primary text-white flex items-center justify-center text-lg font-bold"
                  >
                    {{ agent.emoji || '🤖' }}
                  </div>
                  <div class="flex-1 min-w-0">
                    <p class="font-medium text-gray-800 truncate">{{ agent.name }}</p>
                    <p class="text-xs text-gray-400 truncate">{{ agent.model || '--' }}</p>
                  </div>
                  <div class="flex gap-1">
                    <Button
                      icon="pi pi-pencil"
                      severity="secondary"
                      text
                      rounded
                      size="small"
                      @click.stop="editAgent(agent.id)"
                      aria-label="编辑提示词"
                    />
                    <Button
                      icon="pi pi-trash"
                      severity="danger"
                      text
                      rounded
                      size="small"
                      @click.stop="deleteAgent(agent.id)"
                      aria-label="删除智能体"
                    />
                  </div>
                </div>
              </div>
              <div v-if="!loadingAgents && agents.length === 0" class="text-xs text-gray-400 text-center py-4">
                暂无智能体，点击下方按钮创建
              </div>
            </div>

            <!-- 添加智能体按钮 -->
            <div class="p-3 border-t border-gray-200">
                <Button label="新建智能体" icon="pi pi-plus" class="w-full" severity="contrast" @click="addAgent"/>
            </div>
        </div>

        <!-- 右侧对话区域 -->
        <div class="flex-1 flex flex-col" style="height: 85vh">
            <!-- 当前智能体信息头部 -->
            <div v-if="currentAgent" class="p-4 bg-white border-b border-gray-200 flex items-center gap-3">
                <div
                    class="w-10 h-10 rounded-full bg-primary text-white flex items-center justify-center text-lg font-bold"
                >
                    {{ currentAgent.emoji || '🤖' }}
                </div>
                <div>
                    <p class="font-semibold text-gray-800">{{ currentAgent.name }}</p>
                    <p class="text-xs text-gray-500">{{ currentAgent.model || '--' }}</p>
                </div>
            </div>

            <!-- 消息列表 -->
            <div class="flex-1 overflow-auto p-4 bg-gray-50" ref="messageContainer">
                <div v-if="!currentAgent" class="flex items-center justify-center h-full text-gray-400">
                    请从左侧选择一个智能体开始对话
                </div>
                <div v-else class="mb-4" v-for="msg in currentAgent.messages" :key="msg.id">
                    <!-- 用户消息 -->
                    <div class="flex justify-end mb-2" v-if="msg.role === 'user'">
                        <div class="bg-primary text-white rounded-lg px-4 py-2 max-w-[95%]">
                            <p>{{ msg.content }}</p>
                        </div>
                    </div>
                    <!-- AI消息 -->
                    <div class="flex justify-start mb-2" v-else>
                        <div class="px-2 py-2 w-[95%]">
                            <MarkdownRenderer fontSize="11px" :markdown="msg.content || ''"/>
                            <Skeleton v-if="msg.isLoading" style="width: 12px" class="inline-block"/>
                        </div>
                    </div>
                </div>
                <div ref="scrollAnchor"></div>
            </div>

            <!-- 输入区域 -->
            <div class="p-4 bg-white border-t border-gray-200">
                <div class="flex gap-2">
                    <InputText
                        v-model="inputMessage"
                        placeholder="输入消息，回车发送..."
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

        <!-- 编辑提示词的对话框（对齐 LLM 配置页交互：平台下拉 → 模型选项联动） -->
        <Dialog
            v-model:visible="showEditDialog"
            header="编辑智能体提示词"
            :modal="true"
            :style="{ width: '60vw' }"
            :breakpoints="{ '960px': '75vw', '640px': '90vw' }"
        >
            <div v-if="editingAgent" class="flex flex-col gap-3">
                <div>
                    <label class="font-medium text-sm">智能体名称</label>
                    <InputText v-model="editingAgent.name" class="w-full mt-1"/>
                </div>
                <div>
                    <label class="font-medium text-sm">平台</label>
                    <Dropdown
                        v-model="editingAgent.platform"
                        :options="platforms"
                        optionLabel="label"
                        optionValue="value"
                        placeholder="选择平台"
                        class="w-full mt-1"
                        @change="onPlatformChange"
                    />
                </div>
                <div>
                    <label class="font-medium text-sm">模型</label>
                    <Dropdown
                        v-model="editingAgent.model"
                        :options="modelOptions(editingAgent.platform)"
                        :loading="modelsLoading[editingAgent.platform]"
                        editable
                        filter
                        placeholder="选择模型，也可手动输入"
                        :empty-message="modelsLoading[editingAgent.platform] ? '正在获取模型列表…' : '该平台暂无可用模型，可手动输入'"
                        class="w-full mt-1"
                    />
                </div>
                <div>
                    <label class="font-medium text-sm">提示词（System Prompt）</label>
                    <Textarea
                        v-model="editingAgent.system_prompt"
                        rows="12"
                        class="w-full mt-1"
                        placeholder="请输入系统提示词..."
                    />
                </div>
                <div>
                    <label class="font-medium text-sm">头像（emoji）</label>
                    <InputText v-model="editingAgent.emoji" class="w-full mt-1" placeholder="如 🤖"/>
                </div>
            </div>
            <template #footer>
                <Button label="取消" icon="pi pi-times" @click="cancelEdit" severity="secondary"/>
                <Button label="保存" icon="pi pi-check" @click="saveAgent" :loading="savingAgent === (editingAgent.id || 'new')"/>
            </template>
        </Dialog>
    </div>
</template>

<style scoped lang="scss">
/* 自定义滚动条 */
::-webkit-scrollbar {
    width: 6px;
}
::-webkit-scrollbar-track {
    background: #f1f1f1;
}
::-webkit-scrollbar-thumb {
    background: #888;
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: #555;
}
/* 左侧智能体列表样式 */
.agent-item {
    transition: all 0.2s;
}
.agent-item:hover {
    background-color: #f3f4f6;
}
</style>
