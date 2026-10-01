<script setup>

import { useRouter } from 'vue-router'; // 导入useRouter
import FloatingConfigurator from '@/components/FloatingConfigurator.vue';
import { useNotification } from '@/composables/useNotification';
import { ref, onMounted } from 'vue';
import axios from 'axios';
import { store } from '@/store'
const identifier = ref('');
const password = ref('');
const checked = ref(true);
const { showSuccess, showError } = useNotification();
// 创建一个路由器实例
const router = useRouter();
const images = [
    '/images/bg1.jpeg',
    '/images/bg2.jpeg',
    '/images/bg3.jpeg',
]
const currentIndex = ref(Math.floor(Math.random() * (images.length)))

// ---- ALTCHA 人机校验 ----
// 组件是 Web Component，会把解题得到的 payload 写进最近的 <form> 里的
// <input type="hidden" name="altcha">。⚠️ 取值的正确姿势是读那个 input，
// 而不是去问组件内部 state。
const altchaWidget = ref(null);
const formEl = ref(null);

// 是否启用人机校验：默认关闭，挂载后探一次 /challenge 由后端给出权威结论。
// ⚠️ 后端在「禁用（dev / ALTCHA_ENABLED=false）」时返回 {enabled:false}，
// 前端据此隐藏 widget、登录也不强制 payload；而在「启用却配置坏」时返回 503，
// 此时兜底开启 widget，让用户在登录阶段看到 503 错误（fail-closed，不被静默绕过）。
const altchaEnabled = ref(false);
const altchaChecked = ref(false);

async function checkAltchaEnabled() {
  try {
    const resp = await axios.get('/api/v1/altcha/challenge');
    // 200 + enabled===false → 明确禁用；其余（含真实题、503 等）→ 兜底开启
    altchaEnabled.value = !(resp.status === 200 && resp.data && resp.data.enabled === false);
  } catch (e) {
    // 取题失败（含 503 配置坏）→ 兜底开启 widget，登录阶段暴露配置错误
    altchaEnabled.value = true;
  } finally {
    altchaChecked.value = true;
  }
}

onMounted(checkAltchaEnabled);

function readAltchaPayload() {
    const el = formEl.value?.querySelector('input[name="altcha"]');
    return el?.value || '';
}

// 组件是否真的挂载出来了。⚠️ 缺失时不能让用户只看到「请先完成人机验证」却
// 找不到任何可点的东西 —— 那是最典型的「自救不了」死胡同。常见成因：
//   1) 页面是缓存的旧 HTML，压根没引 /altcha/altcha.min.js；
//   2) 构建时没放行自定义元素（Vue 把 <altcha-widget> 当组件 resolve → 渲染成注释）；
//   3) 非 secure context（http + 非 localhost）→ crypto.subtle 不可用，组件不工作。
// 所以这里返回可区分的文案，而不是笼统的「验证失败」。
function altchaUnavailableReason() {
    if (!window.customElements || !window.customElements.get('altcha-widget')) {
        return '人机校验组件未加载，请强制刷新页面（Ctrl+F5）后重试';
    }
    if (!formEl.value?.querySelector('altcha-widget')) {
        return '人机校验组件未渲染，请强制刷新页面（Ctrl+F5）后重试';
    }
    // 组件在，但还没解出题：多半是刚点太快，或本页非 secure context 导致解题失败
    if (!window.isSecureContext) {
        return '当前页面不是安全上下文（需 HTTPS 或 localhost），人机校验无法工作';
    }
    return '人机校验正在计算，请稍候一秒再点登录';
}

// 服务端每次校验都会「消费」掉这份 payload（一次性，防重放），所以**业务失败后
// 必须换一道新题重新解**。只 reset() 不 verify() 会停在未验证态 ——
// 漏掉这一步的表现很隐蔽：密码输错一次后再点登录，会拿到「人机验证已使用过」，
// 用户会以为是自己账号出了问题。
function resetAltcha() {
    const w = altchaWidget.value;
    if (!w) return;
    try {
        w.reset();
        w.verify();
    } catch (e) {
        // 组件还没挂载完（或脚本没加载出来）时忽略：下次提交会自动取新题
    }
}

function handleLogin() {
    // ⚠️ 账号字段既接受**用户名**也接受**邮箱**（后端 find_by_identifier 先按用户名、
    // 没命中再按邮箱查），所以这里绝不能做「必须是邮箱格式」的校验 —— 否则
    // 用户名（如 admin）会被前端自己拦下来。标签也就写成「用户名 / 邮箱」，
    // 历史上前端标签写 Email、后端却只认 username，导致填邮箱永远登不上。
    const account = identifier.value?.trim();
    const pwd = password.value?.trim();

    if (!account) {
        showError('请输入用户名或邮箱');
        return;
    }
    if (!pwd) {
        showError('请输入密码');
        return;
    }

    // payload 由组件异步解出，点击过快时可能还没好；此时提示而不是白跑一次请求
    // （后端也会拒，但前端先拦一句的文案更有指向性，也能帮用户区分「组件没加载」
    //  和「正在计算」这两件事）。
    // ⚠️ 人机校验被禁用（dev / ALTCHA_ENABLED=false）时不要求 payload，直接放行提交。
    const altcha = altchaEnabled.value ? readAltchaPayload() : '';
    if (altchaEnabled.value && !altcha) {
        showError(altchaUnavailableReason());
        return;
    }

    axios.post('/api/v1/auth/login', {
        username: account,
        password: pwd,
        altcha,
    }).then(response => {
        if (response.status === 200 && response.data.status === 1) {
            // 存令牌与当前用户：走 mutation（原实现直接改 store.state，
            // localStorage 也要手写一遍，容易漏），后续请求由 main.js 的
            // 拦截器自动带上 Authorization 头。
            store.commit('setToken', response.data.token);
            store.commit('setUser', response.data.user);
            showSuccess('登录成功');
            // 跳转页面
            router.push({ path: '/market/cn_market_overview' });
        }
    }).catch(error => {
        const status = error?.response?.status;
        const message = error?.response?.data?.message;
        if (status === 503) {
            // 区分「账号密码错」与「后端鉴权/人机服务不可用」：后者重试才有意义，
            // 提示成密码错会让人白试很多次。
            showError(message || '服务暂不可用，请稍后再试');
        } else if (status === 400) {
            // 人机校验类失败（缺失/无效/已使用/过期）—— 后端文案已经说清了原因，
            // 直接透传，然后换题重解，让用户下一次点击能正常提交。
            showError(message || '人机验证失败，请重试');
            resetAltcha();
        } else {
            showError('登录失败，用户名/邮箱或密码错误！');
        }
    });
}

