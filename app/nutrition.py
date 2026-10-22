"""能量计算：BMR / TDEE / 运动消耗 / 安全下限。

公式来源：
  BMR  Mifflin-St Jeor (1990)
  运动 MET × 3.5 × 体重(kg) / 200 × 时长(min)
"""
from __future__ import annotations

from datetime import date, datetime

# MET 取值参考《体力活动纲要》(Compendium of Physical Activities)，按常见强度取中位数
EXERCISE_TYPES: list[dict] = [
    {"id": "walk",      "label": "快走",     "met": 4.3,  "icon": "🚶"},
    {"id": "run",       "label": "跑步",     "met": 9.0,  "icon": "🏃"},
    {"id": "cycle",     "label": "骑行",     "met": 7.5,  "icon": "🚴"},
    {"id": "swim",      "label": "游泳",     "met": 8.0,  "icon": "🏊"},
    {"id": "strength",  "label": "力量训练", "met": 5.0,  "icon": "🏋️"},
    {"id": "hiit",      "label": "HIIT",     "met": 8.0,  "icon": "🔥"},
    {"id": "rope",      "label": "跳绳",     "met": 12.3, "icon": "🪢"},
    {"id": "yoga",      "label": "瑜伽",     "met": 2.5,  "icon": "🧘"},
    {"id": "basketball","label": "篮球",     "met": 6.5,  "icon": "🏀"},
    {"id": "badminton", "label": "羽毛球",   "met": 5.5,  "icon": "🏸"},
    {"id": "football",  "label": "足球",     "met": 7.0,  "icon": "⚽"},
    {"id": "dance",     "label": "舞蹈",     "met": 5.0,  "icon": "💃"},
    {"id": "stairs",    "label": "爬楼梯",   "met": 8.8,  "icon": "🪜"},
    {"id": "elliptical","label": "椭圆机",   "met": 5.0,  "icon": "⚙️"},
    {"id": "rowing",    "label": "划船机",   "met": 7.0,  "icon": "🚣"},
    {"id": "hike",      "label": "徒步",     "met": 5.3,  "icon": "🥾"},
    {"id": "tennis",    "label": "网球",     "met": 7.3,  "icon": "🎾"},
    {"id": "tabletennis","label": "乒乓球",  "met": 4.0,  "icon": "🏓"},
]

_EXERCISE_BY_ID = {e["id"]: e for e in EXERCISE_TYPES}
_EXERCISE_BY_LABEL = {e["label"]: e for e in EXERCISE_TYPES}

MEAL_SLOTS = ["早餐", "午餐", "下午茶", "晚餐", "夜宵"]


def get_exercise(kind: str) -> dict | None:
    return _EXERCISE_BY_ID.get(kind) or _EXERCISE_BY_LABEL.get(kind)


def bmr(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + (5 if sex == "male" else -161)


def exercise_kcal(met: float, weight_kg: float, minutes: float) -> float:
    return met * 3.5 * weight_kg / 200 * minutes


def intake_floor(sex: str, bmr_value: float) -> float:
    """安全下限：不推荐低于基础代谢，且不低于通用最低摄入。"""
    hard_floor = 1500 if sex == "male" else 1200
    return max(bmr_value, hard_floor)


def daily_targets(profile: dict, exercise_kcal_today: float = 0.0) -> dict:
    """计算当日可摄入目标。"""
    sex = profile.get("sex", "female")
    age = int(profile.get("age", 26))
    height = float(profile.get("height_cm", 165))
    weight = float(profile.get("weight_kg", 58))
    activity = float(profile.get("activity_level", 1.375))
    deficit = float(profile.get("goal_deficit", 300))
    protein_per_kg = float(profile.get("protein_g_per_kg", 1.4))

    bmr_value = bmr(sex, weight, height, age)
    tdee = bmr_value * activity
    total_out = tdee + max(0.0, exercise_kcal_today)
    floor = intake_floor(sex, bmr_value)
    raw_target = total_out - deficit
    target = max(floor, raw_target)

    return {
        "bmr": round(bmr_value),
        "tdee": round(tdee),
        "exercise_kcal": round(exercise_kcal_today),
        "total_out": round(total_out),
        "deficit_planned": round(deficit),
        "floor": round(floor),
        "floor_applied": raw_target < floor,
        "intake_target": round(target),
        "protein_target_g": round(weight * protein_per_kg),
        "activity_level": activity,
        "weight_kg": weight,
    }


def slot_share(now: datetime | None = None) -> tuple[str, float]:
    """当前时段 & 这一餐建议占当日剩余额度的比例。"""
    now = now or datetime.now()
    h = now.hour
    if 5 <= h < 10:
        return "早餐", 0.30
    if 10 <= h < 14:
        return "午餐", 0.45
    if 14 <= h < 17:
        return "下午茶", 0.20
    if 17 <= h < 22:
        return "晚餐", 0.45
    return "夜宵", 0.20


def today_str() -> str:
    return date.today().isoformat()


def month_bounds(year: int, month: int) -> tuple[str, str]:
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1)
    end = end.fromordinal(end.toordinal() - 1)
    return start.isoformat(), end.isoformat()
