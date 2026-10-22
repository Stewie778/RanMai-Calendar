"""燃麦日历 · 后端入口。

启动：
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, demo_data, nutrition, recommend, tools
from .catalog import categorize
from .config import DEMO_MODE, LIVE_MODE, MCD_MCP_TOKEN, STATIC_DIR
from .mcp_client import MCPError
from .taste import build_taste


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if DEMO_MODE:
        demo_data.ensure_demo_seed()
    else:
        demo_data.ensure_reference_menu()

    task = None
    if LIVE_MODE:
        task = asyncio.create_task(_background_sync())
    try:
        yield
    finally:
        if task:
            task.cancel()


async def _background_sync() -> None:
    try:
        await _run_sync(None)
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(title="燃麦日历 RanMai", version="0.1.0", lifespan=lifespan)


# ---------- 请求模型 ----------

class ExerciseIn(BaseModel):
    day: str | None = None
    kind: str
    minutes: float = Field(gt=0, le=600)
    note: str = ""


class MealItemIn(BaseModel):
    code: str | None = None
    name: str
    category: str | None = None
    kcal: float = 0
    protein: float = 0
    fat: float = 0
    carb: float = 0
    price: float = 0


class MealIn(BaseModel):
    day: str | None = None
    slot: str = "午餐"
    items: list[MealItemIn]
    coupon_id: str | None = None
    saved: float = 0


class FeedbackIn(BaseModel):
    item_code: str
    liked: bool
    day: str | None = None


class ProfileIn(BaseModel):
    nickname: str | None = None
    sex: str | None = None
    age: int | None = Field(default=None, ge=14, le=90)
    height_cm: float | None = Field(default=None, ge=120, le=230)
    weight_kg: float | None = Field(default=None, ge=30, le=250)
    activity_level: float | None = Field(default=None, ge=1.0, le=2.0)
    goal_deficit: int | None = Field(default=None, ge=0, le=1000)
    daily_food_budget: float | None = Field(default=None, ge=0, le=1000)
    protein_g_per_kg: float | None = Field(default=None, ge=0.8, le=3.0)


class SyncIn(BaseModel):
    store_code: str | None = None


# ---------- 工具函数 ----------

def _parse_day(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc


def _menu_by_name() -> dict[str, dict]:
    return {item["name"]: item for item in db.all_menu()}


def _taste() -> dict:
    today = date.today()
    start = (today - timedelta(days=60)).isoformat()
    meals = db.meals_between(start, today.isoformat())
    return build_taste(meals, db.all_feedback(), today)


def _consumed(meals: list[dict]) -> dict:
    return {
        "kcal": round(sum(float(m.get("kcal") or 0) for m in meals), 1),
        "protein": round(sum(float(m.get("protein") or 0) for m in meals), 1),
        "fat": round(sum(float(m.get("fat") or 0) for m in meals), 1),
        "carb": round(sum(float(m.get("carb") or 0) for m in meals), 1),
        "price": round(sum(float(m.get("price") or 0) for m in meals), 2),
        "saved": round(sum(float(m.get("saved") or 0) for m in meals), 2),
    }


def _streak() -> int:
    """连续记录天数（运动或饮食任一）。"""
    today = date.today()
    start = (today - timedelta(days=120)).isoformat()
    days = set(db.meals_between_sums(start, today.isoformat())) | set(
        db.exercise_between(start, today.isoformat())
    )
    count = 0
    cursor = today
    if cursor.isoformat() not in days:
        cursor -= timedelta(days=1)
    while cursor.isoformat() in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def _cached_campaigns() -> list[dict]:
    raw = db.kv_get("campaigns")
    if not raw:
        return []
    try:
        return json.loads(raw)[:6]
    except json.JSONDecodeError:
        return []


def _status():
    return {
        "mode": "demo" if DEMO_MODE else "live",
        "live": LIVE_MODE,
        "has_token": bool(MCD_MCP_TOKEN),
        "menu_items": db.menu_count(),
        "last_sync": db.kv_get("last_sync", ""),
        "last_sync_error": db.kv_get("last_sync_error", ""),
    }


# ---------- 页面 ----------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ---------- 状态 ----------

@app.get("/api/status")
def api_status() -> dict:
    return _status()


@app.get("/api/exercise-types")
def api_exercise_types() -> list[dict]:
    return nutrition.EXERCISE_TYPES


# ---------- 面板 ----------

@app.get("/api/dashboard")
def api_dashboard(day: str | None = Query(default=None)) -> dict:
    target_day = _parse_day(day)
    profile = db.get_profile()
    exercises = db.list_exercise(target_day)
    exercise_kcal = sum(float(e.get("kcal") or 0) for e in exercises)
    meals = db.list_meals(target_day)
    consumed = _consumed(meals)
    targets = nutrition.daily_targets(profile, exercise_kcal)
    remaining = max(0.0, targets["intake_target"] - consumed["kcal"])

    slot, share = nutrition.slot_share()
    taste = _taste()
    coupons = db.all_coupons()
    menu = db.all_menu()
    reco = recommend.recommend(
        menu=menu,
        taste=taste,
        targets=targets,
        consumed_kcal=consumed["kcal"],
        consumed_protein=consumed["protein"],
        coupons=coupons,
        slot=slot,
    )

    return {
        "date": target_day,
        "today": date.today().isoformat(),
        "slot": slot,
        "share": share,
        "profile": profile,
        "targets": targets,
        "consumed": consumed,
        "remaining": {
            "kcal": round(remaining),
            "protein": round(max(0, targets["protein_target_g"] - consumed["protein"])),
            "ratio": round(consumed["kcal"] / max(targets["intake_target"], 1) * 100),
        },
        "exercise": exercises,
        "exercise_kcal": round(exercise_kcal),
        "meals": meals,
        "taste": taste,
        "coupons": coupons,
        "recommendation": reco,
        "campaigns": _cached_campaigns(),
        "streak": _streak(),
        "status": _status(),
    }


@app.get("/api/calendar")
def api_calendar(
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
) -> dict:
    today = date.today()
    year = year or today.year
    month = month or today.month
    start, end = nutrition.month_bounds(year, month)
    profile = db.get_profile()
    exercise_map = db.exercise_between(start, end)
    meal_map = db.meals_between_sums(start, end)

    days = []
    cursor = date.fromisoformat(start)
    last = date.fromisoformat(end)
    total_intake = 0.0
    total_exercise = 0.0
    total_price = 0.0
    logged_days = 0

    while cursor <= last:
        key = cursor.isoformat()
        intake = float(meal_map.get(key, {}).get("kcal", 0))
        spent = float(meal_map.get(key, {}).get("price", 0))
        moved = float(exercise_map.get(key, 0))
        target = nutrition.daily_targets(profile, moved)["intake_target"]

        if intake <= 0 and moved <= 0:
            status = "empty"
        elif intake > target:
            status = "over"
        elif intake <= 0:
            status = "moved"
        elif intake >= target * 0.7:
            status = "ok"
        else:
            status = "light"

        if intake > 0 or moved > 0:
            logged_days += 1
            total_intake += intake
            total_exercise += moved
            total_price += spent

        days.append({
            "date": key,
            "day": cursor.day,
            "dow": cursor.isoweekday(),
            "intake": round(intake),
            "exercise": round(moved),
            "target": target,
            "net": round(intake - target),
            "spent": round(spent, 1),
            "status": status,
            "is_today": key == today.isoformat(),
            "future": cursor > today,
        })
        cursor += timedelta(days=1)

    return {
        "year": year,
        "month": month,
        "days": days,
        "summary": {
            "logged_days": logged_days,
            "total_intake": round(total_intake),
            "total_exercise": round(total_exercise),
            "total_spent": round(total_price, 1),
            "avg_intake": round(total_intake / logged_days) if logged_days else 0,
        },
    }


@app.get("/api/menu")
def api_menu(q: str = "", limit: int = Query(default=200, ge=1, le=500)) -> list[dict]:
    items = db.all_menu()
    if q:
        items = [i for i in items if q in (i.get("name") or "")]
    return items[:limit]


# ---------- 运动 ----------

@app.post("/api/exercise")
def api_add_exercise(payload: ExerciseIn) -> dict:
    target_day = _parse_day(payload.day)
    meta = nutrition.get_exercise(payload.kind)
    if not meta:
        raise HTTPException(status_code=400, detail="未知的运动类型")
    profile = db.get_profile()
    weight = float(profile.get("weight_kg") or 58)
    kcal = nutrition.exercise_kcal(meta["met"], weight, payload.minutes)
    exercise_id = db.add_exercise(
        target_day, meta["label"], payload.minutes, meta["met"], kcal, payload.note
    )
    return {
        "id": exercise_id,
        "day": target_day,
        "kind": meta["label"],
        "minutes": payload.minutes,
        "met": meta["met"],
        "kcal": round(kcal),
    }


@app.delete("/api/exercise/{exercise_id}")
def api_delete_exercise(exercise_id: int) -> dict:
    if not db.delete_exercise(exercise_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"deleted": exercise_id}


# ---------- 饮食 ----------

@app.post("/api/meal")
def api_add_meal(payload: MealIn) -> dict:
    target_day = _parse_day(payload.day)
    if not payload.items:
        raise HTTPException(status_code=400, detail="至少选择一个餐品")

    menu_by_name = _menu_by_name()
    enriched = []
    for item in payload.items:
        known = menu_by_name.get(item.name)
        if known:
            enriched.append({
                "code": known["code"],
                "name": known["name"],
                "category": known["category"],
                "kcal": float(known["kcal"] or 0),
                "protein": float(known["protein"] or 0),
                "fat": float(known["fat"] or 0),
                "carb": float(known["carb"] or 0),
                "price": float(known["price"] or 0),
            })
        else:
            enriched.append({
                "code": item.code or item.name,
                "name": item.name,
                "category": item.category or categorize(item.name),
                "kcal": item.kcal,
                "protein": item.protein,
                "fat": item.fat,
                "carb": item.carb,
                "price": item.price,
            })

    list_price = sum(i["price"] for i in enriched)
    coupons = db.all_coupons()
    best = recommend.apply_coupon(enriched, list_price, coupons)
    if payload.coupon_id:
        chosen = next((c for c in coupons if str(c.get("id")) == payload.coupon_id), None)
        if chosen:
            specific = recommend.apply_coupon(enriched, list_price, [chosen])
            if specific:
                best = specific

    saved = best["saved"] if best else 0.0
    pay_price = best["pay_price"] if best else list_price

    meal_id = db.add_meal(
        day=target_day,
        slot=payload.slot or "午餐",
        title="、".join(i["name"] for i in enriched),
        items=enriched,
        kcal=sum(i["kcal"] for i in enriched),
        protein=sum(i["protein"] for i in enriched),
        fat=sum(i["fat"] for i in enriched),
        carb=sum(i["carb"] for i in enriched),
        price=pay_price,
        saved=saved,
        coupon=best["title"] if best else "",
        source="manual",
    )
    return {"id": meal_id, "day": target_day, "pay_price": pay_price, "saved": saved}


@app.delete("/api/meal/{meal_id}")
def api_delete_meal(meal_id: int) -> dict:
    if not db.delete_meal(meal_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"deleted": meal_id}


@app.post("/api/feedback")
def api_feedback(payload: FeedbackIn) -> dict:
    db.add_feedback(payload.item_code, payload.liked, payload.day)
    return {"ok": True}


# ---------- 资料 ----------

@app.get("/api/profile")
def api_get_profile() -> dict:
    return db.get_profile()


@app.put("/api/profile")
def api_update_profile(payload: ProfileIn) -> dict:
    return db.update_profile(**payload.model_dump(exclude_none=True))


# ---------- 同步真实数据 ----------

@app.post("/api/sync")
async def api_sync(payload: SyncIn) -> dict:
    if not MCD_MCP_TOKEN:
        raise HTTPException(status_code=400, detail="未配置 MCD_MCP_TOKEN，当前为演示模式")
    summary = await _run_sync(payload.store_code)
    return summary


async def _run_sync(store_code: str | None) -> dict:
    """一次连接内完成全部同步，减少往返。"""
    from .config import MCD_MCP_URL
    from .mcp_client import MCPClient

    summary: dict = {
        "nutrition": 0, "orders": 0, "orders_imported": 0,
        "coupons": 0, "menu": 0, "stores": 0, "campaigns": 0,
        "store_code": store_code or "", "errors": [],
    }

    async with MCPClient(MCD_MCP_URL, MCD_MCP_TOKEN, timeout=90) as client:
        try:
            items = await tools.fetch_nutrition(client)
            if items:
                db.replace_menu(items, source="live")
                db.replace_menu([], source="demo")
            summary["nutrition"] = len(items)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"nutrition: {exc}")

        try:
            orders = await tools.fetch_orders(client)
            summary["orders"] = len(orders)
            menu_by_name = _menu_by_name()
            existing = db.all_meal_sources()
            added = 0
            for meal in tools.orders_to_meals(orders, menu_by_name):
                if meal["source"] in existing:
                    continue
                db.add_meal(
                    day=meal["day"], slot=meal["slot"], title=meal["title"],
                    items=meal["items"], kcal=meal["kcal"], protein=meal["protein"],
                    fat=meal["fat"], carb=meal["carb"], price=meal["price"],
                    saved=0, coupon="", source=meal["source"],
                )
                added += 1
            summary["orders_imported"] = added
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"orders: {exc}")

        try:
            coupons = await tools.fetch_coupons(client)
            if coupons:
                db.replace_coupons(coupons, source="live")
                db.replace_coupons([], source="demo")
            summary["coupons"] = len(coupons)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"coupons: {exc}")

        try:
            campaigns = await tools.fetch_campaigns(client)
            if campaigns:
                db.kv_set("campaigns", json.dumps(campaigns, ensure_ascii=False))
            summary["campaigns"] = len(campaigns)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"campaigns: {exc}")

        if not store_code:
            try:
                stores = await tools.fetch_favorite_stores(client)
                summary["stores"] = len(stores)
                if stores:
                    store_code = str(stores[0].get("storeCode") or "")
                    summary["store_code"] = store_code
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"stores: {exc}")

        if store_code:
            try:
                products = await tools.fetch_store_menu(client, store_code)
                if products:
                    db.apply_live_prices(products)
                summary["menu"] = len(products)
            except MCPError as exc:
                summary["errors"].append(f"menu: {exc}")
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"menu: {exc}")

    summary["errors"] = [e for e in summary["errors"] if e]
    db.kv_set("last_sync", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    db.kv_set("last_sync_error", " | ".join(summary["errors"])[:500])
    return summary


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
