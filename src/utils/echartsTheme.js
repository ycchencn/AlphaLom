// echartsTheme.js
// ============================================================================
// 全项目 ECharts 统一样式规范（线宽 / 字号 / 颜色 / 调色板 / 坐标轴 / tooltip）。
//
// 基准来源：恐惧贪婪指标图（StockDetail / ETFDetail / MarketOverview）的实测配置，
//          DCF 三情景估值图（StockValuationChartEcharts.vue）已对齐到此基准。
//
// 设计原则：所有「样式 magic number」只在这里定义一次，各图表组件 import 后取用，
//          禁止在组件里再写死 fontSize / lineWidth / 坐标轴颜色等。
//
// ⚠️ 暗色适配（2026-10-19）：COLORS 原来是**写死的常量对象**，图表画在 canvas 上，
//    CSS 变量对 canvas 无效 —— 于是暗色模式下坐标轴/网格线/tooltip 仍是亮色。
//    现在 COLORS 改成 getter 形式的响应式对象：底层两套值（THEME_COLORS.light/.dark），
//    对外暴露的字段在读取时按当前主题返回。现有组件无需改动即可自动适配。
//    ⚠️ 但 option 是**快照**，主题切换后必须重新 setOption 才会变 —— 组件需
//       watch(themeVersion) 重绘，见文末 registerThemeRedraw。
//
// 用法：
//   import {
//     COLORS, LINE, FONT, PALETTE,
//     hexToRgba, areaGradient,
//     axisLabel, splitLine, tooltipBase,
//     lineSeriesStyle, vLine, hLine, markLevels,
//     registerThemeRedraw, onThemeChange,
//   } from '@/utils/echartsTheme'
// ============================================================================

import * as echarts from 'echarts'
import { watch } from 'vue'
import { isDark, themeVersion } from '@/composables/useTheme'

/* ============ 颜色（两套主题） ============ */
const THEME_COLORS = {
  light: {
    // A 股习惯：涨红跌绿
    // ⚠️ 全站涨跌色的唯一来源。CSS 侧的 --app-up / --app-down 必须与这两值一致，
    //    否则会出现「列表里一种红、走势图里另一种红」。
    up: '#dc2626',
    down: '#16a34a',
    flat: '#909399', // 平（无涨跌）
    // 涨跌色的半透明填充（SVG 面积图、柱状图底色用）。
    // 集中在此定义，避免各组件手写 rgba 而色值漂移。
    upArea: 'rgba(220, 38, 38, 0.15)',
    downArea: 'rgba(22, 163, 74, 0.15)',
    // 情绪中性档（恐惧贪婪的「中性」区间用橙），与涨跌红绿区分开
    warn: '#f59e0b',

    // 坐标轴 / 网格 / 文本
    axisLine: '#e2e8f0',
    splitLine: '#eef1f6', // 横向网格线
    axisLabel: '#94a3b8', // 主刻度文字
    axisLabelThin: '#cbd5e1', // 次要刻度文字
    text: '#374151', // 通用文字（tooltip 等）
    textStrong: '#1f2937', // 强调文字
    secondary: '#64748b', // 次数据线 / 图例弱文字

    guide: '#e2e8f0', // 参考线 / 档位线（淡）
    guideStrong: '#cbd5e1', // 主参考线（如「现在」）
    dotBg: '#fff', // 数据点 / 散点底色
    // 投影色（SVG feDropShadow）。深色里若仍用黑投影，圆点/卡片周围会发脏。
    shadow: 'rgba(15,23,42,0.25)',
    markBg: 'rgba(59,130,246,0.035)', // 区域底纹
    bandBorder: '#eef0f3', // 标签描边

    // tooltip / 图表容器底色
    tooltipBg: 'rgba(255,255,255,0.97)',
    tooltipBorder: '#e5e7eb',
    canvasBg: 'transparent',

    // 主数据线蓝（均线偏离曲线、面积图主线）。两套主题同亮度，蓝色本身在深浅底上都够读。
    accent: '#3b82f6',

    // 主力行为阶段分类色板。
    // ⚠️ 刻意**不**复用 up/down：阶段是有序分类（黄→橙→红→蓝灰→绿），
    // 用涨跌色会让「拉升红 / 出货末绿」与「涨红跌绿」撞成同一套含义。
    phaseUnknown: '#c0c4cc',
    phase1: '#f6c445',
    phase2: '#f59e0b',
    phase3: '#dc2626',
    phase5: '#7c9cbf',
    phase6: '#5b8c5a',
  },

  dark: {
    // ⚠️ 暗色下必须提亮：亮色版的 #dc2626/#16a34a 在深底上对比度不足
    up: '#f87171',
    down: '#4ade80',
    flat: '#a1a1aa', // zinc-400
    upArea: 'rgba(248, 113, 113, 0.18)',
    downArea: 'rgba(74, 222, 128, 0.18)',
    warn: '#fbbf24', // amber-400，亮色版 #f59e0b 在深底上偏暗

    // 坐标轴：暗色下网格线要比亮色**更亮一点**才看得出层次，
    // 但不能太亮抢数据线。
    axisLine: '#3f3f46', // zinc-700
    splitLine: '#27272a', // zinc-800
    axisLabel: '#a1a1aa', // zinc-400
    axisLabelThin: '#52525b', // zinc-600
    text: '#d4d4d8', // zinc-300
    textStrong: '#fafafa', // zinc-50
    secondary: '#a1a1aa', // zinc-400

    guide: '#3f3f46',
    guideStrong: '#52525b',
    // 散点/数据点底色要用略浅于卡片的色，否则点在深色卡片上「消失」
    dotBg: '#27272a', // zinc-800
    shadow: 'rgba(0,0,0,0.55)', // 深底上黑投影才看得见
    markBg: 'rgba(59,130,246,0.10)', // 底纹在深色上要加浓才可见
    bandBorder: '#3f3f46',

    tooltipBg: 'rgba(39,39,42,0.97)', // zinc-800
    tooltipBorder: '#52525b',
    canvasBg: 'transparent',

    accent: '#3b82f6',

    // 阶段分类色板：亮色版的 #c0c4cc / #7c9cbf / #5b8c5a 在深底上偏暗，
    // 各档往上提一档亮度；红橙黄本身够亮，保持不变（压暗会失去「热」的语义）。
    phaseUnknown: '#71717a', // zinc-500
    phase1: '#f6c445',
    phase2: '#f59e0b',
    phase3: '#dc2626',
    phase5: '#93b4d4',
    phase6: '#7bb378',
  },
}

