#!/usr/bin/env python3
"""把本地已命名的原片素材上传到飞书云盘。

云盘现有结构（照现有习惯，不自己发明层级）：
    拍摄原片 > {YYYY}年拍摄素材 > {M}月{D}日 > 原片
注意：日期文件夹一律 `M月D日` 且不补零（如 11月3日，不是 11月03日）。

用法:
    # 先看要传哪些，不写
    python upload_to_drive.py --root "<文件夹URL或token>" --dirs "D:\\原片素材\\9.14\\梁思思" --dry-run

    # 真传
    python upload_to_drive.py --root "<...>" --dirs "..."

--root 给哪一层都行，脚本先认清它自己的身份再决定往哪放：
    - 给的是「日期」层且与素材日期一致  -> 直接传进这一层，一个文件夹都不建
    - 给的是「日期」层但与素材日期不符  -> 报错停下，别在别人日期文件夹里套娃
    - 给的是「年份」层                  -> 在这一层里找/建日期文件夹
    - 给的是「拍摄原片」层或其他上层    -> 找/建年份层，再找/建日期层

设计原则：
- 绝不重复建层：能复用现有文件夹就复用，名字按现有习惯匹配（含等价写法）
- 只传「本地有、云盘没有」的，同名一律跳过，绝不覆盖云盘已有文件
- 不删本地任何东西，也不删云盘任何东西
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

# 日期文件夹的各种写法都认，统一归一到 (月, 日)
DAY_PATTERNS = [
    re.compile(r"^(\d{1,2})月(\d{1,2})[日号]$"),
    re.compile(r"^(\d{1,2})[.\-](\d{1,2})$"),
    re.compile(r"^(\d{4})[.\-年](\d{1,2})[.\-月](\d{1,2})日?$"),
]
YEAR_PATTERNS = [
    re.compile(r"^(\d{4})年拍摄素材$"),
    re.compile(r"^(\d{4})年.(?:拍摄)?素材$"),
    re.compile(r"^(\d{4})年$"),
    re.compile(r"^(\d{4})$"),
]


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
        t = datetime.date.today()
        return t.year, t.month, t.day
    return c.most_common(1)[0][0]


def api(args):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    try:
        return json.loads(r.stdout.lstrip("\ufeff")), None
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
        data = (d or {}).get("data") or {}
        out += data.get("files") or []
        page = data.get("next_page_token")
        n += 1
        if not page or n > 20:
            break
    return out


def folders_of(token):
    return [f for f in list_all(token) if f.get("type") == "folder"]


def inspect_folder(token, raw_url=None):
    """认清一个文件夹自身的名字与类型——这是不重复建层的前提。"""
    url = raw_url or ("https://www.feishu.cn/drive/folder/%s" % token)
    d, err = api(["drive", "+inspect", "--url", url])
    if err:
        return {}
    data = (d or {}).get("data") or {}
    return {"title": (data.get("title") or "").strip(),
            "type": (data.get("type") or "").strip(),
            "token": data.get("token") or token}


def parse_day(name):
    """把各种写法的日期文件夹名归一成 (月, 日)，认不出返回 None。"""
    s = (name or "").strip()
    for i, p in enumerate(DAY_PATTERNS):
        m = p.match(s)
        if not m:
            continue
        if i == 2:                       # 带年写法，只取月日
            return int(m.group(2)), int(m.group(3))
        return int(m.group(1)), int(m.group(2))
    return None


def parse_year(name):
    """把各种写法的年份文件夹名归一成 2026 这样的整数，认不出返回 None。"""
    s = (name or "").strip()
    for p in YEAR_PATTERNS:
        m = p.match(s)
        if m:
            return int(m.group(1))
    return None


def day_style(names):
    """从现有日期文件夹名里学写法，别硬编码一种。

    实测「2026年拍摄素材」下 96 个文件夹清一色 `M月D日` 且不补零，
    但换个空间可能就是 `M.D`。学它的写法，生成的名字才能跟旁边对齐。
    """
    for n in names:
        if re.match(r"^\d{1,2}月\d{1,2}[日号]$", n or ""):
            return "cn"
        if re.match(r"^\d{1,2}[.\-]\d{1,2}$", n or ""):
            return "dot" if "." in n else "dash"
    return "cn"


def make_day_name(mo, d, style):
    if style == "dot":
        return "%d.%d" % (mo, d)
    if style == "dash":
        return "%d-%d" % (mo, d)
    return "%d月%d日" % (mo, d)


def make_year_name(y, existing):
    """年份文件夹也照现有写法：2026年拍摄素材 / 2026年素材 / 2026。"""
    for n in existing:
        if parse_year(n) == y:
            return n
    for n in existing:
        m = re.match(r"^(\d{4})(.*)$", n or "")
        if m:
            return "%d%s" % (y, m.group(2))
    return "%d年拍摄素材" % y


def find_day(folders, mo, d):
    for f in folders:
        pd = parse_day(f.get("name"))
        if pd == (mo, d):
            return f
    return None


def find_year(folders, y):
    for f in folders:
        if parse_year(f.get("name")) == y:
            return f
    return None


def ensure_folder(parent, name, dry):
    for f in folders_of(parent):
        if f.get("name") == name:
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


def resolve_day(root_token, raw_url, y, mo, d, dry):
    """认清 root 是日期层 / 年份层 / 还是更上层，再决定日期文件夹落哪。

    root 本身就是目标日期层时直接返回它自己，一个文件夹都不建。
    早期版本无条件把 root 当「拍摄原片」层，会在用户给出的「11月13日」里
    再建「2026年拍摄素材/11月13日」，纯属套娃。
    """
    info = inspect_folder(root_token, raw_url)
    title = info.get("title", "")
    target = (mo, d)
    folders = folders_of(root_token)

    root_day = parse_day(title)
    if root_day:
        if root_day == target:
            print("   给定位置本身就是目标日期文件夹「%s」，直接上传到这一层" % title)
            return root_token
        sys.exit(
            "给定文件夹是「%s」，与素材编号推出的日期「%d月%d日」不一致。\n"
            "  要么把 --root 换成 %d月%d日 那一层，要么换成它上层的「拍摄原片」或年份文件夹。"
            % (title, mo, d, mo, d))

    style = day_style([f.get("name") for f in folders])
    day_name = make_day_name(mo, d, style)

    hit = find_day(folders, mo, d)
    if hit:
        print("   日期文件夹已存在：%s（就在给定位置下）" % hit["name"])
        return hit["token"]

    root_year = parse_year(title)
    if root_year:
        print("   给定位置是年份文件夹「%s」" % title)
        if root_year != y:
            print("   注意：年份与素材日期 %d 年不一致，仍按给定位置处理" % y)
        return ensure_folder(root_token, day_name, dry)[0]

    year = find_year(folders, y)
    if year:
        print("   找到年份文件夹：%s" % year["name"])
        return ensure_folder(year["token"], day_name, dry)[0]

    print("   给定位置下既没有目标日期文件夹也没有年份文件夹，按上层处理")
    year_name = make_year_name(y, [f.get("name") for f in folders])
    year_tok, _ = ensure_folder(root_token, year_name, dry)
    if year_tok is None:
        return None
    return ensure_folder(year_tok, day_name, dry)[0]


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
    ap.add_argument("--root", required=True,
                    help="目标文件夹 URL 或 token；日期层/年份层/「拍摄原片」层都行")
    ap.add_argument("--dirs", nargs="+", required=True, help="本地素材目录（会递归扫描）")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认从文件名编号段推断")
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
    print("目标日期：%d年%d月%d日   （来源：%s）" % (y, mo, d, src))

    day_tok = resolve_day(root, args.root, y, mo, d, args.dry_run)
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
        # lark-cli 的 --file 只接受「当前目录下的相对路径」，
        # 传绝对路径会报 unsafe file path。上传前切到文件所在目录，用完切回来。
        cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(path))
            d, err = api(["drive", "+upload", "--folder-token", day_tok,
                          "--file", os.path.basename(path), "--name", name])
        finally:
            os.chdir(cwd)
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
