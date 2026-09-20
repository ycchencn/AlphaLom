<script setup>
import {ref} from 'vue'

import AppMenuItem from './AppMenuItem.vue'

const model = ref([
    {
        label: '市场监控',
        enable: true, // 控制该组是否展示
        items: [
            {
                label: '沪深大盘',
                icon: 'pi pi-fw pi-wave-pulse',
                to: '/market/cn_market_overview',
                enable: true, // 可进一步控制该菜单项是否展示或禁用
            },
            {
                label: '事件驱动',
                icon: 'pi pi-fw pi-twitter',
                to: '/market/news_flow',
                enable: true,
            },
            {
                label: 'ETF洞察',
                icon: 'pi pi-fw pi-cloud-download',
                to: '/market/etf_insight',
                enable: true,
            },
        ]
    },
    {
        label: '投资组合',
        enable: true,
        items: [
            {
                label: '股票池',
                icon: 'pi pi-fw pi-clone',
                to: '/quant/stock_monitor',
                enable: true,
            }
        ]
    },
    {
        label: '量化模型',
        enable: true,
        items: [
            {
                label: '量化策略',
                icon: 'pi pi-fw pi-microchip-ai',
                to: '/quant/portfolio_list',
                enable: true,
            },
            {
                label: '智能体',
                icon: 'pi pi-fw pi-wave-pulse',
                to: '/ai/chat',
                enable: true,
            },
            {
                label: 'DCF估值',
                icon: 'pi pi-fw pi-clone',
                to: '/quant/dcf_insight',
                enable: true,
            }
        ]
    },
    {
        label: '系统设置',
        enable: true, // 若设为 false，则整个系统设置分组不显示
        items: [
            {
                label: '系统日志',
                icon: 'pi pi-fw pi-stopwatch',
                to: '/system/system_log',
                enable: true,
            },
            {
                label: 'API文档',
                icon: 'pi pi-fw pi-twitch',
                url: 'https://www.databull.cn/docs',
                target: '_blank',
                enable: true,
            }
        ]
    }
])
</script>

<template>
    <div class="menu-logo-wrap">
        <router-link to="/market/cn_market_overview" class="layout-topbar-logo">
            <img src="/images/alphalom-logo-220.png" alt="AlphaLom" class="menu-logo"/>
        </router-link>
    </div>
    <Divider/>
    <ul class="layout-menu">
        <template v-for="(item, i) in model" :key="item">
            <!-- 当顶层分组 enable 不为 false 时才渲染 -->
            <template v-if="item.enable !== false">
                <app-menu-item
                    v-if="!item.separator"
                    :item="item"
                    :index="i"
                ></app-menu-item>
                <li v-if="item.separator" class="menu-separator"></li>
            </template>
        </template>
    </ul>
</template>

<style lang="scss" scoped>
.menu-logo-wrap {
    display: flex;
    justify-content: center;
    padding: 1rem 0 0.25rem;
}

.layout-topbar-logo {
    display: inline-flex;
    align-items: center;
}

/* 源图 976×204，这里按 CSS 缩放显示；用 height 定高、宽度自适应以保持比例。
   侧边栏固定宽度 16rem(256px)，源图按 180px 宽显示时会占掉 70% 宽度、显得过大，
   故改为定高 ~26px（约合宽度 124px，占侧边栏 48%），留出舒适边距。 */
.menu-logo {
    height: 1.6rem;       /* ≈25.6px → 渲染宽度约 122px */
    width: auto;
    max-width: 10rem;
    object-fit: contain;
    display: block;
}
</style>