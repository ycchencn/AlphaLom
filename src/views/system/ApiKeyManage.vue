<script setup>
/**
 * 系统设置 · API Key 管理（仅管理员）
 *
 * 对外开放 API（/api/ext/*）的密钥管理面。后端 CRUD 已就绪（/api/v1/api-keys），
 * 这里提供：创建 / 列表 / 编辑（改名·启停·改配额）/ 吊销。
 *
 * ⚠️ 明文密钥**只在创建响应里返回这一次**（后端只存 sha256 摘要），因此：
 *   - 创建成功后立刻弹出「明文只显示这一次」对话框 + 一键复制；
 *   - 关闭后无法再查看，遗失只能吊销重发。
 *
 * 响应信封：后端返回 `{code, msg, data}`（与 /users 的裸数组不同），这里统一取 `data`。
 */
import { onBeforeMount, reactive, ref } from 'vue';
import axios from 'axios';
import { useNotification } from '@/composables/useNotification';

const { showSuccess, showError } = useNotification();

const keys = ref([]);
const loading = ref(false);

// ---------------- 创建 ----------------
const createVisible = ref(false);
const creating = ref(false);
const createForm = reactive({ name: '', daily_quota: null, expires_at: '' });

// 创建成功后的「明文只显示一次」弹窗
const secretVisible = ref(false);
const secretKey = ref('');

// ---------------- 编辑 ----------------
const editVisible = ref(false);
const saving = ref(false);
const editTarget = ref(null);
const editForm = reactive({ name: '', status: 'active', daily_quota: null });

// ---------------- 吊销 ----------------
const revokeVisible = ref(false);
const revoking = ref(false);
const revokeTarget = ref(null);

function errText(error, fallback) {
    return error?.response?.data?.detail || error?.response?.data?.msg || fallback;
}

function formatTime(value) {
    if (!value) return '--';
    const d = new Date(String(value).replace(' ', 'T'));
    if (Number.isNaN(d.getTime())) return value;
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function isExpired(row) {
    if (!row.expires_at) return false;
    return new Date(String(row.expires_at).replace(' ', 'T')).getTime() < Date.now();
}

function statusOf(row) {
    if (row.status === 'revoked') return { label: '已吊销', severity: 'danger' };
    if (isExpired(row)) return { label: '已过期', severity: 'secondary' };
    return { label: '有效', severity: 'success' };
}

function loadKeys() {
    loading.value = true;
    return axios.get('/api/v1/api-keys')
        .then(response => {
            keys.value = Array.isArray(response.data?.data) ? response.data.data : [];
        })
        .catch(error => {
            keys.value = [];
            showError(errText(error, '读取密钥列表失败'));
        })
        .finally(() => {
            loading.value = false;
        });
}

function openCreate() {
    Object.assign(createForm, { name: '', daily_quota: null, expires_at: '' });
    createVisible.value = true;
}

function submitCreate() {
    const name = createForm.name.trim();
    if (!name) return showError('请填写密钥名称');

    // daily_quota 空字符串 → null（后端 None=用全局默认）；非空必须是非负整数
    let quota = null;
    if (createForm.daily_quota !== null && createForm.daily_quota !== '' && createForm.daily_quota !== undefined) {
        quota = Number(createForm.daily_quota);
        if (!Number.isInteger(quota) || quota < 0) return showError('每日配额必须是非负整数');
    }

    creating.value = true;
    axios.post('/api/v1/api-keys', {
        name,
        daily_quota: quota,
        expires_at: createForm.expires_at || null,
    })
        .then(response => {
            // ⚠️ 明文只在这次响应里，之后再也拿不到
            secretKey.value = response.data?.data?.key || '';
            createVisible.value = false;
            secretVisible.value = true;
            loadKeys();
        })
        .catch(error => showError(errText(error, '创建密钥失败')))
        .finally(() => {
            creating.value = false;
        });
}

async function copySecret() {
    const text = secretKey.value;
    if (!text) return;
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            // 非安全上下文（纯 http 内网）下 clipboard API 不可用，退回 execCommand
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        showSuccess('密钥已复制到剪贴板');
    } catch (e) {
        showError('复制失败，请手动选中复制');
    }
}

function openEdit(row) {
    editTarget.value = row;
    Object.assign(editForm, {
        name: row.name || '',
        status: row.status || 'active',
        daily_quota: row.daily_quota ?? null,
    });
    editVisible.value = true;
}

