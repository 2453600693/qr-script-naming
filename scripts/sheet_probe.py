#!/usr/bin/env python3
"""探测素材总表的结构：有哪些 sheet、表头是什么列、目标行区间现在长什么样。

用法:
    python sheet_probe.py --url "<表格URL>"                          # 只列 sheet
    python sheet_probe.py --url "<表格URL>" --sheet-id Amvc8S --start-row 192 --rows 25

为什么必须先跑它：写表前必须知道"脚本内容"和"原片编号"具体是哪一列，
不能凭列序号猜。本脚本会顺带把候选列标出来。
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys

CLI = shutil.which("lark-cli") or "lark-cli"
LETTERS = [chr(ord("A") + i) for i in range(26)]


def lark(args):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI, "sheets"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    if r.returncode != 0:
        sys.exit("lark-cli 失败:\n" + (r.stderr or r.stdout))
    try:
        return json.loads(r.stdout)
    except Exception:
        sys.exit("无法解析 lark-cli 输出:\n" + r.stdout[:1500])


def parse_rows(annotated):
    out = {}
    parts = re.split(r"\[row=(\d+)\] ", annotated)
    for i in range(1, len(parts), 2):
        body = parts[i + 1]
        body = body[:-1] if body.endswith("\n") else body
        try:
            out[int(parts[i])] = next(csv.reader(io.StringIO(body)))
        except StopIteration:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--sheet-id", default=None)
    ap.add_argument("--header-row", type=int, default=1)
    ap.add_argument("--start-row", type=int, default=None)
    ap.add_argument("--rows", type=int, default=25)
    args = ap.parse_args()

    info = lark(["+workbook-info", "--url", args.url])["data"]
    print("工作簿: %s" % info.get("title"))
    print("sheet 列表:")
    for s in info["sheets"]:
        mark = "  <== 本次目标" if s["sheet_id"] == args.sheet_id else ""
        print("  %-8s %-14s 行数 %-5s%s" % (s["sheet_id"], s["sheet_name"], s["row_count"], mark))

    if not args.sheet_id:
        print("\n未指定 --sheet-id。从上表挑一个再跑一次，带上 --start-row 看目标区间。")
        return

    csv_text = lark(["+csv-get", "--url", args.url, "--sheet-id", args.sheet_id,
                     "--range", "A%d:T%d" % (args.header_row, args.header_row)])["data"]["annotated_csv"]
    head = parse_rows(csv_text).get(args.header_row, [])
    print("\n表头（第 %d 行）:" % args.header_row)
    cand = {"脚本": [], "编号": []}
    for i, v in enumerate(head):
        v = (v or "").strip()
        if not v:
            continue
        print("  %-2s %s" % (LETTERS[i], v.replace("\n", " ")[:40]))
        if "脚本" in v or "文案" in v:
            cand["脚本"].append(LETTERS[i])
        if "编号" in v or "原片" in v:
            cand["编号"].append(LETTERS[i])
    print("\n候选列 -> 脚本内容列: %s   原片编号列: %s" % (
        ",".join(cand["脚本"]) or "未识别到，请人工确认",
        ",".join(cand["编号"]) or "未识别到，请人工确认"))

    if args.start_row:
        end = args.start_row + args.rows - 1
        txt = lark(["+csv-get", "--url", args.url, "--sheet-id", args.sheet_id,
                    "--range", "A%d:T%d" % (args.start_row, end)])["data"]["annotated_csv"]
        rows = parse_rows(txt)
        print("\n第 %d 到 %d 行现状:" % (args.start_row, end))
        for n in sorted(rows):
            vals = rows[n]
            brief = " | ".join(
                "%s=%s" % (LETTERS[i], (v or "").replace("\n", " ")[:18])
                for i, v in enumerate(vals) if (v or "").strip())
            print("  [%d] %s" % (n, brief or "（整行空）"))


if __name__ == "__main__":
    main()
