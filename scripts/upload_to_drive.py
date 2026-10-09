#!/usr/bin/env python3
"""把本地已命名的原片素材上传到飞书云盘。

路径约定（照现有结构）：云盘 > 拍摄原片 > {YYYY}年拍摄素材 > {M}月{D}日
日期文件夹不存在会自动创建，命名格式与现有一致。

用法:
    # 先看要传哪些，不写
    python upload_to_drive.py --root "<拍摄原片文件夹URL或token>" \
        --dirs "D:\\原片素材\\9.14\\梁思思" "D:\\原片素材\\9.14\\蓝蓝" --dry-run

    # 真传
    python upload_to_drive.py --root "<...>" --dirs "..." "..."

设计原则：
- 只传「本地有、云盘没有」的，同名一律跳过，绝不覆盖云盘已有文件
- 不删本地任何东西（要清理本地由用户自己决定）
- 上传后回读校验，缺了就报错
"""
import argparse
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

CLI = shutil.which("lark-cli") or "lark-cli"
MEDIA_EXT = (".mov", ".mp4", ".m4v", ".avi", ".mkv")
TOKEN_IN_URL = re.compile(r"/(?:drive/)?folder/([A-Za-z0-9]+)")
DATE_IN_NAME = re.compile(r"^(\d{2})\.(\d{1,2})\.(\d{1,2})-")


def date_from_names(names):
    """从文件名里的编号段推日期，如 26.9.14-MJ-182-1.mov -> (2026, 9, 14)。

    云盘日期文件夹必须跟着编号走，而不是跟着"今天"走——
    9月14日处理出来的 26.9.14-* 素材，就该躺在「9月14日」里，
    哪怕今天是 10 月某天。取众数，避免个别文件名不规范带偏。
    """
    c = collections.Counter()
    for n in names:
        m = DATE_IN_NAME.match(n)
        if m:
            c[(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))] += 1
    if not c:
        import datetime
        t = datetime.date.today()
        return t.year, t.month, t.day
    return c.most_common(1)[0][0]


def api(args):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    try:
        return json.loads(r.stdout), None
    except Exception:
        err = (r.stderr or r.stdout or "").strip().replace("\n", " ")
        return None, err[:300]


def list_all(token):
    out, page, n = [], None, 0
    while True:
        params = {"folder_token": token, "page_size": 200}
        if page:
            params["page_token"] = page
        d, err = api(["drive", "files", "list", "--params", json.dumps(params)])
        if err:
            sys.exit("列出文件夹失败: " + err)
        data = d.get("data") or {}
        out += data.get("files") or []
        page = data.get("next_page_token")
        n += 1
        if not page or n > 20:
            break
    return out


def ensure_folder(parent, name, dry):
    for f in list_all(parent):
        if f.get("type") == "folder" and f.get("name") == name:
            return f["token"], False
    if dry:
        print("   [dry-run] 需要创建文件夹：%s" % name)
        return None, True
    d, err = api(["drive", "+create-folder", "--folder-token", parent, "--name", name])
    if err:
        sys.exit("创建文件夹 %s 失败: %s" % (name, err))
    tok = ((d.get("data") or {}).get("token")
           or (d.get("data") or {}).get("folder_token"))
    print("   已创建文件夹：%s" % name)
    return tok, True


def scan_local(dirs, prefix):
    found = {}
    for d in dirs:
        if not os.path.isdir(d):
            print("   目录不存在，跳过：" + d)
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.startswith(prefix) and os.path.splitext(f)[1].lower() in MEDIA_EXT:
                    if f in found:
                        print("   警告：同名文件出现在两处 -> " + f)
                    found[f] = os.path.join(root, f)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="「拍摄原片」文件夹的 URL 或 token")
    ap.add_argument("--dirs", nargs="+", required=True, help="本地素材目录（会递归扫描）")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    ap.add_argument("--prefix", default="26.", help="已命名素材的文件名前缀")
    ap.add_argument("--limit", type=int, default=0, help="最多传几个（0=全部）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    m = TOKEN_IN_URL.search(args.root)
    root = m.group(1) if m else args.root

    local = scan_local(args.dirs, args.prefix)
    print("本地已命名素材 %d 个" % len(local))

    if args.date:
        y, mo, d = (int(x) for x in args.date.split("-"))
        src = "命令行指定"
    else:
        y, mo, d = date_from_names(local)
        src = "从文件名编号段推断"
    year_name = "%d年拍摄素材" % y
    day_name = "%d月%d日" % (mo, d)
    print("目标路径：拍摄原片 / %s / %s   （日期来源：%s）" % (year_name, day_name, src))

    year_tok, _ = ensure_folder(root, year_name, args.dry_run)
    if year_tok is None:
        print("（dry-run：年份文件夹还不存在，先不继续）")
        return
    day_tok, _ = ensure_folder(year_tok, day_name, args.dry_run)
    if day_tok is None:
        print("（dry-run：日期文件夹还不存在，先不继续）")
        return

    remote = {f.get("name") for f in list_all(day_tok)}
    print("云盘该文件夹现有 %d 个条目" % len(remote))

    todo = sorted(set(local) - remote)
    print("要上传 %d 个（同名的一律跳过）\n" % len(todo))
    if args.limit:
        todo = todo[:args.limit]

    if not todo:
        print("没有需要上传的文件，云盘已是最新。")
        return

    if args.dry_run:
        for n in todo:
            print("  [dry-run] " + n)
        print("\n共 %d 个待传。去掉 --dry-run 正式上传。" % len(todo))
        return

    ok, fail = [], []
    for i, name in enumerate(todo, 1):
        path = local[name]
        size = os.path.getsize(path) / 1024 / 1024
        d, err = api(["drive", "+upload", "--folder-token", day_tok,
                      "--file", path, "--name", name])
        if err:
            fail.append((name, err))
            print("  [%d/%d] 失败 %s -> %s" % (i, len(todo), name, err))
        else:
            ok.append(name)
            print("  [%d/%d] 已上传 %s (%.1f MB)" % (i, len(todo), name, size), flush=True)

    after = {f.get("name") for f in list_all(day_tok)}
    missing = [n for n in ok if n not in after]
    print("\n成功 %d 个，失败 %d 个" % (len(ok), len(fail)))
    for n, e in fail:
        print("  失败：%s -> %s" % (n, e))
    if missing:
        sys.exit("回读校验失败，以下文件没出现在云盘：%s" % missing)
    print("回读校验通过，云盘现有 %d 个条目。" % len(after))


if __name__ == "__main__":
    main()
