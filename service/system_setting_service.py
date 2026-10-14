"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from typing import Any, Dict, List

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from models import SystemSetting
from models.database import db_session
from utils.logger import logger


class SystemSettingService:
    """
    系统配置的通用读写层（system_setting 表）。

    设计约定：
    - 配置键 = "<group>.<名称>"，group 用于整组读取（如 llm_model_setting 一次取回全部场景）；
    - 值统一按 JSON 存取，字符串/数字/布尔/对象/数组都能放，前端按 value_type 决定用哪种控件；
    - **库里没有行 = 使用代码里的默认值**。所以「恢复默认」就是删行，而不是写一行默认值 ——
      否则代码里改了默认值也永远生效不了（表里那行旧值会一直盖住它）；
    - 读取失败一律返回默认值 / 空，绝不向外抛：配置表不可用不该打断业务，尤其是 LLM 调用。
    """

    # 键与分组的分隔符
    KEY_SEP = '.'

    @staticmethod
    def _is_missing_table_error(e: Exception) -> bool:
        """
        判断异常是否因 system_setting 表尚未创建（首次运行 / 增量迁移前）。

        这种情况是预期的、良性的：配置会退回到代码默认值。应降级为 INFO 日志，
        不要打 ERROR 吓到新用户；真正的坏库（连接/权限）仍按 ERROR 上报。
        pymysql 的 1146 = "Table '...' doesn't exist"。
        """
        orig = getattr(e, 'orig', None)
        args = getattr(orig, 'args', None)
        if isinstance(args, (list, tuple)) and args and args[0] == 1146:
            return True
        msg = str(e).lower()
        return "doesn't exist" in msg or 'unknown table' in msg



    # ---------- 读 ----------

    @staticmethod
    def list_by_group(group: str) -> List[SystemSetting]:
        """读取某一组配置的全部行（不存在或读失败返回空列表）。"""
        try:
            return (db_session.query(SystemSetting)
                    .filter(SystemSetting.setting_group == group)
                    .order_by(SystemSetting.setting_key)
                    .all())
        except SQLAlchemyError as e:
            if SystemSettingService._is_missing_table_error(e):
                logger.info(
                    f"system_setting 表尚不存在（首次运行，建表后生效），group={group} 暂用代码默认值"
                )
            else:
                logger.error(f"list system_setting group={group} failed: {e}")
            return []

    @staticmethod
    def get_value(key: str, default: Any = None) -> Any:
        """按完整 key 读取单个配置值，不存在或读失败返回 default。"""
        try:
            row = db_session.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
            return row.setting_value if row is not None else default
        except SQLAlchemyError as e:
            if SystemSettingService._is_missing_table_error(e):
                logger.info(
                    f"system_setting 表尚不存在（首次运行，建表后生效），key={key} 暂用代码默认值"
                )
            else:
                logger.error(f"get system_setting key={key} failed: {e}")
            return default

    @staticmethod
    def get_group_values(group: str) -> Dict[str, Any]:
        """
        整组读取，返回 {名称: 值}（名称已去掉 "<group>." 前缀）。
        走一次查询取回整组，避免逐 key 查库。
        """
        prefix = f'{group}{SystemSettingService.KEY_SEP}'
        result: Dict[str, Any] = {}
        for row in SystemSettingService.list_by_group(group):
            name = row.setting_key
            if name.startswith(prefix):
                name = name[len(prefix):]
            result[name] = row.setting_value
        return result

    # ---------- 写 ----------

    @staticmethod
    def upsert(key: str, value: Any, group: str = None, value_type: str = 'json',
               description: str = None, updated_by: str = None) -> SystemSetting:
        """
        写入（存在则更新）一条配置。group 缺省时取 key 中第一个 '.' 之前的部分。
        并发首次写入撞唯一键时回滚后改为更新已有行。
        """
        key = (key or '').strip()
        if not key:
            raise ValueError('配置键不能为空')
        group = (group or key.split(SystemSettingService.KEY_SEP)[0]).strip()
        if not group:
            raise ValueError('配置分组不能为空')

        def _apply(row: SystemSetting):
            row.setting_value = value
            row.value_type = value_type or 'json'
            if description is not None:
                row.description = description
            if updated_by is not None:
                row.updated_by = updated_by

        try:
            row = db_session.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
            if row is None:
                row = SystemSetting(setting_key=key, setting_group=group)
                _apply(row)
                db_session.add(row)
            else:
                _apply(row)
            db_session.commit()
            db_session.refresh(row)
            return row
        except IntegrityError:
            # 并发下两个请求同时判定「不存在」→ 后提交的那个撞唯一键，退化为更新
            db_session.rollback()
            logger.warning(f"system_setting 并发插入冲突，改为更新已有行：{key}")
            row = db_session.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
            if row is None:
                raise
            _apply(row)
            db_session.commit()
            db_session.refresh(row)
            return row
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"upsert system_setting key={key} failed: {e}")
            raise

    @staticmethod
    def delete(key: str) -> bool:
        """删除一条配置（语义 = 恢复代码默认值）。不存在返回 False。"""
        try:
            row = db_session.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
            if row is None:
                return False
            db_session.delete(row)
            db_session.commit()
            return True
        except SQLAlchemyError as e:
            db_session.rollback()
            logger.error(f"delete system_setting key={key} failed: {e}")
            return False
