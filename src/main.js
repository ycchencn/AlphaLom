import {createApp} from 'vue';
import App from './App.vue';
import router from './router';

import Aura from '@primeuix/themes/aura';
import PrimeVue from 'primevue/config';
import ConfirmationService from 'primevue/confirmationservice';
import ToastService from 'primevue/toastservice';

import '@/assets/styles.scss';
import '@/assets/tailwind.css';

import 'katex/dist/katex.min.css';

import Tooltip from 'primevue/tooltip';

import { definePreset } from '@primevue/themes';

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

// 注册 v-tooltip 全局指令
app.directive('tooltip', Tooltip);

app.mount('#app');
