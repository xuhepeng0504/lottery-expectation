# -*- coding: utf-8 -*-
"""
号码统计 / 期望值建模 / 推荐号码生成 / 历史回测。

说明：
  彩票每期开奖相互独立，任何模型都无法真正预测下一期号码。
  这里的「期望值」是号码的综合统计得分（近期热度 + 遗漏回补 + 邻号关联 + 结构均衡），
  仅用于生成有统计依据的参考组合，不代表中奖概率提升。
"""
import calendar
import datetime
import itertools
import json
import math
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DECAY = 0.90          # 时间衰减：越近期权重越高
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
CN_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 彩票按北京时间

SSQ_TOTAL = 17_721_088
SSQ_TIER_COUNTS = [1, 15, 162, 7695, 137_475, 1_043_640]
SSQ_TIERS = [
    ("一等奖", "6 红 + 1 蓝", "浮动（奖池）"),
    ("二等奖", "6 红 + 0 蓝", "浮动"),
    ("三等奖", "5 红 + 1 蓝", "3,000 元"),
    ("四等奖", "5 红 + 0 蓝 / 4 红 + 1 蓝", "200 元"),
    ("五等奖", "4 红 + 0 蓝 / 3 红 + 1 蓝", "10 元"),
    ("六等奖", "2 红 + 1 蓝 / 1 红 + 1 蓝 / 0 红 + 1 蓝", "5 元"),
]

DLT_TOTAL = 21_425_712
DLT_TIER_COUNTS = [1, 20, 45, 150, 3000, 4350, 6750, 127_600, 1_287_281]
DLT_TIERS = [
    ("一等奖", "5+2", "浮动（奖池）"),
    ("二等奖", "5+1", "浮动"),
    ("三等奖", "5+0", "10,000 元"),
    ("四等奖", "4+2", "3,000 元"),
    ("五等奖", "4+1", "300 元"),
    ("六等奖", "3+2", "200 元"),
    ("七等奖", "4+0", "100 元"),
    ("八等奖", "3+1 / 2+2", "15 元"),
    ("九等奖", "3+0 / 2+1 / 1+2 / 0+2", "5 元"),
]


def mean_std(values):
    n = len(values)
    if n == 0:
        return 0.0, 1.0
    mu = sum(values) / n
    var = sum((v - mu) ** 2 for v in values) / n
    return mu, (math.sqrt(var) or 1.0)


def zscores(values):
    mu, sd = mean_std(values)
    return [(v - mu) / sd for v in values], mu, sd


def combs_of(nums):
    """连号对数"""
    return sum(1 for a, b in zip(nums, nums[1:]) if b - a == 1)


def ac_value(nums):
    diffs = {b - a for i, a in enumerate(nums) for b in nums[i + 1:]}
    return len(diffs) - (len(nums) - 1)


def number_stats(draws, getter, universe, pick, adjacency=False):
    """计算每个号码的 频率 / 遗漏 / 时间加权热度 / 综合得分。"""
    n = len(draws)
    freq = [0] * (universe + 1)
    last = [-1] * (universe + 1)
    wsum = [0.0] * (universe + 1)
    total_w = 0.0
    for i, draw in enumerate(draws):
        wt = DECAY ** i
        total_w += wt
        for x in getter(draw):
            freq[x] += 1
            wsum[x] += wt
            if last[x] < 0:
                last[x] = i

    omit = [last[x] if last[x] >= 0 else n for x in range(universe + 1)]
    expected_w = pick * total_w / universe
    hot = [wsum[x] / expected_w for x in range(universe + 1)]

    zhot, _, _ = zscores(hot[1:])
    zomit, _, _ = zscores([float(o) for o in omit[1:]])

    zadj = [0.0] * universe
    if adjacency:
        latest = set(getter(draws[0]))
        adj = [0.0] * universe
        for x in range(1, universe + 1):
            if x in latest:
                adj[x - 1] = 1.2      # 重号
            elif (x - 1) in latest or (x + 1) in latest:
                adj[x - 1] = 0.7      # 邻号
        zadj, _, _ = zscores(adj)

    stats = []
    for x in range(1, universe + 1):
        if adjacency:
            score = 0.45 * zhot[x - 1] + 0.35 * zomit[x - 1] + 0.20 * zadj[x - 1]
        else:
            score = 0.55 * zhot[x - 1] + 0.45 * zomit[x - 1]
        stats.append({
            "n": x,
            "freq": freq[x],
            "omit": omit[x],
            "hot": round(hot[x], 3),
            "score": round(score, 4),
            "zhot": round(zhot[x - 1], 3),
            "zomit": round(zomit[x - 1], 3),
        })
    return stats


