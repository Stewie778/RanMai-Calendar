"""口味画像：从历史订单与显式反馈学习偏好。

不做复杂模型，用「时间衰减加权频次」——最近吃的权重高，半衰期 30 天。
这个方案可解释、可调、评审一眼能看懂。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

HALF_LIFE_DAYS = 30.0


def _decay(age_days: float) -> float:
    age_days = max(0.0, age_days)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def build_taste(
    meals: list[dict],
    feedback: list[dict],
    today: date | None = None,
) -> dict:
    today = today or date.today()
    item_scores: dict[str, float] = defaultdict(float)
    category_scores: dict[str, float] = defaultdict(float)
    slot_scores: dict[str, float] = defaultdict(float)
    prices: list[float] = []
    item_counts: dict[str, int] = defaultdict(int)
    orders = 0

    for meal in meals:
        try:
            day = date.fromisoformat(str(meal.get("day", ""))[:10])
            weight = _decay((today - day).days)
        except ValueError:
            weight = 0.0
        if weight <= 0:
            continue
        orders += 1
        if meal.get("price"):
            prices.append(float(meal["price"]))
        slot = meal.get("slot") or ""
        if slot:
            slot_scores[slot] += weight

        for item in meal.get("items") or []:
            name = item.get("name") or ""
            if not name:
                continue
            item_scores[name] += weight
            item_counts[name] += 1
            category = item.get("category") or ""
            if category:
                category_scores[category] += weight * 0.6

    for fb in feedback:
        name = fb.get("item_code") or ""
        if not name:
            continue
        # 显式反馈权重高于一次自然点单
        item_scores[name] += 1.6 if fb.get("liked") else -1.2

    max_item = max(item_scores.values(), default=0.0)
    max_cat = max(category_scores.values(), default=0.0)

    normalized_items = {
        k: round(v / max_item, 3) for k, v in item_scores.items() if max_item > 0
    }
    normalized_categories = {
        k: round(v / max_cat, 3) for k, v in category_scores.items() if max_cat > 0
    }

    top_items = sorted(item_scores.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "items": normalized_items,
        "categories": normalized_categories,
        "slots": dict(slot_scores),
        "avg_price": round(sum(prices) / len(prices), 1) if prices else 0.0,
        "top_items": [
            {"name": name, "score": round(score, 2), "count": item_counts.get(name, 0)}
            for name, score in top_items
            if score > 0
        ],
        "orders_analyzed": orders,
    }


def item_affinity(taste: dict, name: str, category: str = "") -> float:
    """单品的口味契合度，0~1。"""
    direct = float((taste.get("items") or {}).get(name, 0.0))
    cat = float((taste.get("categories") or {}).get(category, 0.0)) * 0.45
    return min(1.0, direct + cat)
