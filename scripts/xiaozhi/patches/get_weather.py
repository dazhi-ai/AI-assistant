import requests
from bs4 import BeautifulSoup
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.utils.util import get_ip_info
from typing import TYPE_CHECKING
from urllib.parse import urlencode
import re

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

GET_WEATHER_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "获取某个地点的天气、未来7天天气概况，以及未来24小时内可能下雨的大致时间。"
            "如果用户问今天会不会下雨、几点下雨、晚上会不会下雨、明早会不会下雨、"
            "下午三点到六点会不会下雨，也调用这个函数。"
            "用户应提供一个位置，比如用户说杭州天气，参数为：杭州。"
            "如果用户没有指明地点，说“天气怎么样”“今天天气如何”，location 参数为空。"
            "如果用户问的是具体时间段，请把原始时间诉求放进 time_query。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "地点名，例如杭州。可选参数，如果不提供则不传",
                },
                "lang": {
                    "type": "string",
                    "description": "返回用户使用的语言 code，例如 zh_CN/zh_HK/en_US/ja_JP 等，默认 zh_CN",
                },
                "time_query": {
                    "type": "string",
                    "description": "用户关注的具体时间描述，例如 今晚、明早、下午三点到六点、明天早上八点。",
                },
            },
            "required": ["lang"],
        },
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
    )
}

# 天气代码 https://dev.qweather.com/docs/resource/icons/#weather-icons
WEATHER_CODE_MAP = {
    "100": "晴",
    "101": "多云",
    "102": "少云",
    "103": "晴间多云",
    "104": "阴",
    "150": "晴",
    "151": "多云",
    "152": "少云",
    "153": "晴间多云",
    "300": "阵雨",
    "301": "强阵雨",
    "302": "雷阵雨",
    "303": "强雷阵雨",
    "304": "雷阵雨伴有冰雹",
    "305": "小雨",
    "306": "中雨",
    "307": "大雨",
    "308": "极端降雨",
    "309": "毛毛雨/细雨",
    "310": "暴雨",
    "311": "大暴雨",
    "312": "特大暴雨",
    "313": "冻雨",
    "314": "小到中雨",
    "315": "中到大雨",
    "316": "大到暴雨",
    "317": "暴雨到大暴雨",
    "318": "大暴雨到特大暴雨",
    "350": "阵雨",
    "351": "强阵雨",
    "399": "雨",
    "400": "小雪",
    "401": "中雪",
    "402": "大雪",
    "403": "暴雪",
    "404": "雨夹雪",
    "405": "雨雪天气",
    "406": "阵雨夹雪",
    "407": "阵雪",
    "408": "小到中雪",
    "409": "中到大雪",
    "410": "大到暴雪",
    "456": "阵雨夹雪",
    "457": "阵雪",
    "499": "雪",
    "500": "薄雾",
    "501": "雾",
    "502": "霾",
    "503": "扬沙",
    "504": "浮尘",
    "507": "沙尘暴",
    "508": "强沙尘暴",
    "509": "浓雾",
    "510": "强浓雾",
    "511": "中度霾",
    "512": "重度霾",
    "513": "严重霾",
    "514": "大雾",
    "515": "特强浓雾",
    "900": "热",
    "901": "冷",
    "999": "未知",
}


def _normalize_api_host(api_host: str) -> str:
    host = (api_host or "").strip().rstrip("/")
    if not host:
        return ""
    if host.startswith("http://") or host.startswith("https://"):
        return host
    return f"https://{host}"


def _build_api_url(api_host: str, path: str, query: dict, api_key: str):
    base = _normalize_api_host(api_host)
    use_header_auth = bool(base)
    headers = dict(HEADERS)
    actual_query = dict(query)
    if use_header_auth:
        headers["X-QW-Api-Key"] = api_key
        url = f"{base}{path}?{urlencode(actual_query)}"
    else:
        actual_query["key"] = api_key
        public_base = "https://geoapi.qweather.com" if path.startswith("/geo/") else "https://devapi.qweather.com"
        url = f"{public_base}{path}?{urlencode(actual_query)}"
    return url, headers


