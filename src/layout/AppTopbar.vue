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
import { cycleThemeMode, useTheme, useThemeIcon, THEME_MODE_LABEL } from '@/composables/useTheme';

const router = useRouter();
const { showSuccess, showError } = useNotification();

// ==================== 配色模式切换 ====================
// 图标取自 useThemeIcon：显示实际生效的配色。
// title 里额外带上「当前选择的模式」，auto 时写成「跟随系统（当前为浅色）」，
// 否则用户点了按钮之后无从判断自己切到哪一档了。
const { mode } = useTheme();
const themeIcon = useThemeIcon();

const themeButtonTitle = computed(() => {
    const current = mode.value === 'auto'
        ? `跟随系统（当前为${THEME_MODE_LABEL[themeIcon.value.includes('moon') ? 'dark' : 'light']}）`
        : THEME_MODE_LABEL[mode.value];
    return `配色模式：${current} · 点击切换`;
});

function onToggleTheme() {
    cycleThemeMode();
}

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

            <!-- 源码仓库：Gitee / GitHub 品牌图标 -->
            <div class="repo-links">
                <a
                    class="repo-link repo-link--gitee"
                    href="https://gitee.com/yc-chan/alphalom"
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Gitee 仓库"
                    aria-label="Gitee 仓库"
                >
                    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor" aria-hidden="true">
                        <path d="M11.984 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.016 0zm6.09 5.333c.328.328.296.843-.086 1.355-1.16 1.508-2.668 3.274-3.992 5.41A47.9 47.9 0 0 0 10.35 13.2c-.36-.568-1.164-2.106-2.026-3.762-1.07-1.937-1.765-3.16-2.566-4.63-.948-1.728-2.624-1.793-2.93-.16-.054.26-.022.62.148 1.05.224.52.654 1.06 1.096 1.49.54.54 1.18 1.06 1.84 1.6.66.54 1.36 1.12 2.02 1.74.66.62 1.3 1.3 1.86 2.04.56.74 1.02 1.56 1.36 2.46.34.9.5 1.86.46 2.9a6.3 6.3 0 0 1-.32 1.74c-.22.56-.54 1.08-1 1.56-.46.48-1.04.86-1.74 1.14-.7.28-1.5.42-2.4.42-.9 0-1.72-.14-2.44-.42a5.9 5.9 0 0 1-1.74-1.14c-.46-.48-.8-1-1.02-1.56a6.4 6.4 0 0 1-.32-1.74c-.04-1.04.12-2 .46-2.9.34-.9.8-1.72 1.36-2.46.56-.74 1.2-1.42 1.86-2.04.66-.62 1.36-1.2 2.02-1.74.66-.54 1.3-1.06 1.84-1.6.442-.43.872-.97 1.096-1.49.17-.43.202-.79.148-1.05-.306-1.633-1.982-1.568-2.93.16-.8 1.47-1.496 2.694-2.566 4.63-.862 1.656-1.666 3.194-2.026 3.762a47.9 47.9 0 0 1-1.646 2.268c-1.324-2.136-2.832-3.902-3.992-5.41-.382-.512-.414-1.027-.086-1.355.246-.246.66-.328 1.11-.22.45.108.87.36 1.22.74 1.43 1.34 3.09 3.42 4.62 5.94.45.6 1.02 1.42 1.44 2.34.42-.92.99-1.74 1.44-2.34 1.53-2.52 3.19-4.6 4.62-5.94.35-.38.77-.632 1.22-.74.45-.108.864-.026 1.11.22z"/>
                    </svg>
                </a>
                <a
                    class="repo-link repo-link--github"
                    href="https://github.com/ycchencn/AlphaLom"
                    target="_blank"
                    rel="noopener noreferrer"
                    title="GitHub 仓库"
                    aria-label="GitHub 仓库"
                >
                    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor" aria-hidden="true">
                        <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>
                    </svg>
                </a>
            </div>

            <!-- 配色模式切换：一键在 跟随系统 → 浅色 → 深色 之间循环。
                 图标显示的是「当前实际生效」的配色（而不是当前选择的模式），
                 这样即使处于 auto，用户也能一眼看出屏幕现在是亮是暗。 -->
            <button
                type="button"
                class="layout-topbar-action theme-toggle"
                :title="themeButtonTitle"
                :aria-label="themeButtonTitle"
                @click="onToggleTheme"
            >
                <i :class="themeIcon"></i>
            </button>

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
/* ==================== 源码仓库图标（Gitee / GitHub） ==================== */
/* 顶栏右区的小图标链接：与用户头像同排，等宽对齐，hover 时浮起。 */
.repo-links {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-right: 0.25rem;
}

.repo-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.9rem;
    height: 1.9rem;
    border-radius: 999px;
    border: 1px solid var(--surface-border);
    font-size: 1.05rem;
    line-height: 1;
    color: var(--text-color-secondary, #64748b);
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.15s ease;

    &:hover {
        background: var(--surface-hover);
        transform: translateY(-1px);
    }
}

/* Gitee 品牌红 */
.repo-link--gitee:hover {
    color: #c71d23;
    border-color: #c71d23;
}

/* GitHub 品牌色（暗色下反白，亮色下近黑） */
.repo-link--github:hover {
    color: #181717;
    border-color: #181717;
}

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
