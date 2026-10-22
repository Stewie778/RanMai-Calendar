"""餐品目录：解析营养库、归类、参考价格。

价格说明：
  麦当劳 MCP 的营养接口不含价格。门店营业时通过 query-meals 拿到真实价格并覆盖；
  否则使用本文件的参考价（标注为估算），界面会显示「参考价」。
"""
from __future__ import annotations

import hashlib
import re

# 参考价：仅用于门店菜单不可用时兜底展示，实际以门店为准
REFERENCE_PRICES: dict[str, float] = {
    "猪柳麦满分": 15, "猪柳蛋麦满分": 16, "烟肉蛋麦满分": 15, "火腿扒麦满分": 14,
    "大脆鸡扒麦满分": 16, "原味板烧鸡腿麦满分": 15, "双层原味板烧鸡腿麦满分": 18,
    "双层猪柳蛋麦满分": 20, "双层火腿扒麦满分": 18, "原味板烧鸡腿炒双蛋堡": 19,
    "中薯条": 11, "大薯条": 13, "小薯条": 9, "迷你薯条": 7, "脆脆薯条": 12,
    "圆筒冰淇淋": 4, "麦乐鸡5块": 12, "麦乐鸡4块": 10,
    "大杯玉米杯": 9, "小杯玉米杯": 7, "麦辣鸡翅-2块": 12,
    "朱古力新地": 10, "草莓新地": 10, "奥利奥麦旋风": 14, "草莓麦旋风": 14,
    "香芋派": 8, "菠萝派": 8, "迷你朱古力新地": 6, "迷你草莓新地": 6,
    "吉士汉堡包": 12, "双层吉士汉堡": 17, "麦香鸡": 17, "麦香鱼": 16,
    "麦辣鸡腿汉堡": 22, "板烧鸡腿堡": 21, "巨无霸": 24, "培根蔬萃双层牛堡": 25,
    "汉堡包": 11, "不素之霸双层牛堡": 26, "双层深海鳕鱼堡": 24, "儿童鱼排堡": 16,
    "培根安格斯厚牛堡": 33, "芝士安格斯厚牛堡": 32, "芝士双层安格斯厚牛堡": 42,
    "培根双层安格斯厚牛堡": 41,
    "可乐中杯": 9, "可乐大杯": 10, "可乐小杯": 8,
    "雪碧中杯": 9, "雪碧大杯": 10, "雪碧小杯": 8,
    "无糖可口可乐中杯": 9, "无糖可口可乐大杯": 10, "无糖可口可乐小杯": 8,
    "大杯鲜萃咖啡": 13, "小杯鲜萃咖啡": 11, "锡兰红茶": 10, "热朱古力": 12,
    "纯牛奶（盒装）": 11, "麦旋酷阳光橙": 13, "浓缩咖啡": 11,
    "那么大鸡排": 15, "阳光柠檬红茶中杯": 12, "阳光柠檬红茶大杯": 14,
    "阳光柠檬红茶小杯": 10, "脆薯饼": 9, "脆香油条": 7, "100%苹果汁": 12,
    "纯悦": 5, "苹果片": 6, "皮蛋鸡肉粥": 8, "雪菜脆笋鸡肉粥": 8,
    "猪柳炒双蛋堡": 18, "柠檬拉明顿": 9, "草莓拉明顿": 9, "德式图林根香肠": 8,
    "火腿扒早安营养卷": 15, "图林根香肠早安营养卷": 15,
    "麦麦脆汁鸡-琵琶腿": 12, "麦麦脆汁鸡-带骨里脊": 12, "薄皮焦香V翅": 11,
    "蜜汁BBQ风味薄皮脆汁鸡-带骨里脊": 11, "蜜汁BBQ风味薄皮脆汁鸡-琵琶腿": 11,
    "蒜了吧黄油风味薄皮脆汁鸡-琵琶腿": 11, "蒜了吧黄油风味薄皮脆汁鸡-带骨里脊": 11,
    "柠萌风味薄皮焦香V翅": 11, "麦麦趣鸡球": 12, "酥酥多笋卷": 11,
    "鲜蔬蛋沙拉叠叠卷": 13, "鸡肉蛋沙拉叠叠卷": 13,
    "优品豆浆大杯": 10, "优品豆浆小杯": 8,
    "浓浓黑巧雪冰中杯": 15, "浓浓黑巧雪冰大杯": 18, "特浓奶香雪冰中杯": 15,
    "特浓奶香雪冰大杯": 18, "浓浓抹茶雪冰中杯": 15, "浓浓抹茶雪冰大杯": 18,
    "热牛奶中杯": 12, "热牛奶大杯": 14, "热牛奶小杯": 10,
    "冰牛奶中杯": 12, "冰牛奶大杯": 14, "冰牛奶小杯": 10,
    "冰奶铁中杯": 15, "冰奶铁大杯": 17, "冰奶铁小杯": 13,
    "热奶铁中杯": 15, "热奶铁大杯": 17, "热奶铁小杯": 13,
    "冰燕麦奶铁中杯": 16, "冰燕麦奶铁大杯": 18, "冰燕麦奶铁小杯": 14,
    "热燕麦奶铁中杯": 16, "热燕麦奶铁大杯": 18, "热燕麦奶铁小杯": 14,
    "冰美式中杯": 12, "冰美式大杯": 13, "冰美式小杯": 11,
    "热美式中杯": 12, "热美式大杯": 13, "热美式小杯": 11,
    "冰焦糖玛奇朵": 16, "热焦糖玛奇朵": 16, "卡布奇诺中杯": 15, "卡布奇诺大杯": 17,
    "冰燕麦奶中杯": 15, "冰燕麦奶大杯": 17, "冰燕麦奶小杯": 13,
    "热燕麦奶中杯": 15, "热燕麦奶大杯": 17, "热燕麦奶小杯": 13,
    "冰浓浓抹茶牛奶中杯": 17, "冰浓浓抹茶牛奶大杯": 19,
    "热浓浓抹茶牛奶中杯": 17, "热浓浓抹茶牛奶大杯": 19,
    "冰浓浓黑巧中杯": 15, "冰浓浓黑巧大杯": 17,
    "热浓浓黑巧中杯": 15, "热浓浓黑巧大杯": 17,
    "冰浓浓燕麦黑巧中杯": 15, "冰浓浓燕麦黑巧大杯": 17,
    "热浓浓燕麦黑巧中杯": 15, "热浓浓燕麦黑巧大杯": 17,
    "川宁伯爵红茶": 10, "抹茶阿芙佳朵": 15, "咖啡阿芙佳朵": 15,
    "yeyeyeye奶冻款": 9, "yeyeyeye爆珠款": 9,
    "果然多肉": 29, "“苹板”支撑Pro": 27, "专“薯鱼”你": 26,
    "绝代双翅": 27, "牛气满满": 28, "蜜汁快乐": 20,
    "中杯怡泉+C": 9, "大杯怡泉+C": 11, "【美汁源】“黄金橙橙”": 13,
}

