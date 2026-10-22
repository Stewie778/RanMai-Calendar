"""套餐推荐与优惠券比价。

目标：在「今天还能吃多少」的约束下，兼顾
  1) 口味契合（来自历史订单）
  2) 蛋白质达标
  3) 热量贴合剩余额度
  4) 价格与可用券最划算
"""
from __future__ import annotations

from itertools import combinations

from .taste import item_affinity

MAIN_CATEGORIES = {"汉堡", "早餐", "套餐"}
SIDE_CATEGORY = "小食"
DRINK_CATEGORY = "饮品"
DESSERT_CATEGORY = "甜品"

MAX_COMBOS = 2500

# 单餐热量上限：下午茶 / 夜宵不该推出一顿 900 kcal 的正餐
SLOT_AIM_CAP = {
    "早餐": 700.0,
    "午餐": 900.0,
    "下午茶": 400.0,
    "晚餐": 850.0,
    "夜宵": 550.0,
}


def _summarize(items: list[dict]) -> dict:
    return {
        "kcal": round(sum(float(i.get("kcal") or 0) for i in items), 1),
        "protein": round(sum(float(i.get("protein") or 0) for i in items), 1),
        "fat": round(sum(float(i.get("fat") or 0) for i in items), 1),
        "carb": round(sum(float(i.get("carb") or 0) for i in items), 1),
        "price": round(sum(float(i.get("price") or 0) for i in items), 2),
    }


def apply_coupon(items: list[dict], list_price: float, coupons: list[dict]) -> dict | None:
    """返回最划算的券及其优惠结果。"""
    best: dict | None = None
    for coupon in coupons:
        min_spend = float(coupon.get("min_spend") or 0)
        if min_spend and list_price < min_spend:
            continue

        match_text = (coupon.get("match_text") or "").strip()
        matched_item = None
        if match_text:
            matched_item = next(
                (i for i in items if match_text and match_text in (i.get("name") or "")), None
            )
            if matched_item is None:
                continue

        kind = coupon.get("kind") or "amount"
        value = float(coupon.get("value") or 0)
        if kind == "amount":
            saved = min(value, list_price)
        elif kind == "price":
            if matched_item is None:
                continue
            saved = max(0.0, float(matched_item.get("price") or 0) - value)
        elif kind == "percent":
            saved = list_price * value / 100.0
        else:
            continue

        saved = round(saved, 2)
        if saved <= 0:
            continue
        if best is None or saved > best["saved"]:
            best = {
                "id": coupon.get("id"),
                "title": coupon.get("title") or "优惠券",
                "saved": saved,
                "pay_price": round(max(0.0, list_price - saved), 2),
            }
    return best


def _candidate_pool(
    menu: list[dict], taste: dict, slot: str = ""
) -> tuple[list[dict], list[dict], list[dict]]:
    """按时段筛主食：早餐不推汉堡，正餐不推粥。"""
    mains, sides, drinks = [], [], []
    is_breakfast = slot == "早餐"

    for item in menu:
        category = item.get("category") or ""
        item = dict(item)
        item["affinity"] = item_affinity(taste, item.get("name", ""), category)
        if category in MAIN_CATEGORIES:
            if is_breakfast and category != "早餐":
                continue
            if not is_breakfast and category == "早餐":
                continue
            mains.append(item)
        elif category == SIDE_CATEGORY:
            sides.append(item)
        elif category == DRINK_CATEGORY:
            drinks.append(item)

    if not mains:  # 兜底：时段过滤后为空则放开
        mains = [
            dict(i, affinity=item_affinity(taste, i.get("name", ""), i.get("category", "")))
            for i in menu
            if (i.get("category") or "") in MAIN_CATEGORIES
        ]

    mains.sort(key=lambda i: (i["affinity"], -float(i.get("kcal") or 0)), reverse=True)
    sides.sort(key=lambda i: i["affinity"], reverse=True)
    drinks.sort(key=lambda i: i["affinity"], reverse=True)
    return mains[:14], sides[:10], drinks[:8]


