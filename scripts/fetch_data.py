# -*- coding: utf-8 -*-
"""
抓取「双色球」与「超级大乐透」官方近期开奖数据，归一化后保存到 data/*.json。

数据源（官方优先，失败时自动切换 500.com 备用源，适合 GitHub Actions 等境外网络）：
  双色球 — 中国福利彩票官网公开接口 (www.cwl.gov.cn) / datachart.500.com
  大乐透 — 中国体育彩票官网公开接口 (webapi.sporttery.cn) / datachart.500.com
"""
import datetime
import html as html_lib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

SSQ_API = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
DLT_API = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"

SSL_CTX = ssl.create_default_context()
CN_TZ = datetime.timezone(datetime.timedelta(hours=8))


def http_json(url, referer, retries=4, timeout=30):
    """带重试的 JSON 请求。"""
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer,
        "Connection": "close",
    }
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                text = resp.read().decode("utf-8", "replace")
            return json.loads(text)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError("请求失败: %s (%s)" % (url, last_err))


def _num(value, default=0):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


# ---------------- 备用数据源：500.com（境外网络也可访问） ----------------
ROW_RE = re.compile(r'(?s)<tr class="t_tr1".*?</tr>')
CELL_RE = re.compile(r'(?s)<td[^>]*>(.*?)</td>')
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _cell_text(cell):
    cell = re.sub(r"<!--.*?-->", "", cell, flags=re.S)
    cell = re.sub(r"<[^>]+>", "", cell)
    return html_lib.unescape(cell).replace("\xa0", " ").strip()


def fetch_500_rows(kind, limit=150):
    url = "https://datachart.500.com/%s/history/newinc/history.php?limit=%d" % (kind, limit)
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://datachart.500.com/%s/" % kind,
        "Connection": "close",
    }
    last_err = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
                text = resp.read().decode("gbk", "replace")
            return [m.group(0) for m in ROW_RE.finditer(text)]
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("500.com 请求失败: %s" % last_err)


def fetch_ssq_500(days=150):
    rows = fetch_500_rows("ssq")
    today = datetime.datetime.now(CN_TZ).date()
    start = today - datetime.timedelta(days=days)
    draws = {}
    for row in rows:
        row = re.sub(r"<!--.*?-->", "", row, flags=re.S)
        cells = [_cell_text(x) for x in CELL_RE.findall(row)]
        if len(cells) < 16:
            continue
        raw_issue, date = cells[0], cells[15]
        if not raw_issue.isdigit() or not DATE_RE.match(date):
            continue
        try:
            reds = sorted(int(cells[i]) for i in range(1, 7))
            blue = int(cells[7])
        except ValueError:
            continue
        if len(set(reds)) != 6 or not all(1 <= x <= 33 for x in reds) or not 1 <= blue <= 16:
            continue
        if datetime.date.fromisoformat(date) < start:
            continue
        issue = ("20" + raw_issue) if len(raw_issue) == 5 else raw_issue
        draws[issue] = {
            "issue": issue,
            "date": date,
            "reds": reds,
            "blue": blue,
            "sales": _num(cells[14]),
            "pool": _num(cells[9]),
            "first_count": _num(cells[10]),
            "first_amount": _num(cells[11]),
            "second_count": _num(cells[12]),
            "second_amount": _num(cells[13]),
            "content": "",
        }
    return sorted(draws.values(), key=lambda d: (d["date"], d["issue"]), reverse=True)


def fetch_dlt_500(days=150):
    rows = fetch_500_rows("dlt")
    today = datetime.datetime.now(CN_TZ).date()
    start = today - datetime.timedelta(days=days)
    draws = {}
    for row in rows:
        row = re.sub(r"<!--.*?-->", "", row, flags=re.S)
        cells = [_cell_text(x) for x in CELL_RE.findall(row)]
        if len(cells) < 15:
            continue
        issue, date = cells[0], cells[14]
        if not issue.isdigit() or not DATE_RE.match(date):
            continue
        try:
            fronts = sorted(int(cells[i]) for i in range(1, 6))
            backs = sorted(int(cells[i]) for i in range(6, 8))
        except ValueError:
            continue
        if len(set(fronts)) != 5 or not all(1 <= x <= 35 for x in fronts):
            continue
        if len(set(backs)) != 2 or not all(1 <= x <= 12 for x in backs):
            continue
        if datetime.date.fromisoformat(date) < start:
            continue
        draws[issue] = {
            "issue": issue,
            "date": date,
            "fronts": fronts,
            "backs": backs,
            "sales": _num(cells[13]),
            "pool": _num(cells[8]),
            "first_count": _num(cells[9]),
            "first_amount": _num(cells[10]),
            "second_count": _num(cells[11]),
            "second_amount": _num(cells[12]),
            "content": "",
        }
    return sorted(draws.values(), key=lambda d: (d["date"], d["issue"]), reverse=True)


def fetch_ssq(days=150):
    try:
        draws = fetch_ssq_official(days)
    except Exception as exc:  # noqa: BLE001
        print("  [警告] 官方双色球接口不可用：%s" % exc)
        draws = []
    if len(draws) < 30:
        print("  改用备用数据源 500.com（双色球）...")
        draws = fetch_ssq_500(days)
    return draws


def fetch_dlt(days=150):
    try:
        draws = fetch_dlt_official(days)
    except Exception as exc:  # noqa: BLE001
        print("  [警告] 官方大乐透接口不可用：%s" % exc)
        draws = []
    if len(draws) < 30:
        print("  改用备用数据源 500.com（大乐透）...")
        draws = fetch_dlt_500(days)
    return draws


