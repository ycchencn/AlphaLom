<script setup>

import { useRouter } from 'vue-router'; // 导入useRouter
import FloatingConfigurator from '@/components/FloatingConfigurator.vue';
import { useNotification } from '@/composables/useNotification';
import { ref } from 'vue';
import axios from 'axios';
import { store } from '@/store'
const email = ref('');
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
    // 去除前后空格后判断是否为空
    const username = email.value?.trim();
    const pwd = password.value?.trim();

    if (!username) {
        showError('请输入用户名或邮箱');
        return;
    }
    if (!pwd) {
        showError('请输入密码');
        return;
    }

    axios.post('/api/v1/auth/login', {
        username: username,
        password: pwd
    }).then(response => {
        showSuccess('登录成功');
        if (response.status === 200 && response.data.status === 1) {
            // 存储 token
            store.state.token = response.data.token;
            localStorage.setItem('token', response.data.token);
            // 跳转页面
            router.push({ path: '/market/cn_market_overview' });
        }
    }).catch(error => {
        // 可选：更详细的错误提示（如区分网络错误与认证失败）
        showError('登录失败，用户名或密码错误！');
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
          <label for="email1" class="block text-surface-900 dark:text-surface-0 text-lg font-medium mb-2">Email</label>
          <InputText id="email1" type="text" placeholder="Email address" class="w-full mb-6" v-model="email" />

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

<script>
export default {
  data() {
    return {
      email: '',
      password: '',
      checked: false
    }
  },
  methods: {
    handleLogin() {
      // 登录逻辑
    }
  }
}
</script>

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
