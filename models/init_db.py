"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

 数据库初始化模块
 - init_database()：服务启动时自动建表（幂等，空库/已有库均安全）+ 创建默认管理员。
 - 兼容两套 metadata：Base（declarative_base，多数模型）与 db（Flask-SQLAlchemy，见 models/__init__.py）。
"""
from models import Base
from models.database import engine, db_session
from utils.logger import logger
from service.user import UserService


def init_database(create_admin: bool = True):
    """
    初次安装 / 空数据库时自动建表，并（可选）创建默认管理员。
    使用 checkfirst=True 幂等：已有表不会被重复创建或改动。
    """
    try:
        # 1. 创建 Base（declarative_base）体系下的所有表
        Base.metadata.create_all(bind=engine, checkfirst=True)
        logger.info("✅ 基础模型表已就绪（Base.metadata）")
    except Exception as e:
        logger.error(f"创建基础模型表失败: {e}")

    try:
        # 2. 创建 Flask-SQLAlchemy（db.Model）体系下的表
        #    注意：需确保 app 上下文已初始化 db。此处以延迟导入避免循环依赖。
        from app import app, db
        with app.app_context():
            db.create_all()
        logger.info("✅ Flask-SQLAlchemy 表已就绪（db.metadata）")
    except Exception as e:
        logger.error(f"创建 Flask-SQLAlchemy 表失败: {e}")

    if create_admin:
        try:
            if UserService.create_admin_if_not_exists():
                logger.info("✅ 默认管理员已创建")
            else:
                logger.info("ℹ️ 管理员账号已存在，跳过创建")
        except Exception as e:
            logger.error(f"初始化默认管理员失败: {e}")


if __name__ == '__main__':
    init_database()
    print("数据库初始化完成")