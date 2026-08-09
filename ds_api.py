# -*- coding: utf-8 -*-
"""DeepSeek 开放平台用量查询 API 封装
接口来源: platform.deepseek.com 网页端内部接口 (非官方公开 API, 随时可能变动)
"""
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "https://platform.deepseek.com"
DAY = 86400
TZ = 28800  # GMT+8 秒偏移

TOKEN_FILE = Path(__file__).parent / "config.json"


class ApiError(Exception):
    pass


def _headers(token: str) -> dict:
    return {
        "accept": "application/json",
        "Authorization": "Bearer " + token,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": BASE + "/usage",
        "Origin": BASE,
    }


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers=_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise ApiError(f"HTTP {e.code}: {body[:200]}")
    except Exception as e:
        raise ApiError(f"网络错误: {e}")


def load_token() -> str:
    """从 config.json 读取 token"""
    if not TOKEN_FILE.exists():
        return ""
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("token", "")
    except Exception:
        return ""


def save_token(token: str, user_id: str = "") -> None:
    cfg = {"token": token.strip(), "user_id": user_id, "saved_at": int(time.time())}
    TOKEN_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _chrome_leveldb_dirs() -> list:
    """定位 Chrome 各 profile 的 Local Storage leveldb 目录"""
    import os
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, r"AppData\Local\Google\Chrome\User Data"),
        os.path.join(home, r"AppData\Local\Google\Chrome Beta\User Data"),
    ]
    dirs = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            p = os.path.join(root, name, "Local Storage", "leveldb")
            if os.path.isdir(p):
                dirs.append(p)
    return dirs


def extract_token_from_chrome() -> list:
    """从 Chrome leveldb 扫描 DeepSeek userToken (localStorage 落盘明文)
    特征: value 为 JSON {"value":"<64位base64>","__version":"0"}, 压缩残留 @token" 模式
    返回候选 token 列表(去重, 按 文件mtime 新->旧)"""
    import glob
    import os
    import re
    pat = re.compile(rb"@([A-Za-z0-9+/]{60,64}={0,2})\"")
    seen, found = set(), []
    for d in _chrome_leveldb_dirs():
        files = glob.glob(os.path.join(d, "*.ldb")) + glob.glob(os.path.join(d, "*.log"))
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        for f in files:
            try:
                data = open(f, "rb").read()
            except OSError:
                continue
            for m in pat.finditer(data):
                tok = m.group(1).decode()
                if tok not in seen:
                    seen.add(tok)
                    found.append(tok)
    return found


def get_valid_token() -> str:
    """优先用 config 内 token; 若失效自动从 Chrome 扫描新 token 并保存"""
    tok = load_token()
    if tok:
        try:
            get_summary(tok)
            return tok
        except ApiError:
            pass  # 失效, 尝试自动获取
    for cand in extract_token_from_chrome():
        try:
            get_summary(cand)
            save_token(cand)
            return cand
        except ApiError:
            continue
    return load_token()  # 都失败则返回原值, 由调用方提示


def _day_range(days: int = 30) -> tuple:
    """返回 [start, end) 天对齐时间戳, end 为 GMT+8 今天零点"""
    now = int(time.time())
    end = (now + TZ) // DAY * DAY - TZ
    start = end - days * DAY
    return start, end


def _today_range() -> tuple:
    """返回今天 [start, end): GMT+8 今天零点 -> 明天零点"""
    now = int(time.time())
    start = (now + TZ) // DAY * DAY - TZ
    return start, start + DAY


def get_summary(token: str) -> dict:
    """账户摘要: 余额 / 累计消费"""
    j = _get(f"{BASE}/api/v0/users/get_user_summary", token)
    if j.get("code") != 0:
        raise ApiError(f"获取账户摘要失败: {j.get('msg')}")
    biz = j["data"]["biz_data"]
    balance = 0.0
    for w in biz.get("normal_wallets", []):
        balance += float(w.get("balance", 0))
    for w in biz.get("bonus_wallets", []):
        balance += float(w.get("balance", 0))
    total_cost = sum(float(c.get("amount", 0)) for c in biz.get("total_costs", []))
    return {"balance": balance, "total_cost": total_cost}


