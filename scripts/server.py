# -*- coding: utf-8 -*-
"""
本地网页服务（仅监听 127.0.0.1）。

作用：
  - 打开 http://127.0.0.1:8765/ 查看页面；
  - 页面每次加载都会请求 /api/data?refresh=1，服务端联网抓取官方最新开奖、
    重新计算并返回最新数据，页面自动重渲染 —— 实现「每次进网页都更新」。

启动方式：双击「查看网页.bat」，或登录时由计划任务「彩票期望值-网页服务」自动启动。
"""
import datetime
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 默认监听所有网卡，手机 / 同一 Wi-Fi 的其他设备才能访问（仅局域网，路由器不对外映射）
HOST = os.environ.get("LOTTERY_HOST", "0.0.0.0")
PORT = int(os.environ.get("LOTTERY_PORT", "8765"))
SITE_DATA = os.path.join(BASE, "data", "site_data.json")
INDEX = os.path.join(BASE, "index.html")
UPDATE_SCRIPT = os.path.join(BASE, "scripts", "update.py")
PUBLIC_URL_FILE = os.path.join(BASE, "data", "public_url.txt")
LOG_DIR = os.path.join(BASE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "server.log")

LOCK = threading.Lock()
STATE = {"last": 0.0, "error": None, "updating": False}
COOLDOWN = 20.0         # 秒：距上次更新不足该时间则直接返回缓存，避免多人同时打开时重复抓取


def log(message):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = "[%s] %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def lan_ips():
    """探测本机局域网 IPv4 地址（用于手机访问）。"""
    ips = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("223.5.5.5", 80))
        ips.append(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if ip and not ip.startswith("127.")]


def lan_urls():
    return ["http://%s:%d/" % (ip, PORT) for ip in lan_ips()]


def public_url():
    """隧道进程写入的公网地址（data/public_url.txt）。"""
    try:
        with open(PUBLIC_URL_FILE, encoding="utf-8") as fh:
            url = fh.read().strip()
        return url if url.startswith("https://") else None
    except OSError:
        return None


def write_access_file(urls):
    path = os.path.join(BASE, "data", "access_url.txt")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("电脑本机访问：http://127.0.0.1:%d/\n" % PORT)
            fh.write("手机访问（需与电脑连同一 Wi-Fi，且已放行防火墙）：\n")
            for url in urls:
                fh.write("  %s\n" % url)
    except OSError:
        pass


def run_update():
    """调用 update.py 完成 抓取 -> 分析 -> 重建页面。"""
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write("[%s] 开始联网更新\n" % stamp)
        fh.flush()
        proc = subprocess.run(
            [sys.executable, UPDATE_SCRIPT],
            cwd=BASE,
            stdout=fh,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    return proc.returncode


def load_site_data():
    """读取分析结果；外部更新脚本写入瞬间可能读到半个文件，重试几次。"""
    last_error = None
    for _ in range(5):
        try:
            with open(SITE_DATA, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.25)
    raise last_error


def refresh(force=False):
    """按需刷新；返回是否真的执行了抓取。"""
    if not force and time.time() - STATE["last"] < COOLDOWN and os.path.exists(SITE_DATA):
        return False
    with LOCK:
        if not force and time.time() - STATE["last"] < COOLDOWN and os.path.exists(SITE_DATA):
            return False
        STATE["updating"] = True
        started = time.time()
        try:
            code = run_update()
            STATE["error"] = None if code == 0 else "更新脚本返回 %d" % code
            log("更新%s，用时 %.1fs" % ("成功" if code == 0 else "失败(exit %d)" % code,
                                       time.time() - started))
        except Exception as exc:  # noqa: BLE001
            STATE["error"] = str(exc)
            log("更新异常：%s" % exc)
        finally:
            STATE["last"] = time.time()
            STATE["updating"] = False
    return True


class Handler(SimpleHTTPRequestHandler):
    server_version = "LotteryLocal/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def log_message(self, fmt, *args):  # 不刷屏
        pass

    def _send(self, body, content_type, status=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        try:
            self._handle_get()
        except Exception as exc:  # noqa: BLE001
            log("请求异常 %s：%s" % (self.path, exc))
            try:
                self._json({"error": str(exc)}, 500)
            except Exception:  # noqa: BLE001
                pass

    def _json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                   "application/json; charset=utf-8", status)

    def _handle_get(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/ping":
            self._json({
                "ok": True,
                "updating": STATE["updating"],
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            return

        if path == "/api/info":
            # 只有本机/局域网访问才返回内网地址，公网访客看不到内网 IP
            host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
            local = host in ("127.0.0.1", "localhost") or host.startswith(
                ("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
                 "172.2", "172.30.", "172.31."))
            self._json({
                "port": PORT,
                "ipv4": lan_ips() if local else [],
                "urls": lan_urls() if local else [],
                "public_url": public_url(),
                "computer_url": ("http://127.0.0.1:%d/" % PORT) if local else None,
            })
            return

        if path == "/api/data":
            started = time.time()
            qs = urllib.parse.parse_qs(parsed.query)
            want_refresh = qs.get("refresh", ["0"])[0] in ("1", "true", "yes")
            force = qs.get("force", ["0"])[0] in ("1", "true", "yes")
            updated = refresh(force=force) if want_refresh else False
            try:
                data = load_site_data()
            except Exception as exc:  # noqa: BLE001
                self._json({"error": "数据文件不可用：%s" % exc}, 500)
                return
            data["_meta"] = {
                "updated": updated,
                "error": STATE["error"],
                "server": "127.0.0.1:%d" % PORT,
                "refreshed_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            log("GET /api/data refresh=%s force=%s -> updated=%s error=%s 用时 %.2fs"
                % (want_refresh, force, updated, STATE["error"] or "-", time.time() - started))
            self._json(data)
            return

        if path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as fh:
                    body = fh.read()
                self._send(body, "text/html; charset=utf-8")
            except OSError:
                self._send("<h1>index.html 不存在</h1><p>请先运行「更新数据.bat」生成页面。</p>",
                           "text/html; charset=utf-8", 500)
            return

        if path == "/favicon.ico":
            self._send(b"", "image/x-icon", 204)
            return

        # 公网分享时只暴露页面与接口，不暴露源码、日志、数据文件
        self._send("404 Not Found", "text/plain; charset=utf-8", 404)


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        log("端口 %d 不可用（可能已有实例在运行）：%s" % (PORT, exc))
        return 2

    log("本地服务启动：http://127.0.0.1:%d/  手机访问：%s"
        % (PORT, " / ".join(lan_urls()) or "未检测到局域网 IP"))
    write_access_file(lan_urls())
    # 启动时后台预热一次，保证首次打开的页面是较新的数据
    threading.Thread(target=lambda: refresh(force=False), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
