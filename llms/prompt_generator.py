"""
 * @author Yc
 * Chaos isn't a pit. Chaos is a ladder. - Littlefinger
 * Copyright (c) 2025 yccheni@163.com. All rights reserved.
"""

# import pandas as pd
import os
from string import Template
# from typing import List, Dict
from pathlib import Path
# from utils.common import df_to_compact_csv

CURRENT_DIR = Path(__file__).parent

def load_prompt_template(template_path: str) -> Template:
    """从文件加载 Prompt 模板"""
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template not found at: {template_path}")
    with open(template_path, "r", encoding="utf-8") as f:
        template_str = f.read()
    return Template(template_str)

def load_prompt_template_by_name(template_name: str) -> Template:
    """从文件加载 Prompt 模板"""
    template_path = f"{CURRENT_DIR}/templates/{template_name}.md"
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Prompt template not found at: {template_path}")
    with open(template_path, "r", encoding="utf-8") as f:
        template_str = f.read()
    return Template(template_str)