def _request_json(url: str, headers: dict):
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def fetch_city_info(location, api_key, api_host):
    url, headers = _build_api_url(
        api_host,
        "/geo/v2/city/lookup",
        {"location": location, "lang": "zh"},
        api_key,
    )
    response = _request_json(url, headers)
    if response.get("code") not in (None, "200", 200):
        logger.bind(tag=TAG).error(f"获取天气失败，原因：{response.get('code')}")
        return None
    return response.get("location", [])[0] if response.get("location") else None


def fetch_hourly_weather(location_id, api_key, api_host):
    url, headers = _build_api_url(
        api_host,
        "/v7/weather/24h",
        {"location": location_id},
        api_key,
    )
    response = _request_json(url, headers)
    if response.get("code") not in (None, "200", 200):
        logger.bind(tag=TAG).error(f"获取逐小时天气失败，原因：{response.get('code')}")
        return []
    return response.get("hourly", []) or []


def fetch_weather_page(url):
    response = requests.get(url, headers=HEADERS, timeout=15)
    return BeautifulSoup(response.text, "html.parser") if response.ok else None


def parse_weather_info(soup):
    city_name = soup.select_one("h1.c-submenu__location").get_text(strip=True)

    current_abstract = soup.select_one(".c-city-weather-current .current-abstract")
    current_abstract = (
        current_abstract.get_text(strip=True) if current_abstract else "未知"
    )

    current_basic = {}
    for item in soup.select(
        ".c-city-weather-current .current-basic .current-basic___item"
    ):
        parts = item.get_text(strip=True, separator=" ").split(" ")
        if len(parts) == 2:
            key, value = parts[1], parts[0]
            current_basic[key] = value

    temps_list = []
    for row in soup.select(".city-forecast-tabs__row")[:7]:
        date = row.select_one(".date-bg .date").get_text(strip=True)
        weather_code = (
            row.select_one(".date-bg .icon")["src"].split("/")[-1].split(".")[0]
        )
        weather = WEATHER_CODE_MAP.get(weather_code, "未知")
        temps = [span.get_text(strip=True) for span in row.select(".tmp-cont .temp")]
        high_temp, low_temp = (temps[0], temps[-1]) if len(temps) >= 2 else (None, None)
        temps_list.append((date, weather, high_temp, low_temp))

    return city_name, current_abstract, current_basic, temps_list


def _format_hour_label(fx_time: str) -> str:
    if not fx_time:
        return "未知时间"
    parts = fx_time.split("T", 1)
    if len(parts) != 2:
        return fx_time
    date_part = parts[0]
    time_part = parts[1][:5]
    day = date_part[-2:]
    return f"{day}日{time_part}"


def _is_rainy_hour(item: dict) -> bool:
    text = str(item.get("text", "") or "")
    precip = str(item.get("precip", "") or "0").strip()
    pop = str(item.get("pop", "") or "0").strip()
    try:
        precip_value = float(precip)
    except ValueError:
        precip_value = 0.0
    try:
        pop_value = int(float(pop))
    except ValueError:
        pop_value = 0
    return ("雨" in text) or precip_value > 0 or pop_value >= 30


def _build_rain_summary(hourly_list: list[dict]) -> str:
    if not hourly_list:
        return "未来24小时暂无逐小时天气数据。"

    rainy_hours = [item for item in hourly_list if _is_rainy_hour(item)]
    if not rainy_hours:
        return "未来24小时暂无明显降雨。"

    first_rain = rainy_hours[0]
    first_label = _format_hour_label(first_rain.get("fxTime", ""))

    ranges = []
    current_range = [rainy_hours[0]]
    for item in rainy_hours[1:]:
        prev = current_range[-1].get("fxTime", "")
        curr = item.get("fxTime", "")
        prev_hour = prev[11:13] if len(prev) >= 13 else ""
        curr_hour = curr[11:13] if len(curr) >= 13 else ""
        prev_day = prev[:10]
        curr_day = curr[:10]
        is_continuous = prev_day == curr_day and prev_hour.isdigit() and curr_hour.isdigit() and int(curr_hour) - int(prev_hour) == 1
        if is_continuous:
            current_range.append(item)
        else:
            ranges.append(current_range)
            current_range = [item]
    ranges.append(current_range)

    range_texts = []
    for hour_range in ranges[:3]:
        start_text = _format_hour_label(hour_range[0].get("fxTime", ""))
        end_text = _format_hour_label(hour_range[-1].get("fxTime", ""))
        if start_text == end_text:
            range_texts.append(start_text)
        else:
            range_texts.append(f"{start_text} 到 {end_text}")

    return (
        f"未来24小时最早可能在 {first_label} 开始下雨。"
        f" 预计降雨时段：{'；'.join(range_texts)}。"
    )


