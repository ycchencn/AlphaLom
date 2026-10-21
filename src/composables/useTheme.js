// ==================== 全局配色模式（亮色 / 暗色 / 跟随系统） ====================
//
// 背景：PrimeVue 4 的暗色靠「预设里的 darkModeSelector」和「theme.options.darkModeSelector」
// 两个开关共同控制 —— 两者任一被关掉，主题就永远只走亮色分支。本项目历史上两处都被写成
// false，所以加 app-dark 类也不会有任何变化。这里统一收口到本模块，main.js 只读这里的常量。
//
// 三种模式：
//   light —— 强制亮色（忽略系统设置）
//   dark  —— 强制暗色
//   auto  —— 跟随操作系统（prefers-color-scheme），默认模式
//
// 实现要点：
//   1. 落地方式是给 <html> 加 `app-dark` 类（而不是 data-theme 属性），因为
//      PrimeVue 预设、tailwind.config.js 的 darkMode selector、_dark.scss 三处都按这个类名。
//   2. localStorage 持久化用户选择；读不到/值非法时回落到 auto（即"没选过 = 跟随系统"）。
//   3. 监听 matchMedia 变化：只有 auto 模式下才响应系统切换，用户手动锁定的模式不被覆盖。
//   4. 暴露一个主题版本号（themeVersion），供图表等「JS 里算颜色」的模块在切主题后重绘。

import { computed, ref } from 'vue';

const STORAGE_KEY = 'alphalom_theme_mode';
const DARK_CLASS = 'app-dark';

const VALID_MODES = ['auto', 'light', 'dark'];
const SYSTEM_DARK_QUERY = '(prefers-color-scheme: dark)';

// ---- 状态（模块级单例） ----
const mode = ref(readStoredMode()); // 'auto' | 'light' | 'dark'
const systemPrefersDark = ref(querySystemDark());
// 切主题时自增，供图表 watch 触发重绘
const themeVersion = ref(0);

let mediaQuery = null;

function readStoredMode() {
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (VALID_MODES.includes(saved)) {
            return saved;
        }
    } catch (e) {
        // 隐私模式 / 禁用 storage 时 localStorage 访问会抛错，不能因此让整个应用挂掉
        console.warn('[theme] 读取本地存储失败，回落到 auto', e);
    }
    return 'auto';
}

function querySystemDark() {
    if (typeof window === 'undefined' || !window.matchMedia) {
        return false;
    }
    return window.matchMedia(SYSTEM_DARK_QUERY).matches;
}

// 实际生效的暗色状态：auto 时读系统，否则读用户锁定值
const isDark = computed(() => (mode.value === 'auto' ? systemPrefersDark.value : mode.value === 'dark'));

// ---- 落地 ----
function applyTheme() {
    const root = document.documentElement;
    root.classList.toggle(DARK_CLASS, isDark.value);
    // 同步浏览器 UI（滚动条、表单控件原生部分、地址栏）跟随配色
    root.style.colorScheme = isDark.value ? 'dark' : 'light';
    themeVersion.value += 1;
}

function persist(modeValue) {
    try {
        localStorage.setItem(STORAGE_KEY, modeValue);
    } catch (e) {
        console.warn('[theme] 写入本地存储失败（配色模式本次会话内仍生效）', e);
    }
}

export function setThemeMode(nextMode) {
    if (!VALID_MODES.includes(nextMode)) {
        console.warn(`[theme] 未知配色模式 ${nextMode}，已忽略`);
        return;
    }
    mode.value = nextMode;
    persist(nextMode);
    applyTheme();
}

// 顶栏一键循环：跟随系统 → 浅色 → 深色 → 跟随系统
// 循环顺序刻意以 auto 起手，让"第一次点"落在用户最容易预期的"我要手动定一个"上，
// 而 auto→dark 会让浅色系统的用户突然看到反转。
const CYCLE_ORDER = ['auto', 'light', 'dark'];

export function cycleThemeMode() {
    const currentIndex = CYCLE_ORDER.indexOf(mode.value);
    setThemeMode(CYCLE_ORDER[(currentIndex + 1) % CYCLE_ORDER.length]);
}

function handleSystemChange(event) {
    systemPrefersDark.value = event.matches;
    // 用户锁定过 light/dark 时不响应系统变化
    if (mode.value === 'auto') {
        applyTheme();
    }
}

let initialized = false;

export function initTheme() {
    if (initialized) {
        return;
    }
    initialized = true;

    // 首帧完成后才启用切换过渡（见 _core.scss）：进场动画与主题过渡叠加会闪烁。
    requestAnimationFrame(() => {
        document.documentElement.classList.add('theme-ready');
    });

    if (typeof window !== 'undefined' && window.matchMedia) {
        mediaQuery = window.matchMedia(SYSTEM_DARK_QUERY);
        // addEventListener 在老 Safari 上缺失，回退到 addListener
        if (mediaQuery.addEventListener) {
            mediaQuery.addEventListener('change', handleSystemChange);
        } else if (mediaQuery.addListener) {
            mediaQuery.addListener(handleSystemChange);
        }
    }

    applyTheme();
}

export function useTheme() {
    return {
        mode,
        isDark,
        systemPrefersDark,
        themeVersion,
        setThemeMode,
        cycleThemeMode
    };
}

// 顶栏图标的语义：auto 模式下用当前实际生效的状态图标（系统亮→太阳/系统暗→月亮），
// 让用户一眼看出"现在到底长什么样"，而不是只显示"我选了 auto"。
export const THEME_ICON = {
    light: 'pi pi-sun',
    dark: 'pi pi-moon',
    autoLight: 'pi pi-sun',
    autoDark: 'pi pi-moon'
};

export function useThemeIcon() {
    return computed(() => {
        if (mode.value === 'auto') {
            return systemPrefersDark.value ? THEME_ICON.autoDark : THEME_ICON.autoLight;
        }
        return mode.value === 'dark' ? THEME_ICON.dark : THEME_ICON.light;
    });
}

export const THEME_MODE_LABEL = {
    auto: '跟随系统',
    light: '浅色',
    dark: '深色'
};

export { isDark };

// 具名导出：供非组件模块（如 utils/echartsTheme.js）直接订阅，
// 不必为了 watch 它而调用 useTheme()。
export { themeVersion };
