"""LLM Prompt Engine & Rule Fallback Service for Vancouver Summer Explorer."""

import json
import math
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

VANCOUVER_LAT = 49.2827
VANCOUVER_LNG = -123.1207

# =====================================================================
# System Prompts (Optimized Versions)
# =====================================================================

AI_PLAN_SYSTEM_PROMPT = """你是一个专业的温哥华定制旅行规划专家。你的任务是根据用户的出行偏好、预算限制以及活动地点的微气候天气数据，在给定的候选活动库中遴选出最优质的一日行程（目标为 3 个活动）。

【核心硬性约束】
1. 活动来源限制（防幻觉）：选出的活动 ID 必须且只能存在于输入的 activity_library 中，严禁自行虚构或引入库外活动。
2. 预算硬上限：
   - 每日总费用计算公式：Total Cost = Σ(selected_activity.cost) × group_size
   - 规则：Total Cost 绝对不能超过用户的最高预算 max_budget。
   - 注意：Cost 为 null 或未填的活动按 0.0 CAD 计算。
3. 天气避险机制：
   - 当某活动所在坐标降雨概率 >= 50% 时，严禁选择户外活动 (is_outdoor = true)。
   - 当下雨时，必须 100% 从室内活动 (is_outdoor = false) 中挑选。
4. 地理时间顺畅度：
   - 根据活动坐标 (lat, lng) 排布顺畅的游览顺序，相邻活动之间的球面距离尽量控制在 5.0 km 以内。
   - 若坐标为空，默认按温哥华市中心 (49.2827, -123.1207) 计算。
5. 活动数量弹性：
   - 目标为选出 3 个活动。若符合预算和避雨条件的活动少于 3 个，可仅挑选 1~2 个最符合条件的活动，切勿为了凑数而违反避雨或预算规则。

输出格式要求（必须输出严格合法 JSON，不得带 Markdown 代码块标记）：
{
  "selected_activities": [
    {
      "id": 1,
      "name": "Stanley Park",
      "cost_per_person": 0.0,
      "reason": "免费户外景点，完美匹配偏好且当日无明显降雨"
    }
  ],
  "total_cost": 0.0,
  "weather_risk_level": "Low",
  "planning_summary": "一句话行程设计亮点"
}"""


SMART_SWAP_SYSTEM_PROMPT = """你是一个智能避雨替换引擎（Smart-Swap Engine）。当原定行程中的户外活动面临高降雨风险（降雨概率 >= 50%）时，你的目标是在给定的室内候选库中寻找最合适的室内活动进行无缝替代。

【三级匹配与排序规则 (3-Tier Ranking)】
请按以下优先级在 indoor_candidates 中评估并选择唯一的最佳替换活动：
- Tier 1（最优候选）：
  1) 候选室内活动与原活动的球面距离 (Haversine Distance) <= 2.0 km。
  2) 价格差值 |indoor.cost - outdoor.cost| <= max(outdoor.cost * 0.20, 10.0) CAD。
- Tier 2（次优候选）：
  球面距离 <= 5.0 km 的任意室内活动。
- Tier 3（保底候选）：
  候选库中任意可用的室内活动。

【破局法则 (Tie-breaking Rule)】
若有多个活动处于同一 Tier，按以下优先级选取唯一候选：
1. 距离最近者优先；
2. 价格差值最小者优先；
3. ID 最小者优先。

输出格式要求（必须输出严格合法 JSON）：
【有合适替换时输出】：
{
  "status": "success",
  "original_activity_id": 101,
  "swapped_activity": {
    "id": 202,
    "name": "Vancouver Art Gallery",
    "tier_matched": "Tier 1",
    "distance_km": 1.2,
    "cost_difference": 5.0
  },
  "swap_reason": "详细解释替换原因及地理/预算优势",
  "transit_suggestion": "提供温哥华 TransLink 公共交通接驳建议（如提示乘坐 SkyTrain 或 SeaBus）"
}

【无候选活动可供替换时输出】：
{
  "status": "no_match_found",
  "original_activity_id": 101,
  "swapped_activity": null,
  "swap_reason": "候选库中未找到可替换的室内活动。",
  "transit_suggestion": "☔ 建议携带雨具，或调整日期出游。"
}"""