/**
 * 响应式颜色表。对外仍以 `COLORS.xxx` 访问，但字段是 getter —— 读取时按当前主题取值。
 * 现有组件的 `COLORS.axisLine` 写法完全不用改。
 */
export const COLORS = new Proxy(
  {},
  {
    get(_target, prop) {
      const palette = isDark.value ? THEME_COLORS.dark : THEME_COLORS.light
      // 支持两种内部取值，供 tooltipBase / markBg 之类使用
      const value = typeof palette[prop] === 'function' ? palette[prop]() : palette[prop]
      return value
    },
    has(_target, prop) {
      const palette = isDark.value ? THEME_COLORS.dark : THEME_COLORS.light
      return prop in palette
    },
  }
)

/* ============ 线宽 ============ */
export const LINE = {
  primary: 1.5, // 主数据线
  secondary: 1, // 次数据线（淡化、dotted）
  guide: 1, // 参考线 / 网格引导线
}

/* ============ 字号（px，非 rem） ============ */
export const FONT = {
  axis: 9, // 坐标轴刻度
  label: 10, // 末端标签 / 图内小字
  legend: 11, // 图例
  tooltip: 11, // tooltip
  title: 12, // 标题
  pie: 12, // 饼图扇区标签
}

/* ============ 调色板 ============ */
// 多系列图表的取色顺序。亮色/暗色用同一组色相 —— 蓝橙绿紫在两种底色上都能分辨，
// 没必要分两套（换主题时图表配色跟着变反而会让用户困惑）。
export const PALETTE = ['#3b82f6', '#f97316', '#10b981', '#8b5cf6']

