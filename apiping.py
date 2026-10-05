#!/usr/bin/env python3
"""apiping: health-check any OpenAI-compatible endpoint in one command.

Usage:
    python -m apiping https://api.openai.com/v1
    python -m apiping --base-url http://localhost:11434/v1 --json
    python -m apiping http://localhost:11434/v1 --watch 60

Health definition (honest): an endpoint counts as healthy only if a real
/chat/completions ping succeeds. A 200 on /models alone proves nothing
about chat serving -- that is why we always ping chat too.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

VERSION = "0.1.0"
DEFAULT_TIMEOUT = 15
PING_MODEL_FALLBACK = "gpt-4o-mini"


def _friendly_error(e):
    """Turn a urllib exception into a short Chinese message (no key material)."""
    if isinstance(e, urllib.error.URLError):
        reason = e.reason
        if isinstance(reason, ConnectionRefusedError):
            return "连接被拒绝（目标端口未监听）"
        r = str(reason)
        if isinstance(reason, TimeoutError) or "timed out" in r:
            return "连接超时"
        if "Name or service not known" in r or "nodename nor servname" in r:
            return "DNS 解析失败"
        return "网络错误：%s" % r
    if isinstance(e, TimeoutError):
        return "连接超时"
    name = type(e).__name__
    return "%s：%s" % (name, e) if str(e) else name


def _req(url, method="GET", payload=None, headers=None, timeout=DEFAULT_TIMEOUT):
    """Return (status|None, body|None, elapsed_ms, error_str|None)."""
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            elapsed = (time.monotonic() - t0) * 1000
            try:
                parsed = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                parsed = {"_raw": raw[:500]}
            return resp.status, parsed, elapsed, None
    except urllib.error.HTTPError as e:
        elapsed = (time.monotonic() - t0) * 1000
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body, elapsed, None
    except Exception as e:  # URLError, timeout, refused, ...
        elapsed = (time.monotonic() - t0) * 1000
        return None, None, elapsed, _friendly_error(e)


def check(base_url, api_key=None, timeout=DEFAULT_TIMEOUT, model=None):
    """Run the two-probe health check. Returns a plain-dict result."""
    base = base_url.rstrip("/")
    result = {
        "base_url": base,
        "reachable": False,
        "models": {"status": "unknown", "count": 0, "ids": [], "note": ""},
        "chat": {"status": "unknown", "latency_ms": None, "model": None, "note": ""},
        "healthy": False,
        "error": "",
    }
    headers = {}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key

    # Probe 1: GET /models
    status, body, _elapsed, err = _req(base + "/models", headers=headers, timeout=timeout)
    if err:
        result["error"] = "无法连接：" + err
        return result
    result["reachable"] = True
    if status == 200 and isinstance(body, dict):
        ids = [m.get("id") for m in body.get("data", [])
               if isinstance(m, dict) and m.get("id")]
        result["models"] = {"status": "ok", "count": len(ids), "ids": ids[:20], "note": ""}
    elif status == 401:
        note = ("key 无效或无权限（401）" if api_key
                else "需要 key（未提供 OPENAI_API_KEY），不是服务故障")
        result["models"] = {"status": "unauthorized", "count": 0, "ids": [], "note": note}
    else:
        result["models"] = {"status": "error", "count": 0, "ids": [],
                            "note": "HTTP %s：%s" % (status, str(body)[:200])}

    # Probe 2: POST /chat/completions with a 1-token ping
    ping_model = model or (result["models"]["ids"][0]
                           if result["models"]["ids"] else PING_MODEL_FALLBACK)
    payload = {"model": ping_model,
               "messages": [{"role": "user", "content": "ping"}],
               "max_tokens": 1}
    status, body, elapsed, err = _req(base + "/chat/completions", method="POST",
                                     payload=payload, headers=headers, timeout=timeout)
    if err:
        result["chat"] = {"status": "error", "latency_ms": round(elapsed, 1),
                          "model": ping_model, "note": "网络错误：" + err}
    elif status == 200:
        result["chat"] = {"status": "ok", "latency_ms": round(elapsed, 1),
                          "model": ping_model, "note": ""}
    elif status == 401:
        note = ("key 无效（401）" if api_key
                else "需要 key 才能调用 chat（未提供 OPENAI_API_KEY）")
        result["chat"] = {"status": "unauthorized", "latency_ms": round(elapsed, 1),
                          "model": ping_model, "note": note}
    else:
        result["chat"] = {"status": "error", "latency_ms": round(elapsed, 1),
                          "model": ping_model,
                          "note": "HTTP %s：%s" % (status, str(body)[:200])}

    result["healthy"] = result["reachable"] and result["chat"]["status"] == "ok"
    return result


def print_card(r):
    print("===== 端点健康检查 =====")
    print("地址：%s" % r["base_url"])
    print("连通：%s" % ("✅ 可达" if r["reachable"] else "❌ 不可达"))
    m = r["models"]
    if m["status"] == "ok":
        extra = "（%s）" % "、".join(m["ids"][:5]) if m["ids"] else ""
        print("模型列表：✅ %d 个模型%s" % (m["count"], extra))
    elif m["status"] == "unauthorized":
        print("模型列表：🔑 %s" % m["note"])
    else:
        print("模型列表：❌ %s" % (m["note"] or m["status"]))
    c = r["chat"]
    if c["status"] == "ok":
        print("对话接口：✅ 正常（模型 %s，延迟 %.0f ms）" % (c["model"], c["latency_ms"]))
    elif c["status"] == "unauthorized":
        print("对话接口：🔑 %s" % c["note"])
    else:
        print("对话接口：❌ %s" % (c["note"] or c["status"]))
    if r["error"]:
        print("错误：%s" % r["error"])
    print("结论：%s" % ("✅ 健康" if r["healthy"] else "❌ 不健康"))


def watch_line(r):
    ts = time.strftime("%H:%M:%S")
    if not r["reachable"]:
        return "[%s] 不可达：%s" % (ts, r["error"])
    lat = r["chat"]["latency_ms"]
    lat_s = ("%.0fms" % lat) if lat is not None else "-"
    return "[%s] chat=%s 延迟=%s 模型数=%s" % (ts, r["chat"]["status"], lat_s,
                                              r["models"]["count"])


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="apiping",
        description="检查 OpenAI-compatible 端点的健康状态（/models + /chat/completions 双探针）")
    ap.add_argument("base_url", nargs="?", default=None,
                    help="端点 base URL，如 https://api.openai.com/v1")
    ap.add_argument("--base-url", dest="base_url_opt", default=None, help="同位置参数")
    ap.add_argument("--model", default=None, help="ping 用的模型（默认取 /models 返回的第一个）")
    ap.add_argument("--api-key", default=None, help="API key（默认读环境变量 OPENAI_API_KEY）")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="单次请求超时秒数")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--watch", type=float, default=0, metavar="秒",
                    help="每 N 秒重复检查一次（Ctrl-C 停止）")
    ap.add_argument("--version", action="version", version="apiping " + VERSION)
    args = ap.parse_args(argv)

    base_url = args.base_url_opt or args.base_url
    if not base_url:
        ap.error("需要指定端点地址（位置参数或 --base-url）")
    if not re.match(r"^https?://", base_url):
        sys.stderr.write("error: 地址必须以 http:// 或 https:// 开头\n")
        return 2
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")

    if args.watch and args.watch > 0:
        try:
            while True:
                r = check(base_url, api_key, args.timeout, args.model)
                if args.json:
                    print(json.dumps({"time": time.strftime("%H:%M:%S"), **r},
                                     ensure_ascii=False), flush=True)
                else:
                    print(watch_line(r), flush=True)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n已停止。")
            return 0

    r = check(base_url, api_key, args.timeout, args.model)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_card(r)
    return 0 if r["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