def fetch_ssq_official(days=150):
    today = datetime.datetime.now(CN_TZ).date()
    day_start = today - datetime.timedelta(days=days)
    raw = []
    page = 1
    while True:
        url = (
            SSQ_API
            + "?name=ssq&issueCount=&issueStart=&issueEnd="
            + "&dayStart=%s&dayEnd=%s&pageNo=%d&pageSize=100&week=&systemType=PC"
            % (day_start.isoformat(), today.isoformat(), page)
        )
        js = http_json(url, referer="https://www.cwl.gov.cn/")
        if js.get("state") != 0:
            raise RuntimeError("福彩接口返回异常: %s" % js.get("message"))
        items = js.get("result") or []
        raw.extend(items)
        total_pages = int(js.get("pageNum") or 1)
        if page >= total_pages or not items:
            break
        page += 1
        time.sleep(0.3)

    draws = []
    for item in raw:
        try:
            reds = sorted(int(x) for x in str(item["red"]).split(","))
            blue = int(str(item["blue"]).strip())
            date = str(item["date"]).split("(")[0]
            issue = str(item["code"]).strip()
        except (KeyError, ValueError, TypeError):
            continue
        grades = {int(g.get("type", 0)): g for g in (item.get("prizegrades") or [])}
        first = grades.get(1, {})
        second = grades.get(2, {})
        draws.append({
            "issue": issue,
            "date": date,
            "reds": reds,
            "blue": blue,
            "sales": _num(item.get("sales")),
            "pool": _num(item.get("poolmoney")),
            "first_count": _num(first.get("typenum")),
            "first_amount": _num(first.get("typemoney")),
            "second_count": _num(second.get("typenum")),
            "second_amount": _num(second.get("typemoney")),
            "content": (item.get("content") or "").strip(),
        })

    draws.sort(key=lambda d: (d["date"], d["issue"]), reverse=True)
    # 去重（同 issue 保留一条）
    seen = set()
    uniq = []
    for d in draws:
        if d["issue"] in seen:
            continue
        seen.add(d["issue"])
        uniq.append(d)
    return uniq


def fetch_dlt_official(min_days=150):
    today = datetime.datetime.now(CN_TZ).date()
    cutoff = today - datetime.timedelta(days=min_days)
    raw = []
    page = 1
    while True:
        url = (
            DLT_API
            + "?gameNo=85&provinceId=0&pageSize=30&isVerify=1&pageNo=%d" % page
        )
        js = http_json(url, referer="https://www.lottery.gov.cn/")
        value = js.get("value") or {}
        items = value.get("list") or []
        raw.extend(items)
        pages = int(value.get("pages") or 1)
        if page >= pages or not items:
            break
        # 已经翻到早于截止日的页面则停止
        dates = [str(it.get("lotteryDrawTime", ""))[:10] for it in items]
        if dates and min(dates) < cutoff.isoformat():
            break
        page += 1
        time.sleep(0.3)

    draws = []
    for item in raw:
        try:
            nums = [int(x) for x in str(item["lotteryDrawResult"]).split()]
            date = str(item["lotteryDrawTime"])[:10]
            issue = str(item["lotteryDrawNum"]).strip()
        except (KeyError, ValueError, TypeError):
            continue
        if len(nums) != 7:
            continue
        fronts, backs = sorted(nums[:5]), sorted(nums[5:])
        levels = {str(p.get("prizeLevel", "")): p for p in (item.get("prizeLevelList") or [])}
        first = levels.get("一等奖", {})
        second = levels.get("二等奖", {})
        draws.append({
            "issue": issue,
            "date": date,
            "fronts": fronts,
            "backs": backs,
            "sales": _num(item.get("totalSaleAmount")),
            "pool": _num(item.get("poolBalanceAfterdraw")),
            "first_count": _num(first.get("stakeCount")),
            "first_amount": _num(first.get("stakeAmountFormat")),
            "second_count": _num(second.get("stakeCount")),
            "second_amount": _num(second.get("stakeAmountFormat")),
            "content": (item.get("lotteryDrawNotice") or "") if isinstance(item.get("lotteryDrawNotice"), str) else "",
        })

    draws.sort(key=lambda d: (d["date"], d["issue"]), reverse=True)
    seen = set()
    uniq = []
    for d in draws:
        if d["issue"] in seen:
            continue
        seen.add(d["issue"])
        uniq.append(d)
    return uniq


def save(game, draws, source):
    payload = {
        "game": game,
        "source": source,
        "fetched_at": datetime.datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "draws": draws,
    }
    path = os.path.join(DATA_DIR, "%s.json" % game)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print("  %-4s 抓取 %d 期，最新 %s %s -> %s"
          % (game, len(draws), draws[0]["date"] if draws else "-",
             draws[0]["issue"] if draws else "-", path))
    return payload


def main():
    print("[1/3] 抓取官方开奖数据 ...")
    ssq = fetch_ssq()
    dlt = fetch_dlt()
    if len(ssq) < 30:
        raise RuntimeError("双色球数据不足：仅 %d 期" % len(ssq))
    if len(dlt) < 30:
        raise RuntimeError("大乐透数据不足：仅 %d 期" % len(dlt))
    save("ssq", ssq, "中国福利彩票官网 www.cwl.gov.cn")
    save("dlt", dlt, "中国体育彩票官网 webapi.sporttery.cn")


if __name__ == "__main__":
    main()
