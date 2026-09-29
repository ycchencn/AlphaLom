"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

news_digest 历史数据的时间订正脚本（幂等，可重复执行）。

背景：`news_digest` 的 generated_at / window_start / window_end 之前用
`datetime.now()` 写入 —— 那是**宿主机本地时区**的 naive 值。后端的定时任务跑在
UTC 的容器里，于是库里存的是 **UTC 墙上时间**，而页面当成北京时间显示，
结果卡片上的时间比真实生成时刻**少 8 小时**（库里 13:30 实为北京 21:30）。

修复后的**存储口径 = UTC**（与展示时区解耦，见 `service/news_digest_service.py`
的 STORAGE_TZ_NAME）：落库一律写 UTC，读出来时再按「后台配置的展示时区」换算。
这样用户改展示时区只是换个换算基准，历史数据语义恒定。

本脚本负责把**存量数据**对齐到这个口径。它按 `--mode` 决定怎么订正：

  - `--mode to-utc`（默认，本项目的实际情况）：
    库里存的是「宿主机本地时区的墙上时间」。若宿主机是 UTC，那它**本来就是 UTC**，
    无需改动 —— 脚本会检测并跳过；若宿主机是其它时区，则按该时区反推成 UTC。
  - `--mode shift --hours -8`：
    无脑整体平移指定小时数。给「已经按某个非 UTC 值落库、需要手工拨回」的场景用。

用法：
    # 先看会改哪些行、改成什么，不动库
    .venv/Scripts/python.exe install/fix_news_digest_timezone.py --dry-run

    # 确认无误后执行（会先备份全表）
    .venv/Scripts/python.exe install/fix_news_digest_timezone.py --apply

    # 已知是「北京墙上时间、要拨回 UTC」
    .venv/Scripts/python.exe install/fix_news_digest_timezone.py --apply --mode shift --hours -8

⚠️ 三条硬约束：
  1. **幂等靠标记**：订正过的行无法靠值本身识别（时间看起来都合法），
     所以本脚本会在 `system_setting` 里写一条
     `general_setting.news_digest_tz_migrated = "<模式>@<时间>"` 作为已处理标记；
     带 `--force` 可无视标记重跑（慎用，会把已经对的值再偏移一次）。
  2. **执行前备份**：整表导出到 `news_digest_tzbak_<日期>`（数据量小，几十行）。
  3. **只订正时间列**，不动 headlines / highlights 等业务内容。
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 允许从仓库根目录直接跑
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from models.database import db_session  # noqa: E402
from utils.logger import logger  # noqa: E402
from utils.timezone_util import DEFAULT_TIMEZONE, GENERAL_SETTING_GROUP  # noqa: E402
from utils.timezone_util import get_tzinfo, get_timezone_name  # noqa: E402

# 迁移标记的配置键
MIGRATED_KEY = f'{GENERAL_SETTING_GROUP}.news_digest_tz_migrated'
# 备份表名日期后缀
BACKUP_DATE = datetime.now().strftime('%Y%m%d')

# 需要订正的时间列（都是 DATETIME）
TIME_COLUMNS = ('generated_at', 'window_start', 'window_end')


def _table_exists(table: str) -> bool:
    row = db_session.execute(text(
        'SELECT COUNT(*) FROM information_schema.tables '
        'WHERE table_schema = DATABASE() AND table_name = :t'
    ), {'t': table}).fetchone()
    return bool(row and row[0])


def _get_migrated_flag() -> str:
    from service.system_setting_service import SystemSettingService
    raw = SystemSettingService.get_value(MIGRATED_KEY, default=None)
    return raw if isinstance(raw, str) else ''


def _set_migrated_flag(value: str) -> None:
    from service.system_setting_service import SystemSettingService
    SystemSettingService.upsert(
        key=MIGRATED_KEY,
        value=value,
        group=GENERAL_SETTING_GROUP,
        value_type='string',
        description='news_digest 时区订正标记（记录已订正到的时区与时间，重跑时据此跳过）',
    )


def _offset_for(tz_name: str) -> timedelta:
    """目标时区相对 UTC 的偏移（用「当前的」偏移，DST 时区按下单日算）。"""
    tz = get_tzinfo(tz_name)
    off = tz.utcoffset(datetime.now())
    return off or timedelta(0)


