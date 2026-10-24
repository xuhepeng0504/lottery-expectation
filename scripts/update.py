# -*- coding: utf-8 -*-
"""一键更新：抓取 -> 分析 -> 生成网页。供「更新数据.bat」与计划任务调用。"""
import datetime
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)

LOG_DIR = os.path.join(BASE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "update.log")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def log(message):
    print(message)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write("[%s] %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))


def main():
    start = time.time()
    log("=" * 64)
    log("开始更新：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    import fetch_data
    import analyze
    import build_site

    fetch_data.main()
    analyze.main()
    build_site.main()

    log("更新完成，用时 %.1f 秒。" % (time.time() - start))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        log("更新失败：\n" + traceback.format_exc())
        sys.exit(1)
