<script setup>
// 顶栏右侧的用户区：显示当前登录用户 + 退出登录（管理员额外可见「用户管理」）。
//
// ⚠️ 退出登录必须**先请求服务端**再去本地令牌：令牌是存在 Redis 里的，只清本地
// 的话服务端那份在 TTL 内依然有效（等于没登出）。反过来则会出现「本地清了、
// 服务端也清了」的正常路径；网络失败时兜底清本地，否则用户被锁在页面里出不去。
import { computed, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import axios from 'axios';
import { store } from '@/store';
import { useNotification } from '@/composables/useNotification';

const router = useRouter();
const { showSuccess, showError } = useNotification();

const userMenu = ref(null);

const currentUser = computed(() => store.state.user || {});
const displayName = computed(() => currentUser.value.nickname || currentUser.value.username || '未登录');
const roleLabel = computed(() => (currentUser.value.role === 'admin' ? '管理员' : '普通用户'));
// 昵称恰好就是角色名时（如 admin 的昵称是「管理员」）同时显示会变成「管理员 管理员」，
// 这种情况只留一个，别把顶栏塞成重复信息。
const showRoleTag = computed(() => !!currentUser.value.role && displayName.value !== roleLabel.value);

const menuItems = computed(() => {
    const items = [];
    if (store.getters.isAdmin) {
        items.push({
            label: '用户管理',
            icon: 'pi pi-fw pi-users',
            command: () => router.push({ path: '/system/user_manage' }),
        });
    }
    items.push({
        label: '退出登录',
        icon: 'pi pi-fw pi-sign-out',
        command: logout,
    });
    return items;
});

function toggleUserMenu(event) {
    userMenu.value?.toggle(event);
}

function clearLocalAndGoLogin() {
    store.commit('removeToken');
    router.replace({ path: '/auth/login' });
}

function logout() {
    axios.post('/api/v1/auth/logout')
        .then(() => {
            showSuccess('已退出登录');
            clearLocalAndGoLogin();
        })
        .catch(() => {
            // 服务端不可达也要本地登出，否则用户被锁在页面里出不去
            showError('退出登录请求失败，已在本地清除登录状态');
            clearLocalAndGoLogin();
        });
}

// ==================== 「请尽快修改默认密码」风险弹窗 ====================
// 首次安装生成的默认管理员 / 仍在使用出厂弱密码时，后端会在用户对象上返回
// must_change_password=1；据此**自动弹出**风险提示框，并可直接唤起自助改密对话框，
// 免去「去用户管理找自己那一行」的弯路。
//
// 这里用弹窗而不是顶部横幅：横幅要多占一行高度、窄屏容易挤成一团，而且很容易被
// 当成广告一样直接忽略；弹窗能明确要求用户做一次选择（立即修改 / 稍后处理）。
// 「稍后处理」只在本次会话内有效（刷新/重新登录后会再次提醒），因为风险是持续的。
const riskDialog = ref(false);
const riskDismissed = ref(false);
const changeDialog = ref(false);
const oldPassword = ref('');
const newPassword = ref('');
const confirmPassword = ref('');
const changing = ref(false);
const pwdError = ref('');

// 新密码强度（1=弱 2=中 3=强，0=未输入）：纯前端提示，不参与校验，
// 真正的规则以后端为准（至少 6 位）。
const pwdStrength = computed(() => {
    const v = newPassword.value;
    if (!v) return 0;
    let score = 0;
    if (v.length >= 8) score += 1;
    if (/[a-zA-Z]/.test(v) && /\d/.test(v)) score += 1;
    if (/[^a-zA-Z0-9]/.test(v)) score += 1;
    return Math.max(1, score);
});
const pwdStrengthLabel = computed(() => ['', '弱', '中', '强'][pwdStrength.value]);

// 标志位来到 1 就弹风险提示（immediate 兜住「用户信息晚于组件挂载才拿到」的情况）；
// 改密成功后 /auth/change-password 返回的用户对象标志已清零，这里顺带关掉弹窗。
watch(
    () => currentUser.value.must_change_password,
    (flag) => {
        if (flag === 1) {
            if (!riskDismissed.value) riskDialog.value = true;
        } else {
            riskDialog.value = false;
            changeDialog.value = false;
        }
    },
    { immediate: true }
);

function dismissRisk() {
    riskDismissed.value = true;
    riskDialog.value = false;
}

function openChangeDialog() {
    oldPassword.value = '';
    newPassword.value = '';
    confirmPassword.value = '';
    pwdError.value = '';
    riskDialog.value = false;
    changeDialog.value = true;
}

async function submitChangePassword() {
    pwdError.value = '';
    // 后端会对新密码做 strip：这里先 trim，避免「末尾空格被无声吃掉」后
    // 用户照自己输入的原文再登录却提示密码错误。
    const oldPwd = oldPassword.value;
    const newPwd = newPassword.value.trim();
    if (!oldPwd || !newPwd) {
        pwdError.value = '请填写原密码和新密码';
        return;
    }
    if (newPwd.length < 6) {
        pwdError.value = '新密码至少 6 位';
        return;
    }
    if (newPwd === oldPwd) {
        pwdError.value = '新密码不能与原密码相同';
        return;
    }
    if (newPwd !== confirmPassword.value.trim()) {
        pwdError.value = '两次输入的新密码不一致';
        return;
    }
    changing.value = true;
    try {
        const resp = await axios.post('/api/v1/auth/change-password', {
            old_password: oldPwd,
            new_password: newPwd,
        });
        // 后端改密后重新签发了令牌并清除了标志，前端同步本地状态，保持登录
        store.commit('setToken', resp.data.token);
        store.commit('setUser', resp.data.user);
        showSuccess('密码修改成功');
        changeDialog.value = false;
    } catch (e) {
        // 错误就地显示在表单里（弹窗遮罩会把右上角的 toast 压在下面，光靠 toast 容易看不见）
        const msg = e?.response?.data?.detail || e?.response?.data?.message || '修改失败，请稍后再试';
        pwdError.value = msg;
        showError(msg);
    } finally {
        changing.value = false;
    }
}
</script>

<template>
    <!-- 安全风险弹窗：仍是默认密码时自动弹出 -->
    <Dialog
        v-model:visible="riskDialog"
        modal
        :closable="false"
        :dismissableMask="false"
        :style="{ width: '27rem', maxWidth: '92vw' }"
    >
        <template #header>
            <div class="risk-dialog-title">
                <i class="pi pi-exclamation-triangle"></i>
                <span>安全风险提示</span>
            </div>
        </template>
        <div class="risk-dialog-body">
            <p>
                您正在使用<strong>默认管理员密码</strong>登录。该密码由系统在首次启动时自动生成，
                并明文打印在服务日志中——任何能看到日志的人都可以登录本系统。
            </p>
            <p>请尽快将其修改为只有您自己知道的密码。</p>
        </div>
        <template #footer>
            <Button label="稍后处理" text severity="secondary" @click="dismissRisk" />
            <Button label="立即修改" icon="pi pi-key" severity="warn" @click="openChangeDialog" />
        </template>
    </Dialog>

    <div class="layout-topbar">
        <div class="layout-topbar-logo-container">

        </div>

        <div class="layout-topbar-actions">
            <div class="layout-topbar-menu hidden lg:block">
                <div class="layout-topbar-menu-content">
<!--                    <router-link class="text-blue-500"-->
<!--                                 target="_blank"-->
<!--                                 :to="{ name: 'trading-terminal', params: { } }">-->
<!--                        <Chip label="Terminal" icon="pi pi-twitch" style="cursor: pointer"/>-->
<!--                    </router-link>-->
                </div>
            </div>

            <!-- 当前用户 + 退出登录 -->
            <button
                type="button"
                class="user-trigger"
                aria-haspopup="true"
                aria-controls="user-menu"
                @click="toggleUserMenu"
            >
                <i class="pi pi-user user-trigger-avatar"></i>
                <span class="user-trigger-name">{{ displayName }}</span>
                <Tag
                    v-if="showRoleTag"
                    :value="roleLabel"
                    :severity="currentUser.role === 'admin' ? 'success' : 'secondary'"
                    class="user-trigger-role"
                />
                <i class="pi pi-angle-down user-trigger-caret"></i>
            </button>
            <Menu id="user-menu" ref="userMenu" :model="menuItems" :popup="true" />
        </div>
    </div>

    <!-- 自助改密对话框 -->
    <Dialog v-model:visible="changeDialog" modal header="修改登录密码" :style="{ width: '30rem', maxWidth: '92vw' }">
        <div class="pwd-form flex flex-col gap-3">
            <div class="flex flex-col gap-1">
                <label class="font-medium" for="oldPwd">原密码</label>
                <Password
                    inputId="oldPwd"
                    v-model="oldPassword"
                    :feedback="false"
                    toggleMask
                    fluid
                    placeholder="请输入当前登录密码"
                    autocomplete="current-password"
                />
            </div>
            <div class="flex flex-col gap-1">
                <label class="font-medium" for="newPwd">新密码</label>
                <Password
                    inputId="newPwd"
                    v-model="newPassword"
                    :feedback="false"
                    toggleMask
                    fluid
                    placeholder="至少 6 位"
                    autocomplete="new-password"
                />
                <!-- 强度只做提示，不是校验规则 -->
                <div v-if="newPassword" class="pwd-strength">
                    <span class="pwd-strength-bars">
                        <i
                            v-for="n in 3"
                            :key="n"
                            class="pwd-strength-bar"
                            :class="[{ on: n <= pwdStrength }, `lv-${pwdStrength}`]"
                        ></i>
                    </span>
                    <div class="pwd-hint">
                        强度：{{ pwdStrengthLabel }}（建议 8 位以上，字母 + 数字 + 符号）
                    </div>
                </div>
                <div v-else class="pwd-hint">至少 6 位；建议混合字母、数字与符号。</div>
            </div>
            <div class="flex flex-col gap-1">
                <label class="font-medium" for="confirmPwd">确认新密码</label>
                <Password
                    inputId="confirmPwd"
                    v-model="confirmPassword"
                    :feedback="false"
                    toggleMask
                    fluid
                    placeholder="再次输入新密码"
                    autocomplete="new-password"
                />
            </div>
            <div v-if="pwdError" class="pwd-error">
                <i class="pi pi-exclamation-circle"></i>{{ pwdError }}
            </div>
        </div>
        <template #footer>
            <Button label="取消" text severity="secondary" @click="changeDialog = false" />
            <Button label="确认修改" icon="pi pi-check" :loading="changing" @click="submitChangePassword" />
        </template>
    </Dialog>
</template>

<style scoped lang="scss">
.user-trigger {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    border: 1px solid var(--surface-border);
    background: transparent;
    color: inherit;
    cursor: pointer;
    line-height: 1;
    transition: background-color 0.15s ease;
}

.user-trigger:hover {
    background: var(--surface-hover);
}

.user-trigger-avatar {
    font-size: 0.95rem;
}

.user-trigger-name {
    font-size: 0.9rem;
    max-width: 9rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.user-trigger-role {
    font-size: 0.75rem;
    padding: 0.1rem 0.4rem;
}

.user-trigger-caret {
    font-size: 0.75rem;
    opacity: 0.7;
}

/* 窄屏（顶栏右区空间紧张）只留头像，点开菜单仍能看到用户名 */
@media (max-width: 768px) {
    .user-trigger-name,
    .user-trigger-role,
    .user-trigger-caret {
        display: none;
    }
}

/* ==================== 安全风险弹窗 ==================== */
.risk-dialog-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 600;

    i.pi-exclamation-triangle {
        font-size: 1.15rem;
        color: #d97706;
    }
}

.risk-dialog-body {
    p {
        margin: 0 0 0.6rem;
        line-height: 1.6;

        &:last-child {
            margin-bottom: 0;
        }
    }
}

/* ==================== 改密表单 ==================== */
/* 密码框撑满整行：不依赖 fluid 属性，避免主题/版本差异下退回窄输入框 */
.pwd-form {
    :deep(.p-password),
    :deep(.p-password-input) {
        width: 100%;
    }
}

.pwd-strength {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.pwd-strength-bars {
    display: inline-flex;
    gap: 0.2rem;
    flex: 0 0 auto;
}

.pwd-strength-bar {
    display: inline-block;
    width: 1.1rem;
    height: 0.3rem;
    border-radius: 999px;
    background: var(--surface-border);

    &.on.lv-1 {
        background: #dc2626;
    }

    &.on.lv-2 {
        background: #d97706;
    }

    &.on.lv-3 {
        background: #16a34a;
    }
}

/* 提示文字：显式给字号，不用 <small>（根字号 12px 下 small≈9.6px，偏小） */
.pwd-hint {
    font-size: 1rem;
    line-height: 1.4;
    color: var(--text-color-secondary, #64748b);
}

/* 校验失败就地提示（弹窗遮罩下右上角 toast 容易被忽略） */
.pwd-error {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    color: #dc2626;
}

</style>