_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("早餐", ("麦满分", "粥", "油条", "薯饼", "营养卷", "炒双蛋", "热香饼")),
    ("饮品", ("可乐", "雪碧", "咖啡", "红茶", "牛奶", "豆浆", "果汁", "纯悦", "雪冰",
              "玛奇朵", "卡布奇诺", "美式", "奶铁", "燕麦奶", "黑巧", "抹茶", "阿芙佳朵",
              "橙橙", "怡泉", "朱古力", "+C", "阳光柠檬")),
    ("甜品", ("冰淇淋", "新地", "麦旋风", "派", "奶冻", "爆珠", "拉明顿")),
    ("小食", ("薯条", "麦乐鸡", "鸡翅", "鸡球", "脆汁鸡", "鸡排", "玉米杯", "苹果片",
              "沙拉", "V翅", "笋卷", "香肠", "叠叠卷", "那么大")),
    ("套餐", ("果然多肉", "苹板", "专“薯鱼”", "绝代双翅", "牛气满满", "蜜汁快乐")),
    ("汉堡", ("汉堡", "堡", "麦香鸡", "麦香鱼", "巨无霸")),
]

_FALLBACK_PRICE = {"汉堡": 20.0, "早餐": 15.0, "小食": 11.0, "饮品": 12.0,
                   "甜品": 10.0, "套餐": 27.0, "其他": 15.0}

# 订单里出现、但营养库暂未收录的常见商品：映射到最接近的已收录餐品
NAME_ALIASES: dict[str, str] = {
    "芝士嘿凤梨板烧鸡腿堡": "板烧鸡腿堡",
    "高达吉士双牛堡": "双层吉士汉堡",
    "可乐麦炫酷": "麦旋酷阳光橙",
    "马来咖喱风味薄皮肉骨鸡3块": "麦麦脆汁鸡-琵琶腿",
    "马来咖喱风味薄皮肉骨鸡随心配": "麦麦脆汁鸡-琵琶腿",
}

# 连别名都匹配不到时，按品类中位数估算，避免把热量记成 0
CATEGORY_NUTRITION = {
    "汉堡": (450.0, 25.0, 20.0, 35.0),
    "早餐": (330.0, 14.0, 15.0, 28.0),
    "小食": (280.0, 12.0, 15.0, 20.0),
    "饮品": (150.0, 1.0, 2.0, 30.0),
    "甜品": (230.0, 3.0, 9.0, 33.0),
    "套餐": (700.0, 30.0, 30.0, 60.0),
    "其他": (300.0, 10.0, 12.0, 30.0),
}


