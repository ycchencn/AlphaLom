"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pytz
from flask import request, jsonify
from app import app, get_real_ip
from service import UserService
from models.init_db import init_database

# 注册蓝图
from routes.main import main_bp
from routes.stock import stock_bp
from routes.market import market_bp
from routes.portfolio import portfolio_bp
from routes.watchlist import watchlist_bp
from routes.etf import etf_bp
from routes.quant import quant_bp
from routes.index import index_bp

# 指定时区为北京时间
beijing_tz = pytz.timezone('Asia/Shanghai')

app.register_blueprint(main_bp)
app.register_blueprint(stock_bp)
app.register_blueprint(market_bp)
app.register_blueprint(portfolio_bp)
app.register_blueprint(watchlist_bp)
app.register_blueprint(etf_bp)
app.register_blueprint(quant_bp)
app.register_blueprint(index_bp)


@app.route('/api/v1/auth/login', methods=['POST'])
def auth_login_action():
    """
    登录接口：从数据库校验用户名/密码（原硬编码 guest 账号已移除）。
    入参：{'username': 'admin', 'password': 'admin123456'}
    成功返回 {'status': 1, 'message': ..., 'token': <uuid>, 'user': {...}}
    """
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'status': 0, 'message': '用户名和密码不能为空'}), 400

    user = UserService.authenticate(username, password)
    if user:
        token = UserService.generate_token(username)
        return jsonify({
            'status': 1,
            'message': 'Login successful!',
            'token': token,
            'user': user,
        }), 200
    return jsonify({'status': 0, 'message': '用户名或密码错误'}), 401


if __name__ == '__main__':
    # 服务启动时自动建表 + 创建默认管理员（空库首次安装场景）
    init_database()
    app.run(debug=True, port=8080, host='0.0.0.0')
