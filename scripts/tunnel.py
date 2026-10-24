# -*- coding: utf-8 -*-
"""
Cloudflare 快速隧道守护进程。

把本机 http://127.0.0.1:8765 映射成公网 HTTPS 地址，供他人手机/电脑访问。
无需注册账号；每次隧道重启后公网地址会变化（写入 data/public_url.txt，页面底部展示）。

启动：双击「分享链接.bat」，或由计划任务「彩票期望值-公网隧道」在登录时自动启动。
"""
import datetime
import os
import re
import subprocess
import sys
import time
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUDFLARED = os.path.join(BASE, "tools", "cloudflared.exe")
LOG_DIR = os.path.join(BASE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "tunnel.log")
CLOUDFLARED_LOG = os.path.join(LOG_DIR, "cloudflared.log")
URL_FILE = os.path.join(BASE, "data", "public_url.txt")
TARGET = "http://127.0.0.1:8765"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def log(message):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = "[%s] %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def clear_url():
    try:
        os.remove(URL_FILE)
    except OSError:
        pass


def wait_for_url(proc, timeout=45):
    """轮询 cloudflared 日志，提取公网地址。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return None
        try:
            with open(CLOUDFLARED_LOG, encoding="utf-8", errors="replace") as fh:
                match = URL_RE.search(fh.read())
            if match:
                return match.group(0)
        except OSError:
            pass
        time.sleep(0.5)
    return None


def run_once():
    """启动一次隧道，直到进程退出。"""
    clear_url()
    try:
        os.remove(CLOUDFLARED_LOG)
    except OSError:
        pass

    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    cmd = [
        CLOUDFLARED, "tunnel",
        "--url", TARGET,
        "--no-autoupdate",
        "--protocol", "http2",
        "--logfile", CLOUDFLARED_LOG,
    ]
    log("启动隧道：%s" % " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=flags)
    url = wait_for_url(proc)
    if url:
        with open(URL_FILE, "w", encoding="utf-8") as fh:
            fh.write(url)
        log("公网地址：%s" % url)
    else:
        log("未能获取公网地址（cloudflared 可能启动失败）")
    proc.wait()
    clear_url()
    log("隧道进程退出，返回码 %s" % proc.returncode)


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    log("隧道守护启动，目标 %s" % TARGET)
    while True:
        try:
            run_once()
        except Exception:  # noqa: BLE001
            log("隧道异常：\n" + traceback.format_exc())
        time.sleep(8)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
