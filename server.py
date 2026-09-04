"""
MCP Demo Server —— 演示「查询当前位置 / 查询天气」

- 传输方式：stdio（MCP 默认），由 MCP 客户端（Inspector / Claude Desktop / Cursor / 自写 client）拉起本进程并通过 JSON-RPC 调用工具。
- 数据源：全部使用免费、无需 API key 的公开接口
    · 当前位置：https://ipwho.is/（主），https://ipinfo.io/json（备）—— 基于出口 IP 定位
    · 城市地理编码：Open-Meteo Geocoding
    · 天气：Open-Meteo Forecast API

用法：
    python server.py            # 以 stdio 方式运行，等待客户端连接
    npx @modelcontextprotocol/inspector python server.py   # 或通过 Inspector 图形化调试
"""

from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("weather-location-demo")

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
    code = w.get("weathercode", -1)
    desc = WEATHER_CODE_MAP.get(code, f"未知({code})")
    return (
        f"{where} 当前天气：{desc}\n"
        f"温度：{w['temperature']}°C（体感 {w['apparent_temperature']}°C）\n"
        f"风速：{w['windspeed']} km/h，风向：{w['winddirection']}°\n"
        f"观测时间：{w['time']}"
    )


def main() -> None:
    # FastMCP 默认以 stdio 方式运行，等待客户端连接
    mcp.run()


if __name__ == "__main__":
    main()