def _build_combos(mains, sides, drinks):
    seen: set[tuple[str, ...]] = set()
    combos: list[list[dict]] = []

    def add(items: list[dict]) -> None:
        if len(combos) >= MAX_COMBOS:
            return
        key = tuple(sorted(i.get("code") or i.get("name") or "" for i in items))
        if not key or key in seen:
            return
        seen.add(key)
        combos.append(items)

    for main in mains:
        add([main])
        for side in sides[:8]:
            add([main, side])
        for drink in drinks[:6]:
            add([main, drink])
        for side_a, side_b in combinations(sides[:5], 2):
            add([main, side_a, side_b])
        for side in sides[:6]:
            for drink in drinks[:5]:
                add([main, side, drink])

    # 纯小食组合：剩余热量很小时也能给出方案
    light_pool = sorted(sides, key=lambda i: float(i.get("kcal") or 0))[:6]
    for r in (1, 2, 3):
        for combo in combinations(light_pool, r):
            add(list(combo))

    return combos


def recommend(
    menu: list[dict],
    taste: dict,
    targets: dict,
    consumed_kcal: float,
    consumed_protein: float,
    coupons: list[dict],
    slot: str = "午餐",
    limit: int = 3,
) -> dict:
    remaining = max(0.0, float(targets.get("intake_target", 1600)) - consumed_kcal)
    protein_target = float(targets.get("protein_target_g", 80))

    if remaining < 120:
        return {
            "remaining_kcal": round(remaining),
            "note": "今天的摄入额度已经用完啦，建议来点轻负担的。",
            "recommendations": _light_options(menu, taste, coupons, remaining),
        }

    aim = min(remaining, SLOT_AIM_CAP.get(slot, 900.0))
    protein_need = max(10.0, protein_target * 0.35)

    mains, sides, drinks = _candidate_pool(menu, taste, slot)
    if not mains:
        return {
            "remaining_kcal": round(remaining),
            "note": "菜单为空，请先同步门店菜单。",
            "recommendations": [],
        }

    scored: list[dict] = []
    for items in _build_combos(mains, sides, drinks):
        summary = _summarize(items)
        kcal = summary["kcal"]
        if kcal <= 0:
            continue
        if kcal > remaining + 40:
            continue
        if kcal > aim * 1.35 + 60:  # 时段硬上限之外，再挡掉明显超量的组合
            continue
        if kcal < min(200.0, aim * 0.45):
            continue

        affinity = sum(i["affinity"] for i in items) / len(items)
        kcal_fit = max(0.0, 1 - abs(kcal - aim) / max(aim, 1.0))
        protein_fit = min(1.0, summary["protein"] / protein_need)
        price = summary["price"]
        coupon = apply_coupon(items, price, coupons)
        pay_price = coupon["pay_price"] if coupon else price
        saved = coupon["saved"] if coupon else 0.0
        avg_price = float(taste.get("avg_price") or 0)
        if avg_price > 0:
            price_fit = max(0.0, 1 - abs(pay_price - avg_price) / (avg_price * 1.5))
        else:
            price_fit = 0.6
        discount_fit = min(1.0, saved / max(pay_price, 1.0) * 2.5)

        score = (
            0.30 * affinity
            + 0.24 * kcal_fit
            + 0.24 * protein_fit
            + 0.12 * price_fit
            + 0.10 * discount_fit
        )

        scored.append({
            "items": [
                {
                    "code": i.get("code"),
                    "name": i.get("name"),
                    "category": i.get("category"),
                    "kcal": round(float(i.get("kcal") or 0)),
                    "protein": round(float(i.get("protein") or 0), 1),
                    "price": round(float(i.get("price") or 0), 2),
                }
                for i in items
            ],
            **summary,
            "pay_price": pay_price,
            "saved": saved,
            "coupon": coupon,
            "affinity": round(affinity, 3),
            "kcal_fit": round(kcal_fit, 3),
            "protein_fit": round(protein_fit, 3),
            "score": round(score, 4),
            "remaining_after": round(remaining - kcal),
            "reasons": _reasons(summary, coupon, affinity, kcal, remaining, protein_need),
        })

    if not scored:
        return {
            "remaining_kcal": round(remaining),
            "note": "剩余额度有点少，先看看小份选项。",
            "recommendations": _light_options(menu, taste, coupons, remaining),
        }

    scored.sort(key=lambda c: c["score"], reverse=True)
    picks: list[dict] = []
    used: set[tuple[str, ...]] = set()

    def take(predicate, badge: str) -> None:
        if len(picks) >= limit:
            return
        for candidate in scored:
            key = tuple(sorted(i["name"] for i in candidate["items"]))
            if key in used or not predicate(candidate):
                continue
            used.add(key)
            candidate = dict(candidate)
            candidate["badge"] = badge
            picks.append(candidate)
            return

    take(lambda c: True, "今日最优")
    take(lambda c: c["protein"] >= protein_need and c["kcal"] <= aim, "高蛋白")
    take(lambda c: c["saved"] > 0, "券后最省")
    take(lambda c: c["pay_price"] <= max(20, aim / 40), "轻负担")
    while len(picks) < limit:
        take(lambda c: True, "备选")

    return {
        "remaining_kcal": round(remaining),
        "aim_kcal": round(aim),
        "protein_target_g": round(protein_target),
        "protein_need_g": round(protein_need),
        "note": _budget_note(remaining, aim),
        "recommendations": picks,
    }


