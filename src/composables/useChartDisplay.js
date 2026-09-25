// composables/useChartDisplay.js
//
// 详情页图表区块的显示开关（后端 system_setting 的 chart_display 组）。
//
// 目前只有一项 `kline_enabled`：K 线（klinecharts 走势图）是否显示。
// **默认开启** —— 后端在代码里定义了默认值（True），表里没有配置行就用它（见 routes/system_setting.py）。
//
// 为什么做成 composable：
//   个股详情页与 ETF 详情页都要按同一个开关决定「走势图表」区块显不显示，
//   两处各写一遍 fetch + 状态很容易漂移（改一处忘另一处）。
//
// ⚠️ 读取失败时**回落到「关闭」**，而不是打开：
//   配置表不可用时不该把 K 线突然显示出来（后端默认也是关闭），
//   保持「默认形态」比「猜一个」更可预期。

import { ref } from 'vue';
import axios from 'axios';

// 进程内缓存：同一页面内多处调用只打一次接口；
// 但设置页改完要能立刻生效 → 导出 refreshChartDisplay 供手动失效。
let cached = null;
let inflight = null;

/**
 * 拉取图表显示配置（带进程内缓存）。
 * @returns {Promise<Object>} 形如 { kline_enabled: false }
 */
export function fetchChartDisplay() {
    if (cached) return Promise.resolve(cached);
    if (inflight) return inflight;

    inflight = axios.get('/api/v1/settings/chart_display')
        .then((response) => {
            // 后端返回 {code, data:{values:{...}, items:[...]}, values:{...}}
            // 优先取归一化后的 values，拿不到就空对象 → 调用方按「默认关闭」处理。
            const values = response.data?.values || response.data?.data?.values || {};
            cached = values;
            return values;
        })
        .catch(() => {
            // 不缓存失败结果：下次进页面还能重试
            return {};
        })
        .finally(() => {
            inflight = null;
        });

    return inflight;
}

/** 手动失效缓存（设置页保存后调用，保证下次读拿到新值）。 */
export function invalidateChartDisplay() {
    cached = null;
}

/**
 * 在组件里使用图表显示配置。
 *
 * 用法：
 *   const { klineEnabled } = useChartDisplay();   // klineEnabled 是 ref<boolean>
 *   onMounted(() => loadChartDisplay());          // 或在已有的 onMounted 里调用
 */
export function useChartDisplay() {
    // 默认 true：与后端默认值一致（表里没配置时 = 开启，详情页默认展示走势图）
    const klineEnabled = ref(true);

    const loadChartDisplay = async () => {
        const values = await fetchChartDisplay();
        // ⚠️ 只有后端**明确返回 false**才关：缺省 / 接口抖动 / 读取失败都保持默认开启，
        // 否则一旦 /chart_display 请求失败（返回 {}），klineEnabled 会被误翻成 false 把走势图整块关掉。
        klineEnabled.value = values.kline_enabled !== false;
        return klineEnabled.value;
    };

    return { klineEnabled, loadChartDisplay };
}
