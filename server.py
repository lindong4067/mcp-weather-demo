"""
MCP Demo Server —— 演示「查询当前位置 / 查询天气」

- 传输方式：stdio（MCP 默认），由 MCP 客户端（Inspector / Claude Desktop / Cursor / 自写 client）拉起本进程并通过 JSON-RPC 调用工具。
- 数据源：全部使用免费、无需 API key 的公开接口
    · 当前位置：https://ipwho.is/（主），https://ipinfo.io/json（备）—— 基于出口 IP 定位
    · 城市地理编码：Open-Meteo Geocoding
    · 天气：Open-Meteo Forecast API

能力（MCP 三大原语）：
- Tools（工具，LLM 自动决定调用、执行动作）：
    get_current_location / get_weather / get_weather_forecast
- Resources（资源，客户端直接读取进上下文的数据）：
    weather://cities（静态）· weather://wmo-codes（静态）· weather://server-info（静态）
    weather://{city}/current（模板）· weather://{city}/forecast（模板）
- Prompts（提示词模板，客户端拉取后渲染进对话）：
    weather-assistant / travel-weather-plan / weather-briefing

用法：
    python server.py            # 以 stdio 方式运行，等待客户端连接
    npx @modelcontextprotocol/inspector python server.py   # 或通过 Inspector 图形化调试
"""

import json

from mcp.server.mcpserver import MCPServer
import httpx

mcp = MCPServer("weather-location-demo")

