"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

import pytz
from flask import request, jsonify
from app import app, get_real_ip

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
    data = request.get_json()
    """ {'username': 'admin', 'password': '123456'} """
    if data['username'] == 'guest' and data['password'] == '2PQSyHU8':
        return jsonify({
            'status': 1,
            'message': 'Login successful!',
            'token': '<PASSWORD>'
        }), 200
    else:
        return jsonify({
            "status": 0,
        }), 500


if __name__ == '__main__':
    app.run(debug=True, port=8080, host='0.0.0.0')