def _light_options(menu, taste, coupons, remaining) -> list[dict]:
    light = [
        i for i in menu
        if float(i.get("kcal") or 0) <= 220 and (i.get("category") in {"小食", "饮品", "甜品", "早餐"})
    ]
    light.sort(key=lambda i: item_affinity(taste, i.get("name", ""), i.get("category", "")), reverse=True)
    out = []
    for item in light[:3]:
        price = float(item.get("price") or 0)
        coupon = apply_coupon([item], price, coupons)
        out.append({
            "badge": "轻负担",
            "items": [{
                "code": item.get("code"),
                "name": item.get("name"),
                "category": item.get("category"),
                "kcal": round(float(item.get("kcal") or 0)),
                "protein": round(float(item.get("protein") or 0), 1),
                "price": round(price, 2),
            }],
            "kcal": round(float(item.get("kcal") or 0)),
            "protein": round(float(item.get("protein") or 0), 1),
            "fat": round(float(item.get("fat") or 0), 1),
            "carb": round(float(item.get("carb") or 0), 1),
            "price": round(price, 2),
            "pay_price": coupon["pay_price"] if coupon else price,
            "saved": coupon["saved"] if coupon else 0,
            "coupon": coupon,
            "score": 0,
            "remaining_after": round(remaining - float(item.get("kcal") or 0)),
            "reasons": [f"只要 {round(float(item.get('kcal') or 0))} kcal"],
        })
    return out


def _reasons(summary, coupon, affinity, kcal, remaining, protein_need) -> list[str]:
    reasons = []
    if 0 < kcal <= remaining:
        reasons.append(f"占用今日剩余额度的 {round(kcal / remaining * 100)}%")
    if summary["protein"] >= protein_need:
        reasons.append(f"蛋白质 {round(summary['protein'])}g，这餐够用")
    if coupon:
        reasons.append(f"用「{coupon['title']}」省 {coupon['saved']:.1f} 元")
    if affinity >= 0.5:
        reasons.append("命中你常点的口味")
    if not reasons:
        reasons.append("热量与价格都比较均衡")
    return reasons[:3]


def _budget_note(remaining: float, aim: float) -> str:
    if remaining > 1200:
        return f"今天还能吃 {round(remaining)} kcal，别饿着，好好吃一顿。"
    if aim < 400:
        return f"只剩 {round(remaining)} kcal，给你挑了不会超标的组合。"
    return f"今天还剩 {round(remaining)} kcal，按这顿饭的目标给你配好了。"
