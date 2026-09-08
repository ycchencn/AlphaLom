/**
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 **/

const defaultStartYear = 3

// 格式化为 %Y%m%d
const formatDate = (date) => {
    const year = date.getFullYear();
    // getMonth() 返回 0-11，需要 +1，并补零
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}${month}${day}`;
};

export function getLineChartOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        // ⬇️ 核心配置：控制显示/隐藏
        plugins: {
            legend: {
                display: false // 隐藏图例 (右上角的颜色标签)
            },
            tooltip: {
                enabled: true // 如果你也想隐藏鼠标悬停提示，设为 false
            },
            // 如果你之前显示了数据点上的数字，需要去掉这个
            datalabels: {
                display: true
            }
        },
        // ⬇️ 隐藏 X轴 和 Y轴 的标题/标签线（如果不需要坐标轴文字也去掉）
        scales: {
            x: {
                display: true, // 设为 false 可以连 X 轴线和刻度都隐藏
                ticks: {
                    display: false // 设为 false 隐藏 X 轴下的文字
                },
                grid: {
                    display: false // 隐藏 X 轴网格线
                }
            },
            y: {
                display: true,
                ticks: {
                    display: true
                },
                grid: {
                    display: false // 隐藏 Y 轴网格线
                }
            }
        },
        // ⬇️ 如果你使用了 elements.line 的配置，保持你的 tension 或 cubicInterpolationMode
        elements: {
            line: {
                tension: 0.4,
                borderWidth: 2
            },
            point: {
                radius: 0 // 隐藏数据点的小圆点
            }
        }
    };
}

export function setColorOptions() {

    const documentStyle = getComputedStyle(document.documentElement);
    const textColor = documentStyle.getPropertyValue('--text-color');
    const textColorSecondary = documentStyle.getPropertyValue('--text-color-secondary');
    const surfaceBorder = documentStyle.getPropertyValue('--surface-border');

    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                labels: {
                    fontColor: textColor
                }
            }
        },
        scales: {
            x: {
                ticks: {
                    color: textColorSecondary
                },
                grid: {
                    color: surfaceBorder,
                    drawBorder: false
                }
            },
            y: {
                ticks: {
                    color: textColorSecondary
                },
                grid: {
                    color: surfaceBorder,
                    drawBorder: false
                }
            }
        }
    };

}

export function dictToMarkdownRecursive(data, indent = 0) {
    let markdown = '';
    const prefix = '  '.repeat(indent); // 每层缩进两个空格

    if (data !== null && typeof data === 'object' && !Array.isArray(data)) {
        // 是普通对象
        for (const [key, value] of Object.entries(data)) {
            if (value !== null && typeof value === 'object') {
                markdown += `${prefix}- **${key}**\n`;
                markdown += dictToMarkdownRecursive(value, indent + 1);
            } else {
                // 处理 null、undefined、字符串、数字等
                const displayValue = value == null ? 'null' : String(value);
                markdown += `${prefix}- **${key}** ${displayValue}\n`;
            }
        }
    } else if (Array.isArray(data)) {
        // 是数组
        for (const item of data) {
            if (item !== null && typeof item === 'object') {
                markdown += `${prefix}- \n`;
                markdown += dictToMarkdownRecursive(item, indent + 1);
            } else {
                const displayItem = item == null ? 'null' : String(item);
                markdown += `${prefix}- ${displayItem}\n`;
            }
        }
    } else {
        // 基本类型（string, number, boolean 等）
        const displayData = data == null ? 'null' : String(data);
        markdown += `${prefix}${displayData}\n`;
    }
    return markdown;
}

export const fetchIndustryList = async () => {
    try {
        let response = await fetch(`/api/v1/stocks/industry_list`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export const fetchStockInfo = async (stockCode) => {
    try {
        let response = await fetch(`/api/v1/stocks/${stockCode}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export const fetchStockProfile = async (stockCode) => {
    try {
        let response = await fetch(`/api/v1/stocks/profile/${stockCode}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

// 生成默认日期范围：3年前到今天
// 格式化为 YYYYMMDD (即 %Y%m%d)
const getDefaultDateRange = () => {
    const endDate = new Date();
    const startDate = new Date();
    startDate.setFullYear(endDate.getFullYear() - defaultStartYear);
    return {
        start_date: formatDate(startDate),
        end_date: formatDate(endDate)
    };
};

export const fetchStockMarketData = async (stockCode, startDate, endDate, Period) => {
    try {
        // 1. 获取默认日期或使用传入的参数
        const {start_date: defaultStart, end_date: defaultEnd} = getDefaultDateRange();
        const start_date = startDate || defaultStart;
        const end_date = endDate || defaultEnd;
        const period = Period || 'd';
        const version = '1.2'

        let response = null;

        // 2. 构建带查询参数的 URL
        const params = new URLSearchParams({start_date, end_date, period, version});

        response = await fetch(`/api/v1/stock_history/${stockCode}?${params}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        return await response.json();

    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export const fetchIndexMarketData = async (stockCode) => {
    try {
        const response = await fetch(`/api/v1/index_history/` + stockCode);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export const fetchMarketTempData = async () => {
    try {
        const response = await fetch(`/api/v1/market/market_temperature_data`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export function getProfitSeverity(profit) {
    // 红涨绿跌
    if (profit < 0) {
        return 'success';
    }
    return 'danger';
}

export function getTradeSeverity(tradeString) {
    if (tradeString === 'sell') {
        return 'success';
    }
    return 'danger';
}

// 定义常量，方便维护
const FEAR_GREED_LEVELS = {
    EXTREME_FEAR: {range: [0, 20], text: '极度恐惧', color: '#b3132b', advice: '市场过度恐慌'},
    FEAR: {range: [20, 50], text: '恐惧', color: '#ef4444', advice: '市场情绪偏谨慎'},
    NEUTRAL: {range: [50, 50], text: '中立', color: '#3b82f6', advice: '市场情绪中性'},
    GREED: {range: [50, 80], text: '贪婪', color: '#22c55e', advice: '市场情绪偏向乐观'},
    EXTREME_GREED: {range: [80, 100], text: '极度贪婪', color: '#15803d', advice: '市场过度狂热，警惕风险'}
};

/**
 * 格式化个股成交金额（对齐券商APP通用显示标准）
 * @param {Number} value - 原始成交金额（单位：元）
 * @returns {String} 格式化后的字符串，如"123.45万"、"2.34亿"
 */
export function formatStockTradeAmount(value) {
    // 非法值兼容
    if (typeof value !== 'number' || isNaN(value) || value < 0) {
        return '--'
    }
    // 分档处理
    if (value < 10000) {
        // 小于1万：显示元，保留2位小数
        return value.toFixed(2) + ' 元'
    } else if (value < 100000000) {
        // 1万到1亿：显示万
        return (value / 10000).toFixed(2) + ' 万'
    } else {
        // 大于等于1亿：显示亿
        return (value / 100000000).toFixed(2) + ' 亿'
    }
}

/**
 * 格式化股票流通市值为亿单位
 * @param {Number} value - 原始市值（单位：元）
 * @returns {String} 格式化后的字符串，如"15.00亿"
 */
export function formatMarketCapToBillions(value) {
    if (value >= 100000000) {
        return (value / 100000000).toFixed(2) + ' 亿';
    }
    return value.toString();
}

/**
 * 将恐惧贪婪数值转换为文字描述
 * @param {number} value - 恐惧贪婪指数值 (0-100)
 * @returns {Object} 包含文字、颜色和建议的描述对象
 */
export function fearGreedToText(value) {
    // 边界处理
    if (value === null) value = 0;
    if (value < 0) value = 0;
    if (value > 100) value = 100;

    // 判断区间
    if (value >= 0 && value < 20) {
        return FEAR_GREED_LEVELS.EXTREME_FEAR;
    } else if (value >= 20 && value < 50) {
        return FEAR_GREED_LEVELS.FEAR;
    } else if (value === 50) {
        return FEAR_GREED_LEVELS.NEUTRAL;
    } else if (value > 50 && value <= 80) {
        return FEAR_GREED_LEVELS.GREED;
    } else {
        // value > 80 && value <= 100
        return FEAR_GREED_LEVELS.EXTREME_GREED;
    }
}

export function formatDaysAgo(dateString) {
    if (!dateString) return 'N/A';

    const date = new Date(dateString);
    const now = new Date();

    // 检查是否是无效日期
    if (isNaN(date.getTime())) return 'N/A';

    const timeDiff = now - date; // 毫秒

    if (timeDiff < 0) return '未来'; // 可选：处理未来时间

    const seconds = Math.floor(timeDiff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (seconds < 30) {
        return '刚刚';
    } else if (seconds < 60) {
        return `${seconds} 秒前`;
    } else if (minutes < 60) {
        return `${minutes} 分钟前`;
    } else if (hours < 24) {
        return `${hours} 小时前`;
    } else if (days === 1) {
        return '1 天前';
    } else {
        return `${days} 天前`;
    }
}

export function formatCurrency(value, showPlusSign = false, formateDigits = 2) {
    if (value == null) return '—';

    // 1. 先进行基础的货币格式化
    const formattedValue = new Intl.NumberFormat('zh-CN', {
        style: 'currency',
        currency: 'CNY',
        minimumFractionDigits: formateDigits
    }).format(value);

    // 2. 如果不需要显示 + 号，或者数值本身是负数/0，直接返回
    if (!showPlusSign || value <= 0) {
        return formattedValue;
    }

    // 3. 如果需要显示 + 号且数值为正数，拼接 '+' 返回
    return '+' + formattedValue;
}

export function formatPercentage(value, showPlusSign = false) {
    if (value == null) return '—';

    // 1. 先进行基础的货币格式化
    const formattedValue = value;

    // 2. 如果不需要显示 + 号，或者数值本身是负数/0，直接返回
    if (!showPlusSign || value <= 0) {
        return formattedValue;
    }

    // 3. 如果需要显示 + 号且数值为正数，拼接 '+' 返回
    return '+' + formattedValue;
}

export function getMarketByCode(stockCode) {
    // 检查股票代码前缀并返回市场昵称
    if (stockCode.length === 5) {
        return '港';
    } else if (stockCode.startsWith('60')) {
        return '沪';  // 上海主板
    } else if (stockCode.startsWith('00')) {
        return '深';  // 深圳主板
    } else if (stockCode.startsWith('30')) {
        return '创';  // 创业板
    } else if (stockCode.startsWith('689')) {
        return '科';  // 科创板
    } else if (stockCode.startsWith('688')) {
        return '科';  // 科创板
    } else if (stockCode.startsWith('83') || stockCode.startsWith('87') || stockCode.startsWith('43')) {
        return '北';  // 北交所（新三板）
    } else if (stockCode.endsWith('usdt')) {
        return '数';  // 数字货币
    } else if (stockCode.startsWith('51') || stockCode.startsWith('15') || stockCode.startsWith('588')) {
        return 'ETF';
    }
    return '美';
}

export const fetchPortfolioInfo = async (portfolio_id) => {
    try {
        let response = await fetch(`/api/v1/investment_portfolios_info/` + portfolio_id);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export const fetchPortfolioTransaction = async (portfolio_id) => {
    try {
        let response = await fetch(`/api/v1/portfolio_transaction/` + portfolio_id);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export const fetchPortfolioQuantStat = async (portfolio_id) => {
    try {
        let response = await fetch(`/api/v1/portfolio_quantstat/${portfolio_id}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.text();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export const fetchPortfolioSummaryDaily = async (portfolio_id) => {
    try {
        let response = await fetch(`/api/v1/portfolio_daily_summary/` + portfolio_id);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
};

export function formatHoldingDuration(dateString) {
    if (!dateString) return 'N/A';

    const date = new Date(dateString);
    const now = new Date();

    // 检查是否是无效日期
    if (isNaN(date.getTime())) return 'N/A';

    // 如果是未来时间，返回 N/A 或者提示
    if (now < date) return '未生效';

    const timeDiff = now - date; // 毫秒
    const dayMs = 1000 * 60 * 60 * 24; // 一天的毫秒数

    const days = Math.floor(timeDiff / dayMs);

    // 少于 1 天
    if (days === 0) {
        return '< 1 天';
    }

    // 1 天到 1 个月之间：显示 X 天
    if (days < 30) {
        return ` ${days} 天`;
    }

    // 1 个月到 1 年之间：显示 X 月 Y 天
    if (days < 365) {
        const months = Math.floor(days / 30);
        const remainingDays = days % 30;
        if (remainingDays === 0) {
            return ` ${months} 月`;
        } else {
            return ` ${months} 月  ${remainingDays} 天`;
        }
    }

    // 1 年及以上：显示 X 年 Y 月
    const years = Math.floor(days / 365);
    const remainingDaysAfterYear = days % 365;
    const months = Math.floor(remainingDaysAfterYear / 30);

    if (months === 0) {
        return ` ${years} 年`;
    } else {
        return ` ${years} 年  ${months} 月`;
    }
}

/** 把可能是数字 / 带单位脏字符串的值，安全转成数字 */
export function parseNumber(input, fallback = 0) {
    if (typeof input === 'number') return Number.isFinite(input) ? input : fallback
    if (typeof input !== 'string') return fallback

    // 全角数字转半角，去掉千分位逗号和所有空白
    const raw = input
        .replace(/[\uFF10-\uFF19]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
        .replace(/[,\s\u00A0]/g, '')
    if (!raw) return fallback

    // 抠出第一个数字（含负号、小数、科学计数法）
    const matched = raw.match(/-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/)
    if (!matched) return fallback          // "—"、"暂无"、"" 都会走到这里

    let n = Number(matched[0])
    // 中文数量单位（长的先匹配，避免 "千万" 被拆成 "千"）
    const unit = raw.match(/(千万|百万|十万|亿|万|千)/)
    if (unit) {
        const map = {千: 1e3, 万: 1e4, 十万: 1e5, 百万: 1e6, 千万: 1e7, 亿: 1e8}
        n *= map[unit[1]]
    }
    return Number.isFinite(n) ? n : fallback
}



/**
 * 计算 DCF 三情景综合评分
 * @param {number} currentPrice - 现价
 * @param {number} optimistic - 乐观 DCF 价值
 * @param {number} neutral - 中性 DCF 价值
 * @param {number} conservative - 保守 DCF 价值
 * @param {object} weights - 权重配置（可选，默认 25/50/25）
 * @returns {object} 包含各维度分数和最终评级
 */
export function calcDcfScore(currentPrice, optimistic, neutral, conservative, weights = {}) {
    // 默认权重
    const w = {optimistic: 0.4, neutral: 0.5, conservative: 0.10, ...weights}

    // 归一化权重
    const totalW = w.optimistic + w.neutral + w.conservative
    const nw = {
        optimistic: w.optimistic / totalW,
        neutral: w.neutral / totalW,
        conservative: w.conservative / totalW,
    }

    // 上涨空间 → 映射函数
    // +100% → 100分, -50% → 0分, 线性插值
    const mapScore = (dcfValue) => {
        const upside = (dcfValue - currentPrice) / currentPrice
        const raw = (upside + 0.5) * (100 / 1.5) // 映射到 0-100
        return Math.max(0, Math.min(100, raw))
    }

    // 各情景得分
    const scores = {
        optimistic: mapScore(optimistic),
        neutral: mapScore(neutral),
        conservative: mapScore(conservative),
    }

    // 加权综合分
    const composite =
        scores.optimistic * nw.optimistic +
        scores.neutral * nw.neutral +
        scores.conservative * nw.conservative

    // 安全边际扣分：现价 > 保守价值时扣分
    let penalty = 0
    if (currentPrice > conservative) {
        const overRatio = (currentPrice - conservative) / conservative
        penalty = Math.min(15, overRatio * 100) // 最多扣 15 分
    }

    // 最终得分
    const finalScore = Math.max(0, Math.min(100, composite - penalty))

    // 评级
    const rating = finalScore >= 80 ? '强烈买入'
        : finalScore >= 65 ? '买入'
            : finalScore >= 50 ? '持有'
                : finalScore >= 35 ? '观望'
                    : '回避'

    return {
        scores,          // 各情景原始分
        composite,       // 加权综合分（扣分前）
        penalty,         // 安全边际扣分
        finalScore,      // 最终得分 0-100
        rating,          // 评级文字
        weights: nw,     // 实际使用的归一化权重
    }
}