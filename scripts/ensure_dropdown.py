#!/usr/bin/env python3
"""确保模特名存在于目标表的下拉列表里；不在就追加进去。

背景：模特列通常是固定列表下拉（type=list）。素材按模特分文件夹时，
目录名就是模特名；如果这个模特是第一次出现，下拉里没有他，写进去会变成"无效值"。
本工具负责把新名字补进下拉选项。

用法:
    python ensure_dropdown.py --url "<表格URL>" --sheet-id Amvc8S --column H \
        --names "梁思思,杜少阳" --range-rows H2:H446

    # 只看缺哪些，不写
    python ensure_dropdown.py ... --dry-run

注意：写回时会把「原有选项 + 新增选项」整体提交，绝不删减原有选项。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

CLI = shutil.which("lark-cli") or "lark-cli"


def lark(args, **kw):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI, "sheets"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env, **kw)
    if r.returncode != 0:
        sys.exit("lark-cli 失败:\n" + (r.stderr or r.stdout))
    return json.loads(r.stdout)


def read_validation(url, sid, col, probe_row):
    d = lark(["+cells-get", "--url", url, "--sheet-id", sid,
              "--range", "%s%d" % (col, probe_row), "--include", "data_validation"])
    cell = d["data"]["ranges"][0]["cells"][0][0]
    return cell.get("data_validation")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--column", default="H", help="模特列")
    ap.add_argument("--names", required=True, help="逗号分隔的模特名")
    ap.add_argument("--range-rows", default=None,
                    help="下拉生效的整列范围，如 H2:H446；不给则用 --probe-row 所在格")
    ap.add_argument("--probe-row", type=int, default=2, help="用来读现有下拉的探针行")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    want = [x.strip() for x in args.names.split(",") if x.strip()]
    if not want:
        sys.exit("--names 为空")

    dv = read_validation(args.url, args.sheet_id, args.column, args.probe_row)
    if not dv:
        print("%s 列没有下拉设置，直接写值即可，无需新增选项。" % args.column)
        return
    if dv.get("type") != "list":
        print("%s 列的下拉类型是 %s（不是固定列表），需要人工确认怎么加选项。"
              % (args.column, dv.get("type")))
        return

    items = list(dv.get("items") or [])
    print("现有选项 %d 个" % len(items))
    missing = [n for n in want if n not in items]
    for n in want:
        print("  %-10s %s" % (n, "已有" if n in items else "缺失 -> 将追加"))
    if not missing:
        print("\n全部已存在，无需改动。")
        return

    items2 = items + missing
    rng = args.range_rows or "%s%d" % (args.column, args.probe_row)
    print("\n将向 %s 写入 %d 个选项（原有 %d + 新增 %d）" % (
        rng, len(items2), len(items), len(missing)))

    if args.dry_run:
        print("--dry-run：不写入。")
        return

    # 选项走相对路径文件，避开命令行长度与转义问题
    payload = "._dd_opts.json"
    json.dump(items2, open(payload, "w", encoding="utf-8"), ensure_ascii=False)
    try:
        cmd = ["+dropdown-set", "--url", args.url, "--sheet-id", args.sheet_id,
               "--range", rng, "--options", "@" + payload]
        if dv.get("support_multiple_values"):
            cmd += ["--multiple=true"]
        lark(cmd)
    finally:
        if os.path.exists(payload):
            os.remove(payload)

    dv2 = read_validation(args.url, args.sheet_id, args.column, args.probe_row)
    items_after = list(dv2.get("items") or [])
    ok = all(n in items_after for n in want)
    print("写入后选项 %d 个，新名字均已存在: %s" % (len(items_after), ok))
    lost = [x for x in items if x not in items_after]
    if lost:
        sys.exit("警告：原有选项丢失 %s，请立即人工核对" % lost)


if __name__ == "__main__":
    main()
