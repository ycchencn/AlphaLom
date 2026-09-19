"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

from service.databull_api import DataBull
from config import databull_host, databull_key

databull = DataBull(api_key=databull_key, base_url=databull_host)