def structural_penalty(nums, sum_mu, sum_sd, zones, big_split, span_lo, span_hi):
    """结构越接近历史常态，惩罚越小。"""
    s = sum(nums)
    pen = abs(s - sum_mu) / (2.0 * sum_sd)

    odd = sum(1 for x in nums if x % 2)
    pen += 0.12 * abs(odd - len(nums) / 2.0)
    big = sum(1 for x in nums if x >= big_split)
    pen += 0.10 * abs(big - len(nums) / 2.0)

    zone_hits = [sum(1 for x in nums if lo <= x <= hi) for lo, hi in zones]
    pen += 0.22 * sum(1 for c in zone_hits if c == 0)

    pairs = combs_of(nums)
    pen += 0.22 * max(0, pairs - 1)

    span = nums[-1] - nums[0]
    pen += 0.06 * max(0, span_lo - span) + 0.06 * max(0, span - span_hi)

    ac = ac_value(nums)
    pen += 0.05 * max(0, 5 - ac)
    return pen


def combo_meta(nums, sum_mu, sum_sd, zones, big_split=17):
    odd = sum(1 for x in nums if x % 2)
    big = sum(1 for x in nums if x >= big_split)
    zone_hits = [sum(1 for x in nums if lo <= x <= hi) for lo, hi in zones]
    return {
        "sum": sum(nums),
        "odd": odd,
        "even": len(nums) - odd,
        "big": big,
        "small": len(nums) - big,
        "zones": zone_hits,
        "span": nums[-1] - nums[0],
        "ac": ac_value(nums),
        "consecutive": combs_of(nums),
        "sum_mean": round(sum_mu, 1),
        "sum_std": round(sum_sd, 1),
    }


def score_to_index(fit):
    return round(max(1.0, min(99.0, 50 + 22 * fit)), 1)


def pick_diverse(cands, count, max_overlap, min_sum_gap=0):
    chosen = []
    for fit, nums in cands:
        if all(len(set(nums) & set(c[1])) <= max_overlap for c in chosen) \
                and all(abs(sum(nums) - sum(c[1])) >= min_sum_gap for c in chosen):
            chosen.append((fit, nums))
        if len(chosen) >= count:
            break
    return chosen


def random_baseline(draws, getter, universe, pick, zones, big_split, span, count):
    """随机组合的平均拟合分，作为「随机基准」参照。"""
    import random
    rng = random.Random(42)
    stats = number_stats(draws, getter, universe, pick, adjacency=True)
    sums = [sum(getter(d)) for d in draws]
    sum_mu, sum_sd = mean_std(sums)
    fits = []
    for _ in range(2500):
        combo = tuple(sorted(rng.sample(range(1, universe + 1), count)))
        base = sum(stats[n - 1]["score"] for n in combo) / float(count)
        pen = structural_penalty(combo, sum_mu, sum_sd, zones,
                                 big_split=big_split, span_lo=span[0], span_hi=span[1])
        fits.append(base * 0.9 - pen * 0.6)
    return score_to_index(sum(fits) / len(fits))


