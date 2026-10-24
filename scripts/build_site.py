# -*- coding: utf-8 -*-
"""
把分析结果注入 HTML 模板，生成页面。

用法：
  python scripts/build_site.py            生成本地单文件 index.html（联网服务模式）
  python scripts/build_site.py --deploy   额外生成静态部署目录 dist/（GitHub Pages 用）
"""
import argparse
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
TEMPLATE = os.path.join(BASE, "scripts", "template.html")
OUTPUT = os.path.join(BASE, "index.html")
DIST = os.path.join(BASE, "dist")

STATIC_FLAG = '<script>window.__STATIC__=true;window.__DATA_URL__="data/site_data.json";</script>\n'

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def render(payload, template):
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # 防止 JSON 中意外出现 </script> 或 U+2028/U+2029 破坏页面
    js = (js.replace("<", "\\u003c")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))
    return template.replace("__DATA_JSON__", js)


def main():
    parser = argparse.ArgumentParser(description="生成彩票期望值页面")
    parser.add_argument("--deploy", action="store_true",
                        help="生成 GitHub Pages 静态部署目录 dist/")
    args = parser.parse_args()

    print("[3/3] 生成网页 ...")
    site_data_path = os.path.join(DATA_DIR, "site_data.json")
    with open(site_data_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    with open(TEMPLATE, encoding="utf-8") as fh:
        template = fh.read()

    html = render(payload, template)
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("  本地页面：%s（%.1f KB）" % (OUTPUT, os.path.getsize(OUTPUT) / 1024))

    if args.deploy:
        if os.path.isdir(DIST):
            shutil.rmtree(DIST)
        os.makedirs(os.path.join(DIST, "data"))
        static_html = html.replace("<script>window.__LOTTERY__ =",
                                   STATIC_FLAG + "<script>window.__LOTTERY__ =", 1)
        with open(os.path.join(DIST, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(static_html)
        shutil.copyfile(site_data_path, os.path.join(DIST, "data", "site_data.json"))
        print("  静态部署目录：%s（index.html + data/site_data.json）" % DIST)

    print("  生成时间：%s" % payload.get("generated_at"))


if __name__ == "__main__":
    main()