def get_usage(token: str, days: int = 30, start: int = None, end: int = None) -> dict:
    """用量汇总: 按 (API key, model) 汇总, 含消费/请求数/各 token 量
    days: 近 N 天; 或显式传 start/end(天对齐时间戳)"""
    if start is None or end is None:
        start, end = _day_range(days)
    cost_j = _get(f"{BASE}/api/v0/usage/by_api_key/cost?start={start}&end={end}&tz={TZ}", token)
    amount_j = _get(f"{BASE}/api/v0/usage/by_api_key/amount?start={start}&end={end}&tz={TZ}", token)
    if cost_j.get("code") != 0 or amount_j.get("code") != 0:
        raise ApiError("获取用量失败: " + cost_j.get("msg") or amount_j.get("msg") or "未知错误")

    cost_biz = cost_j["data"]["biz_data"]
    amount_biz = amount_j["data"]["biz_data"]

    # cost: data[] -> currency -> series[] -> {api_key, model, buckets[{time, cost}]}
    # amount: series[] -> {api_key, model, buckets[{time, usage{REQUEST, RESPONSE_TOKEN, PROMPT_CACHE_HIT_TOKEN, PROMPT_CACHE_MISS_TOKEN}}]}
    cost_map = {}
    for cur in cost_biz.get("data", []):
        for s in cur.get("series", []):
            key = (s["api_key"]["tracking_id"], s.get("model", ""))
            cost_map[key] = {"name": s["api_key"].get("name", ""),
                             "sensitive_id": s["api_key"].get("sensitive_id", ""),
                             "cost": sum(float(b.get("cost", 0)) for b in s.get("buckets", []))}

    amount_map = {}
    for s in amount_biz.get("series", []):
        key = (s["api_key"]["tracking_id"], s.get("model", ""))
        reqs = 0
        resp_tok = 0
        cache_hit = 0
        cache_miss = 0
        for b in s.get("buckets", []):
            u = b.get("usage", {})
            reqs += int(u.get("REQUEST", 0))
            resp_tok += int(u.get("RESPONSE_TOKEN", 0))
            cache_hit += int(u.get("PROMPT_CACHE_HIT_TOKEN", 0))
            cache_miss += int(u.get("PROMPT_CACHE_MISS_TOKEN", 0))
        amount_map[key] = {"requests": reqs, "response_tokens": resp_tok,
                           "cache_hit_tokens": cache_hit, "cache_miss_tokens": cache_miss}

    rows = []
    all_keys = set(cost_map) | set(amount_map)
    for key in all_keys:
        name, model = cost_map.get(key, {}).get("name") or amount_map.get(key, {}).get("name") or key[0], key[1]
        cost = cost_map.get(key, {}).get("cost", 0.0)
        amt = amount_map.get(key, {})
        total_tokens = amt.get("response_tokens", 0) + amt.get("cache_hit_tokens", 0) + amt.get("cache_miss_tokens", 0)
        rows.append({
            "api_name": name,
            "model": model,
            "cost": cost,
            "requests": amt.get("requests", 0),
            "tokens": total_tokens,
            "cache_hit_tokens": amt.get("cache_hit_tokens", 0),
            "cache_miss_tokens": amt.get("cache_miss_tokens", 0),
            "sensitive_id": cost_map.get(key, {}).get("sensitive_id", ""),
        })
    rows.sort(key=lambda r: -r["cost"])
    total_hit = sum(r["cache_hit_tokens"] for r in rows)
    total_miss = sum(r["cache_miss_tokens"] for r in rows)
    return {"rows": rows,
            "total_cost": sum(r["cost"] for r in rows),
            "total_requests": sum(r["requests"] for r in rows),
            "total_tokens": sum(r["tokens"] for r in rows),
            "total_cache_hit": total_hit,
            "total_cache_miss": total_miss,
            "cache_rate": (total_hit / (total_hit + total_miss)) if (total_hit + total_miss) else None,
            "start": start, "end": end}


if __name__ == "__main__":
    tok = load_token()
    if not tok:
        print("config.json 中没有 token")
    else:
        s = get_summary(tok)
        print("余额:", s["balance"], "累计消费:", s["total_cost"])
        u = get_usage(tok)
        print("近30天 消费:", round(u["total_cost"], 4), "请求:", u["total_requests"], "tokens:", u["total_tokens"])
        for r in u["rows"]:
            print(f"  {r['api_name']} | {r['model']} | ¥{r['cost']:.4f} | {r['requests']}次 | {r['tokens']}tok")
