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
</script>

<template>
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
</style>