def _strip_brackets(name: str) -> str:
    return re.sub(r"[（(].*?[)）]", "", name).strip()


def resolve_menu_item(name: str, menu_by_name: dict[str, dict]) -> tuple[dict | None, bool]:
    """把订单商品名对齐到营养库。

    返回 (菜单项, 是否估算)。估算只在别名/品类兜底时出现，
    精确命中（含去掉括号后命中）视为真实数据。
    """
    known = menu_by_name.get(name)
    if known:
        return known, False

    cleaned = _strip_brackets(name)
    known = menu_by_name.get(cleaned)
    if known:
        return known, False

    alias = NAME_ALIASES.get(cleaned) or NAME_ALIASES.get(name)
    if alias and alias in menu_by_name:
        return menu_by_name[alias], True

    category = categorize(cleaned)
    kcal, protein, fat, carb = CATEGORY_NUTRITION.get(category, CATEGORY_NUTRITION["其他"])
    price, _ = price_for(cleaned, category)
    return {
        "code": code_for(cleaned),
        "name": cleaned or name,
        "category": category,
        "kcal": kcal,
        "protein": protein,
        "fat": fat,
        "carb": carb,
        "price": price,
        "price_is_estimate": True,
    }, True


def categorize(name: str) -> str:
    for category, keywords in _CATEGORY_RULES:
        if any(k in name for k in keywords):
            return category
    return "其他"


def code_for(name: str) -> str:
    """稳定短码。真实菜单有 productCode 时用真实的，否则由名称派生。"""
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"ref-{digest}"


def price_for(name: str, category: str | None = None) -> tuple[float, bool]:
    if name in REFERENCE_PRICES:
        return float(REFERENCE_PRICES[name]), True
    category = category or categorize(name)
    return _FALLBACK_PRICE.get(category, 15.0), True


def parse_nutrition_payload(data: object) -> list[dict]:
    """解析 list-nutrition-foods 返回的表格文本。

    形如：
        [160]{productName,nutritionDescription,energyKj,...,calcium}:
          巨无霸,null,2145,513,27,30,44,...
    """
    if not isinstance(data, str) or not data.strip():
        return []

    items: list[dict] = []
    lines = [line.strip() for line in data.splitlines() if line.strip()]
    for line in lines:
        if line.startswith("["):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 9:
            continue
        name = parts[0]
        try:
            energy_kj = float(parts[2] or 0)
            energy_kcal = float(parts[3] or 0)
            protein = float(parts[4] or 0)
            fat = float(parts[5] or 0)
            carb = float(parts[6] or 0)
            sodium = float(parts[7] or 0)
            calcium = float(parts[8] or 0)
        except ValueError:
            continue
        category = categorize(name)
        price, estimate = price_for(name, category)
        items.append({
            "code": code_for(name),
            "name": name,
            "category": category,
            "kcal": energy_kcal,
            "protein": protein,
            "fat": fat,
            "carb": carb,
            "sodium": sodium,
            "calcium": calcium,
            "energy_kj": energy_kj,
            "price": price,
            "price_is_estimate": estimate,
        })
    return items


def merge_live_menu(nutrition_items: list[dict], live_products: list[dict]) -> list[dict]:
    """用门店实时菜单覆盖价格与 productCode（按名称精确匹配）。"""
    by_name = {p.get("name"): p for p in live_products if p.get("name")}
    merged = []
    for item in nutrition_items:
        clone = dict(item)
        live = by_name.get(item["name"])
        if live:
            code = live.get("code") or live.get("productCode")
            if code:
                clone["product_code"] = str(code)
            if live.get("price") is not None:
                clone["price"] = float(live["price"])
                clone["price_is_estimate"] = False
        merged.append(clone)
    return merged


def normalize_product(raw: dict) -> dict | None:
    """把 query-meals 的单条餐品归一化。字段名以实测为准，做多重兜底。"""
    name = raw.get("name") or raw.get("productName") or raw.get("mealName")
    code = raw.get("code") or raw.get("productCode") or raw.get("mealCode")
    if not name:
        return None
    price = raw.get("price")
    if price is None:
        price = raw.get("salePrice") or raw.get("originalPrice") or raw.get("showPrice")
    try:
        price = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price = None

    # 既没有编码也没有价格，多半是分类节点而不是商品
    if not code and price is None:
        return None

    return {
        "name": str(name),
        "code": str(code) if code else None,
        "price": price,
        "category": raw.get("categoryName") or raw.get("category") or categorize(str(name)),
    }


def sanitize_name(name: str) -> str:
    return re.sub(r"\s+", "", name)