function submitEdit() {
    const row = editTarget.value;
    if (!row) return;

    // 只提交真正改过的字段
    const payload = {};
    const name = editForm.name.trim();
    if (name && name !== row.name) payload.name = name;
    if (editForm.status !== row.status) payload.status = editForm.status;
    const quota = editForm.daily_quota === '' || editForm.daily_quota === null ? null : Number(editForm.daily_quota);
    if (quota !== null && (!Number.isInteger(quota) || quota < 0)) {
        return showError('每日配额必须是非负整数');
    }
    if (quota !== (row.daily_quota ?? null)) payload.daily_quota = quota;

    if (!Object.keys(payload).length) {
        showError('没有修改任何内容');
        return;
    }

    saving.value = true;
    axios.put(`/api/v1/api-keys/${row.id}`, payload)
        .then(() => {
            const notes = [];
            if (payload.status === 'revoked') notes.push('已吊销，该密钥立即失效');
            if (payload.status === 'active' && row.status === 'revoked') notes.push('已重新启用');
            showSuccess(`已更新密钥 ${name || row.name}${notes.length ? '：' + notes.join('，') : ''}`);
            editVisible.value = false;
            loadKeys();
        })
        .catch(error => showError(errText(error, '更新密钥失败')))
        .finally(() => {
            saving.value = false;
        });
}

function openRevoke(row) {
    revokeTarget.value = row;
    revokeVisible.value = true;
}

function submitRevoke() {
    const row = revokeTarget.value;
    if (!row) return;
    revoking.value = true;
    axios.delete(`/api/v1/api-keys/${row.id}`)
        .then(() => {
            showSuccess(`已吊销密钥 ${row.name}`);
            revokeVisible.value = false;
            loadKeys();
        })
        .catch(error => showError(errText(error, '吊销密钥失败')))
        .finally(() => {
            revoking.value = false;
        });
}

onBeforeMount(() => {
    loadKeys();
});
</script>

