import {fileURLToPath, URL} from 'node:url';

import {PrimeVueResolver} from '@primevue/auto-import-resolver';
import vue from '@vitejs/plugin-vue';
import Components from 'unplugin-vue-components/vite';
import {defineConfig} from 'vite';
import {viteStaticCopy} from 'vite-plugin-static-copy';
import viteCompression from 'vite-plugin-compression'

// https://vitejs.dev/config/
export default defineConfig({
    server: {
        port: 3000,
        host: '0.0.0.0',
        proxy: {
            '/api': {
                target: 'http://127.0.0.1:8080', // 后端服务器地址
                changeOrigin: true // 是否改变请求的源头
            },
            '/chat': {
                target: 'http://127.0.0.1:8000', // 后端服务器地址
                changeOrigin: true // 是否改变请求的源头
            }
        }
    },
    optimizeDeps: {
        noDiscovery: true
    },
    plugins: [
        vue({
            // ⚠️ 必须显式声明自定义元素，否则 `<altcha-widget>` 会被 Vue 编译器当成
            // Vue 组件去 resolve，编译成 `createVNode(_resolveComponent("altcha-widget"))`
            // —— 运行期解析不到就渲染成注释占位（页面上什么都不显示，且**没有任何报错**，
            // 只有控制台一条 "Failed to resolve component" 的 warning）。
            // 组件是 index.html 里用 <script type="module"> 注册的 Web Component，
            // 不属于 Vue 管辖，必须在这里放行。
            template: {
                compilerOptions: {
                    isCustomElement: (tag) => tag.startsWith('altcha-'),
                },
            },
        }),
        Components({
            resolvers: [PrimeVueResolver()]
        }),
        viteStaticCopy({
            targets: [
                {
                    src: 'node_modules/monaco-editor/min/vs/**/*',
                    dest: 'vs'
                }
            ]
        }),
        // ✅ gzip 压缩
        viteCompression({
            verbose: true,          // 显示压缩日志
            disable: false,         // 是否禁用
            threshold: 614400,       // 只压缩大于 600KB 的文件
            algorithm: 'gzip',      // gzip | brotliCompress | deflate | deflateRaw
            ext: '.gz',             // 生成的文件后缀
            deleteOriginFile: false // 是否删除源文件
        })
    ],
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url))
        }
    }
});
