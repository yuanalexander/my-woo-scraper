# -*- coding: utf-8 -*-
"""
Shopify -> WooCommerce CSV 采集脚本 v2

相对 main.py 的修复：
1. 价格映射修正（compare_at_price -> Regular price，price -> Sale price）
2. 数量上限正确截断（不会整页 250 个全部写入）
3. 支持最多 3 个属性（Attribute 1/2/3）
4. 采集 inventory_quantity 到 Stock
5. 变体行不再写 Categories/Tags；父级 variable 行价格留空
6. SKU 可配置补零宽度与变体后缀宽度
7. Published 可选草稿(-1)/发布(1)
8. 分类模式可选：Product Type / Vendor > Product Type / 留空
9. 描述清洗增强（删空标签、剥图片、压缩空白）
"""

import requests
import pandas as pd
import time
import re
from datetime import datetime
from bs4 import BeautifulSoup

VERSION = "2.0"

# WooCommerce CSV 列（29 基础列 + Attribute 3 四列）
CSV_COLUMNS = [
    "ID", "Type", "SKU", "Name", "Published", "Is featured?",
    "Visibility in catalog", "Short description", "Description",
    "Regular price", "Sale price", "In stock?", "Stock",
    "Categories", "Tags", "Images", "Parent",
    "Attribute 1 name", "Attribute 1 value(s)", "Attribute 1 visible",
    "Attribute 1 global", "Attribute 1 default",
    "Attribute 2 name", "Attribute 2 value(s)", "Attribute 2 visible",
    "Attribute 2 global", "Attribute 2 default",
    "Attribute 3 name", "Attribute 3 value(s)", "Attribute 3 visible",
    "Attribute 3 global", "Attribute 3 default",
    "Meta: _rank_math_title", "Meta: _rank_math_description",
    "Meta: _rank_math_focus_keyword",
]

MAX_ATTRIBUTES = 3


def clean_price(price_str):
    """去掉货币符号/空格，返回纯数字字符串；空值返回空串"""
    if price_str is None:
        return ""
    s = str(price_str).strip()
    if not s:
        return ""
    s = re.sub(r"[^0-9.\-]", "", s)
    return s


def map_price(price, compare_at):
    """Shopify 价格 -> WooCommerce 原价/促销价
    Shopify: price=现售价, compare_at_price=划线原价
    WooCommerce: Regular price=原价, Sale price=促销价
    """
    price = clean_price(price)
    compare_at = clean_price(compare_at)
    try:
        p = float(price) if price else 0
        c = float(compare_at) if compare_at else 0
    except ValueError:
        return price, ""
    if compare_at and c > p:
        return compare_at, price
    return price, ""


def extract_short_desc(html_body, max_chars=200):
    """从 body_html 提取纯文本第一段作为 Short description"""
    if not html_body:
        return ""
    soup = BeautifulSoup(html_body, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + "..."


def clean_html_for_woo(raw_html):
    """清洗 Shopify body_html -> WooCommerce Description
    - 删除 script/style/iframe/表单/头部/底部/导航
    - 删除图片
    - 删除所有标签属性（含竞品链接 href）
    - 循环删除空标签
    - 压缩空白为单行
    """
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