<template>
    <Toast/>
    <div class="card">
        <DataTable
            :value="keys"
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
                            API Key 管理 · 共 {{ keys.length }} 枚密钥
                        </div>
                        <div class="flex gap-2 items-center whitespace-nowrap">
                            <Button
                                icon="pi pi-refresh"
                                label="刷新"
                                size="small"
                                severity="secondary"
                                outlined
                                :loading="loading"
                                @click="loadKeys"
                            />
                            <Button
                                icon="pi pi-plus"
                                label="创建密钥"
                                size="small"
                                @click="openCreate"
                            />
                        </div>
                    </div>
                    <div class="text-xs text-gray-500">
                        对外开放 API（<b>/api/ext/*</b>）的调用凭证。外部交易决策系统请求时携带
                        <b>X-API-Key</b>（或 <b>Authorization: Bearer</b>）请求头，接口文档在
                        <b>/api/ext/docs</b>。按用户 + 自然日计调用次数，密钥与配额均只对<b>当前账号</b>生效。
                    </div>
                </div>
            </template>

            <template #empty> 暂无密钥，点「创建密钥」生成一枚 </template>
            <template #loading> 正在读取密钥… </template>

            <Column header="名称" :style="{ minWidth: '10rem' }">
                <template #body="{ data }">
                    <div class="font-semibold">{{ data.name }}</div>
                    <div class="text-xs text-gray-400 font-mono">{{ data.key_prefix }}…</div>
                </template>
            </Column>

            <Column header="状态" :style="{ width: '7rem' }">
                <template #body="{ data }">
                    <Tag :value="statusOf(data).label" :severity="statusOf(data).severity"/>
                </template>
            </Column>

            <Column header="每日配额" :style="{ width: '9rem' }">
                <template #body="{ data }">
                    <span class="text-gray-600">{{ data.daily_quota ?? '默认' }}</span>
                </template>
            </Column>

            <Column header="最近使用" :style="{ minWidth: '10rem' }">
                <template #body="{ data }">
                    <span class="text-gray-600">{{ formatTime(data.last_used_at) }}</span>
                </template>
            </Column>

            <Column header="过期时间" :style="{ minWidth: '10rem' }">
                <template #body="{ data }">
                    <span class="text-gray-600">{{ data.expires_at ? formatTime(data.expires_at) : '不过期' }}</span>
                </template>
            </Column>

            <Column header="创建时间" :style="{ minWidth: '10rem' }">
                <template #body="{ data }">
                    <span class="text-gray-600">{{ formatTime(data.created_at) }}</span>
                </template>
            </Column>

            <Column header="操作" :style="{ width: '11rem' }">
                <template #body="{ data }">
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
                            icon="pi pi-ban"
                            size="small"
                            severity="danger"
                            text
                            rounded
                            v-tooltip.top="data.status === 'revoked' ? '重新启用后可恢复调用' : '吊销后立即失效'"
                            :disabled="data.status === 'revoked'"
                            @click="openRevoke(data)"
                        />
                    </div>
                </template>
            </Column>
        </DataTable>
    </div>

    <!-- 创建密钥 -->
    <Dialog v-model:visible="createVisible" header="创建 API Key" :modal="true" :style="{ width: '30rem' }">
        <div class="flex flex-col gap-3">
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">名称 *</label>
                <InputText v-model="createForm.name" placeholder="如：量化交易系统" autocomplete="off"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">每日配额</label>
                <InputNumber v-model="createForm.daily_quota" :useGrouping="false" :min="0"
                             placeholder="留空 = 用全局默认" class="w-full"/>
                <small class="text-gray-500">按自然日计；留空表示不单独限制（回退全局默认）。</small>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">过期时间</label>
                <InputText v-model="createForm.expires_at" placeholder="留空 = 不过期，如 2026-12-31" autocomplete="off"/>
                <small class="text-gray-500">格式 YYYY-MM-DD，可留空表示长期有效。</small>
            </div>
        </div>
        <template #footer>
            <Button label="取消" severity="secondary" text @click="createVisible = false"/>
            <Button label="创建" icon="pi pi-check" :loading="creating" @click="submitCreate"/>
        </template>
    </Dialog>

    <!-- 明文密钥：只显示这一次 -->
    <Dialog v-model:visible="secretVisible" header="密钥已创建（明文只显示这一次）" :modal="true"
            :style="{ width: '34rem' }" :closable="true">
        <div class="flex flex-col gap-3">
            <div class="secret-warn">
                ⚠️ 请<b>立即复制并保存</b>。出于安全考虑，平台只存密钥的哈希摘要，
                <b>关闭后无法再次查看</b>；若遗失，只能吊销本枚并重新创建。
            </div>
            <div class="secret-box">
                <code class="secret-text">{{ secretKey }}</code>
            </div>
            <div class="text-xs text-gray-500">
                使用方式：请求头 <b>X-API-Key: &lt;上面的密钥&gt;</b>
                （或 <b>Authorization: Bearer &lt;密钥&gt;</b>），接口文档 <b>/api/ext/docs</b>。
            </div>
        </div>
        <template #footer>
            <Button label="关闭" severity="secondary" text @click="secretVisible = false"/>
            <Button label="复制密钥" icon="pi pi-copy" @click="copySecret"/>
        </template>
    </Dialog>

    <!-- 编辑密钥 -->
    <Dialog v-model:visible="editVisible" :header="`编辑密钥 · ${editTarget?.name || ''}`" :modal="true"
            :style="{ width: '30rem' }">
        <div class="flex flex-col gap-3">
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">名称</label>
                <InputText v-model="editForm.name"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">状态</label>
                <Dropdown v-model="editForm.status" :options="[
                        { label: '有效', value: 'active' },
                        { label: '已吊销', value: 'revoked' },
                    ]" optionLabel="label" optionValue="value"/>
            </div>
            <div class="flex flex-col gap-1">
                <label class="text-sm font-medium">每日配额</label>
                <InputNumber v-model="editForm.daily_quota" :useGrouping="false" :min="0"
                             placeholder="留空 = 用全局默认" class="w-full"/>
            </div>
        </div>
        <template #footer>
            <Button label="取消" severity="secondary" text @click="editVisible = false"/>
            <Button label="保存" icon="pi pi-check" :loading="saving" @click="submitEdit"/>
        </template>
    </Dialog>

    <!-- 吊销确认 -->
    <Dialog v-model:visible="revokeVisible" header="吊销密钥" :modal="true" :style="{ width: '28rem' }">
        <div class="flex flex-col gap-3">
            <div>
                确定要吊销密钥
                <b>{{ revokeTarget?.name }}</b> 吗？
            </div>
            <div class="del-warn">
                ⚠️ 吊销后使用该密钥的所有外部请求会<b>立即返回 401</b>，无法恢复（只能重新创建一枚新的）。
            </div>
        </div>
        <template #footer>
            <Button label="取消" severity="secondary" text @click="revokeVisible = false"/>
            <Button label="确认吊销" icon="pi pi-ban" severity="danger" :loading="revoking" @click="submitRevoke"/>
        </template>
    </Dialog>
</template>

<style scoped lang="scss">
:deep(.p-datatable) {
    font-size: 12px;
}

.secret-warn {
    background: var(--amber-50, #fffbeb);
    border-left: 3px solid var(--amber-500, #f59e0b);
    padding: 0.6rem 0.75rem;
    font-size: 0.9rem;
    line-height: 1.5;
}

.secret-box {
    background: #1e293b;
    border-radius: 6px;
    padding: 0.75rem;
    word-break: break-all;
}

.secret-text {
    color: #e2e8f0;
    font-size: 0.85rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    line-height: 1.5;
}

.del-warn {
    background: var(--red-50, #fef2f2);
    border-left: 3px solid var(--red-500, #ef4444);
    padding: 0.6rem 0.75rem;
    font-size: 0.9rem;
    line-height: 1.5;
}
</style>
