#!/usr/bin/env python3
"""从素材总表读"原片编号"列，与匹配结果合并，生成最终改名 plan。

用法:
    python sheet_ids.py --url "<表格URL>" --sheet-id Amvc8S --id-column I \
        --start-row 192 --plan plan.json --out plan_rename.json

这是整条链路的关键一环：文件名要用**表格里已有的编号**，不是自己按顺序拼的。
表里的编号可能跳号或带后缀（26.9.14-MJ-192-1），只有读出来才作数。

前提约定：plan 按脚本编号升序排列，表格行也按同一顺序排布，
第 start_row + i 行对应 plan[i]。
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


def lark(args):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI, "sheets"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    if r.returncode != 0:
        sys.exit("lark-cli 失败:\n" + (r.stderr or r.stdout))
    return json.loads(r.stdout)


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
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--id-column", default="I")
    ap.add_argument("--sheet-column", default=None,
                    help="脚本内容列；给了就顺带校验该行脚本已填，没填会警告")
    ap.add_argument("--start-row", type=int, required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", default="plan_rename.json")
    ap.add_argument("--media", default=None, help="若 plan 里没有目录，用它补上")
    args = ap.parse_args()

    plan = json.load(open(args.plan, encoding="utf-8-sig"))
    plan.sort(key=lambda p: p["code"])

    ic = args.id_column.upper()
    end = args.start_row + len(plan) - 1
    cols = "A%d:%s%d" % (args.start_row, ic, end)
    rows = parse_rows(lark(["+csv-get", "--url", args.url, "--sheet-id", args.sheet_id,
                            "--range", cols])["data"]["annotated_csv"])

    out, problems = [], []
    for i, p in enumerate(plan):
        row = args.start_row + i
        vals = rows.get(row, [])
        idx = ord(ic) - ord("A")
        oid = (vals[idx] if len(vals) > idx else "").strip()
        if not oid:
            problems.append("第%d行 %s 的编号列(%s)为空" % (row, p["code"], ic))
            continue
        if args.sheet_column:
            si = ord(args.sheet_column.upper()) - ord("A")
            if not ((vals[si] if len(vals) > si else "") or "").strip():
                problems.append("第%d行 %s 的脚本内容列(%s)还是空的" % (row, p["code"], args.sheet_column))
        item = dict(p)
        item["row"] = row
        item["id"] = oid
        item["new"] = oid + ".mov"
        if args.media and "dir" not in item:
            item["dir"] = args.media
        out.append(item)

    print("读取 %s%d:%s%d，共 %d 行" % (ic, args.start_row, ic, end, len(plan)))
    for p in out:
        print("  第%-4d行  %-6s  %s  <- %s" % (p["row"], p["code"], p["new"], p["uuid8"]))

    names = [p["new"] for p in out]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        problems.append("编号重复: " + " ".join(sorted(dup)))

    if problems:
        print("\n发现 %d 个问题:" % len(problems))
        for x in problems:
            print("  - " + x)
        if dup:
            sys.exit("编号重复，不能继续")
        print("  （编号为空的行可能是还没排上，确认后可以只处理有编号的部分）")

    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    csvp = os.path.splitext(args.out)[0] + ".csv"
    with open(csvp, "w", encoding="utf-8-sig") as f:
        f.write("表格行号,脚本编号,原片编号,新文件名,原素材\n")
        for p in out:
            f.write("%d,%s,%s,%s,%s\n" % (p["row"], p["code"], p["id"], p["new"], p["old"]))
    print("\n写出 %s 与 %s" % (args.out, csvp))
    print("下一步: python rename_atomic.py %s --media \"<素材目录>\"  先预演再 --apply" % args.out)


if __name__ == "__main__":
    main()
