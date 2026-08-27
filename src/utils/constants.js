/**
 * 作者：Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * 根据涨跌颜色模式和主题风格生成完整的图表配置
 * @param {'greenUp' | 'redUp'} colorMode - 颜色模式，默认绿涨红跌
 * @param {'light' | 'dark'} theme - 主题风格，默认亮白
 * @returns {object} 完整的 chartConfigs
 */
export function createChartConfig(colorMode = 'greenUp', theme = 'light') {
    const isGreenUp = colorMode === 'greenUp';
    const isDark = theme === 'dark';

    // ---------- 涨跌颜色映射 ----------
    const upColor = isGreenUp ? '#2DC08E' : '#f13e3a';
    const downColor = isGreenUp ? '#f13e3a' : '#2DC08E';
    const upBorderColor = isGreenUp ? '#2DC08E' : '#f13e3a';
    const downBorderColor = isGreenUp ? '#f13e3a' : '#2DC08E';
    const upWickColor = isGreenUp ? '#2DC08E' : '#f13e3a';
    const downWickColor = isGreenUp ? '#f13e3a' : '#2DC08E';
    const noChangeColor = '#888888';

    const upColorAlpha = isGreenUp ? '#f13e3a' : '#f13e3a';
    const downColorAlpha = isGreenUp ? '#f13e3a' : 'rgba(45, 192, 142, .7)';

    // ---------- 主题颜色映射 ----------
    const themeColors = {
        gridColor: isDark ? '#333' : '#eee',
        axisLineColor: isDark ? '#555' : '#888888',
        tickTextColor: isDark ? '#aaa' : '#D9D9D9',
        tickLineColor: isDark ? '#555' : '#888888',
        separatorColor: isDark ? '#555' : '#888888',
        crosshairLineColor: isDark ? '#555' : '#888888',
        crosshairTextBg: isDark ? '#333' : '#686D76',
        crosshairBorderColor: isDark ? '#555' : '#686D76'
    };

    // ---------- 基础配置（始终为亮白模板，后续通过覆盖调整） ----------
    const baseConfig = {
        grid: {
            show: true,
            horizontal: {
                show: true,
                size: 1,
                color: '#eee',
                style: 'dashed',
                dashedValue: [1, 1]
            },
            vertical: {
                show: true,
                size: 1,
                color: '#eee',
                style: 'dashed',
                dashedValue: [1, 1]
            }
        },
        candle: {
            type: 'candle_solid',
            bar: {
                compareRule: 'current_open',
                upColor: '#2DC08E',
                downColor: '#f13e3a',
                noChangeColor: '#888888',
                upBorderColor: '#2DC08E',
                downBorderColor: '#f13e3a',
                noChangeBorderColor: '#888888',
                upWickColor: '#2DC08E',
                downWickColor: '#f13e3a',
                noChangeWickColor: '#888888'
            },
            area: {
                lineSize: 2,
                lineColor: '#1677FF',
                smooth: false,
                value: 'close',
                backgroundColor: [
                    {offset: 0, color: 'rgba(33, 150, 243, 0.01)'},
                    {offset: 1, color: 'rgba(33, 150, 243, 0.2)'}
                ],
                point: {
                    show: true,
                    color: 'rgba(33, 150, 243, 0.01)',
                    radius: 4,
                    rippleRadius: 8,
                    animation: true,
                    animationDuration: 1000
                }
            },
            priceMark: {
                show: true,
                high: {
                    show: true,
                    color: '#D9D9D9',
                    textMargin: 5,
                    textSize: 10,
                    textFamily: 'Helvetica Neue',
                    textWeight: 'normal'
                },
                low: {
                    show: true,
                    color: '#D9D9D9',
                    textMargin: 5,
                    textSize: 10,
                    textFamily: 'Helvetica Neue',
                    textWeight: 'normal'
                },
                last: {
                    show: true,
                    compareRule: 'current_open',
                    upColor: '#2DC08E',
                    downColor: '#f13e3a',
                    noChangeColor: '#888888',
                    line: {
                        show: true,
                        style: 'dashed',
                        dashedValue: [4, 4],
                        size: 1
                    },
                    text: {
                        show: true,
                        style: 'fill',
                        size: 10,
                        paddingLeft: 4,
                        paddingTop: 4,
                        paddingRight: 4,
                        paddingBottom: 4,
                        borderStyle: 'solid',
                        borderSize: 0,
                        borderColor: 'transparent',
                        borderDashedValue: [2, 2],
                        color: '#FFFFFF',
                        family: 'Helvetica Neue',
                        weight: 'normal',
                        borderRadius: 2
                    },
                    extendTexts: []
                }
            },
            tooltip: {
                offsetLeft: 4,
                offsetTop: 6,
                offsetRight: 4,
                offsetBottom: 6,
                showRule: 'always',
                showType: 'standard',
                rect: {
                    position: 'fixed',
                    paddingLeft: 4,
                    paddingRight: 4,
                    paddingTop: 4,
                    paddingBottom: 4,
                    offsetLeft: 4,
                    offsetTop: 4,
                    offsetRight: 4,
                    offsetBottom: 4,
                    borderRadius: 4,
                    borderSize: 1,
                    borderColor: '#f2f3f5',
                    color: '#FEFEFE'
                },
                title: {
                    show: false,
                    size: 10,
                    family: 'Helvetica Neue',
                    weight: 'normal',
                    marginLeft: 8,
                    marginTop: 4,
                    marginRight: 8,
                    marginBottom: 4,
                    template: '{ticker} · {period}'
                },
                legend: {
                    size: 10,
                    family: 'Helvetica Neue',
                    weight: 'normal',
                    color: '#76808F',
                    marginLeft: 8,
                    marginTop: 4,
                    marginRight: 8,
                    marginBottom: 4,
                    defaultValue: 'n/a',
                    template: [
                        {title: 'time', value: '{time}'},
                        {title: 'open', value: '{open}'},
                        {title: 'high', value: '{high}'},
                        {title: 'low', value: '{low}'},
                        {title: 'close', value: '{close}'},
                        {title: 'volume', value: '{volume}'},
                        {title: 'ChangePct: ', value: '{chg_pct}%'}
                    ]
                },
                features: []
            }
        },
        indicator: {
            ohlc: {
                compareRule: 'current_open',
                upColor: 'rgba(45, 192, 142, .7)',
                downColor: '#f13e3a',
                noChangeColor: '#888888'
            },
            bars: [
                {
                    style: 'fill',
                    borderStyle: 'solid',
                    borderSize: 1,
                    borderDashedValue: [2, 2],
                    upColor: 'rgba(45, 192, 142, .7)',
                    downColor: '#f13e3a',
                    noChangeColor: '#888888'
                }
            ],
            lines: [
                {style: 'solid', smooth: false, size: 1, dashedValue: [2, 2], color: '#FF9600'},
                {style: 'solid', smooth: false, size: 1, dashedValue: [2, 2], color: '#935EBD'},
                {style: 'solid', smooth: false, size: 1, dashedValue: [2, 2], color: '#1677FF'},
                {style: 'solid', smooth: false, size: 1, dashedValue: [2, 2], color: '#E11D74'},
                {style: 'solid', smooth: false, size: 1, dashedValue: [2, 2], color: '#01C5C4'}
            ],
            circles: [
                {
                    style: 'fill',
                    borderStyle: 'solid',
                    borderSize: 1,
                    borderDashedValue: [2, 2],
                    upColor: 'rgba(45, 192, 142, .7)',
                    downColor: '#f13e3a',
                    noChangeColor: '#888888'
                }
            ],
            texts: [
                {
                    paddingLeft: 0, paddingTop: 0, paddingRight: 0, paddingBottom: 0,
                    style: 'fill', size: 10, color: '#1677FF',
                    family: 'Helvetica Neue', weight: 'normal',
                    borderStyle: 'solid', borderDashedValue: [2, 2],
                    borderSize: 0, borderColor: 'transparent',
                    borderRadius: 0, backgroundColor: 'transparent'
                }
            ],
            lastValueMark: {
                show: false,
                text: {
                    show: false, style: 'fill', color: '#FFFFFF', size: 10,
                    family: 'Helvetica Neue', weight: 'normal',
                    borderStyle: 'solid', borderSize: 1, borderDashedValue: [2, 2],
                    paddingLeft: 4, paddingTop: 4, paddingRight: 4, paddingBottom: 4, borderRadius: 2
                }
            },
            tooltip: {
                offsetLeft: 4, offsetTop: 6, offsetRight: 4, offsetBottom: 6,
                showRule: 'always', showType: 'standard',
                title: {
                    show: true, showName: true, showParams: true,
                    size: 10, family: 'Helvetica Neue', weight: 'normal',
                    color: '#76808F',
                    marginLeft: 8, marginTop: 4, marginRight: 8, marginBottom: 4
                },
                legend: {
                    size: 10, family: 'Helvetica Neue', weight: 'normal',
                    color: '#76808F',
                    marginLeft: 8, marginTop: 4, marginRight: 8, marginBottom: 4,
                    defaultValue: 'n/a'
                },
                features: []
            }
        },
        xAxis: {
            show: true, size: 'auto',
            axisLine: {show: true, color: '#888888', size: 1},
            tickText: {
                show: true, color: '#D9D9D9', family: 'Helvetica Neue',
                weight: 'normal', size: 10, marginStart: 4, marginEnd: 4
            },
            tickLine: {show: true, size: 1, length: 3, color: '#888888'}
        },
        yAxis: {
            show: true, size: 'auto',
            axisLine: {show: true, color: '#888888', size: 1},
            tickText: {
                show: true, color: '#D9D9D9', family: 'Helvetica Neue',
                weight: 'normal', size: 10, marginStart: 4, marginEnd: 4
            },
            tickLine: {show: true, size: 1, length: 3, color: '#888888'}
        },
        separator: {
            size: 1, color: '#888888', fill: true,
            activeBackgroundColor: 'rgba(230, 230, 230, .15)'
        },
        crosshair: {
            show: true,
            horizontal: {
                show: true,
                line: {
                    show: true,
                    style: 'dashed',
                    dashedValue: [4, 2],
                    size: 1,
                    color: '#888888'
                },
                text: {
                    show: true,
                    style: 'fill',
                    color: '#FFFFFF',
                    size: 10,
                    family: 'Helvetica Neue',
                    weight: 'normal',
                    borderStyle: 'solid',
                    borderDashedValue: [2, 2],
                    borderSize: 1,
                    borderColor: '#686D76',
                    borderRadius: 2,
                    paddingLeft: 4,
                    paddingRight: 4,
                    paddingTop: 4,
                    paddingBottom: 4,
                    backgroundColor: '#686D76'
                },
                features: []
            },
            vertical: {
                show: true,
                line: {
                    show: true,
                    style: 'dashed',
                    dashedValue: [4, 2],
                    size: 1,
                    color: '#888888'
                },
                text: {
                    show: true,
                    style: 'fill',
                    color: '#FFFFFF',
                    size: 10,
                    family: 'Helvetica Neue',
                    weight: 'normal',
                    borderStyle: 'solid',
                    borderDashedValue: [2, 2],
                    borderSize: 1,
                    borderColor: '#686D76',
                    borderRadius: 2,
                    paddingLeft: 4,
                    paddingRight: 4,
                    paddingTop: 4,
                    paddingBottom: 4,
                    backgroundColor: '#686D76'
                }
            }
        },
        overlay: {
            point: {
                color: '#1677FF', borderColor: 'rgba(22, 119, 255, 0.35)',
                borderSize: 1, radius: 5,
                activeColor: '#1677FF', activeBorderColor: 'rgba(22, 119, 255, 0.35)',
                activeBorderSize: 3, activeRadius: 5
            },
            line: {style: 'solid', smooth: false, color: '#1677FF', size: 1, dashedValue: [2, 2]},
            rect: {
                style: 'fill', color: 'rgba(22, 119, 255, 0.25)',
                borderColor: '#1677FF', borderSize: 1, borderRadius: 0,
                borderStyle: 'solid', borderDashedValue: [2, 2]
            },
            polygon: {
                style: 'fill', color: '#1677FF', borderColor: '#1677FF', borderSize: 1,
                borderStyle: 'solid', borderDashedValue: [2, 2]
            },
            circle: {
                style: 'fill', color: 'rgba(22, 119, 255, 0.25)',
                borderColor: '#1677FF', borderSize: 1,
                borderStyle: 'solid', borderDashedValue: [2, 2]
            },
            arc: {style: 'solid', color: '#1677FF', size: 1, dashedValue: [2, 2]},
            text: {
                style: 'fill', color: '#FFFFFF', size: 10,
                family: 'Helvetica Neue', weight: 'normal',
                borderStyle: 'solid', borderDashedValue: [2, 2], borderSize: 0,
                borderRadius: 2, borderColor: '#1677FF',
                paddingLeft: 0, paddingRight: 0, paddingTop: 0, paddingBottom: 0,
                backgroundColor: '#1677FF'
            }
        }
    };

    return {
        ...baseConfig,
        // ---------- 覆盖涨跌颜色 ----------
        candle: {
            ...baseConfig.candle,
            bar: {
                ...baseConfig.candle.bar,
                upColor, downColor, upBorderColor, downBorderColor,
                upWickColor, downWickColor,
                noChangeColor, noChangeBorderColor: noChangeColor, noChangeWickColor: noChangeColor
            },
            priceMark: {
                ...baseConfig.candle.priceMark,
                last: {...baseConfig.candle.priceMark.last, upColor, downColor, noChangeColor}
            }
        },
        indicator: {
            ...baseConfig.indicator,
            ohlc: {...baseConfig.indicator.ohlc, upColor: upColorAlpha, downColor: downColorAlpha},
            bars: baseConfig.indicator.bars.map((bar, index) => {
                if (index === 0) return {...bar, upColor: upColorAlpha, downColor: downColorAlpha};
                return bar;
            }),
            circles: baseConfig.indicator.circles.map((circle, index) => {
                if (index === 0) return {...circle, upColor: upColorAlpha, downColor: downColorAlpha};
                return circle;
            })
        },
        // ---------- 覆盖主题颜色（暗黑 / 亮白） ----------
        grid: {
            ...baseConfig.grid,
            horizontal: {...baseConfig.grid.horizontal, color: themeColors.gridColor},
            vertical: {...baseConfig.grid.vertical, color: themeColors.gridColor}
        },
        xAxis: {
            ...baseConfig.xAxis,
            axisLine: {...baseConfig.xAxis.axisLine, color: themeColors.axisLineColor},
            tickText: {...baseConfig.xAxis.tickText, color: themeColors.tickTextColor},
            tickLine: {...baseConfig.xAxis.tickLine, color: themeColors.tickLineColor}
        },
        yAxis: {
            ...baseConfig.yAxis,
            axisLine: {...baseConfig.yAxis.axisLine, color: themeColors.axisLineColor},
            tickText: {...baseConfig.yAxis.tickText, color: themeColors.tickTextColor},
            tickLine: {...baseConfig.yAxis.tickLine, color: themeColors.tickLineColor}
        },
        separator: {
            ...baseConfig.separator,
            color: themeColors.separatorColor
        },
        crosshair: {
            ...baseConfig.crosshair,
            horizontal: {
                ...baseConfig.crosshair.horizontal,
                line: {...baseConfig.crosshair.horizontal.line, color: themeColors.crosshairLineColor},
                text: {
                    ...baseConfig.crosshair.horizontal.text,
                    backgroundColor: themeColors.crosshairTextBg,
                    borderColor: themeColors.crosshairBorderColor
                }
            },
            vertical: {
                ...baseConfig.crosshair.vertical,
                line: {...baseConfig.crosshair.vertical.line, color: themeColors.crosshairLineColor},
                text: {
                    ...baseConfig.crosshair.vertical.text,
                    backgroundColor: themeColors.crosshairTextBg,
                    borderColor: themeColors.crosshairBorderColor
                }
            }
        }
    };
}

// 默认导出（红涨绿跌 + 亮白主题）
export const chartConfigs = createChartConfig('redUp', 'light');