"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import threading
from contextvars import ContextVar
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from config import database_conn_str

# 数据库配置
DATABASE_URI = database_conn_str  # 可以修改为其他数据库URI，如postgresql或mysql
POOL_SIZE = 30  # 连接池大小
MAX_OVERFLOW = 50  # 允许的最大溢出连接数

# 创建引擎并配置连接池
engine = create_engine(
    DATABASE_URI,
    pool_size=POOL_SIZE,
    pool_recycle=3600,
    pool_pre_ping=True,
    max_overflow=MAX_OVERFLOW,
    echo=False  # 可以设置为True来调试
)

# ==================== 会话作用域 ====================
# scoped_session 必须显式确定"一个 Session 管多久"。默认的 threading.local 在 Flask
# 时代没问题 —— Flask-SQLAlchemy 会在每个应用上下文结束时自动 remove()。迁到 FastAPI
# 之后这个钩子没有了，thread-local 作用域再也回不到 0，两种路由写法都中招：
#   - `async def` 路由全跑在同一个事件循环线程上 → 整个进程共用同一个 Session；
#   - 同步 `def` 路由由 Starlette 丢进 anyio 线程池（线程会被复用）→ 变成每个工作
#     线程各挂一个 Session，同样永不复位。
# 于是 thread-local 作用域会退化成：**Session 只增不减，永不复位**。
#
# 后果不是"慢"，而是"错"：
#   1. Session 首次 SELECT 即进入事务并一直挂着（读接口从不 commit），
#      MySQL InnoDB 默认 REPEATABLE READ，一致性读快照被钉死在第一次读的时刻，
#      之后所有查询都返回那个旧快照 —— 表现为接口数据"被缓存了"、怎么刷新都不变；
#   2. Session 的身份映射（identity map）不会用新行覆盖已加载对象，
#      重复查询会一直返回同一个陈旧对象（需 populate_existing() 才会刷新）；
#   3. 事务不结束 → 连接不归还连接池，每个进程稳定占住 POOL_SIZE 个连接。
#
# 因此改用「请求级」作用域：请求中间件写入唯一令牌，Session 按令牌隔离，响应结束即回收。
# 令牌放在 ContextVar 里 —— anyio 会把 context 复制进工作线程，所以同步 `def` 路由
# （走线程池）也能正确清理（`ScopedRegistry.registry` 是普通 dict，键为请求令牌，
# 不依赖线程）。请求之外（定时任务、日志消费线程等）回退到线程 ID，与原有行为一致。
_request_scope: ContextVar[Optional[str]] = ContextVar('db_request_scope', default=None)


def _session_scope() -> str:
    """Session 的作用域键：请求内用请求令牌，请求外用线程 ID"""
    token = _request_scope.get()
    return token if token is not None else f'thread-{threading.get_ident()}'


def begin_request_scope(token: str):
    """进入请求级作用域，返回值供 end_request_scope 复位使用"""
    return _request_scope.set(token)


def end_request_scope(reset_token) -> None:
    """退出请求级作用域"""
    _request_scope.reset(reset_token)


# 自定义 scopefunc 时 SQLAlchemy 使用普通 dict 作注册表，键为每次请求的唯一令牌，
# 因此不存在跨请求争用；请求外的线程 ID 键与原先的 thread-local 行为等价。
db_session = scoped_session(sessionmaker(bind=engine), scopefunc=_session_scope)
