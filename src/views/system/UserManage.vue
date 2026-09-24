<script setup>
/**
 * 系统设置 · 用户管理（仅管理员）
 *
 * 系统不开放自助注册，账号一律由管理员在这里创建。
 * 每个用户在自己的账号下拥有独立的股票池 / 量化策略（投资组合）/ ETF 自选。
 *
 * ⚠️ 删除账号只删 `users` 里那一行，**不会**连带清理该用户名下的业务数据
 * （股票池 / 组合 / ETF 自选会变成无主数据），所以删除前必须让管理员看清这条提示。
 * ⚠️ 改密码 / 禁用会撤销该用户所有在线令牌，立即下线（后端已实现）。
 */
import { computed, onBeforeMount, reactive, ref } from 'vue';
import axios from 'axios';
// 显式导入（与 MarketOverview.vue 一致）：ToggleSwitch 走自动导入也认，
// 但项目里已有显式写法，这里保持一致，避免构建期自动导入解析差异。
import ToggleSwitch from 'primevue/toggleswitch';
import { useNotification } from '@/composables/useNotification';
import { store } from '@/store';

const { showSuccess, showError } = useNotification();

const roleOptions = [
    { label: '普通用户', value: 'user' },
    { label: '管理员', value: 'admin' },
];

const users = ref([]);
const loading = ref(false);

const currentUserId = computed(() => Number(store.state.user?.id ?? 0));

// ---------------- 新建 ----------------
const createVisible = ref(false);
const creating = ref(false);
const createForm = reactive({ username: '', password: '', nickname: '', email: '', role: 'user' });

// ---------------- 编辑 ----------------
const editVisible = ref(false);
const saving = ref(false);
const editTarget = ref(null);
const editForm = reactive({ nickname: '', email: '', role: 'user', is_active: 1, password: '' });

// ---------------- 删除 ----------------
const deleteVisible = ref(false);
const deleting = ref(false);
const deleteTarget = ref(null);

function errText(error, fallback) {
    return error?.response?.data?.detail || fallback;
}

