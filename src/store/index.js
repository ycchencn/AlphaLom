// 导入必要的库
import { createStore } from 'vuex';

// localStorage 里读出来的用户信息可能被手工改坏，解析失败时当作未登录，
// 不要让一个坏字符串把整个应用卡在启动阶段（JSON.parse 会抛错）。
function readStoredUser() {
    try {
        return JSON.parse(localStorage.getItem('user') || 'null');
    } catch (e) {
        localStorage.removeItem('user');
        return null;
    }
}

// 创建一个新的Vuex store
export const store = createStore({
    state: {
        token: localStorage.getItem('token') || null,
        // 当前登录用户（后端 /auth/me 或登录接口返回），用于展示与管理员功能判断
        user: readStoredUser()
    },
    mutations: {
        setToken(state, token) {
            state.token = token;
            localStorage.setItem('token', token);
        },
        removeToken(state) {
            state.token = null;
            state.user = null;
            localStorage.removeItem('token');
            localStorage.removeItem('user');
        },
        setUser(state, user) {
            state.user = user;
            if (user) {
                localStorage.setItem('user', JSON.stringify(user));
            } else {
                localStorage.removeItem('user');
            }
        }
    },
    getters: {
        // ⚠️ 只表示「本地有令牌」，**不代表令牌有效** —— 有效性以后端为准，
        // 失效时接口会返回 401，由 main.js 的响应拦截器统一清令牌并跳登录页。
        isAuthenticated: state => !!state.token,
        isAdmin: state => state.user?.role === 'admin'
    },
    actions: {
        // 可以在这里定义一些异步操作
    }
});
