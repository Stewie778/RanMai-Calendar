"""SQLite 存储层。单用户本地应用，数据只存在本机 data/ranmai.db。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    nickname            TEXT    NOT NULL DEFAULT '麦友',
    sex                 TEXT    NOT NULL DEFAULT 'female',
    age                 INTEGER NOT NULL DEFAULT 26,
    height_cm           REAL    NOT NULL DEFAULT 165,
    weight_kg           REAL    NOT NULL DEFAULT 58,
    activity_level      REAL    NOT NULL DEFAULT 1.375,
    goal_deficit        INTEGER NOT NULL DEFAULT 300,
    daily_food_budget   REAL    NOT NULL DEFAULT 45,
    protein_g_per_kg    REAL    NOT NULL DEFAULT 1.4,
    updated_at          TEXT
);

CREATE TABLE IF NOT EXISTS exercise (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    minutes    REAL    NOT NULL,
    met        REAL    NOT NULL,
    kcal       REAL    NOT NULL,
    note       TEXT    DEFAULT '',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_exercise_day ON exercise(day);

CREATE TABLE IF NOT EXISTS meal_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT    NOT NULL,
    slot       TEXT    NOT NULL DEFAULT '午餐',
    title      TEXT    NOT NULL DEFAULT '',
    items_json TEXT    NOT NULL DEFAULT '[]',
    kcal       REAL    NOT NULL DEFAULT 0,
    protein    REAL    NOT NULL DEFAULT 0,
    fat        REAL    NOT NULL DEFAULT 0,
    carb       REAL    NOT NULL DEFAULT 0,
    price      REAL    NOT NULL DEFAULT 0,
    saved      REAL    NOT NULL DEFAULT 0,
    coupon     TEXT    DEFAULT '',
    source     TEXT    NOT NULL DEFAULT 'manual',
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_meal_day ON meal_log(day);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code  TEXT    NOT NULL,
    liked      INTEGER NOT NULL,
    day        TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS menu (
    code             TEXT PRIMARY KEY,
    product_code     TEXT,
    name             TEXT NOT NULL,
    category         TEXT NOT NULL DEFAULT '其他',
    kcal             REAL NOT NULL DEFAULT 0,
    protein          REAL NOT NULL DEFAULT 0,
    fat              REAL NOT NULL DEFAULT 0,
    carb             REAL NOT NULL DEFAULT 0,
    sodium           REAL NOT NULL DEFAULT 0,
    calcium          REAL NOT NULL DEFAULT 0,
    price            REAL,
    price_is_estimate INTEGER NOT NULL DEFAULT 1,
    source           TEXT NOT NULL DEFAULT 'demo',
    updated_at       TEXT
);

CREATE TABLE IF NOT EXISTS coupon (
    id           TEXT PRIMARY KEY,
    code         TEXT DEFAULT '',
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'amount',
    value        REAL NOT NULL DEFAULT 0,
    min_spend    REAL NOT NULL DEFAULT 0,
    match_text   TEXT DEFAULT '',
    order_types  TEXT DEFAULT '',
    expires      TEXT DEFAULT '',
    note         TEXT DEFAULT '',
    source       TEXT NOT NULL DEFAULT 'demo',
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT COUNT(*) AS n FROM profile").fetchone()
        if row["n"] == 0:
            conn.execute(
                "INSERT INTO profile (id, updated_at) VALUES (1, ?)", (now_text(),)
            )


# ---------- profile ----------

def get_profile() -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    return dict(row) if row else {}


def update_profile(**fields: Any) -> dict:
    allowed = {
        "nickname", "sex", "age", "height_cm", "weight_kg",
        "activity_level", "goal_deficit", "daily_food_budget", "protein_g_per_kg",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if updates:
        cols = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [now_text()]
        with get_db() as conn:
            conn.execute(f"UPDATE profile SET {cols}, updated_at = ? WHERE id = 1", values)
    return get_profile()


# ---------- exercise ----------

def add_exercise(day: str, kind: str, minutes: float, met: float, kcal: float, note: str = "") -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO exercise (day, kind, minutes, met, kcal, note, created_at) VALUES (?,?,?,?,?,?,?)",
            (day, kind, minutes, met, round(kcal, 1), note, now_text()),
        )
        return int(cur.lastrowid)


def delete_exercise(exercise_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM exercise WHERE id = ?", (exercise_id,))
        return cur.rowcount > 0


def list_exercise(day: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM exercise WHERE day = ? ORDER BY id", (day,)
        ).fetchall()
    return [dict(r) for r in rows]


def exercise_between(start: str, end: str) -> dict[str, float]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT day, SUM(kcal) AS kcal FROM exercise WHERE day BETWEEN ? AND ? GROUP BY day",
            (start, end),
        ).fetchall()
    return {r["day"]: float(r["kcal"] or 0) for r in rows}


# ---------- meal log ----------

def add_meal(
    day: str,
    slot: str,
    title: str,
    items: list[dict],
    kcal: float,
    protein: float,
    fat: float,
    carb: float,
    price: float = 0,
    saved: float = 0,
    coupon: str = "",
    source: str = "manual",
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO meal_log
               (day, slot, title, items_json, kcal, protein, fat, carb, price, saved, coupon, source, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                day, slot, title, json.dumps(items, ensure_ascii=False),
                round(kcal, 1), round(protein, 1), round(fat, 1), round(carb, 1),
                round(price, 2), round(saved, 2), coupon, source, now_text(),
            ),
        )
        return int(cur.lastrowid)


def delete_meal(meal_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM meal_log WHERE id = ?", (meal_id,))
        return cur.rowcount > 0


def list_meals(day: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM meal_log WHERE day = ? ORDER BY id", (day,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["items"] = json.loads(item.pop("items_json") or "[]")
        except json.JSONDecodeError:
            item["items"] = []
        result.append(item)
    return result


def meals_between(start: str, end: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM meal_log WHERE day BETWEEN ? AND ? ORDER BY day, id", (start, end)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["items"] = json.loads(item.pop("items_json") or "[]")
        except json.JSONDecodeError:
            item["items"] = []
        result.append(item)
    return result


def meals_between_sums(start: str, end: str) -> dict[str, dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT day, SUM(kcal) kcal, SUM(protein) protein, SUM(price) price
               FROM meal_log WHERE day BETWEEN ? AND ? GROUP BY day""",
            (start, end),
        ).fetchall()
    return {
        r["day"]: {
            "kcal": float(r["kcal"] or 0),
            "protein": float(r["protein"] or 0),
            "price": float(r["price"] or 0),
        }
        for r in rows
    }


