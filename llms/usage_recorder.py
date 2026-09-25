"""LLM token 使用量记录器。

与 llms 包解耦：llms 各基类只调用 record_llm_usage()，本模块负责落库，
全程 try/except 兜底 —— 记录失败绝不能影响主链路的 LLM 调用。

落库使用独立 Session（不复用请求级 db_session），既避免污染主请求事务，
也保证即使主链路只读、未提交，usage 记录也能独立持久化。
"""

from utils.logger import logger

# 单次记录输入/输出文本的最大长度，避免超长对话撑爆存储
_MAX_TEXT_LEN = 6000


def _truncate(text, limit=_MAX_TEXT_LEN):
    if text is None:
        return None
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f'\n...[已截断，原始长度 {len(text)} 字符]'


def record_llm_usage(*, user_id, scene, platform, model,
                     prompt_tokens, completion_tokens, total_tokens,
                     input_text, output_text):
    """记录一次 LLM 调用的 token 消耗与对话输入输出。失败静默忽略。"""
    try:
        from models.database import engine
        from models import LlmTokenUsage
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=engine)
        with Session() as s:
            rec = LlmTokenUsage(
                user_id=int(user_id) if user_id else None,
                scene=scene,
                platform=platform,
                model=model or '',
                prompt_tokens=int(prompt_tokens or 0),
                completion_tokens=int(completion_tokens or 0),
                total_tokens=int(total_tokens or 0),
                input_text=_truncate(input_text),
                output_text=_truncate(output_text),
            )
            s.add(rec)
            s.commit()
    except Exception as e:
        logger.warning(f"LLM token 使用记录失败（已忽略）：{e}")
