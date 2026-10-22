/* 燃麦日历 · 前端（原生 JS，无构建步骤） */
const $ = (selector) => document.querySelector(selector);
const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
const DONUT_C = 2 * Math.PI * 56;

const state = {
  date: todayISO(),
  viewYear: new Date().getFullYear(),
  viewMonth: new Date().getMonth() + 1,
  dashboard: null,
  types: [],
  busy: false,
};

/* ---------- 日期工具 ---------- */
function pad(n) { return String(n).padStart(2, "0"); }
function isoOf(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function todayISO() { return isoOf(new Date()); }
function parseISO(s) { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); }
function weekdayOf(iso) { return WEEKDAYS[parseISO(iso).getDay() === 0 ? 6 : parseISO(iso).getDay() - 1]; }
function prettyDate(iso) {
  const d = parseISO(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日 · 周${weekdayOf(iso)}`;
}
function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- 请求 ---------- */
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `请求失败 (${response.status})`);
  }
  return data;
}

let toastTimer = null;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

/* ---------- 初始化 ---------- */
async function init() {
  try {
    state.types = await api("/api/exercise-types");
    const select = $("#exerciseKind");
    select.innerHTML = state.types
      .map((t) => `<option value="${t.id}">${t.icon} ${esc(t.label)}</option>`)
      .join("");
  } catch (error) {
    console.error(error);
  }

  bindEvents();
  await loadDashboard(state.date);
  await loadCalendar(state.viewYear, state.viewMonth);

  // 真实模式启动后会后台同步一次，稍后自动刷新
  setTimeout(async () => {
    try {
      const status = await api("/api/status");
      if (status.live) {
        await loadDashboard(state.date);
        await loadCalendar(state.viewYear, state.viewMonth);
      }
    } catch (_) { /* 忽略 */ }
  }, 6000);
}

function bindEvents() {
  $("#prevMonth").addEventListener("click", () => shiftMonth(-1));
  $("#nextMonth").addEventListener("click", () => shiftMonth(1));
  $("#addExercise").addEventListener("click", addExercise);
  $("#todayBtn").addEventListener("click", () => selectDate(todayISO()));
  $("#syncBtn").addEventListener("click", syncLive);
  $("#settingsBtn").addEventListener("click", openSettings);
  $("#cancelSettings").addEventListener("click", () => $("#settingsModal").classList.add("hidden"));
  $("#saveSettings").addEventListener("click", saveSettings);
  $("#settingsModal").addEventListener("click", (event) => {
    if (event.target.id === "settingsModal") $("#settingsModal").classList.add("hidden");
  });
}

/* ---------- 面板 ---------- */
async function selectDate(iso) {
  state.date = iso;
  await loadDashboard(iso);
  await loadCalendar(state.viewYear, state.viewMonth);
}

async function loadDashboard(iso) {
  try {
    const data = await api(`/api/dashboard?day=${encodeURIComponent(iso)}`);
    state.dashboard = data;
    renderDashboard(data);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderDashboard(d) {
  const isToday = d.date === d.today;
  $("#todayTitle").textContent = isToday ? "今天" : prettyDate(d.date);
  $("#todayBtn").classList.toggle("hidden", isToday);

  const badge = $("#modeBadge");
  const live = d.status && d.status.live;
  badge.textContent = live ? "真实账号 · 本机" : "演示数据";
  badge.classList.toggle("live", Boolean(live));

  $("#streakBadge").textContent = d.streak > 0 ? `连续记录 ${d.streak} 天` : "今天开始记录";

  renderBudget(d);
  renderStats(d);
  renderExercise(d);
  renderMeals(d);
  renderCampaigns(d);
  renderRecommendations(d);
  renderTaste(d);
  renderCoupons(d);
}

function renderBudget(d) {
  const consumed = d.consumed.kcal;
  const target = d.targets.intake_target;
  const ratio = target > 0 ? consumed / target : 0;
  const over = consumed > target;

  const ring = $("#donutFg");
  ring.style.strokeDasharray = String(DONUT_C);
  ring.style.strokeDashoffset = String(DONUT_C * (1 - Math.min(1, Math.max(0, ratio))));
  ring.style.stroke = over ? "var(--red)" : (ratio > 0.75 ? "var(--green)" : "var(--yellow)");

  $("#remainingKcal").textContent = d.remaining.kcal;
  $("#budgetHeadline").textContent = `已摄入 ${Math.round(consumed)} / 目标 ${target} kcal`;

  const protein = d.consumed.protein;
  const proteinTarget = d.targets.protein_target_g;
  $("#macroRow").innerHTML = `
    <div class="macro p"><b>${Math.round(protein)}/${proteinTarget}g</b> 蛋白质</div>
    <div class="macro"><b>${Math.round(d.consumed.fat)}g</b> 脂肪</div>
    <div class="macro"><b>${Math.round(d.consumed.carb)}g</b> 碳水</div>
    <div class="macro"><b>${d.remaining.ratio}%</b> 额度</div>
  `;

  const parts = [
    `基础代谢 ${d.targets.bmr}`,
    `日常消耗 ${d.targets.tdee}`,
    `运动 ${d.targets.exercise_kcal}`,
  ];
  let sub = parts.join(" · ");
  if (d.targets.floor_applied) {
    sub += `。为了安全，目标已抬到下限 ${d.targets.floor} kcal。`;
  } else if (d.remaining.kcal > 0) {
    sub += `。扣掉计划缺口 ${d.targets.deficit_planned} kcal。`;
  }
  $("#budgetSub").textContent = sub;
}

function renderStats(d) {
  const stats = [
    ["运动消耗", d.exercise_kcal, "kcal"],
    ["已摄入", Math.round(d.consumed.kcal), "kcal"],
    ["今日目标", d.targets.intake_target, "kcal"],
    ["已花", `¥${(d.consumed.price || 0).toFixed(1)}`, ""],
  ];
  $("#statRow").innerHTML = stats
    .map(([label, value, unit]) => `
      <div class="stat"><b>${value}${unit ? `<span class="small"> ${unit}</span>` : ""}</b><span>${label}</span></div>
    `)
    .join("");
}

function renderExercise(d) {
  const list = $("#exerciseList");
  $("#exerciseKcal").textContent = `共 ${d.exercise_kcal} kcal`;
  if (!d.exercise.length) {
    list.innerHTML = `<li class="empty">还没有运动记录。动一动，午餐预算就多出来啦。</li>`;
    return;
  }
  list.innerHTML = d.exercise.map((item) => `
    <li>
      <div class="li-main">
        <div class="li-title">${esc(item.kind)} · ${item.minutes} 分钟</div>
        <div class="li-sub">MET ${item.met}${item.note ? ` · ${esc(item.note)}` : ""}</div>
      </div>
      <div class="li-right">
        <span class="li-kcal">-${Math.round(item.kcal)} kcal</span>
        <button class="del" data-del-exercise="${item.id}" title="删除">×</button>
      </div>
    </li>
  `).join("");
  list.querySelectorAll("[data-del-exercise]").forEach((btn) => {
    btn.addEventListener("click", () => deleteExercise(btn.dataset.delExercise));
  });
}

function renderMeals(d) {
  const list = $("#mealList");
  if (!d.meals.length) {
    list.innerHTML = `<li class="empty">还没有记录。从下面的推荐里挑一份试试。</li>`;
    return;
  }
  list.innerHTML = d.meals.map((meal) => `
    <li>
      <div class="li-main">
        <div class="li-title">${esc(meal.slot)} · ${esc(meal.title)}</div>
        <div class="li-sub">¥${Number(meal.price).toFixed(1)}${meal.saved ? ` · 省 ${Number(meal.saved).toFixed(1)}` : ""}${meal.coupon ? ` · ${esc(meal.coupon)}` : ""}</div>
      </div>
      <div class="li-right">
        <span class="li-kcal">${Math.round(meal.kcal)} kcal</span>
        <button class="del" data-del-meal="${meal.id}" title="删除">×</button>
      </div>
    </li>
  `).join("");
  list.querySelectorAll("[data-del-meal]").forEach((btn) => {
    btn.addEventListener("click", () => deleteMeal(btn.dataset.delMeal));
  });
}

function renderCampaigns(d) {
  const box = $("#campaigns");
  const campaigns = (d.campaigns || []).filter((c) => c.date === d.date);
  if (!campaigns.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = campaigns.slice(0, 3).map((c) => `
    <div class="campaign">🎉 ${esc(c.title)}${c.highlight ? ` · ${esc(c.highlight)}` : ""}</div>
  `).join("");
}

/* ---------- 推荐 ---------- */
function renderRecommendations(d) {
  const reco = d.recommendation || {};
  $("#recoNote").textContent = reco.note || "";
  const cards = reco.recommendations || [];
  const container = $("#recoCards");

  if (!cards.length) {
    container.innerHTML = `<div class="card empty">暂时给不出推荐，先同步一下菜单或补一条运动记录。</div>`;
    return;
  }

  container.innerHTML = cards.map((card, index) => {
    const items = card.items || [];
    const names = items.map((i) => esc(i.name)).join(" + ");
    const chips = items.map((i) => `<span class="chip">${esc(i.name)} · ${Math.round(i.kcal)} kcal</span>`).join("");
    const couponLine = card.coupon
      ? `用「${esc(card.coupon.title)}」省 ${Number(card.saved).toFixed(1)} 元 · 实付 ¥${Number(card.pay_price).toFixed(1)}`
      : `暂无可用券 · 参考价 ¥${Number(card.pay_price).toFixed(1)}`;
    return `
      <article class="reco ${index === 0 ? "best" : ""}">
        <span class="reco-badge ${index === 0 ? "hot" : ""}">${esc(card.badge || "推荐")}</span>
        <h3>${names}</h3>
        <div class="reco-items">${chips}</div>
        <div class="reco-stats">
          <span class="kcal"><b>${Math.round(card.kcal)}</b> kcal</span>
          <span>蛋白 <b>${Math.round(card.protein)}</b>g</span>
          <span>实付 <b>¥${Number(card.pay_price).toFixed(1)}</b></span>
        </div>
        <p class="reco-coupon ${card.coupon ? "" : "muted"}">${couponLine}</p>
        <ul class="reasons">${(card.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
        <div class="reco-actions">
          <button class="primary" data-eat="${index}">就吃这个</button>
          <button class="thumb" data-like="1" data-index="${index}" title="喜欢这个搭配">👍</button>
          <button class="thumb" data-like="0" data-index="${index}" title="不太喜欢">👎</button>
        </div>
      </article>
    `;
  }).join("");

  container.querySelectorAll("[data-eat]").forEach((btn) => {
    btn.addEventListener("click", () => addMeal(cards[Number(btn.dataset.eat)]));
  });
  container.querySelectorAll("[data-like]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = cards[Number(btn.dataset.index)];
      const first = (card.items || [])[0];
      if (first) sendFeedback(first.name, btn.dataset.like === "1");
    });
  });
}

function renderTaste(d) {
  const taste = d.taste || {};
  const chips = $("#tasteChips");
  const top = taste.top_items || [];
  if (!top.length) {
    chips.innerHTML = `<span class="muted small">吃几顿之后，这里会长出你的口味画像。</span>`;
  } else {
    chips.innerHTML = top.map((item, index) => `
      <span class="chip ${index < 2 ? "strong" : ""}">${esc(item.name)}${item.count ? ` · ${item.count} 次` : ""}</span>
    `).join("");
  }
  const avg = taste.avg_price ? `常点均价 ¥${taste.avg_price} · ` : "";
  $("#tasteMeta").textContent = `${avg}分析 ${taste.orders_analyzed || 0} 笔历史记录；越近的订单权重越高。`;
}

function renderCoupons(d) {
  const list = $("#couponList");
  const coupons = d.coupons || [];
  if (!coupons.length) {
    list.innerHTML = `<li class="empty">暂无可用券。真实模式下从你的麦当劳卡包同步。</li>`;
    return;
  }
  list.innerHTML = coupons.slice(0, 8).map((coupon) => {
    const label = coupon.kind === "price"
      ? `¥${Number(coupon.value).toFixed(1)}`
      : (coupon.min_spend ? `满${Number(coupon.min_spend).toFixed(0)}减${Number(coupon.value).toFixed(0)}` : `减${Number(coupon.value).toFixed(0)}`);
    return `
      <li class="coupon-row">
        <span>${esc(coupon.title)}</span>
        <span class="coupon-tag">${esc(label)}</span>
      </li>
    `;
  }).join("");
}

/* ---------- 日历 ---------- */
async function loadCalendar(year, month) {
  try {
    const data = await api(`/api/calendar?year=${year}&month=${month}`);
    renderCalendar(data);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderCalendar(data) {
  $("#monthLabel").textContent = `${data.year} 年 ${data.month} 月`;
  const grid = $("#calendar");
  const firstDow = data.days.length ? data.days[0].dow : 1;
  const blanks = firstDow - 1;

  let html = "";
  for (let i = 0; i < blanks; i += 1) html += `<div class="day blank"></div>`;

  for (const day of data.days) {
    const ratio = day.target > 0 ? Math.min(1, day.intake / day.target) : 0;
    const classes = ["day", day.status];
    if (day.is_today) classes.push("today");
    if (day.date === state.date) classes.push("selected");
    if (day.future) classes.push("future");

    let caption = "";
    if (day.status === "empty") caption = "";
    else if (day.intake > 0) caption = `${Math.round(day.intake)}`;
    else caption = "运动";

    html += `
      <div class="${classes.join(" ")}" data-date="${day.date}" title="${day.date}">
        ${day.exercise > 0 ? '<span class="exercise-dot"></span>' : ""}
        <span class="num">${day.day}</span>
        <span class="cal">${caption}${day.intake > 0 ? " kcal" : ""}</span>
        <span class="bar"><i style="width:${(ratio * 100).toFixed(1)}%"></i></span>
      </div>
    `;
  }
  grid.innerHTML = html;

  grid.querySelectorAll("[data-date]").forEach((cell) => {
    cell.addEventListener("click", () => selectDate(cell.dataset.date));
  });

  const summary = data.summary;
  $("#monthSummary").innerHTML = `
    <div class="item"><b>${summary.logged_days}</b><span>记录天数</span></div>
    <div class="item"><b>${summary.total_exercise}</b><span>运动消耗 kcal</span></div>
    <div class="item"><b>${summary.avg_intake}</b><span>日均摄入 kcal</span></div>
    <div class="item"><b>¥${summary.total_spent}</b><span>本月餐费</span></div>
  `;
}

function shiftMonth(delta) {
  let month = state.viewMonth + delta;
  let year = state.viewYear;
  if (month < 1) { month = 12; year -= 1; }
  if (month > 12) { month = 1; year += 1; }
  state.viewYear = year;
  state.viewMonth = month;
  loadCalendar(year, month);
}

/* ---------- 操作 ---------- */
async function addExercise() {
  if (state.busy) return;
  const kind = $("#exerciseKind").value;
  const minutes = Number($("#exerciseMinutes").value);
  if (!minutes || minutes <= 0) {
    toast("先填一下运动时长", true);
    return;
  }
  state.busy = true;
  try {
    await api("/api/exercise", {
      method: "POST",
      body: JSON.stringify({ day: state.date, kind, minutes }),
    });
    toast("记下了，今天的额度多了一点");
    await loadDashboard(state.date);
    await loadCalendar(state.viewYear, state.viewMonth);
  } catch (error) {
    toast(error.message, true);
  } finally {
    state.busy = false;
  }
}

async function deleteExercise(id) {
  try {
    await api(`/api/exercise/${id}`, { method: "DELETE" });
    await loadDashboard(state.date);
    await loadCalendar(state.viewYear, state.viewMonth);
  } catch (error) {
    toast(error.message, true);
  }
}

async function addMeal(card) {
  if (state.busy) return;
  state.busy = true;
  try {
    const result = await api("/api/meal", {
      method: "POST",
      body: JSON.stringify({
        day: state.date,
        slot: state.dashboard?.slot || "午餐",
        items: card.items,
        coupon_id: card.coupon ? card.coupon.id : null,
      }),
    });
    toast(`记好了，实付 ¥${Number(result.pay_price).toFixed(1)}`);
    await loadDashboard(state.date);
    await loadCalendar(state.viewYear, state.viewMonth);
  } catch (error) {
    toast(error.message, true);
  } finally {
    state.busy = false;
  }
}

async function deleteMeal(id) {
  try {
    await api(`/api/meal/${id}`, { method: "DELETE" });
    await loadDashboard(state.date);
    await loadCalendar(state.viewYear, state.viewMonth);
  } catch (error) {
    toast(error.message, true);
  }
}

async function sendFeedback(itemName, liked) {
  try {
    await api("/api/feedback", {
      method: "POST",
      body: JSON.stringify({ item_code: itemName, liked, day: state.date }),
    });
    toast(liked ? "收到，之后多推这类" : "收到，之后少推这类");
    await loadDashboard(state.date);
  } catch (error) {
    toast(error.message, true);
  }
}

/* ---------- 资料 ---------- */
function openSettings() {
  const p = state.dashboard?.profile;
  if (!p) return;
  $("#pNickname").value = p.nickname || "";
  $("#pSex").value = p.sex || "female";
  $("#pAge").value = p.age;
  $("#pHeight").value = p.height_cm;
  $("#pWeight").value = p.weight_kg;
  $("#pActivity").value = String(p.activity_level);
  $("#pDeficit").value = p.goal_deficit;
  $("#pProtein").value = p.protein_g_per_kg;
  $("#settingsModal").classList.remove("hidden");
}

async function saveSettings() {
  try {
    await api("/api/profile", {
      method: "PUT",
      body: JSON.stringify({
        nickname: $("#pNickname").value.trim() || "麦友",
        sex: $("#pSex").value,
        age: Number($("#pAge").value),
        height_cm: Number($("#pHeight").value),
        weight_kg: Number($("#pWeight").value),
        activity_level: Number($("#pActivity").value),
        goal_deficit: Number($("#pDeficit").value),
        protein_g_per_kg: Number($("#pProtein").value),
      }),
    });
    $("#settingsModal").classList.add("hidden");
    toast("资料已更新");
    await loadDashboard(state.date);
    await loadCalendar(state.viewYear, state.viewMonth);
  } catch (error) {
    toast(error.message, true);
  }
}

/* ---------- 同步 ---------- */
async function syncLive() {
  const btn = $("#syncBtn");
  btn.disabled = true;
  btn.textContent = "同步中…";
  try {
    const summary = await api("/api/sync", { method: "POST", body: JSON.stringify({}) });
    const bits = [`营养 ${summary.nutrition}`, `订单 ${summary.orders_imported || 0}`, `券 ${summary.coupons}`];
    if (summary.menu) bits.push(`门店菜单 ${summary.menu}`);
    toast(`同步完成：${bits.join(" · ")}`);
    if (summary.errors && summary.errors.length) {
      console.warn("同步告警", summary.errors);
    }
    await loadDashboard(state.date);
    await loadCalendar(state.viewYear, state.viewMonth);
  } catch (error) {
    toast(error.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "同步真实数据";
  }
}

init();