def generate_ssq(draws, count=5):
    """返回 count 组双色球号码（含得分与说明）。"""
    reds_stat = number_stats(draws, lambda d: d["reds"], 33, 6, adjacency=True)
    blue_stat = number_stats(draws, lambda d: [d["blue"]], 16, 1, adjacency=False)

    sums = [sum(d["reds"]) for d in draws]
    sum_mu, sum_sd = mean_std(sums)
    zones = [(1, 11), (12, 22), (23, 33)]

    pool = sorted(range(1, 34), key=lambda n: reds_stat[n - 1]["score"], reverse=True)
    cands = []
    for size in (20, 24, 28, 33):
        cands = []
        for combo in itertools.combinations(sorted(pool[:size]), 6):
            base = sum(reds_stat[n - 1]["score"] for n in combo) / 6.0
            pen = structural_penalty(combo, sum_mu, sum_sd, zones,
                                     big_split=17, span_lo=12, span_hi=30)
            cands.append((base * 0.9 - pen * 0.6, combo))
        cands.sort(reverse=True)
        chosen = pick_diverse(cands, count, 2, 6)
        if len(chosen) >= count:
            break
    if len(chosen) < count:
        chosen = pick_diverse(cands, count, 3, 0)

    blues = sorted(range(1, 17), key=lambda n: blue_stat[n - 1]["score"], reverse=True)
    blue_pick = blues[:count] if len(blues) >= count else blues

    result = []
    for idx, (fit, combo) in enumerate(chosen):
        blue = blue_pick[idx % len(blue_pick)]
        meta = combo_meta(list(combo), sum_mu, sum_sd, zones)
        hot = [n for n in combo if reds_stat[n - 1]["hot"] >= 1.15]
        overdue = [n for n in combo if reds_stat[n - 1]["omit"] >= 8]
        latest = set(draws[0]["reds"])
        repeat = [n for n in combo if n in latest]
        neighbor = [n for n in combo if n not in latest and ((n - 1) in latest or (n + 1) in latest)]

        tags = []
        if len(hot) >= 2:
            tags.append("热号 %d 枚" % len(hot))
        if overdue:
            tags.append("遗漏回补 " + "、".join("%02d" % n for n in overdue[:2]))
        if repeat:
            tags.append("重号 %02d" % repeat[0])
        if neighbor:
            tags.append("邻号 %02d" % neighbor[0])
        tags.append("和值 %d" % meta["sum"])
        tags.append("奇偶 %d:%d" % (meta["odd"], meta["even"]))
        tags.append("三区 %s" % ":".join(str(z) for z in meta["zones"]))

        reasons = [
            "综合期望指数 %.1f：近期热度权重 45%%、遗漏回补 35%%、重邻号关联 20%%。" % score_to_index(fit),
            "红球热号 %s（时间加权出现率高于均值 15%% 以上）。" %
            ("、".join("%02d" % n for n in hot) if hot else "无明显热号，以冷热均衡为主"),
            "遗漏较深：%s，超过理论平均间隔 5.5 期。" %
            ("、".join("%02d（%d 期）" % (n, reds_stat[n - 1]["omit"]) for n in overdue[:2]) if overdue else "无，号码整体处于正常回补区间"),
            "结构：和值 %d（近 %d 期均值 %.1f±%.1f），奇偶 %d:%d，三区 %s，跨度 %d。" %
            (meta["sum"], len(draws), sum_mu, sum_sd, meta["odd"], meta["even"],
             ":".join(str(z) for z in meta["zones"]), meta["span"]),
        ]

        result.append({
            "reds": list(combo),
            "blue": blue,
            "score": score_to_index(fit),
            "fit": round(fit, 3),
            "tags": tags[:6],
            "reasons": reasons,
            **meta,
        })
    return result


