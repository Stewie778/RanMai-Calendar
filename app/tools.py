"""把麦当劳 MCP 的工具调用封装成业务动作。

所有真实调用都集中在这里，方便评审对照 MCP_INTEGRATION.md 逐条核验。
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from .catalog import normalize_product, parse_nutrition_payload, resolve_menu_item
from .config import MCD_MCP_TOKEN, MCD_MCP_URL
from .mcp_client import MCPClient, MCPError


def _data(response: object) -> object:
    if isinstance(response, dict) and "data" in response:
        return response.get("data")
    return response


def _ok(response: object) -> bool:
    return not (isinstance(response, dict) and response.get("success") is False)


async def fetch_nutrition(client: MCPClient) -> list[dict]:
    response = await client.call_tool("list-nutrition-foods", {})
    return parse_nutrition_payload(_data(response))


async def fetch_orders(client: MCPClient) -> list[dict]:
    response = await client.call_tool("order-list", {})
    data = _data(response) or {}
    if isinstance(data, dict):
        return data.get("list") or []
    return []


def parse_coupon(raw: dict) -> dict | None:
    title = (raw.get("title") or raw.get("couponName") or "").strip()
    coupon_id = str(raw.get("id") or raw.get("code") or title)
    if not title:
        return None

    kind = "amount"
    value = 0.0
    min_spend = 0.0
    match_text = ""

    # 满 30 减 5
    full = re.search(r"满\s*(\d+(?:\.\d+)?)\s*减\s*(\d+(?:\.\d+)?)", title)
    if full:
        min_spend = float(full.group(1))
        value = float(full.group(2))
    else:
        # 11.9 元麦辣鸡腿堡 —— 指定商品一口价
        priced = re.search(r"(\d+(?:\.\d+)?)\s*元\s*(.+)", title)
        if priced:
            kind = "price"
            value = float(priced.group(1))
            match_text = re.sub(r"[（(].*?[)）]", "", priced.group(2)).strip()
        else:
            discount = raw.get("discountInfo") or {}
            try:
                value = float(discount.get("discountValue") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value <= 0:
                return None

    expires = raw.get("tradeEndDateTime") or raw.get("tradeEndDate") or ""
    return {
        "id": coupon_id,
        "code": str(raw.get("code") or ""),
        "title": title,
        "kind": kind,
        "value": value,
        "min_spend": min_spend,
        "match_text": match_text,
        "order_types": ",".join(str(x) for x in (raw.get("orderTypes") or [])),
        "expires": str(expires),
        "note": (raw.get("discountInfo") or {}).get("discountDesc", ""),
        "source": "live",
    }


async def fetch_coupons(client: MCPClient) -> list[dict]:
    response = await client.call_tool("query-my-coupons", {"page": "1", "pageSize": "200"})
    data = _data(response) or {}
    coupons = data.get("coupons") if isinstance(data, dict) else None
    parsed = [parse_coupon(c) for c in (coupons or [])]
    return [c for c in parsed if c]


async def fetch_claimable_coupons(client: MCPClient) -> list[dict]:
    response = await client.call_tool("available-coupons", {})
    data = _data(response) or []
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def extract_products(data: object) -> list[dict]:
    """从 query-meals 的任意嵌套结构里捞出商品。"""
    found: list[dict] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            product = normalize_product(node)
            if product:
                found.append(product)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    deduped: dict[str, dict] = {}
    for product in found:
        deduped.setdefault(product["name"], product)
    return list(deduped.values())


async def fetch_store_menu(
    client: MCPClient, store_code: str, be_type: int = 1, order_type: int = 1
) -> list[dict]:
    arguments = {"storeCode": store_code, "orderType": order_type, "beType": be_type}
    response = await client.call_tool("query-meals", arguments)
    if not _ok(response):
        raise MCPError(str((response or {}).get("message") or "query-meals 失败"))
    return extract_products(_data(response))


async def fetch_favorite_stores(client: MCPClient, be_type: int = 1) -> list[dict]:
    response = await client.call_tool(
        "query-nearby-stores", {"beType": be_type, "searchType": 1}
    )
    data = _data(response) or []
    return data if isinstance(data, list) else []


async def fetch_campaigns(client: MCPClient, day: str | None = None) -> list[dict]:
    arguments = {"specifiedDate": day} if day else {}
    response = await client.call_tool("campaign-calendar", arguments)
    data = _data(response) or {}
    daily = data.get("dailyList") if isinstance(data, dict) else None
    events: list[dict] = []
    for entry in daily or []:
        for event in entry.get("events") or []:
            article = event.get("articleDto") or {}
            title = article.get("title") or event.get("activityTitle") or ""
            if not title:
                continue
            events.append({
                "date": entry.get("date"),
                "title": title,
                "highlight": article.get("highlights") or "",
            })
    return events


async def calculate_price(
    client: MCPClient,
    store_code: str,
    items: list[dict],
    be_type: int = 1,
    order_type: int = 1,
) -> dict:
    """用官方接口核验实付价（含券）。仅计算，不会下单。"""
    arguments = {
        "storeCode": store_code,
        "orderType": order_type,
        "beType": be_type,
        "items": [
            {
                "productCode": i.get("code"),
                "quantity": int(i.get("quantity") or 1),
                **({"couponCode": i["coupon_code"]} if i.get("coupon_code") else {}),
            }
            for i in items
            if i.get("code")
        ],
    }
    response = await client.call_tool("calculate-price", arguments)
    if not _ok(response):
        raise MCPError(str((response or {}).get("message") or "calculate-price 失败"))
    return _data(response) or {}


# ---------- 订单 → 餐次 ----------

def _slot_from_time(stamp: str) -> str:
    try:
        hour = datetime.strptime(stamp[11:16], "%H:%M").hour
    except (ValueError, IndexError):
        return "午餐"
    if 5 <= hour < 10:
        return "早餐"
    if 10 <= hour < 14:
        return "午餐"
    if 14 <= hour < 17:
        return "下午茶"
    if 17 <= hour < 22:
        return "晚餐"
    return "夜宵"


def orders_to_meals(orders: list[dict], menu_by_name: dict[str, dict]) -> list[dict]:
    """把 MCP 历史订单转换成可直接入库的餐次记录。"""
    meals: list[dict] = []
    for order in orders:
        stamp = str(order.get("createTime") or "")
        if len(stamp) < 10:
            continue
        day = stamp[:10]
        slot = _slot_from_time(stamp)
        items: list[dict] = []

        for product in order.get("orderProductList") or []:
            sub_items = product.get("comboItemList") or []
            if sub_items:
                for sub in sub_items:
                    name = (sub.get("name") or "").strip()
                    quantity = int(sub.get("quantity") or 1)
                    items.extend(_make_item(name, menu_by_name) for _ in range(quantity))
            else:
                name = (product.get("productName") or "").strip()
                quantity = int(product.get("quantity") or 1)
                items.extend(_make_item(name, menu_by_name) for _ in range(quantity))

        items = [i for i in items if i]
        if not items:
            continue

        meals.append({
            "day": day,
            "slot": slot,
            "title": "历史订单",
            "items": items,
            "kcal": sum(i["kcal"] for i in items),
            "protein": sum(i["protein"] for i in items),
            "fat": sum(i["fat"] for i in items),
            "carb": sum(i["carb"] for i in items),
            "price": _to_float(order.get("realTotalAmount")),
            "source": f"order:{order.get('orderId')}",
            "coupon": "",
        })
    return meals


def _make_item(name: str, menu_by_name: dict[str, dict]) -> dict | None:
    if not name:
        return None
    matched, estimated = resolve_menu_item(name, menu_by_name)
    if not matched:
        return None
    item = {
        "code": matched["code"],
        "name": name,  # 保留订单里的原始名字，方便用户对照
        "matched_name": matched["name"],
        "category": matched.get("category") or "其他",
        "kcal": float(matched.get("kcal") or 0),
        "protein": float(matched.get("protein") or 0),
        "fat": float(matched.get("fat") or 0),
        "carb": float(matched.get("carb") or 0),
        "price": float(matched.get("price") or 0),
    }
    if estimated:
        item["estimated"] = True
    return item


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# ---------- 一次同步 ----------

async def sync_live(store_code: str | None = None) -> dict:
    """同步营养库、历史订单、优惠券、门店菜单。返回同步摘要。"""
    if not MCD_MCP_TOKEN:
        raise MCPError("未配置 MCD_MCP_TOKEN")

    summary: dict = {"nutrition": 0, "orders": 0, "coupons": 0, "menu": 0,
                     "stores": 0, "campaigns": 0, "errors": []}

    async with MCPClient(MCD_MCP_URL, MCD_MCP_TOKEN, timeout=90) as client:
        try:
            summary["nutrition"] = len(await fetch_nutrition(client))
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"nutrition: {exc}")

        try:
            summary["orders"] = len(await fetch_orders(client))
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"orders: {exc}")

        try:
            summary["coupons"] = len(await fetch_coupons(client))
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"coupons: {exc}")

        try:
            summary["campaigns"] = len(await fetch_campaigns(client))
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"campaigns: {exc}")

        try:
            stores = await fetch_favorite_stores(client)
            summary["stores"] = len(stores)
            if not store_code and stores:
                store_code = str(stores[0].get("storeCode") or "")
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"stores: {exc}")

        if store_code:
            try:
                products = await fetch_store_menu(client, store_code)
                summary["menu"] = len(products)
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"menu: {exc}")

    summary["store_code"] = store_code
    return summary