# ---------- feedback ----------

def add_feedback(item_code: str, liked: bool, day: str | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO feedback (item_code, liked, day, created_at) VALUES (?,?,?,?)",
            (item_code, 1 if liked else 0, day or date.today().isoformat(), now_text()),
        )


def all_feedback() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ---------- menu ----------

def replace_menu(items: list[dict], source: str) -> int:
    with get_db() as conn:
        conn.execute("DELETE FROM menu WHERE source = ?", (source,))
        for item in items:
            conn.execute(
                """INSERT OR REPLACE INTO menu
                   (code,product_code,name,category,kcal,protein,fat,carb,sodium,calcium,price,price_is_estimate,source,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["code"], item.get("product_code"), item["name"],
                    item.get("category", "其他"),
                    item.get("kcal", 0), item.get("protein", 0), item.get("fat", 0),
                    item.get("carb", 0), item.get("sodium", 0), item.get("calcium", 0),
                    item.get("price"), 1 if item.get("price_is_estimate", True) else 0,
                    source, now_text(),
                ),
            )
        return len(items)


def apply_live_prices(products: list[dict]) -> int:
    """把门店实时菜单的价格与 productCode 写回目录（按名称匹配）。"""
    updated = 0
    with get_db() as conn:
        for product in products:
            name = product.get("name")
            if not name:
                continue
            price = product.get("price")
            code = product.get("code") or product.get("productCode")
            if price is None and not code:
                continue
            cursor = conn.execute(
                """UPDATE menu
                   SET price = COALESCE(?, price),
                       price_is_estimate = CASE WHEN ? IS NULL THEN price_is_estimate ELSE 0 END,
                       product_code = COALESCE(?, product_code),
                       updated_at = ?
                   WHERE name = ?""",
                (price, price, code, now_text(), name),
            )
            updated += cursor.rowcount
    return updated


def all_meal_sources() -> set[str]:
    with get_db() as conn:
        rows = conn.execute("SELECT DISTINCT source FROM meal_log").fetchall()
    return {r["source"] for r in rows}


def all_menu() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM menu ORDER BY category, name").fetchall()
    return [dict(r) for r in rows]


def menu_count() -> int:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM menu").fetchone()
    return int(row["n"])


# ---------- coupons ----------

def replace_coupons(coupons: list[dict], source: str) -> int:
    with get_db() as conn:
        conn.execute("DELETE FROM coupon WHERE source = ?", (source,))
        for c in coupons:
            conn.execute(
                """INSERT OR REPLACE INTO coupon
                   (id,code,title,kind,value,min_spend,match_text,order_types,expires,note,source,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    c["id"], c.get("code", ""), c["title"], c.get("kind", "amount"),
                    c.get("value", 0), c.get("min_spend", 0), c.get("match_text", ""),
                    c.get("order_types", ""), c.get("expires", ""), c.get("note", ""),
                    source, now_text(),
                ),
            )
        return len(coupons)


def all_coupons() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM coupon ORDER BY value DESC").fetchall()
    return [dict(r) for r in rows]


# ---------- kv ----------

def kv_get(key: str, default: str | None = None) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
    return row["v"] if row else default


def kv_set(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (key, value))
