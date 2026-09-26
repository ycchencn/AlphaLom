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
// 用法：
//   import {
//     COLORS, LINE, FONT, PALETTE,
//     hexToRgba, areaGradient,
//     axisLabel, splitLine, tooltipBase,
//     lineSeriesStyle, vLine, hLine, markLevels,
//   } from '@/utils/echartsTheme'
// ============================================================================

import * as echarts from 'echarts'

/* ============ 颜色 ============ */
export const COLORS = {
  // A 股习惯：涨红跌绿
  up: '#dc2626',
  down: '#16a34a',

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
  markBg: 'rgba(59,130,246,0.035)', // 区域底纹
  bandBorder: '#eef0f3', // 标签描边
}

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
    backgroundColor: 'rgba(255,255,255,0.97)',
    borderColor: '#e5e7eb',
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