# ---------- 外部接口地址 ----------
IP_GEO_URLS = [
    "https://ipwho.is/",       # 主：免 key，返回 city/region/lat/lon
    "https://ipinfo.io/json",  # 备：免 key（有限频），返回 loc "lat,lon"
]
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# ---------- WMO 天气代码 → 中文描述 ----------
WEATHER_CODE_MAP = {
    0: "晴", 1: "基本晴", 2: "多云", 3: "阴",
    45: "雾", 48: "冻雾",
    51: "毛毛雨", 53: "毛毛雨", 55: "浓毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}

# ---------- 内置常用城市列表（静态资源 weather://cities 的数据源） ----------
COMMON_CITIES = [
    {"name": "北京", "country": "中国", "lat": 39.9042, "lon": 116.4074, "timezone": "Asia/Shanghai"},
    {"name": "上海", "country": "中国", "lat": 31.2304, "lon": 121.4737, "timezone": "Asia/Shanghai"},
    {"name": "广州", "country": "中国", "lat": 23.1291, "lon": 113.2644, "timezone": "Asia/Shanghai"},
    {"name": "深圳", "country": "中国", "lat": 22.5431, "lon": 114.0579, "timezone": "Asia/Shanghai"},
    {"name": "成都", "country": "中国", "lat": 30.5728, "lon": 104.0668, "timezone": "Asia/Shanghai"},
    {"name": "杭州", "country": "中国", "lat": 30.2741, "lon": 120.1551, "timezone": "Asia/Shanghai"},
    {"name": "武汉", "country": "中国", "lat": 30.5928, "lon": 114.3055, "timezone": "Asia/Shanghai"},
    {"name": "西安", "country": "中国", "lat": 34.3416, "lon": 108.9398, "timezone": "Asia/Shanghai"},
    {"name": "Tokyo", "country": "日本", "lat": 35.6762, "lon": 139.6503, "timezone": "Asia/Tokyo"},
    {"name": "London", "country": "英国", "lat": 51.5074, "lon": -0.1278, "timezone": "Europe/London"},
    {"name": "New York", "country": "美国", "lat": 40.7128, "lon": -74.006, "timezone": "America/New_York"},
    {"name": "Singapore", "country": "新加坡", "lat": 1.3521, "lon": 103.8198, "timezone": "Asia/Singapore"},
]


def _get_ip_location() -> dict:
    """通过出口 IP 定位当前位置，返回 {city, region, country, lat, lon, timezone}。"""
    for url in IP_GEO_URLS:
        try:
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "ipwho" in url or data.get("success") is not False:
                if "loc" in data:  # ipinfo 格式："lat,lon"
                    lat, lon = (float(x) for x in data["loc"].split(","))
                    return {
                        "city": data.get("city", ""),
                        "region": data.get("region", ""),
                        "country": data.get("country", ""),
                        "lat": lat, "lon": lon,
                        "timezone": data.get("timezone", ""),
                    }
                if data.get("latitude") is not None:  # ipwho.is 格式
                    tz = data.get("timezone", "")
                    if isinstance(tz, dict):  # ipwho.is 的 timezone 是对象，取 id
                        tz = tz.get("id", "")
                    return {
                        "city": data.get("city", ""),
                        "region": data.get("region", ""),
                        "country": data.get("country", ""),
                        "lat": data["latitude"], "lon": data["longitude"],
                        "timezone": tz,
                    }
        except Exception:
            continue  # 尝试下一个备用接口
    raise RuntimeError("无法获取当前位置（IP 定位接口均不可用）")


@mcp.tool()
def get_current_location() -> str:
    """获取当前所在位置：城市、省份、国家、经纬度、时区。基于出口 IP 定位，无需任何 API key。"""
    loc = _get_ip_location()
    return (
        f"当前定位：{loc['city']} · {loc['region']} · {loc['country']}\n"
        f"经纬度：({loc['lat']}, {loc['lon']})\n"
        f"时区：{loc['timezone']}"
    )


def _geocode(city: str) -> dict:
    """城市名 → 经纬度（Open-Meteo 地理编码，支持中文城市名）。"""
    resp = httpx.get(
        GEOCODING_URL,
        params={"name": city, "count": 1, "language": "zh", "format": "json"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        raise ValueError(f"未找到城市：{city}")
    r = results[0]
    return {
        "name": r.get("name", city),
        "country": r.get("country", ""),
        "lat": r["latitude"],
        "lon": r["longitude"],
    }


def _fetch_weather(lat: float, lon: float) -> dict:
    """按经纬度拉取当前天气（Open-Meteo，新版 current 接口）。"""
    resp = httpx.get(
        WEATHER_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m",
            "timezone": "auto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    cur = resp.json()["current"]
    return {
        "temperature": cur["temperature_2m"],
        "apparent_temperature": cur["apparent_temperature"],
        "weathercode": cur["weather_code"],
        "windspeed": cur["wind_speed_10m"],
        "winddirection": cur["wind_direction_10m"],
        "time": cur["time"],
    }


def _fetch_forecast(lat: float, lon: float, days: int = 7) -> dict:
    """按经纬度拉取未来 N 天逐日预报（Open-Meteo daily 接口）。"""
    resp = httpx.get(
        WEATHER_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,wind_speed_10m_max"
            ),
            "forecast_days": days,
            "timezone": "auto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]
    return {
        "time": daily["time"],
        "weather_code": daily["weather_code"],
        "temp_max": daily["temperature_2m_max"],
        "temp_min": daily["temperature_2m_min"],
        "precip_prob": daily["precipitation_probability_max"],
        "wind_max": daily["wind_speed_10m_max"],
    }


def _format_weather(where: str, w: dict) -> str:
    """把当前天气 dict 格式化成可读文本（get_weather 工具与当前天气资源共用）。"""
    code = w.get("weathercode", -1)
    desc = WEATHER_CODE_MAP.get(code, f"未知({code})")
    return (
        f"{where} 当前天气：{desc}\n"
        f"温度：{w['temperature']}°C（体感 {w['apparent_temperature']}°C）\n"
        f"风速：{w['windspeed']} km/h，风向：{w['winddirection']}°\n"
        f"观测时间：{w['time']}"
    )


def _format_forecast(where: str, fc: dict, days: int) -> str:
    """把逐日预报 dict 格式化成可读文本（forecast 工具与预报资源共用）。"""
    lines = [f"{where} 未来 {days} 天天气预报："]
    for i, day in enumerate(fc["time"]):
        code = fc["weather_code"][i]
        desc = WEATHER_CODE_MAP.get(code, f"未知({code})")
        lines.append(
            f"  {day}：{desc}，{fc['temp_min'][i]}~{fc['temp_max'][i]}°C，"
            f"降水概率 {fc['precip_prob'][i]}%，最大风速 {fc['wind_max'][i]} km/h"
        )
    return "\n".join(lines)


@mcp.tool()
def get_weather(city: str = "") -> str:
    """查询天气。参数 city 传城市名（如"上海"、"London"）；不传则使用当前 IP 所在位置的天气。"""
    if city.strip():
        loc = _geocode(city.strip())
        lat, lon = loc["lat"], loc["lon"]
        where = f"{loc['name']}（{loc['country']}）"
    else:
        pos = _get_ip_location()
        lat, lon = pos["lat"], pos["lon"]
        where = f"{pos['city']} · {pos['region']}"
    w = _fetch_weather(lat, lon)
    return _format_weather(where, w)


@mcp.tool()
def get_weather_forecast(city: str = "", days: int = 7) -> str:
    """查询未来多天天气预报。city 传城市名（如"上海"）；不传则使用当前 IP 所在位置。days 为查询天数（1-16）。"""
    if city.strip():
        loc = _geocode(city.strip())
        lat, lon = loc["lat"], loc["lon"]
        where = f"{loc['name']}（{loc['country']}）"
    else:
        pos = _get_ip_location()
        lat, lon = pos["lat"], pos["lon"]
        where = f"{pos['city']} · {pos['region']}"
    days = max(1, min(int(days), 16))
    fc = _fetch_forecast(lat, lon, days)
    return _format_forecast(where, fc, days)


# ================================================================
# Resources（资源）—— 客户端通过 resources/list + resources/read 读取
# 静态资源：固定 URI，返回静态数据
# 模板资源：URI 含 {参数}，参数绑定到函数同名形参
# ================================================================

@mcp.resource(
    "weather://cities",
    name="常用城市列表",
    title="常用城市列表",
    description="内置精选常用城市及其经纬度/时区，客户端可直接读取，无需调用工具",
    mime_type="application/json",
)
def cities_resource() -> str:
    """静态资源：常用城市列表（JSON）。"""
    return json.dumps(COMMON_CITIES, ensure_ascii=False, indent=2)


@mcp.resource(
    "weather://wmo-codes",
    name="WMO 天气代码对照表",
    title="WMO 天气代码对照表",
    description="WMO 天气代码 → 中文描述对照表，工具返回 weathercode 后可读取本表理解含义",
    mime_type="application/json",
)
def wmo_codes_resource() -> str:
    """静态资源：WMO 天气代码对照表（JSON，即 WEATHER_CODE_MAP）。"""
    return json.dumps(WEATHER_CODE_MAP, ensure_ascii=False, indent=2)


@mcp.resource(
    "weather://server-info",
    name="Server 能力说明",
    title="Server 能力说明",
    description="Server 能力、数据源与使用注意事项，客户端可嵌入系统上下文",
    mime_type="text/plain",
)
def server_info_resource() -> str:
    """静态资源：Server 能力说明文档。"""
    return (
        "MCP Weather Demo Server（weather-location-demo）能力说明\n"
        "----------------------------------------\n"
        "工具（Tools，由 LLM 自动调用执行动作）：\n"
        "  - get_current_location：基于出口 IP 定位当前位置\n"
        "  - get_weather(city?)：当前或指定城市实时天气\n"
        "  - get_weather_forecast(city?, days?)：未来多天天气预报（1-16 天）\n"
        "资源（Resources，由客户端直接读取）：\n"
        "  - weather://cities：内置常用城市列表\n"
        "  - weather://wmo-codes：WMO 天气代码对照表\n"
        "  - weather://server-info：本说明\n"
        "  - weather://{city}/current：指定城市当前天气\n"
        "  - weather://{city}/forecast：指定城市未来 7 天预报\n"
        "提示词（Prompts，由客户端拉取模板）：\n"
        "  - weather-assistant：天气问答引导\n"
        "  - travel-weather-plan(city, days)：出行天气规划\n"
        "  - weather-briefing(city?)：每日天气简报\n"
        "数据源（全部免费、无需 API key）：\n"
        "  - 定位：ipwho.is（主）、ipinfo.io（备）\n"
        "  - 地理编码：Open-Meteo Geocoding\n"
        "  - 天气：Open-Meteo Forecast API\n"
        "注意事项：IP 定位返回出口 IP 所在城市，可能不等于物理位置；免费接口有限频，请控制调用频率。"
    )


@mcp.resource(
    "weather://{city}/current",
    name="城市当前天气",
    title="城市当前天气",
    description="模板资源：读取指定城市当前天气（天气/温度/体感/风速/风向）",
    mime_type="text/plain",
)
def city_current_resource(city: str) -> str:
    """模板资源：weather://{city}/current —— URI 中的 {city} 绑定到函数参数 city。"""
    loc = _geocode(city)
    w = _fetch_weather(loc["lat"], loc["lon"])
    return _format_weather(f"{loc['name']}（{loc['country']}）", w)


@mcp.resource(
    "weather://{city}/forecast",
    name="城市未来天气预报",
    title="城市未来天气预报",
    description="模板资源：读取指定城市未来 7 天逐日预报（天气/最高最低温/降水概率/最大风速）",
    mime_type="text/plain",
)
def city_forecast_resource(city: str) -> str:
    """模板资源：weather://{city}/forecast —— 读取指定城市未来 7 天逐日预报。"""
    loc = _geocode(city)
    fc = _fetch_forecast(loc["lat"], loc["lon"], days=7)
    return _format_forecast(f"{loc['name']}（{loc['country']}）", fc, days=7)


# ================================================================
# Prompts（提示词模板）—— 客户端通过 prompts/list + prompts/get 拉取
# 函数参数会成为 Prompt 的 inputSchema（参数型模板）；返回 messages 列表。
# 注意：MCP 规范中 Prompt 消息只支持 user / assistant 两种角色（无 system），
#       因此"引导规则"放在 user 消息里，由客户端拉取后作为对话起点注入。
# ================================================================

@mcp.prompt(
    name="weather-assistant",
    title="天气问答助手",
    description="引导 LLM 如何回答天气问题：未指定城市先定位、指定城市直接查、多天预报用 forecast、禁止编造数据",
)
def weather_assistant_prompt() -> list:
    """提示词模板：天气问答引导（无参数）。"""
    return [{
        "role": "user",
        "content": (
            "【天气问答助手 · 引导规则】\n"
            "你是一个生活助手，可以调用工具获取实时天气信息。规则：\n"
            "1. 若用户指定了城市（如\"上海\"），直接调用 get_weather(city=城市名) 查询；\n"
            "2. 若用户未指定城市，先调用 get_current_location 获取当前位置，再把城市名作为参数调用 get_weather；\n"
            "3. 若用户需要未来多天天气预报，调用 get_weather_forecast(city, days)；\n"
            "4. 不要编造数据，一切以工具返回结果为准，最后用自然语言回答用户。\n"
            "请按上述规则回答用户接下来的问题。"
        ),
    }]


@mcp.prompt(
    name="travel-weather-plan",
    title="出行天气规划",
    description="按目标城市与出行天数生成出行天气规划提示词（参数：city 必填，days 可选默认 3）",
)
def travel_weather_plan_prompt(city: str, days: int = 3) -> list:
    """提示词模板：出行天气规划（参数型：city 必填、days 可选）。"""
    return [
        {
            "role": "user",
            "content": (
                f"【出行天气规划 · 任务】\n"
                f"我计划去 {city} 出行 {days} 天。你是出行规划助手，所有天气数据必须来自工具返回结果，"
                f"不得编造。请按以下步骤完成：\n"
                f"1. 先用 get_weather_forecast 查询 {city} 未来 {days} 天的天气预报；\n"
                f"2. 结合真实天气数据给出：逐日天气概览（天气/温度/降水概率/风力）；\n"
                f"3. 每天的建议穿搭、是否需要带雨具/防晒；\n"
                f"4. 适合安排的户外活动与注意事项。\n"
                f"最后按日期整理成清晰的出行天气计划。"
            ),
        },
    ]


@mcp.prompt(
    name="weather-briefing",
    title="每日天气简报",
    description="生成指定城市（默认当前位置）的结构化每日天气简报（参数：city 可选）",
)
def weather_briefing_prompt(city: str = "") -> list:
    """提示词模板：每日天气简报（可选参数 city，默认当前位置）。"""
    target = city.strip() or "当前位置"
    return [
        {
            "role": "user",
            "content": (
                f"【每日天气简报 · 任务】\n"
                f"请为 {target} 生成今日天气简报。你是天气简报编辑，数据必须来自工具返回结果，"
                f"输出结构清晰、便于阅读。步骤：\n"
                f"1. 先调用天气工具获取实时数据（未指定城市时先调用 get_current_location 定位）；\n"
                f"2. 按以下结构输出：\n"
                f"   【天气概况】天气现象\n"
                f"   【温度】气温与体感温度\n"
                f"   【风力】风速与风向\n"
                f"   【生活建议】穿衣 / 出行 / 防晒等建议"
            ),
        },
    ]


def main() -> None:
    # MCPServer 默认以 stdio 方式运行，等待客户端连接
    mcp.run()


if __name__ == "__main__":
    main()
