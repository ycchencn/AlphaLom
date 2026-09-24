<script setup>

import { useRouter } from 'vue-router'; // 导入useRouter
import FloatingConfigurator from '@/components/FloatingConfigurator.vue';
import { useNotification } from '@/composables/useNotification';
import { ref } from 'vue';
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

    axios.post('/api/v1/auth/login', {
        username: account,
        password: pwd
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
        // 区分「账号密码错」与「后端鉴权服务不可用」：后者重试才有意义，
        // 提示成密码错会让人白试很多次。
        if (error?.response?.status === 503) {
            showError('鉴权服务暂不可用，请稍后再试');
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
        <div>
          <label for="loginAccount" class="block text-surface-900 dark:text-surface-0 text-lg font-medium mb-2">用户名 / 邮箱</label>
          <InputText id="loginAccount" type="text" placeholder="用户名或邮箱" class="w-full mb-6" v-model="identifier" />

          <label for="password1" class="block text-surface-900 dark:text-surface-0 font-medium text-lg mb-2">Password</label>
          <Password id="password1" v-model="password" placeholder="Password" :toggleMask="true" class="mb-6" fluid :feedback="false" @keyup.enter="handleLogin"></Password>

          <div class="flex items-center justify-between mt-2 mb-8 gap-4">
            <div class="flex items-center">
              <Checkbox v-model="checked" id="rememberme1" binary class="mr-2"></Checkbox>
              <label for="rememberme1">Remember me</label>
            </div>
            <span class="font-medium no-underline ml-2 text-right cursor-pointer text-primary">Forgot password?</span>
          </div>

          <Button label="Sign In" class="w-full" @click="handleLogin"></Button>
        </div>
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