def _build_hourly_brief(hourly_list: list[dict]) -> str:
    if not hourly_list:
        return ""
    useful = []
    for item in hourly_list[:8]:
        label = _format_hour_label(item.get("fxTime", ""))
        text = item.get("text", "未知")
        temp = item.get("temp", "")
        pop = item.get("pop", "")
        if pop not in ("", None):
            useful.append(f"{label} {text} {temp}°C，降水概率{pop}%")
        else:
            useful.append(f"{label} {text} {temp}°C")
    return "未来几小时：\n" + "\n".join(f"  · {line}" for line in useful)


def _get_hour_and_date(item: dict):
    fx_time = str(item.get("fxTime", "") or "")
    date_part = fx_time[:10]
    hour_text = fx_time[11:13] if len(fx_time) >= 13 else ""
    try:
        hour_value = int(hour_text)
    except ValueError:
        hour_value = -1
    return date_part, hour_value


def _filter_time_window(hourly_list: list[dict], target_date: str | None, start_hour: int, end_hour: int):
    result = []
    for item in hourly_list:
        item_date, item_hour = _get_hour_and_date(item)
        if item_hour < 0:
            continue
        if target_date and item_date != target_date:
            continue
        if start_hour <= item_hour <= end_hour:
            result.append(item)
    return result


def _format_hour_only(item: dict) -> str:
    fx_time = str(item.get("fxTime", "") or "")
    return fx_time[11:16] if len(fx_time) >= 16 else _format_hour_label(fx_time)


def _analyze_target_window(hourly_list: list[dict], time_query: str) -> str:
    if not hourly_list or not time_query:
        return ""

    query = str(time_query).strip()
    if not query:
        return ""

    first_date = hourly_list[0].get("fxTime", "")[:10] if hourly_list else ""
    second_date = ""
    for item in hourly_list:
        item_date, _ = _get_hour_and_date(item)
        if item_date and item_date != first_date:
            second_date = item_date
            break

    target_date = first_date
    if "明" in query and second_date:
        target_date = second_date

    windows = [
        ("今晚", 18, 23),
        ("今天晚上", 18, 23),
        ("今夜", 18, 23),
        ("明晚", 18, 23),
        ("明天晚上", 18, 23),
        ("明早", 5, 11),
        ("明晨", 5, 11),
        ("明天早上", 5, 11),
        ("明天上午", 6, 11),
        ("今天早上", 5, 11),
        ("早上", 5, 11),
        ("上午", 6, 11),
        ("中午", 11, 13),
        ("下午", 12, 17),
        ("傍晚", 17, 19),
        ("晚上", 18, 23),
        ("凌晨", 0, 5),
    ]

    match = re.search(r"(\d{1,2})\s*点\s*(?:到|至|\-|~)\s*(\d{1,2})\s*点", query)
    if match:
        start_hour = int(match.group(1))
        end_hour = int(match.group(2))
        if end_hour < start_hour:
            end_hour = start_hour
        focus_hours = _filter_time_window(hourly_list, target_date, start_hour, end_hour)
        label = f"{query}这段时间"
    else:
        single_match = re.search(r"(\d{1,2})\s*点", query)
        focus_hours = []
        label = query
        if single_match:
            hour_value = int(single_match.group(1))
            focus_hours = _filter_time_window(hourly_list, target_date, hour_value, hour_value)
            label = f"{hour_value}点左右"
        else:
            for text, start_hour, end_hour in windows:
                if text in query:
                    if text.startswith("明") and second_date:
                        target_date = second_date
                    focus_hours = _filter_time_window(hourly_list, target_date, start_hour, end_hour)
                    label = text
                    break

    if not focus_hours:
        return ""

    rainy_hours = [item for item in focus_hours if _is_rainy_hour(item)]
    if rainy_hours:
        rain_labels = [_format_hour_only(item) for item in rainy_hours[:5]]
        rain_desc = "、".join(rain_labels)
        first_text = rainy_hours[0].get("text", "有雨")
        return f"关于“{query}”：{label}有下雨可能，重点时段在 {rain_desc}，天气以{first_text}为主。"

    max_pop = -1
    max_item = None
    for item in focus_hours:
        pop_text = str(item.get("pop", "") or "0").strip()
        try:
            pop_value = int(float(pop_text))
        except ValueError:
            pop_value = 0
        if pop_value > max_pop:
            max_pop = pop_value
            max_item = item

    if max_item is not None:
        return (
            f"关于“{query}”：{label}暂无明显降雨，"
            f"最高降水概率大约在 {_format_hour_only(max_item)}，约 {max_pop}% 。"
        )
    return f"关于“{query}”：{label}暂无明显降雨。"


