import {createApp} from 'vue';
import App from './App.vue';
import router from './router';
import axios from 'axios';
import { store } from './store';

import Aura from '@primeuix/themes/aura';
import PrimeVue from 'primevue/config';
import ConfirmationService from 'primevue/confirmationservice';
import ToastService from 'primevue/toastservice';

import '@/assets/styles.scss';
import '@/assets/tailwind.css';

import 'katex/dist/katex.min.css';

import Tooltip from 'primevue/tooltip';

import { definePreset } from '@primevue/themes';

import * as echarts from 'echarts';

const app = createApp(App);

const MyPreset = definePreset(Aura, {
    //Your customizations, see the following sections for examples
    darkModeSelector: false,
    semantic: {
        primary: {
            50: '{blue.50}',
            100: '{blue.100}',
            200: '{blue.200}',
            300: '{blue.300}',
            400: '{blue.400}',
            500: '{blue.500}',
            600: '{blue.600}',
            700: '{blue.700}',
            800: '{blue.800}',
            900: '{blue.900}',
            950: '{blue.950}'
        }
    }
});

app.use(router);
app.use(PrimeVue, {
    theme: {
        preset: MyPreset,
        options: {
            darkModeSelector: false   // 或 'none'，二选一
        }
    }
})
app.use(ToastService);
app.use(ConfirmationService);

// ==================== 登录令牌注入与 401 统一处理 ====================
// 后端已是多用户：股票池 / 量化策略 / ETF 自选这些「用户私有」接口不带令牌一律 401，
// 所以每个请求都必须带上 `Authorization: Bearer <token>`。
// 这里在 axios 全局实例上挂拦截器（各页面是直接 `import axios` 用的同一个实例，
// 因此一处注册即全局生效），避免 22 个页面各写一遍、漏一个就那个页面报未登录。
axios.interceptors.request.use(config => {
    const token = store.state.token;
    if (token) {
        config.headers = config.headers || {};
        // 不覆盖调用方显式设置的 Authorization（便于临时用别的凭证调试）
        if (!config.headers.Authorization) {
            config.headers.Authorization = `Bearer ${token}`;
        }
    }
    return config;
});

// 401 = 未登录 / 令牌失效（后端 Redis 里查不到或已过期）：
// 清掉本地令牌并送回登录页，否则用户会停在一个「每个请求都失败」的页面里。
axios.interceptors.response.use(
    response => response,
    error => {
        const status = error?.response?.status;
        if (status === 401) {
            store.commit('removeToken');
            const current = router.currentRoute.value;
            if (current.path !== '/auth/login') {
                router.replace({ path: '/auth/login' });
            }
        }
        return Promise.reject(error);
    }
);

// 启动时用 /auth/me 复核一次登录态：localStorage 里的令牌可能已经被服务端撤销
// （管理员改了密码 / 禁用账号 / 用户在别处登出 / Redis TTL 到期）。不复核的话，
// 用户会先进入一个「每个请求都失败」的页面，等服务端 401 回来才被弹回登录页。
if (store.state.token) {
    axios.get('/api/v1/auth/me')
        .then(response => {
            // 顺手刷新本地缓存的用户信息（角色可能已被管理员改过，isAdmin 依赖它）
            store.commit('setUser', response.data);
        })
        .catch(() => {
            // 401 已由上面的响应拦截器统一处理（清令牌 + 跳登录页）；
            // 网络异常时保持现状，避免把用户从离线可看的页面上踢走。
        });
}

app.config.globalProperties.$echarts = echarts;

// 注册 v-tooltip 全局指令
app.directive('tooltip', Tooltip);

app.mount('#app');