/* ============ 工具 ============ */
export function hexToRgba(hex, alpha = 1) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '')
  if (!m) return `rgba(148,163,184,${alpha})`
  return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${alpha})`
}

/** 纵向线性渐变（top→bottom），返回 echarts 渐变对象 */
export function areaGradient(color, fromAlpha = 0.16, toAlpha = 0) {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: hexToRgba(color, fromAlpha) },
    { offset: 1, color: hexToRgba(color, toAlpha) },
  ])
}

/* ============ 构造器 ============ */

/** Y/X 轴刻度文字样式 */
export function axisLabel(overrides = {}) {
  return { fontSize: FONT.axis, color: COLORS.axisLabel, ...overrides }
}

/** 横向网格线样式（show 默认开，传 {show:false} 关闭） */
export function splitLine(overrides = {}) {
  return {
    show: true,
    lineStyle: { color: COLORS.splitLine, ...(overrides.lineStyle || {}) },
    ...overrides,
  }
}

/** tooltip 基础样式（默认 trigger:'axis'，无 axisPointer；需指示线请 overrides） */
export function tooltipBase(overrides = {}) {
  return {
    trigger: 'axis',
    // ⚠️ 原为写死的 'rgba(255,255,255,0.97)' —— 暗色下是一块刺眼的白板
    backgroundColor: COLORS.tooltipBg,
    borderColor: COLORS.tooltipBorder,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: COLORS.text, fontSize: FONT.tooltip },
    ...overrides,
  }
}

/**
 * 折线系列通用样式。
 * @param {object} opts
 *   color      线色（必填）
 *   width      线宽，默认 LINE.primary
 *   type       显式线型（'solid'|'dashed'|'dotted'），优先于 dashed
 *   dashed     布尔，true→'dashed'
 *   opacity    线透明度（如次数据线 0.5）
 *   area       是否带面积渐变
 *   areaFrom   顶部 alpha，默认 0.16
 *   areaTo     底部 alpha，默认 0
 *   shadow     是否带轻阴影，默认 true
 */
export function lineSeriesStyle({
  color,
  width = LINE.primary,
  type,
  dashed = false,
  opacity,
  area = false,
  areaFrom = 0.16,
  areaTo = 0,
  shadow = true,
} = {}) {
  const line = { color, width, type: type || (dashed ? 'dashed' : 'solid') }
  if (opacity != null) line.opacity = opacity
  if (shadow) {
    line.shadowBlur = 4
    line.shadowColor = hexToRgba(color, 0.2)
    line.shadowOffsetY = 2
  }
  const out = {
    lineStyle: line,
    itemStyle: { color },
  }
  if (area) out.areaStyle = { color: areaGradient(color, areaFrom, areaTo) }
  return out
}

/** 竖直参考线（如「现在」）。不传 label 则隐藏标签 */
export function vLine({ xAxis, color = COLORS.guideStrong, width = LINE.guide, dashed = true, label } = {}) {
  return {
    xAxis,
    lineStyle: { color, width, type: dashed ? 'dashed' : 'solid' },
    label: label ? { show: true, ...label } : { show: false },
  }
}

/** 水平参考线 */
export function hLine({ yAxis, color = COLORS.guide, width = LINE.guide, dashed = true, label } = {}) {
  return {
    yAxis,
    lineStyle: { color, width, type: dashed ? 'dashed' : 'solid' },
    label: label ? { show: true, ...label } : { show: false },
  }
}

/** 一组水平档位线（如恐惧贪婪 25/50/75）。统一隐藏标签、淡虚线 */
export function markLevels(values, { color = COLORS.guide, width = LINE.guide, dashed = true } = {}) {
  return {
    silent: true,
    symbol: 'none',
    label: { show: false },
    lineStyle: { type: dashed ? 'dashed' : 'solid', color, width },
    data: values.map((v) => ({ yAxis: v })),
  }
}

/* ============ 主题切换重绘 ============ */

/**
 * 注册一个「主题变化后重绘」的回调。
 *
 * ⚠️ ECharts 的 setOption 是**快照**：option 在调用时刻就把颜色固化了，
 *    之后主题变了不会自动重画。所以每个图表组件必须自己订阅。
 *
 * 用法（在组件里）：
 *   const chartRef = ref(null)
 *   let chart = null
 *   onMounted(() => { chart = echarts.init(chartRef.value); render() })
 *   // render() 里重新组装 option 并 setOption
 *   registerThemeRedraw(() => { if (chart) render() })
 *
 * @param {Function} callback 主题变化时的重绘函数
 * @returns {Function} 取消订阅函数（在组件 onBeforeUnmount 里调用）
 */
export function registerThemeRedraw(callback) {
  const stop = watch(themeVersion, () => {
    try {
      callback()
    } catch (e) {
      // 单个图表重绘失败不应打断其它图表
      console.warn('[echartsTheme] 主题切换重绘失败', e)
    }
  })
  return stop
}
