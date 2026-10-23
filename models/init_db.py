"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 数据库初始化模块
 - init_database()：服务启动时自动建表（幂等，空库/已有库均安全）+ 创建默认管理员。
 - ensure_schema_upgrades()：为**已存在**的表补齐后续新增的列 / 索引（增量迁移）。
"""
from sqlalchemy import inspect, text

from models import Base
from models.database import engine
from utils.logger import logger
from service.user import UserService, DEFAULT_ADMIN_USERNAME


# 已存在表后续新增的列。
#
# 为什么需要它：`create_all(checkfirst=True)` 只会「建不存在的表」，对**已存在**的表
# 一律不碰——因此给既有表加的列永远不会自动出现，线上会直接报
# `Unknown column 'xxx' in 'field list'`。新增列时在这里登记一条即可，部署时自动补。
#
# 每项为 (表名, 列名, ALTER TABLE 的加列片段)。注意字符串里的反引号与 COMMENT
# 必须与 Column(comment=...) 保持一致，否则建出来的列注释与模型对不上。
_SCHEMA_UPGRADES = (
    # 首次运行体验优化：默认管理员首次安装用随机密码创建，需提示用户尽快改密。
    # 老库升级时这里补列（DEFAULT 0 = 不强制），再靠
    # UserService.flag_default_admin_if_using_factory_password() 给仍用出厂弱密码的
    # 管理员单独打标，历史已改密的用户不受打扰。
    ('users', 'must_change_password',
     "ADD COLUMN `must_change_password` SMALLINT NOT NULL DEFAULT 0 "
     "COMMENT '是否需强制修改密码：1-需修改, 0-已修改'"),
    # 公司公告 AI 解读（2026-10）：正文懒加载 + 首轮解读缓存。
    # ⚠️ content_text / ai_summary 用 LONGTEXT 而不是 TEXT：TEXT 上限 64KB，
    #    一份年报正文抽出来轻松超过（实测 13 页季报已 18k 字符，年报可达 30 万），
    #    超长会被 MySQL 静默截断（严格模式下直接报错），导致解读只看得到开头。
    ('stock_announcements', 'content_status',
     "ADD COLUMN `content_status` VARCHAR(16) NULL "
     "COMMENT '正文提取状态：NULL未尝试 / ok / unsupported乱码 / empty扫描件 / failed'"),
    ('stock_announcements', 'content_text',
     "ADD COLUMN `content_text` LONGTEXT NULL COMMENT 'PDF 正文纯文本（截断存储，供 AI 解读与检索）'"),
    ('stock_announcements', 'content_chars',
     "ADD COLUMN `content_chars` INT NULL COMMENT '正文原始字符数（截断前，判断是否够用）'"),
    ('stock_announcements', 'content_fetch_time',
     "ADD COLUMN `content_fetch_time` DATETIME NULL COMMENT '正文提取时间'"),
    ('stock_announcements', 'ai_summary',
     "ADD COLUMN `ai_summary` LONGTEXT NULL "
     "COMMENT 'AI 解读首轮结果（Markdown），命中则直接回放不再调用模型'"),
    ('stock_announcements', 'ai_model',
     "ADD COLUMN `ai_model` VARCHAR(64) NULL COMMENT '生成该解读的模型'"),
    ('stock_announcements', 'ai_update_time',
     "ADD COLUMN `ai_update_time` DATETIME NULL COMMENT 'AI 解读生成时间'"),
)


# 已存在表后续新增的「唯一索引 / 约束」升级。
#
# 与 _SCHEMA_UPGRADES（加列）分开：唯一索引需要先去重再 ALTER，否则表里若已有
# 重复行，ADD UNIQUE 会直接失败。每项 (表名, 索引名, ALTER 片段)。
#
# ⚠️ ddl 必须**自包含**去重逻辑：若目标表可能存在重复行，在 ADD UNIQUE 前先把
# 重复行删掉（保留每组唯一键里 id 最小的一行），例如：
#   ("DELETE t1 FROM `plan_orders` t1 INNER JOIN `plan_orders` t2 "
#    "ON t1.out_trade_no = t2.out_trade_no AND t1.id > t2.id; "
#    "ADD UNIQUE INDEX `uq_out_trade_no` (`out_trade_no`)")
# 表已存在但索引已建过时，循环会跳过（见 ensure_schema_upgrades）。
# 当前暂无条目，留作后续增量迁移模板。
_INDEX_UPGRADES = (
    # ('some_table', 'uq_some_col',
    #  "ADD UNIQUE INDEX `uq_some_col` (`some_col`)"),
)


# 已存在表后续新增的「普通（非唯一）索引」升级。
#
# 与 _INDEX_UPGRADES 分开：普通索引不用去重，直接 ADD INDEX（已存在则跳过）。
# 用于加速高频查询。每项 (表名, 索引名, ALTER 片段)。当前暂无条目，留作模板。
_NONUNIQUE_INDEX_UPGRADES = (
    # ('some_table', 'ix_some_cols',
    #  "ADD INDEX `ix_some_cols` (`col_a`, `col_b`)"),
)


def ensure_schema_upgrades():
    """
    为已存在的表补齐新增列 / 索引（增量迁移，幂等，可重复执行）。

    只做「加列」「加索引」这类升级：先查实际列名 / 索引名，缺了才 ALTER。
    表不存在时跳过——那种情况由 create_all 直接建出完整的新表，不需要补。

    设计要点：
    - 每个 ALTER 单独一个事务：DDL 在 MySQL 上隐式提交，失败一条不牵连其它；
    - 补列 / 建索引失败不阻断启动（warning 提示手工执行）；
    - 唯一索引升级前先按唯一键删除重复行，避免 ADD UNIQUE 因重复数据失败。

    :return: 本次实际补上的列 / 索引数
    """
    try:
        existing_tables = set(inspect(engine).get_table_names())
    except Exception as e:  # pragma: no cover - 取不到表结构（无库/无权限）
        logger.warning(f"读取表清单失败，跳过列/索引补齐：{e}")
        return 0

    added = 0

    # 1) 加列（幂等：先 introspect 现有列名，缺了才 ALTER）
    for table, column, ddl in _SCHEMA_UPGRADES:
        if table not in existing_tables:
            continue
        try:
            columns = {c['name'] for c in inspect(engine).get_columns(table)}
            if column in columns:
                continue
            # 每个 ALTER 单独一个事务：DDL 在 MySQL 上隐式提交，失败一条不牵连其它
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE `{table}` {ddl}"))
            added += 1
            logger.info(f"✅ 已为表 {table} 补齐新增列 {column}")
        except Exception as e:  # pragma: no cover - 补列失败不应阻断服务启动
            logger.warning(f"为表 {table} 补列 {column} 失败（请手工执行 ALTER）：{e}")

    # 2) 唯一索引升级：先按登记 ddl 去重（若含 DELETE）再建索引（幂等，可重复执行）
    for table, index_name, ddl in _INDEX_UPGRADES:
        if table not in existing_tables:
            continue
        try:
            idx_names = {i['name'] for i in inspect(engine).get_indexes(table)}
            if index_name in idx_names:
                continue
            with engine.begin() as conn:
                # ddl 自包含去重 DELETE（如有）+ ADD UNIQUE INDEX，由登记项保证顺序
                conn.execute(text(f"ALTER TABLE `{table}` {ddl}"))
            added += 1
            logger.info(f"✅ 已为表 {table} 补齐唯一索引 {index_name}")
        except Exception as e:  # pragma: no cover - 建索引失败不应阻断服务启动
            logger.warning(f"为表 {table} 建唯一索引 {index_name} 失败（请手工执行 ALTER）：{e}")

    # 3) 普通（非唯一）索引升级：已存在则跳过，直接 ADD INDEX（在线 DDL，不阻塞读写）
    for table, index_name, ddl in _NONUNIQUE_INDEX_UPGRADES:
        if table not in existing_tables:
            continue
        try:
            idx_names = {i['name'] for i in inspect(engine).get_indexes(table)}
            if index_name in idx_names:
                continue
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE `{table}` {ddl}"))
            added += 1
            logger.info(f"✅ 已为表 {table} 补齐普通索引 {index_name}")
        except Exception as e:  # pragma: no cover - 建索引失败不应阻断服务启动
            logger.warning(f"为表 {table} 建普通索引 {index_name} 失败（请手工执行 ALTER）：{e}")
    return added


def _announce_default_admin(username: str, plaintext: str | None):
    """
    首次运行创建默认管理员时，醒目回显登录凭证并提示尽快改密。
    同时走 logger（进日志文件）和 print（进启动 stdout / docker logs）。
    """
    line = "=" * 60
    if plaintext is not None:
        banner = (
            f"\n{line}\n"
            f"  【首次安装】已自动创建默认管理员账号\n"
            f"  用户名：{username}\n"
            f"  密  码：{plaintext}\n"
            f"  ⚠️ 这是系统随机生成的临时密码，请登录后尽快在\n"
            f"     「系统管理 → 用户管理」中修改！\n"
            f"{line}"
        )
    else:
        banner = (
            f"\n{line}\n"
            f"  【首次安装】已使用环境变量 ADMIN_PASSWORD 创建默认管理员\n"
            f"  用户名：{username}\n"
            f"  密  码：见你的 ADMIN_PASSWORD 配置\n"
            f"  ⚠️ 请登录后尽快在「系统管理 → 用户管理」中修改！\n"
            f"{line}"
        )
    logger.info(banner)
    # 同时打印到 stdout，确保 docker logs / 控制台一眼可见
    print(banner, flush=True)


def init_database(create_admin: bool = True):
    """
    初次安装 / 空数据库时自动建表，并（可选）创建默认管理员。
    使用 checkfirst=True 幂等：已有表不会被重复创建或改动。

    建表之后还会调用 ensure_schema_upgrades()，把既有表缺的新增列 / 索引补上——
    create_all 管不到这一步。
    """
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        logger.info("✅ 基础模型表已就绪（Base.metadata）")
    except Exception as e:
        logger.error(f"创建基础模型表失败: {e}")
    try:
        ensure_schema_upgrades()
    except Exception as e:  # pragma: no cover - 兜底，绝不让补列/索引影响启动
        logger.error(f"补齐新增列/索引失败: {e}")

    if create_admin:
        try:
            created, plaintext = UserService.create_user_if_not_exists()
            if created:
                _announce_default_admin(DEFAULT_ADMIN_USERNAME, plaintext)
            else:
                # 已存在：若仍在使用出厂弱密码，打上「需改密」标记
                UserService.flag_default_admin_if_using_factory_password()
                logger.debug("ℹ️ 管理员账号已存在，跳过创建")
        except Exception as e:
            logger.error(f"初始化默认管理员失败: {e}")


if __name__ == '__main__':
    init_database()
    print("数据库初始化完成")
