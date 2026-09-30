"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.

ALTCHA 人机校验的出题接口（自托管开源版）。

前端 `<altcha-widget challenge="/api/v1/altcha/challenge">` 会来取题；
组件把 `{parameters, signature}` 交给浏览器解，解出来的 payload 随登录表单提交，
由 `routes/auth.py` 的登录接口校验（见 utils/altcha.py）。

为什么出题接口不鉴权：它是登录页在**拿到令牌之前**调的，此时用户还没有身份。
出题本身是无副作用的纯计算，不需要保护。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.fastapi_app import api_prefix
from utils import altcha
from utils.logger import logger

altcha_router = APIRouter(prefix=api_prefix, tags=['人机校验'])


@altcha_router.get(
    '/altcha/challenge',
    summary='获取人机校验挑战',
    description='返回一道 ALTCHA proof-of-work 题目（含签名）。登录页在提交前用它解题。',
)
def altcha_challenge():
    """
    ⚠️ 密钥缺失 / 库没装时返回 **503 而不是空题**：给一个没有签名的题，前端解出来的
    payload 在登录接口必然验不过，用户会看到「验证失败」但查不出原因。配置问题必须
    显式暴露在取题这一步（fail-closed，不静默降级成「不校验」）。
    """
    try:
        challenge = altcha.create()
    except altcha.AltchaNotConfigured as e:
        logger.error(f'ALTCHA 未正确配置，无法出题：{e}')
        return JSONResponse(
            content={'code': 1, 'message': f'人机校验服务未配置：{e}'},
            status_code=503,
        )
    except Exception:
        logger.error('ALTCHA 出题失败', exc_info=True)
        return JSONResponse(
            content={'code': 1, 'message': '人机校验服务暂不可用，请稍后再试'},
            status_code=503,
        )

    # 直接返回挑战对象本身（组件要求 challenge 响应就是这个结构，不要包一层 data）
    return JSONResponse(content=challenge)