def generate_dlt(draws, count=5):
    """返回 count 组大乐透号码。"""
    front_stat = number_stats(draws, lambda d: d["fronts"], 35, 5, adjacency=True)
    back_stat = number_stats(draws, lambda d: d["backs"], 12, 2, adjacency=False)

    sums = [sum(d["fronts"]) for d in draws]
    sum_mu, sum_sd = mean_std(sums)
    zones = [(1, 12), (13, 24), (25, 35)]

    pool = sorted(range(1, 36), key=lambda n: front_stat[n - 1]["score"], reverse=True)
    cands = []
    for size in (20, 25, 30, 35):
        cands = []
        for combo in itertools.combinations(sorted(pool[:size]), 5):
            base = sum(front_stat[n - 1]["score"] for n in combo) / 5.0
            pen = structural_penalty(combo, sum_mu, sum_sd, zones,
                                     big_split=18, span_lo=15, span_hi=32)
            cands.append((base * 0.9 - pen * 0.6, combo))
        cands.sort(reverse=True)
        chosen = pick_diverse(cands, count, 2, 5)
        if len(chosen) >= count:
            break
    if len(chosen) < count:
        chosen = pick_diverse(cands, count, 3, 0)

    backs_sorted = sorted(range(1, 13), key=lambda n: back_stat[n - 1]["score"], reverse=True)
    back_pairs = [tuple(sorted(p)) for p in itertools.combinations(backs_sorted[:6], 2)]
    back_pairs = back_pairs[:count] if len(back_pairs) >= count else back_pairs

    result = []
    for idx, (fit, combo) in enumerate(chosen):
        backs = list(back_pairs[idx % len(back_pairs)])
        meta = combo_meta(list(combo), sum_mu, sum_sd, zones, big_split=18)
        hot = [n for n in combo if front_stat[n - 1]["hot"] >= 1.15]
        overdue = [n for n in combo if front_stat[n - 1]["omit"] >= 8]
        latest = set(draws[0]["fronts"])
        repeat = [n for n in combo if n in latest]
        neighbor = [n for n in combo if n not in latest and ((n - 1) in latest or (n + 1) in latest)]

        tags = []
        if len(hot) >= 2:
            tags.append("热号 %d 枚" % len(hot))
        if overdue:
            tags.append("遗漏回补 " + "、".join("%02d" % n for n in overdue[:2]))
        if repeat:
            tags.append("重号 %02d" % repeat[0])
        if neighbor:
            tags.append("邻号 %02d" % neighbor[0])
        tags.append("和值 %d" % meta["sum"])
        tags.append("奇偶 %d:%d" % (meta["odd"], meta["even"]))

        reasons = [
            "综合期望指数 %.1f：前区热度 45%%、遗漏回补 35%%、重邻号关联 20%%。" % score_to_index(fit),
            "前区热号 %s。" % ("、".join("%02d" % n for n in hot) if hot else "无明显热号，以冷热均衡为主"),
            "遗漏较深：%s。" % ("、".join("%02d（%d 期）" % (n, front_stat[n - 1]["omit"]) for n in overdue[:2]) if overdue else "无，号码整体处于正常回补区间"),
            "结构：前区和值 %d（近 %d 期均值 %.1f±%.1f），奇偶 %d:%d，跨度 %d。" %
            (meta["sum"], len(draws), sum_mu, sum_sd, meta["odd"], meta["even"], meta["span"]),
        ]

        result.append({
            "fronts": list(combo),
            "backs": backs,
            "score": score_to_index(fit),
            "fit": round(fit, 3),
            "tags": tags[:6],
            "reasons": reasons,
            **meta,
        })
    return result


def ssq_ev(draw):
    amounts = [draw["first_amount"], draw["second_amount"], 3000, 200, 10, 5]
    return sum(c * a for c, a in zip(SSQ_TIER_COUNTS, amounts)) / SSQ_TOTAL


def dlt_ev(draw):
    amounts = [draw["first_amount"], draw["second_amount"], 10000, 3000, 300, 200, 100, 15, 5]
    return sum(c * a for c, a in zip(DLT_TIER_COUNTS, amounts)) / DLT_TOTAL


def fmt_prob(count, total):
    return "{:,}".format(round(total / count))


def next_draw(days, draw_time, latest_date, now):
    """推算下一期开奖日期。"""
    cur = now.date()
    if latest_date >= cur:
        cur = latest_date + datetime.timedelta(days=1)
    for _ in range(14):
        if cur.weekday() in days:
            hh, mm = [int(x) for x in draw_time.split(":")]
            when = datetime.datetime.combine(cur, datetime.time(hh, mm), tzinfo=CN_TZ)
            if when > now:
                return {
                    "date": cur.isoformat(),
                    "weekday": WEEKDAYS[cur.weekday()],
                    "time": draw_time,
                    "days_left": (cur - now.date()).days,
                    "timestamp": when.isoformat(),
                }
        cur += datetime.timedelta(days=1)
    return None


