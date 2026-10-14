<script setup>
// 顶栏右侧的用户区：显示当前登录用户 + 退出登录（管理员额外可见「用户管理」）。
//
// ⚠️ 退出登录必须**先请求服务端**再去本地令牌：令牌是存在 Redis 里的，只清本地
// 的话服务端那份在 TTL 内依然有效（等于没登出）。反过来则会出现「本地清了、
// 服务端也清了」的正常路径；网络失败时兜底清本地，否则用户被锁在页面里出不去。
import { computed, ref } from 'vue';
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

// ==================== 「请尽快修改默认密码」提示 ====================
// 首次安装生成的默认管理员 / 仍在使用出厂弱密码时，后端会在用户对象上返回
// must_change_password=1；此处据此显示全局横幅，并内嵌自助改密对话框，
// 免去「去用户管理找自己那一行」的弯路。
const bannerVisible = ref(true);
const changeDialog = ref(false);
const oldPassword = ref('');
const newPassword = ref('');
const confirmPassword = ref('');
const changing = ref(false);

const needChangePwd = computed(
    () => bannerVisible.value && currentUser.value.must_change_password === 1
);

function openChangeDialog() {
    oldPassword.value = '';
    newPassword.value = '';
    confirmPassword.value = '';
    changeDialog.value = true;
}

function dismissBanner() {
    bannerVisible.value = false;
}

async function submitChangePassword() {
    if (!oldPassword.value || !newPassword.value) {
        showError('请填写原密码和新密码');
        return;
    }
    if (newPassword.value.length < 6) {
        showError('新密码至少 6 位');
        return;
    }
    if (newPassword.value !== confirmPassword.value) {
        showError('两次输入的新密码不一致');
        return;
    }
    changing.value = true;
    try {
        const resp = await axios.post('/api/v1/auth/change-password', {
            old_password: oldPassword.value,
            new_password: newPassword.value,
        });
        // 后端改密后重新签发了令牌并清除了标志，前端同步本地状态，保持登录
        store.commit('setToken', resp.data.token);
        store.commit('setUser', resp.data.user);
        showSuccess('密码修改成功');
        changeDialog.value = false;
        bannerVisible.value = false;
    } catch (e) {
        const msg = e?.response?.data?.detail || e?.response?.data?.message || '修改失败';
        showError(msg);
    } finally {
        changing.value = false;
    }
}
</script>

<template>
    <!-- 首次安装 / 出厂弱密码提示横幅：全局置顶，点击「立即修改」内嵌对话框改密 -->
    <div v-if="needChangePwd" class="pwd-change-banner">
        <i class="pi pi-exclamation-triangle"></i>
        <span class="pwd-change-banner-text">
            您正在使用<strong>默认管理员密码</strong>，存在安全风险，请尽快修改。
        </span>
        <Button label="立即修改" size="small" severity="warn" @click="openChangeDialog" />
        <Button label="暂不处理" size="small" text @click="dismissBanner" />
    </div>

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
    <Dialog v-model:visible="changeDialog" modal header="修改登录密码" :style="{ width: '26rem' }">
        <div class="flex flex-column gap-3">
            <div class="field">
                <label for="oldPwd" class="block text-sm mb-1">原密码</label>
                <Password id="oldPwd" v-model="oldPassword" :feedback="false" toggleMask fluid />
            </div>
            <div class="field">
                <label for="newPwd" class="block text-sm mb-1">新密码（至少 6 位）</label>
                <Password id="newPwd" v-model="newPassword" toggleMask fluid />
            </div>
            <div class="field">
                <label for="confirmPwd" class="block text-sm mb-1">确认新密码</label>
                <Password id="confirmPwd" v-model="confirmPassword" :feedback="false" toggleMask fluid />
            </div>
        </div>
        <template #footer>
            <Button label="取消" text @click="changeDialog = false" />
            <Button label="确认修改" :loading="changing" @click="submitChangePassword" />
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

/* 默认密码风险提示横幅：置顶整条，唤起改密 */
.pwd-change-banner {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 1.25rem;
    background: #d97706;
    color: #fff;
    font-size: 0.875rem;
    line-height: 1.4;

    i.pi-exclamation-triangle {
        font-size: 1.1rem;
    }

    .pwd-change-banner-text {
        flex: 1 1 auto;
        min-width: 0;

        strong {
            font-weight: 700;
        }
    }
}

[data-theme='dark'] .pwd-change-banner,
.app-dark .pwd-change-banner {
    background: #b45309;
}

</style>
