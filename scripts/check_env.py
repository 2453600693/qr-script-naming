#!/usr/bin/env python3
"""环境自检：一条命令看清还缺什么。

用法:
    python scripts/check_env.py

只做诊断，不自动安装（装什么、装到哪，用户自己决定更稳妥）。
"""
import importlib
import json
import os
import shutil
import subprocess
import sys

OK = "[OK]  "
BAD = "[缺]  "
CLI = shutil.which("lark-cli") or "lark-cli"


def cmd_ok(name):
    return shutil.which(name) is not None


def module_ok(name):
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def model_cached(name="small"):
    hub = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    if not os.path.isdir(hub):
        return False
    return any(d.startswith("models--") and name in d for d in os.listdir(hub))


def lark_login():
    """lark-cli auth status 的实际字段：identities.user.status = ready，tokenStatus = valid。"""
    try:
        r = subprocess.run([CLI, "auth", "status", "--json", "--verify"], capture_output=True,
                           text=True, encoding="utf-8", errors="ignore", timeout=40)
        d = json.loads(r.stdout or "{}")
        user = ((d.get("identities") or {}).get("user") or {})
        name = user.get("userName") or user.get("openId") or "已登录"
        if user.get("verified") or user.get("tokenStatus") == "valid":
            return True, str(name)
        if user.get("status") == "ready":
            return True, "%s（未联网校验）" % name
        return False, user.get("message") or "未登录或登录态失效"
    except Exception as e:
        return False, "无法检测（%s）" % type(e).__name__


def main():
    print("=" * 58)
    print("  QR脚本命名工具 · 环境自检")
    print("=" * 58)
    print("系统: %s   Python %s" % (sys.platform, sys.version.split()[0]))
    print()
    todo = []

    for c, hint in [("ffmpeg", "winget install Gyan.FFmpeg  (macOS: brew install ffmpeg)"),
                    ("ffprobe", "随 ffmpeg 一起安装")]:
        if cmd_ok(c):
            print(OK + c)
        else:
            print(BAD + c + "   -> " + hint)
            todo.append(hint)

    for m, hint in [("faster_whisper", "pip install faster-whisper"),
                    ("scipy", "pip install scipy"),
                    ("numpy", "pip install numpy")]:
        if module_ok(m):
            print(OK + "python 包 " + m)
        else:
            print(BAD + "python 包 " + m + "   -> " + hint)
            if hint not in todo:
                todo.append(hint)

    if cmd_ok("lark-cli"):
        print(OK + "lark-cli " + CLI)
        good, detail = lark_login()
        if good:
            print(OK + "飞书登录态: " + detail)
        else:
            print(BAD + "飞书登录态: " + detail + "   -> lark-cli config init && lark-cli auth login")
            todo.append("lark-cli config init && lark-cli auth login")
    else:
        print(BAD + "lark-cli   -> npm i -g @larksuite/cli")
        todo.append("npm i -g @larksuite/cli")

    if model_cached("small"):
        print(OK + "whisper small 模型已缓存（离线可用）")
    else:
        print("      whisper small 模型未缓存，首次转写会联网下载（约 500MB）")

    print()
    if todo:
        print("还需处理 %d 项:" % len(todo))
        for t in todo:
            print("  - " + t)
    else:
        print("全部就绪，可以直接开工。")
    print()
    print("下一步: 按 AGENTS.md 开头的\"开工三行\"向用户收集信息。")


if __name__ == "__main__":
    main()