function formatTime(value) {
    if (!value) return '--';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function isSelf(row) {
    return Number(row.id) === currentUserId.value;
}

function loadUsers() {
    loading.value = true;
    return axios.get('/api/v1/users')
        .then(response => {
            users.value = Array.isArray(response.data) ? response.data : [];
        })
        .catch(error => {
            users.value = [];
            showError(errText(error, '读取用户列表失败'));
        })
        .finally(() => {
            loading.value = false;
        });
}

function openCreate() {
    Object.assign(createForm, { username: '', password: '', nickname: '', email: '', role: 'user' });
    createVisible.value = true;
}

function submitCreate() {
    const username = createForm.username.trim();
    if (!username) return showError('请填写用户名');
    if (!createForm.password) return showError('请填写初始密码');

    creating.value = true;
    axios.post('/api/v1/users', {
        username,
        password: createForm.password,
        nickname: createForm.nickname.trim() || username,
        email: createForm.email.trim() || null,
        role: createForm.role,
    })
        .then(() => {
            showSuccess(`已创建用户 ${username}`);
            createVisible.value = false;
            loadUsers();
        })
        .catch(error => showError(errText(error, '创建用户失败')))
        .finally(() => {
            creating.value = false;
        });
}

function openEdit(row) {
    editTarget.value = row;
    Object.assign(editForm, {
        nickname: row.nickname || '',
        email: row.email || '',
        role: row.role || 'user',
        is_active: row.is_active ? 1 : 0,
        password: '',
    });
    editVisible.value = true;
}

function submitEdit() {
    const row = editTarget.value;
    if (!row) return;

    // 只提交真正改过的字段：后端对「没有可更新字段」会返回 400
    const payload = {};
    const nickname = editForm.nickname.trim();
    const email = editForm.email.trim();
    if (nickname !== (row.nickname || '')) payload.nickname = nickname;
    if (email !== (row.email || '')) payload.email = email || null;
    if (editForm.role !== row.role) payload.role = editForm.role;
    if (Number(editForm.is_active) !== (row.is_active ? 1 : 0)) payload.is_active = Number(editForm.is_active);
    if (editForm.password) payload.password = editForm.password;

    if (!Object.keys(payload).length) {
        showError('没有修改任何内容');
        return;
    }

    saving.value = true;
    axios.put(`/api/v1/users/${row.id}`, payload)
        .then(() => {
            const notes = [];
            if (payload.password) notes.push('密码已重置，该用户需重新登录');
            if (payload.is_active === 0) notes.push('账号已禁用');
            showSuccess(`已更新 ${row.username}${notes.length ? '：' + notes.join('，') : ''}`);
            editVisible.value = false;
            loadUsers();
        })
        .catch(error => showError(errText(error, '更新用户失败')))
        .finally(() => {
            saving.value = false;
        });
}

function openDelete(row) {
    deleteTarget.value = row;
    deleteVisible.value = true;
}

function submitDelete() {
    const row = deleteTarget.value;
    if (!row) return;
    deleting.value = true;
    axios.delete(`/api/v1/users/${row.id}`)
        .then(() => {
            showSuccess(`已删除账号 ${row.username}`);
            deleteVisible.value = false;
            loadUsers();
        })
        .catch(error => showError(errText(error, '删除用户失败')))
        .finally(() => {
            deleting.value = false;
        });
}

onBeforeMount(() => {
    loadUsers();
});
</script>

<template>
    <Toast/>
    <div class="card">
        <DataTable
            :value="users"
            dataKey="id"
            :loading="loading"
            :rowHover="true"
            :showGridlines="false"
            size="medium"
        >
            <template #header>
                <div class="flex flex-col gap-2 w-full">
                    <div class="flex flex-col md:flex-row items-center justify-between gap-3 w-full">
                        <div class="text-gray-500 text-sm">
                            用户管理 · 共 {{ users.length }} 个账号
                        </div>
                        <div class="flex gap-2 items-center whitespace-nowrap">
                            <Button
                                icon="pi pi-refresh"
                                label="刷新"
                                size="small"
                                severity="secondary"
                                outlined
                                :loading="loading"
                                @click="loadUsers"
                            />
                            <Button
                                icon="pi pi-plus"
                                label="新建用户"
                                size="small"
                                @click="openCreate"
                            />
                        </div>
                    </div>
                    <div class="text-xs text-gray-500">
                        系统不开放自助注册，账号一律由管理员创建。每个账号拥有<b>独立的股票池 / 量化策略 / ETF 自选</b>。
                        改密码或禁用账号会让该用户<b>立即下线</b>。
                    </div>
                </div>
            </template>

            <template #empty> 暂无账号 </template>
            <template #loading> 正在读取用户… </template>

            <Column header="用户名" :style="{ minWidth: '10rem' }">
                <template #body="{ data }">
                    <div class="font-semibold">{{ data.username }}</div>
                    <div v-if="isSelf(data)" class="text-xs text-gray-400">当前登录账号</div>
                </template>
            </Column>

            <Column field="nickname" header="昵称" :style="{ minWidth: '8rem' }"/>

            <Column header="邮箱" :style="{ minWidth: '12rem' }">
                <template #body="{ data }">
                    <span class="text-gray-600">{{ data.email || '--' }}</span>
                </template>
            </Column>

            <Column header="角色" :style="{ width: '7rem' }">
                <template #body="{ data }">
                    <Tag :value="data.role === 'admin' ? '管理员' : '普通用户'"
                         :severity="data.role === 'admin' ? 'success' : 'secondary'"/>
                </template>
            </Column>

            <Column header="状态" :style="{ width: '6rem' }">
                <template #body="{ data }">
                    <Tag :value="data.is_active ? '启用' : '已禁用'"
                         :severity="data.is_active ? 'success' : 'danger'"/>
                </template>
            </Column>

            <Column header="最后登录" :style="{ minWidth: '10rem' }">
                <template #body="{ data }">
                    <span class="text-gray-600">{{ formatTime(data.last_login_at) }}</span>
                </template>
            </Column>

            <Column header="创建时间" :style="{ minWidth: '10rem' }">
                <template #body="{ data }">
                    <span class="text-gray-600">{{ formatTime(data.created_at) }}</span>
                </template>
            </Column>

            <Column header="操作" :style="{ width: '11rem' }">
                <template #body="{ data }">
                    <!-- 必须 nowrap：两个按钮在窄列里会被压成竖排 -->
                    <div class="flex gap-1 items-center whitespace-nowrap">
                        <Button
                            icon="pi pi-pencil"
                            label="编辑"
                            size="small"
                            severity="secondary"
                            outlined
                            @click="openEdit(data)"
                        />
                        <Button
                            icon="pi pi-trash"
                            size="small"
                            severity="danger"
                            text
                            rounded
                            v-tooltip.top="isSelf(data) ? '不能删除当前登录账号' : '删除账号'"
                            :disabled="isSelf(data)"
                            @click="openDelete(data)"
                        />
                    </div>
                </template>
            </Column>
        </DataTable>
    </div>

    <!-- 新建用户 -->
    <Dialog v-model:visible="createVisible" header="新建用户" :modal="true" :style="{ width: '30rem' }">
        <div class="flex flex-col gap-3">
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">用户名 *</label>
                <InputText v-model="createForm.username" placeholder="登录用户名，唯一" autocomplete="off"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">初始密码 *</label>
                <InputText v-model="createForm.password" type="password" placeholder="交给用户后请其自行修改" autocomplete="new-password"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">昵称</label>
                <InputText v-model="createForm.nickname" placeholder="留空则用用户名"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">邮箱</label>
                <InputText v-model="createForm.email" placeholder="可选"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">角色</label>
                <Dropdown v-model="createForm.role" :options="roleOptions" optionLabel="label" optionValue="value"/>
            </div>
        </div>
        <template #footer>
            <Button label="取消" severity="secondary" text @click="createVisible = false"/>
            <Button label="创建" icon="pi pi-check" :loading="creating" @click="submitCreate"/>
        </template>
    </Dialog>

    <!-- 编辑用户 -->
    <Dialog v-model:visible="editVisible" :header="`编辑用户 · ${editTarget?.username || ''}`" :modal="true" :style="{ width: '30rem' }">
        <div class="flex flex-col gap-3">
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">昵称</label>
                <InputText v-model="editForm.nickname"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">邮箱</label>
                <InputText v-model="editForm.email" placeholder="可选"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">角色</label>
                <Dropdown v-model="editForm.role" :options="roleOptions" optionLabel="label" optionValue="value"
                          :disabled="isSelf(editTarget || {})"/>
                <small v-if="isSelf(editTarget || {})" class="text-gray-500">不能取消自己的管理员角色</small>
            </div>
            <div class="flex items-center gap-2">
                <ToggleSwitch v-model="editForm.is_active" :trueValue="1" :falseValue="0"
                              :disabled="isSelf(editTarget || {})"/>
                <label class="text-sm">启用账号</label>
                <small v-if="isSelf(editTarget || {})" class="text-gray-500">不能禁用自己</small>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">重置密码</label>
                <InputText v-model="editForm.password" type="password" placeholder="留空表示不修改" autocomplete="new-password"/>
                <small class="text-gray-500">重置后该用户的所有登录令牌会立即失效</small>
            </div>
        </div>
        <template #footer>
            <Button label="取消" severity="secondary" text @click="editVisible = false"/>
            <Button label="保存" icon="pi pi-check" :loading="saving" @click="submitEdit"/>
        </template>
    </Dialog>

    <!-- 删除确认 -->
    <Dialog v-model:visible="deleteVisible" header="删除账号" :modal="true" :style="{ width: '28rem' }">
        <div class="flex flex-col gap-3">
            <div>
                确定要删除账号
                <b>{{ deleteTarget?.username }}</b>
                吗？该账号的所有登录令牌会立即失效。
            </div>
            <div class="del-warn">
                ⚠️ 该用户名下的<b>股票池 / 量化策略 / ETF 自选不会被删除</b>，会变成无主数据留在库里。
                如需彻底清理，请先在对应页面清空再删账号。
            </div>
        </div>
        <template #footer>
            <Button label="取消" severity="secondary" text @click="deleteVisible = false"/>
            <Button label="确认删除" icon="pi pi-trash" severity="danger" :loading="deleting" @click="submitDelete"/>
        </template>
    </Dialog>
</template>

<style scoped lang="scss">
:deep(.p-datatable) {
    font-size: 12px;
}

.del-warn {
    background: var(--red-50, #fef2f2);
    border-left: 3px solid var(--red-500, #ef4444);
    padding: 0.6rem 0.75rem;
    font-size: 0.9rem;
    line-height: 1.5;
}
</style>
