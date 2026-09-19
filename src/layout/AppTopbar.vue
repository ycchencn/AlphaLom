<script setup>
import {useLayout} from '@/layout/composables/layout';
import AppConfigurator from './AppConfigurator.vue';
import router from "@/router";

// const {toggleMenu, toggleDarkMode, isDarkTheme} = useLayout();

</script>

<template>
    <div class="layout-topbar">
        <div class="layout-topbar-logo-container">

        </div>

        <div class="layout-topbar-actions">
            <div class="layout-topbar-menu hidden lg:block">
                <div class="layout-topbar-menu-content">
<!--                    <router-link class="text-blue-500"-->
<!--                                 target="_blank"-->
<!--                                 :to="{ name: 'trading-terminal', params: { } }">-->
<!--                        <Chip label="Terminal" icon="pi pi-twitch" style="cursor: pointer"/>-->
<!--                    </router-link>-->
                </div>
            </div>
        </div>
    </div>
</template>
