<template>
    <div class="profit-loss-calendar">
        <!--        <div class="calendar-header">-->
        <!--            <button @click="prevMonth" class="nav-btn">&lt;</button>-->
        <!--            <h3>{{ currentMonthYear }}</h3>-->
        <!--            <button @click="nextMonth" class="nav-btn">&gt;</button>-->
        <!--        </div>-->

        <div class="weekdays">
            <div v-for="day in weekdays" :key="day" class="weekday"><span class="text-xs">{{ day }}</span></div>
        </div>

        <div class="days-grid">
            <div
                v-for="(day, index) in daysInMonth"
                :key="index"
                class="day-cell"
                :class="{
                  'empty': !day.date,
                  'profit': day.profit > 0,
                  'loss': day.profit < 0,
                  'today': isToday(day.date)
                }"
            >
                <span v-if="day.date" class="day-number">{{ day.date.getDate() }}</span>
                <div v-if="day.date && day.profit !== undefined && day.profit !== 0" class="profit-info">
                    <span
                        class="profit-value"
                        :class="{ 'positive': day.profit > 0, 'negative': day.profit < 0 }"
                    >
                        {{ formatProfit(day.profit) }}
                    </span>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup>
import {ref, computed, onMounted} from 'vue';

// 接收传入的参数
const props = defineProps({
    profitData: {
        type: Object,
        default: () => ({})
    },
    initialDate: {
        type: Date,
        default: () => new Date()
    }
});

// 当前显示的月份
const currentDate = ref(new Date(props.initialDate));

// 星期几的标题
const weekdays = ['一', '二', '三', '四', '五', '六', '日'];

// 计算当前月份和年份的标题
const currentMonthYear = computed(() => {
    return `${currentDate.value.getFullYear()}年 ${currentDate.value.getMonth() + 1}月`;
});

// 获取当月的天数信息
const daysInMonth = computed(() => {
    const year = currentDate.value.getFullYear();
    const month = currentDate.value.getMonth();

    // 当月第一天和最后一天
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);

    // 当月总天数
    const daysInMonthCount = lastDay.getDate();

    // 第一天是星期几 (0=周日, 1=周一, ..., 6=周六)
    // 转换为 0=周一, 1=周二, ..., 6=周日
    const firstDayOfWeek = (firstDay.getDay() + 6) % 7;

    const days = [];

    // 添加上个月的空单元格
    for (let i = 0; i < firstDayOfWeek; i++) {
        days.push({date: null, profit: undefined});
    }

    // 添加当月的日期
    for (let day = 1; day <= daysInMonthCount; day++) {
        const date = new Date(year, month, day);
        const dateString = formatDate(date);  // 格式化为字符串用于查找
        // console.log(dateString);
        const profit = props.profitData[dateString];  // 使用格式化的字符串查找
        // console.log(props.profitData[dateString]);

        days.push({
            date: date,
            profit: profit
        });
    }

    // 计算需要多少个下个月的空单元格来填满网格
    const totalCells = 42; // 6行 * 7列
    const remaining = totalCells - days.length;
    for (let i = 0; i < remaining; i++) {
        days.push({date: null, profit: undefined});
    }

    return days;
});

// 格式化日期为 YYYY-MM-DD 字符串
const formatDate = (date) => {
    if (!date) return '';
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
};

// 格式化盈亏值
const formatProfit = (value) => {
    if (value === undefined || value === null) return '';
    if (value === 0) return '0';

    // 如果绝对值大于等于10000，使用万为单位
    if (Math.abs(value) >= 10000) {
        return (value / 10000).toFixed(1) + '万';
    }

    // 如果绝对值大于等于1000，保留一位小数
    if (Math.abs(value) >= 1000) {
        return value.toFixed(1);
    }

    // 否则保留整数
    return Math.round(value);
};

// 检查是否是今天
const isToday = (date) => {
    if (!date) return false;
    const today = new Date();
    return (
        date.getDate() === today.getDate() &&
        date.getMonth() === today.getMonth() &&
        date.getFullYear() === today.getFullYear()
    );
};

// 切换到上个月
const prevMonth = () => {
    currentDate.value = new Date(
        currentDate.value.getFullYear(),
        currentDate.value.getMonth() - 1,
        1
    );
};

// 切换到下个月
const nextMonth = () => {
    currentDate.value = new Date(
        currentDate.value.getFullYear(),
        currentDate.value.getMonth() + 1,
        1
    );
};

// 暴露方法给父组件（如果需要）
defineExpose({
    prevMonth,
    nextMonth,
    currentDate
});
</script>

<style scoped>

.profit-loss-calendar {
    width: 100%;
    max-width: 800px;
    margin: 0 auto;
    background-color: #ffffff;
    border-radius: 3px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.calendar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px;
    background-color: #f5f7fa;
    border-bottom: 1px solid #ebeef5;
}

.calendar-header h3 {
    margin: 0;
    color: #303133;
    font-size: 18px;
    font-weight: 600;
}

.nav-btn {
    background-color: #409eff;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 12px;
    cursor: pointer;
    font-size: 14px;
    transition: background-color 0.3s;
}

.nav-btn:hover {
    background-color: #66b1ff;
}

.weekdays {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    background-color: #f5f7fa;
    border-bottom: 1px solid #ebeef5;
}

.weekday {
    padding: 10px 0;
    text-align: center;
    font-size: 14px;
    color: #606266;
    font-weight: 500;
}

.days-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 1px;
    background-color: #ebeef5;
}

.day-cell {
    min-height: 60px;
    background-color: #fff;
    position: relative;
    transition: all 0.3s ease;
}

.day-cell.empty {
    background-color: #fafafa;
    /*min-height: 80px;*/
}

.day-cell:hover:not(.empty) {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
    z-index: 1;
}

.day-number {
    position: absolute;
    top: 4px;
    right: 4px;
    font-size: 12px;
    font-weight: 500;
    color: #606266;
}

.today .day-number {
    color: #409eff;
    font-weight: bold;
}

.profit-info {
    position: absolute;
    bottom: 4px;
    left: 4px;
    right: 4px;
    text-align: center;
}

.profit-value {
    font-size: 11px;
    font-weight: 500;
    display: inline-block;
    padding: 1px 3px;
    border-radius: 2px;
    min-width: 30px;
}

.profit-value.positive {
    color: #f56c6c;
    background-color: rgba(245, 108, 108, 0.1);
}

.profit-value.negative {
    color: #67c23a;
    background-color: rgba(103, 194, 58, 0.1);
}

/* 盈利日（红色系） */
.day-cell.profit {
    background: linear-gradient(135deg, #fef0f0, #fde2e2);
    border-left: 3px solid #f56c6c;
}

/* 亏损日（绿色系） */
.day-cell.loss {
    background: linear-gradient(135deg, #f0f9eb, #e6f4e1);
    border-left: 3px solid #67c23a;
}

/* 盈亏为0的日子 */
.day-cell.zero {
    background: linear-gradient(135deg, #f4f4f5, #e9e9eb);
    border-left: 3px solid #909399;
}

/* 今天的特殊样式 */
.day-cell.today {
    background: linear-gradient(135deg, #ecf5ff, #d9ecff);
    border-left: 3px solid #409eff !important;
    box-shadow: inset 0 0 0 1px rgba(64, 158, 255, 0.3);
}
</style>