WEATHER_ADVISORY_SYSTEM_PROMPT = """你是 Vancouver Summer Explorer 的微气候分析助手。你需要分析指定日期内各个活动特定坐标的天气预测，并生成具有温哥华本地特色的出行、防晒与公共交通建议。

【分析规则与触发逻辑】
1. 高风险活动判断（仅针对户外活动 is_outdoor = true）：
   - 降雨风险 (Rain Risk)：当某户外活动的 precipitation_probability_max >= 50% (0.50) 时，将该活动 ID 加入 high_risk_activity_ids，并设置 rain_risk: true。
   - 紫外线风险 (UV Risk)：当某户外活动的 uv_index_max >= 6.0 时，设置 uv_risk: true，并在建议中补充防晒/避暑提示。
2. 本地化交通指导 (TransLink Guidance)：
   - Downtown 地区：提示利用地下通道系统 (Underground Concourses) 避雨。
   - 跨海前往 North Vancouver：推荐搭乘 SeaBus。
   - 暴雨天出行：推荐使用 SkyTrain (Expo / Canada / Millennium Line) 避雨站台。
3. 数据源不可用 (source == "unavailable")：
   - 若天气数据缺失，设定 rain_risk: false, uv_risk: false，并提示“天气预报暂不可用，请保持行程弹性”。

输出格式要求（必须输出严格合法 JSON）：
{
  "date": "YYYY-MM-DD",
  "rain_risk": true,
  "uv_risk": false,
  "high_risk_activity_ids": [101],
  "recommendation": "个性化避雨/防晒建议",
  "transit_advice": "结合 TransLink 的实用交通建议"
}"""


# =====================================================================
# Utility Functions
# =====================================================================

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculates great-circle distance between two coordinates in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


