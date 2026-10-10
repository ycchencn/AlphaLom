"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
 *
 * 调度器入口：任务定义已拆到 scheduler_jobs.yaml（配置驱动）。
 * 本文件只负责四件事：加载 YAML → 校验 → 按 func 字符串动态导入并注册到
 * APScheduler。调整任务时间 / 停用任务 / 新增任务只改 YAML，不动代码。
 *
 * ⚠️ 配置是故障点，两个原则：
 *   1. 配置文件本身读不了 / 结构不对 → 启动即报错退出（宁可失败，不默默少任务）；
 *   2. 单个任务注册失败（func 路径写错等）→ 记 error 日志、跳过该任务，
 *      不拖垮其它任务；若全部失败则拒绝启动空调度器。
 *
 * 用法：
 *   python scheduler.py           正常启动调度器
 *   python scheduler.py --check  只校验配置（YAML 结构 + func 可导入 + cron 字段），不启动
"""

import importlib
import sys
from pathlib import Path

import yaml

from models.init_db import init_database
from utils.logger import logger
from apscheduler.schedulers.blocking import BlockingScheduler

CONFIG_PATH = Path(__file__).resolve().parent / 'scheduler_jobs.yaml'

# APScheduler cron 触发器支持的字段白名单。配置里多写一个键会在 add_job 时抛
# TypeError（拖死整个调度器），这里显式过滤并在报错里列出来，一眼可见。
CRON_FIELDS = (
    'year', 'month', 'day', 'week', 'day_of_week', 'hour', 'minute', 'second',
    'start_date', 'end_date', 'timezone', 'jitter',
)

# add_job 的通用关键字（非触发器参数），按白名单透传
JOB_OPTIONS = (
    'id', 'name', 'misfire_grace_time', 'coalesce', 'max_instances',
    'replace_existing', 'jobstore', 'executor',
)


def _resolve_func(spec: str):
    """'module.path:attribute' 字符串 → 可调用对象。

    attribute 支持带点（如 package.module:Class.method）。任何一段解析不到都会抛
    异常，由调用处捕获后按「单任务失败不拖垮整体」处理（--check 则直接列出来）。
    """
    module_path, _, attr_path = spec.partition(':')
    if not attr_path:
        raise ValueError(f"任务的 func 必须是 'module:attribute' 形式，当前：{spec!r}")
    obj = importlib.import_module(module_path)
    for part in attr_path.split('.'):
        obj = getattr(obj, part)
    if not callable(obj):
        raise TypeError(f"{spec!r} 解析出的对象不可调用：{obj!r}")
    return obj


def load_schedule(config_path: Path):
    """读取 YAML 并做结构校验，返回 (default_timezone: str, jobs: list[dict])。

    这里抛出的异常属于「配置坏了」，调用方不吞 —— 配置错宁可启动失败，
    也不要一个静默少任务的调度器（少跑一天的因子/恐贪，影响远大于启动时报错）。
    """
    if not config_path.exists():
        raise FileNotFoundError(f'调度配置不存在：{config_path}')

    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError('调度配置顶层必须是 map（timezone / jobs）')

    default_tz = data.get('timezone') or 'Asia/Shanghai'
    jobs = data.get('jobs')
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('调度配置里 jobs 必须是非空列表')

    for i, j in enumerate(jobs):
        if not isinstance(j, dict):
            raise ValueError(f'jobs[{i}] 必须是 map')
        if not j.get('func'):
            raise ValueError(f'jobs[{i}] 缺 func（module:attribute 形式）')
        cron = j.get('cron')
        if cron is not None and not isinstance(cron, dict):
            raise ValueError(f'jobs[{i}]（{j.get("func")}）的 cron 必须是 map')
        kwargs = j.get('kwargs')
        if kwargs is not None and not isinstance(kwargs, dict):
            raise ValueError(f'jobs[{i}]（{j.get("func")}）的 kwargs 必须是 map')

    return default_tz, jobs


def _register_one(scheduler, job_cfg: dict, default_tz: str) -> bool:
    """注册单个任务到调度器。返回是否成功（失败只记日志，不中断其它任务）。"""
    name = job_cfg.get('id') or job_cfg['func']
    try:
        if job_cfg.get('enabled') is False:
            logger.info(f'[scheduler] 跳过已禁用任务 {name}（enabled=false）')
            return True

        func = _resolve_func(job_cfg['func'])

        trigger_cfg = job_cfg.get('cron') or {}
        unknown = set(trigger_cfg) - set(CRON_FIELDS)
        if unknown:
            raise ValueError(f'cron 含不受支持的字段：{sorted(unknown)}，支持：{list(CRON_FIELDS)}')
        trigger_kwargs = {k: v for k, v in trigger_cfg.items() if k in CRON_FIELDS}
        # 时区优先级：cron.timezone > 任务级 timezone > 全局默认
        trigger_kwargs.setdefault('timezone', job_cfg.get('timezone') or default_tz)

        job_options = {k: v for k, v in job_cfg.items() if k in JOB_OPTIONS}
        job_options.setdefault('id', name)

        scheduler.add_job(
            func, 'cron',
            kwargs=job_cfg.get('kwargs') or {},
            **job_options, **trigger_kwargs,
        )
        logger.info(f"[scheduler] 已注册 {name} → {job_cfg['func']} @ {trigger_kwargs}")
        return True
    except Exception as e:
        logger.error(f'[scheduler] 任务注册失败 {name}: {e}')
        return False


def register_jobs(scheduler, default_tz: str, jobs: list) -> int:
    """注册全部任务，返回成功个数。"""
    ok = 0
    for j in jobs:
        if _register_one(scheduler, j, default_tz):
            ok += 1
    return ok


def check_config(config_path: Path) -> int:
    """--check：不启动调度器、不碰数据库，只验证配置可用。"""
    default_tz, jobs = load_schedule(config_path)
    print(f'调度配置：{config_path}（默认时区 {default_tz}，共 {len(jobs)} 个任务）')
    errors = 0
    for i, j in enumerate(jobs):
        name = j.get('id') or j.get('func')
        try:
            func = _resolve_func(j['func'])
            cron = j.get('cron') or {}
            unknown = set(cron) - set(CRON_FIELDS)
            if unknown:
                raise ValueError(f'cron 含不受支持的字段：{sorted(unknown)}')
            tz = cron.get('timezone') or j.get('timezone') or default_tz
            print(f'  [ok]   {i + 1:>2}. {name} -> {func.__module__}.{func.__name__}'
                  f' | cron={cron} | tz={tz} | kwargs={j.get("kwargs") or {}}')
        except Exception as e:
            errors += 1
            print(f'  [FAIL] {i + 1:>2}. {name}: {e}')
    print(f'校验完成：{len(jobs) - errors}/{len(jobs)} 个任务可用' if not errors
          else f'校验完成：{errors} 个任务存在问题，请修复后重试')
    return 1 if errors else 0


def main():
    # --check 优先：纯校验不连库、不启动（部署前跑一次即可）
    if '--check' in sys.argv:
        sys.exit(check_config(CONFIG_PATH))

    # 服务启动时自动建表 + 创建默认管理员（首次安装 / 空库场景）
    init_database()

    default_tz, jobs = load_schedule(CONFIG_PATH)

    # 创建调度器实例
    scheduler = BlockingScheduler()

    ok = register_jobs(scheduler, default_tz, jobs)
    if ok == 0:
        logger.error(f'[scheduler] 配置里 {len(jobs)} 个任务全部注册失败，拒绝启动空调度器，请先修 scheduler_jobs.yaml')
        sys.exit(1)
    if ok < len(jobs):
        logger.warning(f'[scheduler] {len(jobs)} 个任务中 {len(jobs) - ok} 个注册失败，已跳过（见上方错误日志）')

    try:
        logger.info(f'[scheduler] 调度器启动，共 {ok} 个任务')
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        # 当用户按下Ctrl+C 或者发生系统退出异常时，捕获异常并结束程序
        pass


if __name__ == '__main__':
    main()