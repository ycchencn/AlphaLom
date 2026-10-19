<script setup>
import AppConfigurator from '@/layout/AppConfigurator.vue';
// ⚠️ 必须用 useTheme，不能用 useLayout().toggleDarkMode：
// 后者是 Svelte 版脚手架遗留的独立实现，自己 toggle app-dark 类且**不写 localStorage**。
// 两套并存时会出现「登录页切了暗色，进后台被 useTheme 按 localStorage 拉回亮色」的割裂。
import { cycleThemeMode, useThemeIcon } from '@/composables/useTheme';

const themeIcon = useThemeIcon();
</script>

<template>
    <div class="fixed flex gap-4 top-8 right-8">
        <Button type="button" @click="cycleThemeMode" rounded :icon="themeIcon" severity="secondary" />
        <div class="relative">
            <Button
                icon="pi pi-palette"
                v-styleclass="{ selector: '@next', enterFromClass: 'hidden', enterActiveClass: 'animate-scalein', leaveToClass: 'hidden', leaveActiveClass: 'animate-fadeout', hideOnOutsideClick: true }"
                type="button"
                rounded
            />
            <AppConfigurator/>
        </div>
    </div>
</template>