def minus_months(d, months):
    """日历意义上的「往前推 N 个月」，不依赖第三方库。"""
    total = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def next_issue(issue):
    try:
        return str(int(str(issue).strip()) + 1)
    except (TypeError, ValueError):
        return str(issue)


def window_draws(draws, months=3):
    latest = datetime.date.fromisoformat(draws[0]["date"])
    start = minus_months(latest, months)
    return [d for d in draws if datetime.date.fromisoformat(d["date"]) >= start]


def backtest_ssq(draws, lookback=20):
    """用历史逐期回测：在第 t 期之前的数据上生成 5 组号码，看命中红球数。"""
    hits, total = 0, 0
    limit = min(lookback, len(draws) - 15)
    for t in range(max(0, limit)):
        hist = draws[t + 1:]
        if len(hist) < 15:
            break
        combos = generate_ssq(hist, count=5)
        actual = set(draws[t]["reds"])
        for c in combos:
            hits += len(set(c["reds"]) & actual)
            total += 1
    if total == 0:
        return None
    return {
        "draws": total // 5,
        "avg_hits": round(hits / total, 3),
        "random": round(6 * 6 / 33, 3),
    }


def backtest_dlt(draws, lookback=20):
    hits, total = 0, 0
    limit = min(lookback, len(draws) - 15)
    for t in range(max(0, limit)):
        hist = draws[t + 1:]
        if len(hist) < 15:
            break
        combos = generate_dlt(hist, count=5)
        actual = set(draws[t]["fronts"])
        for c in combos:
            hits += len(set(c["fronts"]) & actual)
            total += 1
    if total == 0:
        return None
    return {
        "draws": total // 5,
        "avg_hits": round(hits / total, 3),
        "random": round(5 * 5 / 35, 3),
    }


def analyze_ssq(all_draws):
    draws = window_draws(all_draws, 3)
    now = datetime.datetime.now(CN_TZ)
    latest = draws[0]

    red_stat = number_stats(draws, lambda d: d["reds"], 33, 6, adjacency=True)
    blue_stat = number_stats(draws, lambda d: [d["blue"]], 16, 1, adjacency=False)
    sums = [sum(d["reds"]) for d in draws]
    sum_mu, sum_sd = mean_std(sums)

    combos = generate_ssq(draws)
    evs = [ssq_ev(d) for d in draws]
    ev_avg = sum(evs) / len(evs)

    prizegrades = [
        {"tier": name, "condition": cond, "prob": "1 / " + fmt_prob(c, SSQ_TOTAL),
         "amount": latest["first_amount"] if i == 0 else
                   (latest["second_amount"] if i == 1 else amt)}
        for i, ((name, cond, amt), c) in enumerate(zip(SSQ_TIERS, SSQ_TIER_COUNTS))
    ]

    nxt = next_draw({1, 3, 6}, "21:15", datetime.date.fromisoformat(latest["date"]), now)
    if nxt:
        nxt["issue"] = next_issue(latest["issue"])

    return {
        "key": "ssq",
        "name": "双色球",
        "rule": "红球 33 选 6 + 蓝球 16 选 1",
        "price": 2,
        "window": {"start": draws[-1]["date"], "end": latest["date"], "count": len(draws)},
        "latest": latest,
        "draws": draws,
        "next": nxt,
        "combos": combos,
        "stats": {
            "red": red_stat,
            "blue": blue_stat,
            "sums": sums,
            "sum_mean": round(sum_mu, 1),
            "sum_std": round(sum_sd, 1),
            "ev_avg": round(ev_avg, 3),
            "ev_pct": round(ev_avg / 2 * 100, 1),
            "ev_latest": round(evs[0], 3),
            "prize_table": prizegrades,
            "backtest": backtest_ssq(draws),
            "baseline_score": random_baseline(
                draws, lambda d: d["reds"], 33, 6,
                [(1, 11), (12, 22), (23, 33)], 17, (12, 30), 6),
            "hot_red": [s["n"] for s in sorted(red_stat, key=lambda x: x["hot"], reverse=True)[:8]],
            "overdue_red": [s["n"] for s in sorted(red_stat, key=lambda x: x["omit"], reverse=True)[:8]],
            "hot_blue": [s["n"] for s in sorted(blue_stat, key=lambda x: x["hot"], reverse=True)[:5]],
            "total_bet": len(draws),
        },
    }


