"""演示数据。

没有 Token、或门店打烊时，用这里的真实营养库 + 参考价把产品完整跑起来，
方便评审直接体验。所有种子数据都会标记 source='demo'。
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from .catalog import categorize, code_for, price_for
from .db import add_meal, all_menu, get_db, kv_get, kv_set, replace_coupons, replace_menu, now_text
from .menu_reference import NUTRITION_ROWS
from .nutrition import exercise_kcal, get_exercise

DEMO_FLAG = "demo_seeded_v1"

DEMO_COUPONS = [
    {"id": "demo-30-5", "code": "DEMO305", "title": "满 30 减 5", "kind": "amount",
     "value": 5, "min_spend": 30, "match_text": "", "expires": "2026-11-30", "source": "demo"},
    {"id": "demo-50-10", "code": "DEMO5010", "title": "满 50 减 10", "kind": "amount",
     "value": 10, "min_spend": 50, "match_text": "", "expires": "2026-11-30", "source": "demo"},
    {"id": "demo-80-15", "code": "DEMO8015", "title": "满 80 减 15", "kind": "amount",
     "value": 15, "min_spend": 80, "match_text": "", "expires": "2026-11-30", "source": "demo"},
    {"id": "demo-spicy", "code": "DEMOSPCY", "title": "11.9 元麦辣鸡腿堡", "kind": "price",
     "value": 11.9, "min_spend": 0, "match_text": "麦辣鸡腿", "expires": "2026-11-15", "source": "demo"},
    {"id": "demo-breakfast", "code": "DEMOBF", "title": "早餐满 20 减 4", "kind": "amount",
     "value": 4, "min_spend": 20, "match_text": "", "expires": "2026-11-30", "source": "demo"},
    {"id": "demo-store-25-3", "code": "DEMO253", "title": "到店满 25 减 3", "kind": "amount",
     "value": 3, "min_spend": 25, "match_text": "", "expires": "2026-11-30", "source": "demo"},
]


def build_demo_menu() -> list[dict]:
    items = []
    for row in NUTRITION_ROWS:
        name, energy_kj, kcal, protein, fat, carb, sodium, calcium = row[:8]
        category = categorize(name)
        price, estimate = price_for(name, category)
        items.append({
            "code": code_for(name),
            "name": name,
            "category": category,
            "kcal": float(kcal),
            "protein": float(protein),
            "fat": float(fat),
            "carb": float(carb),
            "sodium": float(sodium),
            "calcium": float(calcium),
            "price": price,
            "price_is_estimate": estimate,
        })
    return items


def seed_menu() -> int:
    items = build_demo_menu()
    return replace_menu(items, source="demo")


def seed_coupons() -> int:
    return replace_coupons(DEMO_COUPONS, source="demo")


def seed_history(days: int = 21) -> int:
    """生成一段可复现的演示历史，让口味画像和日历有内容。"""
    menu = {m["name"]: m for m in all_menu()}
    if not menu:
        seed_menu()
        menu = {m["name"]: m for m in all_menu()}

    rng = random.Random(20261022)
    today = date.today()
    inserted = 0

    breakfast = ["猪柳蛋麦满分", "烟肉蛋麦满分", "皮蛋鸡肉粥", "脆薯饼", "优品豆浆小杯"]
    lunch_mains = ["麦辣鸡腿汉堡", "板烧鸡腿堡", "巨无霸", "双层吉士汉堡", "麦香鸡", "麦香鱼"]
    sides = ["中薯条", "麦乐鸡5块", "大杯玉米杯", "苹果片", "麦辣鸡翅-2块"]
    drinks = ["无糖可口可乐中杯", "可乐中杯", "冰美式中杯", "雪碧中杯"]
    dinner = ["麦香鱼", "板烧鸡腿堡", "鲜蔬蛋沙拉叠叠卷", "麦乐鸡5块"]

    # 今天的数据单独构造，避免与历史循环重复计入
    for offset in range(days, 0, -1):
        day = (today - timedelta(days=offset)).isoformat()

        if rng.random() < 0.55:
            picks = [breakfast[0], breakfast[4]] if rng.random() < 0.5 else [breakfast[2], breakfast[3]]
            _insert(day, "早餐", picks, menu)
            inserted += 1

        if offset % 7 == 3:
            continue  # 留几天空档，日历更真实

        picks = [rng.choice(lunch_mains), rng.choice(sides), rng.choice(drinks)]
        if offset > 10 and rng.random() < 0.3:
            picks = [rng.choice(lunch_mains), rng.choice(drinks)]
        _insert(day, "午餐", picks, menu)
        inserted += 1

        if rng.random() < 0.4:
            _insert(day, "晚餐", [rng.choice(dinner), rng.choice(sides)], menu)
            inserted += 1

        if rng.random() < 0.62 and offset > 0:
            kind = rng.choice(["run", "strength", "swim", "walk", "cycle", "hiit"])
            minutes = rng.choice([25, 30, 35, 40, 45, 60])
            _insert_exercise(day, kind, minutes)

    # 今天：早餐 + 晨跑，留出午餐额度给推荐
    _insert(today.isoformat(), "早餐", ["猪柳蛋麦满分", "冰美式中杯"], menu)
    _insert_exercise(today.isoformat(), "run", 32)
    inserted += 2
    return inserted


def _insert(day: str, slot: str, names: list[str], menu: dict) -> None:
    items = []
    for name in names:
        item = menu.get(name)
        if not item:
            continue
        items.append({
            "code": item["code"],
            "name": item["name"],
            "category": item["category"],
            "kcal": item["kcal"],
            "protein": item["protein"],
            "fat": item["fat"],
            "carb": item["carb"],
            "price": item["price"],
        })
    if not items:
        return
    add_meal(
        day=day,
        slot=slot,
        title="、".join(i["name"] for i in items),
        items=items,
        kcal=sum(i["kcal"] for i in items),
        protein=sum(i["protein"] for i in items),
        fat=sum(i["fat"] for i in items),
        carb=sum(i["carb"] for i in items),
        price=sum(float(i["price"] or 0) for i in items),
        source="demo",
    )


def _insert_exercise(day: str, kind: str, minutes: int) -> None:
    meta = get_exercise(kind)
    if not meta:
        return
    weight = 58.0
    from .db import get_profile
    profile = get_profile()
    weight = float(profile.get("weight_kg") or weight)
    kcal = exercise_kcal(meta["met"], weight, minutes)
    from .db import add_exercise
    add_exercise(day, meta["label"], float(minutes), meta["met"], kcal)


def ensure_reference_menu() -> bool:
    """真实模式下也要保证目录非空，否则推荐引擎无从下手。"""
    from .db import menu_count

    if menu_count() > 0:
        return False
    seed_menu()
    return True


def ensure_demo_seed() -> bool:
    """幂等播种，返回是否本次执行了播种。"""
    if kv_get(DEMO_FLAG) == "1":
        return False
    seed_menu()
    seed_coupons()
    seed_history()
    kv_set(DEMO_FLAG, "1")
    kv_set("seeded_at", now_text())
    return True
