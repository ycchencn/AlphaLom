import {createApp} from 'vue';
import App from './App.vue';
import router from './router';

import Aura from '@primeuix/themes/aura';
import Lara from '@primeuix/themes/lara';
import Material from '@primeuix/themes/material';
import PrimeVue from 'primevue/config';
import ConfirmationService from 'primevue/confirmationservice';
import ToastService from 'primevue/toastservice';

import '@/assets/styles.scss';
import '@/assets/tailwind.css';

import 'katex/dist/katex.min.css';

import Tooltip from 'primevue/tooltip';

const app = createApp(App);

app.use(router);
app.use(PrimeVue, {
    theme: {
        preset: Lara,
        options: {
            darkModeSelector: false   // 或 'none'，二选一
        }
    }
})
app.use(ToastService);
app.use(ConfirmationService);

// 注册 v-tooltip 全局指令
app.directive('tooltip', Tooltip);

app.mount('#app');
