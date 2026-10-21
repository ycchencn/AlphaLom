import { computed, reactive } from 'vue';

// ⚠️ 这里的 darkTheme / toggleDarkMode / isDarkTheme 是 Svelte 版脚手架遗留，
// 与 src/composables/useTheme.js 是两套独立实现。历史上只有登录页的
// FloatingConfigurator 在用它，导致「登录页切了暗色但不写 localStorage，
// 进后台又被 useTheme 拉回亮色」。现已全部改用 useTheme，这里只保留
// 菜单相关的状态，不再承担配色职责 —— 新的代码请勿从这里取暗色状态。
const layoutConfig = reactive({
    preset: 'Aura',
    primary: 'emerald',
    surface: null,
    menuMode: 'static'
});

const layoutState = reactive({
    staticMenuDesktopInactive: false,
    overlayMenuActive: false,
    profileSidebarVisible: false,
    configSidebarVisible: false,
    staticMenuMobileActive: false,
    menuHoverActive: false,
    activeMenuItem: null
});

export function useLayout() {
    const setActiveMenuItem = (item) => {
        layoutState.activeMenuItem = item.value || item;
    };

    // ⚠️ 配色切换已迁至 @/composables/useTheme（cycleThemeMode），
    //    原因见文件顶部注释。这里不再提供 toggleDarkMode，避免两套实现并存。

    const toggleMenu = () => {
        if (layoutConfig.menuMode === 'overlay') {
            layoutState.overlayMenuActive = !layoutState.overlayMenuActive;
        }
        if (window.innerWidth > 991) {
            layoutState.staticMenuDesktopInactive = !layoutState.staticMenuDesktopInactive;
        } else {
            layoutState.staticMenuMobileActive = !layoutState.staticMenuMobileActive;
        }
    };

    const isSidebarActive = computed(() => layoutState.overlayMenuActive || layoutState.staticMenuMobileActive);

    const getPrimary = computed(() => layoutConfig.primary);

    const getSurface = computed(() => layoutConfig.surface);

    return {
        layoutConfig,
        layoutState,
        toggleMenu,
        isSidebarActive,
        getPrimary,
        getSurface,
        setActiveMenuItem
    };
}