</script>

<template>
  <Toast />
  <FloatingConfigurator />

  <!-- 外层容器：h-screen 确保高度占满，flex 横向排列 -->
  <div class="flex h-screen w-full overflow-hidden">

    <!-- 1. 左侧背景图区域 (自动占据剩余 70%) -->
    <div class="hidden lg:block relative flex-1">
      <!-- 背景图 -->
      <div
        class="absolute inset-0 bg-cover bg-center"
        :style="{ backgroundImage: `url('${images[currentIndex]}')` }"
      ></div>
      <!-- 遮罩层 (可选) -->
      <div class="absolute inset-0 bg-black/30"></div>
    </div>

    <!-- 2. 右侧登录区域 (强制宽度 30%) -->
    <!-- w-[30%]: 强制宽度为30% -->
    <!-- h-full: 高度100% -->
    <!-- bg-surface-0: 白色背景，无圆角 -->
    <div class="w-[35%] h-full flex items-center justify-center bg-surface-0 dark:bg-surface-900 shadow-xl z-10">

      <!-- 登录表单内容 -->
      <div class="w-full max-w-md px-8 py-10">

        <!-- Logo -->
        <div class="text-center mb-10">
          <img src="/images/alphalom-logo.png" alt="AlphaLom" class="login-logo mb-6 mx-auto" />
          <div class="text-surface-900 dark:text-surface-0 text-3xl font-medium mb-2">Welcome to AlphaLom!</div>
          <span class="text-muted-color font-medium">Sign in to System</span>
        </div>

        <!-- 表单字段 -->
        <!-- ⚠️ 必须是真正的 <form>：altcha-widget 会把 <input type="hidden" name="altcha">
             插进**最近的 form**，取 payload 就读这个 input。div 包裹时组件无处可插。 -->
        <form ref="formEl" @submit.prevent="handleLogin">
          <label for="loginAccount" class="block text-surface-900 dark:text-surface-0 text-lg font-medium mb-2">用户名 / 邮箱</label>
          <InputText id="loginAccount" type="text" placeholder="用户名或邮箱" class="w-full mb-6" v-model="identifier" />

          <label for="password1" class="block text-surface-900 dark:text-surface-0 font-medium text-lg mb-2">Password</label>
          <Password id="password1" v-model="password" placeholder="Password" :toggleMask="true" class="mb-6" fluid :feedback="false" @keyup.enter="handleLogin"></Password>

          <!-- 人机校验：challenge 指向自建出题接口；同源相对路径即可。
               ⚠️ 组件依赖 crypto.subtle，必须在 secure context（HTTPS 或 localhost）。
               用 http://<内网IP> 打开时组件会直接失效 —— 部署时要么上 HTTPS，
               要么把出口限制在 localhost / 反向代理成 https。
               ⚠️ 是否渲染由后端 /challenge 的 enabled 决定（dev / ALTCHA_ENABLED=false
               时禁用，不渲染 widget）；altchaChecked 未探明前先不渲染，避免闪烁。 -->
          <div class="mb-6" v-if="altchaChecked">
            <altcha-widget
              v-if="altchaEnabled"
              ref="altchaWidget"
              challenge="/api/v1/altcha/challenge"
              name="altcha"
              language="zh-cn"
              type="checkbox"
              auto="onload"
            ></altcha-widget>
            <p v-else class="text-muted-color text-sm">（开发环境已关闭人机校验）</p>
          </div>

          <div class="flex items-center justify-between mt-2 mb-8 gap-4">
            <div class="flex items-center">
              <Checkbox v-model="checked" id="rememberme1" binary class="mr-2"></Checkbox>
              <label for="rememberme1">Remember me</label>
            </div>
            <span class="font-medium no-underline ml-2 text-right cursor-pointer text-primary">Forgot password?</span>
          </div>

          <Button label="Sign In" type="submit" class="w-full" @click="handleLogin"></Button>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 源图 488×102，按 CSS 定高缩放；原先 w-56(224px) 偏大，收窄到 ~176px */
.login-logo {
  height: 2.2rem;   /* ≈35px → 渲染宽度约 168px */
  width: auto;
  max-width: 11rem;
  object-fit: contain;
  display: block;
}
</style>

<style>
/* ⚠️ 不能用 scoped：altcha-widget 是 Web Component，scoped 属性选择器打不进它的
   阴影边界（而且它由 index.html 的 <script type="module"> 注册，不是本组件的子组件）。 */
altcha-widget {
  /* 组件默认主题用 CSS light-dark() 取色；在组件自身上声明 color-scheme 就能整体
     切暗色，比逐个覆盖 --altcha-* 变量稳。项目的暗色开关是 [class*="app-dark"]。 */
  color-scheme: light;
  display: block;
  width: 100%;
}

[class*='app-dark'] altcha-widget {
  color-scheme: dark;
}
</style>