def _call_llm_api(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Sends prompt to external LLM API if LLM_API_KEY is configured in env."""
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        return None

    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


# =====================================================================
# Engine Functions (With Rule Fallback)
# =====================================================================

def run_smart_swap(
    outdoor_activity: Dict[str, Any],
    indoor_candidates: List[Dict[str, Any]],
    group_size: int = 1,
) -> Dict[str, Any]:
    """Executes Smart-Swap Prompt engine with fallback to deterministic 3-Tier rule engine."""
    user_prompt = json.dumps({
        "outdoor_activity": outdoor_activity,
        "indoor_candidates": indoor_candidates,
        "group_size": group_size,
    }, ensure_ascii=False)

    llm_raw = _call_llm_api(SMART_SWAP_SYSTEM_PROMPT, user_prompt)
    if llm_raw:
        try:
            return json.loads(llm_raw)
        except Exception:
            pass

    # --- Rule Fallback Engine (Guaranteed Execution matching Prompt logic) ---
    if not indoor_candidates:
        return {
            "status": "no_match_found",
            "original_activity_id": outdoor_activity.get("id") or outdoor_activity.get("activity_id", 0),
            "swapped_activity": None,
            "swap_reason": "候选库中未找到可替换的室内活动。",
            "transit_suggestion": "☔ 建议携带雨具，或调整日期出游。",
        }

    target_lat = outdoor_activity.get("lat") or VANCOUVER_LAT
    target_lng = outdoor_activity.get("lng") or VANCOUVER_LNG
    target_cost = outdoor_activity.get("cost") or 0.0

    evaluated = []
    for cand in indoor_candidates:
        cand_lat = cand.get("lat") or VANCOUVER_LAT
        cand_lng = cand.get("lng") or VANCOUVER_LNG
        cand_cost = cand.get("cost") or 0.0

        dist = haversine_km(target_lat, target_lng, cand_lat, cand_lng)
        cost_diff = abs(cand_cost - target_cost)
        cost_tolerance = max(target_cost * 0.20, 10.0)

        if dist <= 2.0 and cost_diff <= cost_tolerance:
            rank = 1
            tier_str = "Tier 1"
        elif dist <= 5.0:
            rank = 2
            tier_str = "Tier 2"
        else:
            rank = 3
            tier_str = "Tier 3"

        cand_id = cand.get("id") or cand.get("activity_id", 0)
        evaluated.append((rank, dist, cost_diff, cand_id, tier_str, cand))

    # Tie-breaking: Rank -> Distance -> Cost diff -> ID
    evaluated.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    best = evaluated[0]
    matched_cand = best[5]
    dist_val = best[1]
    cost_diff_val = best[2]
    tier_str = best[4]

    orig_id = outdoor_activity.get("id") or outdoor_activity.get("activity_id", 0)
    matched_id = matched_cand.get("id") or matched_cand.get("activity_id", 0)

    transit_advice = (
        f"🚆 TransLink 公交建议：靠近距离 {dist_val:.1f}km 的 {matched_cand['name']}，"
        f"建议乘坐 SkyTrain / SeaBus 通过覆盖走廊前往。"
    )

    return {
        "status": "success",
        "original_activity_id": orig_id,
        "swapped_activity": {
            "id": matched_id,
            "name": matched_cand["name"],
            "tier_matched": tier_str,
            "distance_km": dist_val,
            "cost_difference": round(cost_diff_val, 2),
        },
        "swap_reason": f"根据 {tier_str} 规则匹配成功：替代方案为 {matched_cand['name']}（距离 {dist_val:.1f}km，差价 ${cost_diff_val:.2f} CAD）。",
        "transit_suggestion": transit_advice,
    }


def run_ai_plan(
    date: str,
    max_budget: float,
    preference: str,
    group_size: int,
    weather_data: List[Dict[str, Any]],
    activity_library: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Executes AI Plan Prompt engine with fallback to deterministic heuristic rule engine."""
    user_prompt = json.dumps({
        "date": date,
        "group_size": group_size,
        "max_budget": max_budget,
        "preferences": preference,
        "weather_data": weather_data,
        "activity_library": activity_library,
    }, ensure_ascii=False)

    llm_raw = _call_llm_api(AI_PLAN_SYSTEM_PROMPT, user_prompt)
    if llm_raw:
        try:
            return json.loads(llm_raw)
        except Exception:
            pass

    # --- Rule Fallback Engine (Guaranteed Execution matching Prompt logic) ---
    is_rainy = any(item.get("rain_probability", 0) >= 0.5 for item in weather_data)
    pref = (preference or "outdoor").lower()

    candidates = []
    for a in activity_library:
        cost = a.get("cost") or 0.0
        score = 0
        is_out = bool(a.get("is_outdoor", False))
        tags = [t.lower() for t in a.get("tags", [])]

        if is_rainy and is_out:
            score -= 100  # Hard rule against outdoor activities on rainy days
        elif not is_rainy and is_out:
            score += 15

        if pref == "outdoor" and is_out and not is_rainy:
            score += 20
        elif pref in ["museum", "art"] and (not is_out or any(t in ["museum", "art", "gallery", "indoor"] for t in tags)):
            score += 20
        elif pref in ["food", "market"] and any(t in ["food", "market", "cafe", "chill", "dining"] for t in tags):
            score += 20
        elif pref == "free" and cost == 0:
            score += 20

        candidates.append((score, a))

    candidates.sort(key=lambda x: x[0], reverse=True)

    selected = []
    current_cost_per_person = 0.0
    for score, a in candidates:
        if is_rainy and a.get("is_outdoor", False):
            continue
        c = a.get("cost") or 0.0
        if (current_cost_per_person + c) * group_size <= max_budget or not selected:
            selected.append(a)
            current_cost_per_person += c
            if len(selected) >= 3:
                break

    selected_activities = [
        {
            "id": a["id"],
            "name": a["name"],
            "cost_per_person": a.get("cost") or 0.0,
            "reason": f"符合偏好 ({preference})，成本 ${a.get('cost') or 0.0:.2f} CAD" + ("（室内避雨推荐）" if is_rainy else ""),
        }
        for a in selected
    ]

    total_cost = round(current_cost_per_person * group_size, 2)
    risk_level = "High" if is_rainy else "Low"
    summary = f"已针对 {date} 精选 {len(selected_activities)} 个最佳活动，预估总预算 ${total_cost:.2f} CAD。"

    return {
        "selected_activities": selected_activities,
        "total_cost": total_cost,
        "weather_risk_level": risk_level,
        "planning_summary": summary,
    }


def run_weather_advisory(
    date: str,
    daily_activities: List[Dict[str, Any]],
    mcp_weather_payload: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Executes MCP Weather Advisory Prompt engine with fallback to local rule logic."""
    user_prompt = json.dumps({
        "date": date,
        "daily_activities": daily_activities,
        "mcp_weather_payload": mcp_weather_payload,
    }, ensure_ascii=False)

    llm_raw = _call_llm_api(WEATHER_ADVISORY_SYSTEM_PROMPT, user_prompt)
    if llm_raw:
        try:
            return json.loads(llm_raw)
        except Exception:
            pass

    # --- Rule Fallback Engine (Guaranteed Execution matching Prompt logic) ---
    high_risk_ids = []
    rain_risk = False
    uv_risk = False

    weather_map = {item.get("activity_id"): item for item in mcp_weather_payload}

    for act in daily_activities:
        act_id = act.get("activity_id") or act.get("id")
        is_outdoor = bool(act.get("is_outdoor", False))
        weather = weather_map.get(act_id, {})
        rain_prob = weather.get("rain_probability", 0.0)
        uv_idx = weather.get("uv_index", 5.0)

        if is_outdoor and rain_prob >= 0.5:
            rain_risk = True
            high_risk_ids.append(act_id)

        if is_outdoor and uv_idx >= 6.0:
            uv_risk = True

    if rain_risk:
        rec = f"检测到 {len(high_risk_ids)} 个户外活动可能遇到降雨，建议携带雨具或通过 Smart-Swap 替换为室内方案。"
        transit = "🚆 TransLink 交通建议：在 Downtown 可利用地下通道 (Concourses) 避雨；前往北温建议使用 SeaBus 与遮罩公交站。"
    elif uv_risk:
        rec = "全天天气良好但紫外线指数偏高 (>= 6.0)，户外活动请注意涂抹防晒霜并佩戴墨镜。"
        transit = "🕶️ TransLink 交通建议：建议优先选择带空调的 SkyTrain / SeaBus 设施乘车出行。"
    else:
        rec = "气象条件良好，适合进行户外与室内游览。"
        transit = "🚆 TransLink 交通建议：全天交通状况顺畅，建议使用 Compass Card 便捷搭乘 SkyTrain 游览。"

    return {
        "date": date,
        "rain_risk": rain_risk,
        "uv_risk": uv_risk,
        "high_risk_activity_ids": high_risk_ids,
        "recommendation": rec,
        "transit_advice": transit,
    }
