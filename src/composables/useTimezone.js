// composables/useTimezone.js
//
// 全站「展示时区」的读取与时间格式化（后端 system_setting 的 general_setting 组）。
//
// 为什么做成 composable：
//   多个页面都要按同一个时区把「后端给的墙上时间」渲染出来，各写一遍
//   fetch + 格式化必然漂移（改一处忘另一处，时间就会对不上）。
//
// 后端返回的时间串是**该时区的墙上时间、不带时区后缀**（形如 2026-09-29T21:30:00）。
//   所以前端**不能**直接 `new Date('2026-09-29T21:30:00')` —— 那会按**浏览器本地时区**
//   解释，一台 UTC 的机器上就会显示成 13:30。正确做法是当作「纯字段」解析：
//   用正则拆出年月日时分秒，不经过 Date 的时区推断。
//
// 读取失败时回默认时区 Asia/Shanghai，绝不让时间显示不出来。

import { ref } from 'vue';
import axios from 'axios';

/** 代码默认时区（与后端 utils/timezone_util.DEFAULT_TIMEZONE 一致）。 */
export const DEFAULT_TIMEZONE = 'Asia/Shanghai';

// 进程内缓存：同一页面内多处调用只打一次接口；
// 设置页改完要能立刻生效 → 导出 invalidateTimezone 供手动失效。
let cached = null;
let inflight = null;

/**
 * 拉取通用设置里的时区（带进程内缓存）。
 * @returns {Promise<{timezone: string, offset: string}>}
 */
export function fetchTimezone() {
    if (cached) return Promise.resolve(cached);
    if (inflight) return inflight;

    inflight = axios.get('/api/v1/settings/general')
        .then((response) => {
            const d = response.data?.data || response.data || {};
            cached = {
                timezone: d.timezone || DEFAULT_TIMEZONE,
                offset: d.utc_offset || '',
            };
            return cached;
        })
        .catch(() => {
            // 不缓存失败结果：下次进页面还能重试
            return { timezone: DEFAULT_TIMEZONE, offset: '' };
        })
        .finally(() => {
            inflight = null;
        });

    return inflight;
}

/** 手动失效缓存（设置页保存后调用，保证下次读拿到新值）。 */
export function invalidateTimezone() {
    cached = null;
}

/**
 * 把「不带时区后缀的墙上时间」解析成 Date（按本地时区解释，但**只用于取字段**）。
 *
 * ⚠️ 关键：这里**不用** `new Date(str)`，因为那会按浏览器本地时区推断时区，
 *    导致同一个后端值在不同机器上显示不同。我们只要拿到字符串里的年月日时分秒，
 *    当作「该时区已经是这个墙钟时间」直接展示。
 *
 * @param {string|Date} raw 后端时间串（2026-09-29T21:30:00 / 2026-09-29 21:30:00）或 Date
 * @returns {{y:number,m:number,d:number,h:number,mi:number}|null}
 */
export function parseWallClock(raw) {
    if (!raw) return null;
    if (raw instanceof Date) {
        if (Number.isNaN(raw.getTime())) return null;
        return {
            y: raw.getFullYear(), m: raw.getMonth() + 1, d: raw.getDate(),
            h: raw.getHours(), mi: raw.getMinutes(),
        };
    }
    const s = String(raw).replace(' ', 'T');
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ]?(\d{2})?:?(\d{2})?/);
    if (!m) return null;
    return {
        y: Number(m[1]), m: Number(m[2]), d: Number(m[3]),
        h: Number(m[4] || 0), mi: Number(m[5] || 0),
    };
}

const pad2 = (n) => String(n).padStart(2, '0');

/**
 * 格式化成 MM.DD HH:mm（速览卡片用），形如 09.29 21:30。
 * @param {string|Date} raw
 * @returns {string} 解析失败返回空串（调用方走空态，绝不渲染 Invalid Date）
 */
export function formatWallClock(raw) {
    const t = parseWallClock(raw);
    if (!t) return '';
    return `${pad2(t.m)}.${pad2(t.d)} ${pad2(t.h)}:${pad2(t.mi)}`;
}

/**
 * 格式化成 HH:mm，可选「明日 / 今日」前缀。
 *
 * ⚠️ 跨天比较必须用**同一个时区的时间**，不能拿 `new Date()`（浏览器本地时区）
 *    去和墙钟字段比 —— 在 UTC 机器上会把「今天 21:30」判成明天。
 *    所以这里由调用方传 nowFields（当前时区的墙钟字段），或显式传 reference。
 *
 * @param {string|Date} raw
 * @param {{y,m,d}|null} nowFields 当前时间在**同一时区**下的墙钟字段
 * @returns {string}
 */
export function formatWallClockTime(raw, nowFields = null) {
    const t = parseWallClock(raw);
    if (!t) return '';
    const hhmm = `${pad2(t.h)}:${pad2(t.mi)}`;
    if (!nowFields) return hhmm;
    const sameDay = t.y === nowFields.y && t.m === nowFields.m && t.d === nowFields.d;
    if (sameDay) return hhmm;
    // 只区分「今天 / 非今天」，非今天统一标「明日」——与既有文案口径一致
    return `明日 ${hhmm}`;
}

/**
 * 在组件里使用展示时区。
 *
 * 用法：
 *   const { timezone, offset, loadTimezone } = useTimezone();
 *   onMounted(() => loadTimezone());
 */
export function useTimezone() {
    // 默认与后端一致：表里没配置时就是 Asia/Shanghai
    const timezone = ref(DEFAULT_TIMEZONE);
    const offset = ref('');

    const loadTimezone = async () => {
        const cfg = await fetchTimezone();
        timezone.value = cfg.timezone || DEFAULT_TIMEZONE;
        offset.value = cfg.offset || '';
        return cfg;
    };

    return { timezone, offset, loadTimezone };
}

/**
 * 取「当前时间在指定时区下的墙钟字段」。
 *
 * 用 Intl.DateTimeFormat 拿到该时区的年月日时分（**不依赖浏览器本地时区**），
 * 供跨天判断使用。
 *
 * @param {string} tzName IANA 时区名
 * @returns {{y,m,d,h,mi}|null}
 */
export function nowFieldsInTimezone(tzName) {
    try {
        const fmt = new Intl.DateTimeFormat('en-CA', {
            timeZone: tzName || DEFAULT_TIMEZONE,
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', hour12: false,
        });
        const parts = {};
        for (const p of fmt.formatToParts(new Date())) {
            if (p.type !== 'literal') parts[p.type] = p.value;
        }
        return {
            y: Number(parts.year), m: Number(parts.month), d: Number(parts.day),
            h: Number(parts.hour) % 24, mi: Number(parts.minute),
        };
    } catch (e) {
        // 时区名不被浏览器支持 → 退回 Asia/Shanghai 口径
        return null;
    }
}