def _backup_table() -> str:
    """整表备份成 news_digest_tzbak_<日期>，返回备份表名。"""
    backup = f'news_digest_tzbak_{BACKUP_DATE}'
    if _table_exists(backup):
        logger.info(f'备份表 {backup} 已存在，跳过备份')
        return backup
    db_session.execute(text(f'CREATE TABLE {backup} LIKE news_digest'))
    db_session.execute(text(f'INSERT INTO {backup} SELECT * FROM news_digest'))
    db_session.commit()
    count = db_session.execute(text(f'SELECT COUNT(*) FROM {backup}')).fetchone()[0]
    logger.info(f'✅ 已备份 {count} 行到 {backup}')
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description='把 news_digest 的存量时间对齐到 UTC 存储口径')
    parser.add_argument('--apply', action='store_true', help='真正写库；缺省只做 dry-run')
    parser.add_argument('--dry-run', action='store_true', help='只看会改什么，不动库（默认行为）')
    parser.add_argument('--mode', choices=['to-utc', 'shift'], default='to-utc',
                        help='to-utc=按宿主机时区反推成 UTC（默认）；shift=按 --hours 整体平移')
    parser.add_argument('--hours', type=float, default=None,
                        help='--mode shift 时的平移小时数（如 -8 表示整体减 8 小时）')
    parser.add_argument('--force', action='store_true', help='无视已处理标记强行重跑（慎用）')
    args = parser.parse_args()

    apply_changes = args.apply and not args.dry_run

    if not _table_exists('news_digest'):
        logger.error('news_digest 表不存在（服务还没跑过 / 表未建），无需订正')
        return 1

    # 计算偏移量
    if args.mode == 'shift':
        if args.hours is None:
            logger.error('--mode shift 必须给出 --hours（如 --hours -8）')
            return 1
        offset = timedelta(hours=args.hours)
        mode_desc = f'整体平移 {args.hours:+.1f} 小时'
        flag_value = f'shift{args.hours:+.1f}'
    else:
        # to-utc：把「宿主机本地时区的墙上时间」反推成 UTC
        # 偏移量 = -（本地相对 UTC 的偏移）；宿主机是 UTC 时偏移为 0 → 无需改动
        import time as _time
        local_offset_sec = -_time.timezone          # 东八区 = +28800
        offset = timedelta(seconds=-local_offset_sec)
        mode_desc = f'按宿主机时区（偏移 {local_offset_sec / 3600:+.1f}h）反推成 UTC'
        flag_value = f'to-utc@{local_offset_sec / 3600:+.1f}'

    print('=' * 72)
    print('news_digest 存量时间对齐（目标口径：UTC 存储）')
    print(f'  模式       : {args.mode} —— {mode_desc}')
    print(f'  实际偏移   : {offset.total_seconds() / 3600:+.1f} 小时')
    print(f'  操作       : {"APPLY（会写库）" if apply_changes else "DRY-RUN（不写库）"}')
    print('=' * 72)

    flag = _get_migrated_flag()
    if flag and not args.force:
        print(f'检测到已处理标记：{flag}')
        print('说明本表已对齐过。确认要再处理一次请加 --force（可能导致重复偏移！）')
        return 0
    if flag and args.force:
        print(f'⚠️ 已处理标记：{flag}，但因 --force 继续执行')

    if offset == timedelta(0):
        print('\n宿主机时区即 UTC → 库里存的本来就已是 UTC，无需订正。')
        print('（仍写入处理标记，避免以后重复排查）')
        if apply_changes:
            _set_migrated_flag(f'{flag_value}@noop@{datetime.now():%Y-%m-%d %H:%M:%S}')
        return 0

    rows = db_session.execute(text(
        'SELECT id, generated_at, window_start, window_end, trigger_type '
        'FROM news_digest ORDER BY id'
    )).fetchall()

    if not rows:
        print('表内没有数据，无需订正')
        return 0

    print(f'\n共 {len(rows)} 行，逐行预览（旧 → 新）：\n')
    print(f'{"id":>4} {"列":<14} {"旧值":<21} → {"新值":<21}')
    print('-' * 72)
    for r in rows:
        rid = r[0]
        for idx, col in enumerate(TIME_COLUMNS, start=1):
            old = r[idx]
            if old is None:
                continue
            print(f'{rid:>4} {col:<14} {str(old):<21} → {str(old + offset):<21}')
        print('-' * 72)

    if not apply_changes:
        print('\nDRY-RUN 结束。确认无误后加 --apply 执行。')
        return 0

    _backup_table()

    updated = 0
    for r in rows:
        rid = r[0]
        sets = ', '.join(f'{c} = :{c}' for c in TIME_COLUMNS)
        params = {c: (r[i + 1] + offset if r[i + 1] is not None else None)
                  for i, c in enumerate(TIME_COLUMNS)}
        params['rid'] = rid
        db_session.execute(text(f'UPDATE news_digest SET {sets} WHERE id = :rid'), params)
        updated += 1
    db_session.commit()

    _set_migrated_flag(f'{flag_value}@{datetime.now():%Y-%m-%d %H:%M:%S}')
    logger.info(f'✅ 已订正 {updated} 行，偏移 {offset.total_seconds() / 3600:+.1f} 小时')
    print(f'\n✅ 已订正 {updated} 行。备份表：news_digest_tzbak_{BACKUP_DATE}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        db_session.rollback()
        logger.error(f'订正失败：{e}', exc_info=True)
        sys.exit(2)