def analyze_dlt(all_draws):
    draws = window_draws(all_draws, 3)
    now = datetime.datetime.now(CN_TZ)
    latest = draws[0]

    front_stat = number_stats(draws, lambda d: d["fronts"], 35, 5, adjacency=True)
    back_stat = number_stats(draws, lambda d: d["backs"], 12, 2, adjacency=False)
    sums = [sum(d["fronts"]) for d in draws]
    sum_mu, sum_sd = mean_std(sums)

    combos = generate_dlt(draws)
    evs = [dlt_ev(d) for d in draws]
    ev_avg = sum(evs) / len(evs)

    prizegrades = []
    for i, ((name, cond, amt), c) in enumerate(zip(DLT_TIERS, DLT_TIER_COUNTS)):
        amount = latest["first_amount"] if i == 0 else (latest["second_amount"] if i == 1 else amt)
        prizegrades.append({
            "tier": name, "condition": cond,
            "prob": "1 / " + fmt_prob(c, DLT_TOTAL), "amount": amount,
        })

    nxt = next_draw({0, 2, 5}, "21:25", datetime.date.fromisoformat(latest["date"]), now)
    if nxt:
        nxt["issue"] = next_issue(latest["issue"])

    return {
        "key": "dlt",
        "name": "超级大乐透",
        "rule": "前区 35 选 5 + 后区 12 选 2",
        "price": 2,
        "window": {"start": draws[-1]["date"], "end": latest["date"], "count": len(draws)},
        "latest": latest,
        "draws": draws,
        "next": nxt,
        "combos": combos,
        "stats": {
            "front": front_stat,
            "back": back_stat,
            "sums": sums,
            "sum_mean": round(sum_mu, 1),
            "sum_std": round(sum_sd, 1),
            "ev_avg": round(ev_avg, 3),
            "ev_pct": round(ev_avg / 2 * 100, 1),
            "ev_latest": round(evs[0], 3),
            "prize_table": prizegrades,
            "backtest": backtest_dlt(draws),
            "baseline_score": random_baseline(
                draws, lambda d: d["fronts"], 35, 5,
                [(1, 12), (13, 24), (25, 35)], 18, (15, 32), 5),
            "hot_front": [s["n"] for s in sorted(front_stat, key=lambda x: x["hot"], reverse=True)[:8]],
            "overdue_front": [s["n"] for s in sorted(front_stat, key=lambda x: x["omit"], reverse=True)[:8]],
            "hot_back": [s["n"] for s in sorted(back_stat, key=lambda x: x["hot"], reverse=True)[:5]],
            "total_bet": len(draws),
        },
    }


def load(game):
    with open(os.path.join(DATA_DIR, "%s.json" % game), encoding="utf-8") as fh:
        return json.load(fh)["draws"]


def main():
    print("[2/3] 统计分析 & 选号 ...")
    ssq = analyze_ssq(load("ssq"))
    print("  双色球：窗口 %s ~ %s，共 %d 期；回测 %s"
          % (ssq["window"]["start"], ssq["window"]["end"], ssq["window"]["count"],
             ssq["stats"]["backtest"]))
    dlt = analyze_dlt(load("dlt"))
    print("  大乐透：窗口 %s ~ %s，共 %d 期；回测 %s"
          % (dlt["window"]["start"], dlt["window"]["end"], dlt["window"]["count"],
             dlt["stats"]["backtest"]))

    payload = {
        "generated_at": datetime.datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "generated_date": datetime.datetime.now(CN_TZ).date().isoformat(),
        "games": {"ssq": ssq, "dlt": dlt},
    }
    path = os.path.join(DATA_DIR, "site_data.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    print("  分析结果 -> %s (%.1f KB)" % (path, os.path.getsize(path) / 1024))


if __name__ == "__main__":
    main()
