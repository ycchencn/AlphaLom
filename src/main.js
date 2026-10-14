import {createApp} from 'vue';
import {watch} from 'vue';
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
// ==================== SPA 兜底误伤：把「接口返回 HTML」变成明确错误 ====================
// 部署形态是「后端同时托管 dist 静态资源」，且 run_fastapi.py 里有一条
// `GET /{full_path:path}` 的 SPA 兜底：**任何未命中的路径都返回 index.html（HTTP 200）**。
//
// 于是「后端还没有这个接口」（例如前端已更新、后端没重新部署）时，浏览器拿到的是
// 200 + text/html，而不是 404。各页面只检查 `response.data.xxx`，就会静默变成
// 「列表为空」——表现为「共 0 个 XX」，完全看不出真实原因（我们踩过这个坑）。
//
// 这里统一把它转成一个**带路径的明确错误**，让页面 catch 里能显示可读提示。
axios.interceptors.response.use(
    response => {
        const status = response.status;
        const ctype = String(response.headers?.['content-type'] || '');
        const url = String(response.config?.url || '');
        // 只针对形如接口的路径（/api/...）；静态资源与页面路由本身返回 HTML 是正常的
        const looksLikeApi = url.includes('/api/');
        const isHtml = ctype.includes('text/html');
        if (status === 200 && looksLikeApi && isHtml) {
            const err = new Error(
                `接口 ${url} 返回了 HTML 而不是 JSON —— 通常是后端没有这个接口（服务端版本落后于前端）。` +
                `请重新部署/重启后端服务后重试。`
            );
            err.isSpaFallback = true;
            err.config = response.config;
            return Promise.reject(err);
        }
        return response;
    },
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

// ==================== 网站统计代码注入 ====================
// 管理员在「系统管理 → 通用设置 → 网站统计代码」粘贴的 <script> 片段（百度统计 /
// CNZZ / Google Analytics 等）。这里在启动后拉一次并注入页面执行。
//
// 两个时机都要覆盖（否则登录后才加载的会话里统计会丢）：
//   1) 刷新进入（localStorage 里已有令牌）—— mount 后立即试一次；
//   2) 登录后进入（首屏是登录页，拿到令牌时再注入）—— watch store token。
// ⚠️ 注入容器用 display:none：挡住代码里可能夹带的可见内容（统计平台偶尔会带
//    个小图标）。代价是 noscript 像素不加载 —— 本应用禁用 JS 本就无法运行，
//    这个代价可以忽略。
// ⚠️ innerHTML 里的 <script> **不会执行**：必须逐个 createElement 重建后再入
//    DOM（<script src> 外链与内联脚本都走这条路）。
// 模块级状态：
//   done    —— 已拿到一次明确答复（成功拿到代码/确认无代码），不再注入；
//   pending —— 请求在途（避免登录与首屏两次触发并发双注入）；
//   retry   —— 在途期间又来了触发（登录），请求结束后补一次。
const _analytics = {done: false, pending: false, retry: false};

function injectAnalyticsCode() {
    if (_analytics.done) return;
    if (_analytics.pending) {
        _analytics.retry = true;
        return;
    }
    _analytics.pending = true;
    axios.get('/api/v1/settings/general/analytics')
        .then((response) => {
            const code = response?.data?.code;
            if (typeof code === 'string' && code.trim()) {
                const container = document.createElement('div');
                container.setAttribute('data-analytics', 'injected');
                container.style.display = 'none';
                container.innerHTML = code;
                container.querySelectorAll('script').forEach((oldScript) => {
                    const fresh = document.createElement('script');
                    for (const attr of oldScript.attributes) {
                        fresh.setAttribute(attr.name, attr.value);
                    }
                    fresh.text = oldScript.text;
                    oldScript.replaceWith(fresh);
                });
                document.body.appendChild(container);
            }
            // 拿到明确答复（有码注入完 / 确认无码）→ 标记完成，同一页面加载不再注入
            _analytics.done = true;
        })
        .catch(() => {
            // 未登录（401）/ 接口不存在 / 网络异常：静默跳过，**不标记 done** ——
            // 登录成功后 watch 会再触发一次（见下方）。统计代码绝不允许影响主流程。
        })
        .finally(() => {
            _analytics.pending = false;
            if (!_analytics.done && _analytics.retry) {
                _analytics.retry = false;
                injectAnalyticsCode();
            }
        });
}

app.config.globalProperties.$echarts = echarts;

// 注册 v-tooltip 全局指令
app.directive('tooltip', Tooltip);

app.mount('#app');

// 登录后（或刷新后令牌本就在）注入统计代码；未登录时 watch 不触发，
// 登录成功 setToken 后补上 —— 见 Login.vue 的 setToken 提交。
watch(() => store.state.token, (token) => {
    if (token) injectAnalyticsCode();
});
injectAnalyticsCode();