@register_function("get_weather", GET_WEATHER_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def get_weather(
    conn: "ConnectionHandler",
    location: str = None,
    lang: str = "zh_CN",
    time_query: str = "",
):
    from core.utils.cache.manager import cache_manager, CacheType

    weather_config = conn.config.get("plugins", {}).get("get_weather", {})
    api_host = weather_config.get("api_host", "")
    api_key = weather_config.get("api_key", "")
    default_location = weather_config.get("default_location", "广州")
    client_ip = conn.client_ip

    if not api_key:
        return ActionResponse(
            Action.REQLLM,
            "天气服务还没有配置好，请联系管理员补充天气接口配置。",
            None,
        )

    if not location:
        if client_ip:
            cached_ip_info = cache_manager.get(CacheType.IP_INFO, client_ip)
            if cached_ip_info:
                location = cached_ip_info.get("city")
            else:
                ip_info = get_ip_info(client_ip, logger)
                if ip_info:
                    cache_manager.set(CacheType.IP_INFO, client_ip, ip_info)
                    location = ip_info.get("city")
            if not location:
                location = default_location
        else:
            location = default_location

    weather_cache_key = f"full_weather_{location}_{lang}_{time_query}"
    cached_weather_report = cache_manager.get(CacheType.WEATHER, weather_cache_key)
    if cached_weather_report:
        return ActionResponse(Action.REQLLM, cached_weather_report, None)

    city_info = fetch_city_info(location, api_key, api_host)
    if not city_info:
        return ActionResponse(
            Action.REQLLM, f"未找到相关的城市: {location}，请确认地点是否正确", None
        )

    soup = fetch_weather_page(city_info.get("fxLink", ""))
    hourly_list = fetch_hourly_weather(city_info.get("id", ""), api_key, api_host)

    weather_report = ""
    if soup:
        city_name, current_abstract, current_basic, temps_list = parse_weather_info(soup)
        weather_report = f"您查询的位置是：{city_name}\n\n当前天气: {current_abstract}\n"

        if current_basic:
            weather_report += "详细参数：\n"
            for key, value in current_basic.items():
                if value != "0":
                    weather_report += f"  · {key}: {value}\n"

        weather_report += "\n未来7天预报：\n"
        for date, weather, high, low in temps_list:
            weather_report += f"{date}: {weather}，气温 {low}~{high}\n"
    else:
        city_name = city_info.get("name", location)
        weather_report = f"您查询的位置是：{city_name}\n"

    weather_report += "\n未来24小时降雨提示：\n"
    weather_report += _build_rain_summary(hourly_list) + "\n"

    target_summary = _analyze_target_window(hourly_list, time_query)
    if target_summary:
        weather_report += "\n重点时段判断：\n"
        weather_report += target_summary + "\n"

    hourly_brief = _build_hourly_brief(hourly_list)
    if hourly_brief:
        weather_report += "\n" + hourly_brief + "\n"

    weather_report += "\n（如需更具体的下雨时间，可以直接问我：今晚会不会下雨、明早会不会下雨、下午三点到六点会不会下雨。）"

    cache_manager.set(CacheType.WEATHER, weather_cache_key, weather_report)
    return ActionResponse(Action.REQLLM, weather_report, None)
