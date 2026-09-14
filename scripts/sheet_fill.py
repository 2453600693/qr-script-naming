#!/usr/bin/env python3
"""把脚本文案回填到飞书素材总表，并逐行回读校验。

用法:
    # 顺序填（plan 按脚本编号排列，从 start-row 往下）
    python sheet_fill.py --url "<表URL>" --sheet-id Amvc8S --column F --start-row 192 \
        --plan plan.json --scripts scripts.json --dry-run

    # 按 plan 自带的 row 填（业务分派场景：劳纠和团购分别落到各自的区块）
    python sheet_fill.py --url "<表URL>" --sheet-id Amvc8S --column F \
        --plan plan_assign.json --scripts scripts.json --dry-run

规矩（都是踩过的坑）：
- 先读后写：先 +workbook-info 拿 sheet_id，读表头确认"脚本内容"是哪一列。
- 先 --dry-run 看落区，再真写。
- 写完逐行回读比对，不抽查。多行文本最容易整体偏移。
- 走 +cells-set 的 JSON payload，不走 +csv-put，避免 CSV 转义把整块写错位。
- plan 自带 row 时以 row 为准：业务分派下"行序"不等于"脚本编号序"。
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

# Windows 上 lark-cli 是 .cmd 包装，必须用 which 解析出真实路径
CLI = shutil.which("lark-cli") or "lark-cli"


def lark(args, **kw):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI, "sheets"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env, **kw)
    if r.returncode != 0:
        sys.exit("lark-cli 失败:\n" + (r.stderr or r.stdout))
    try:
        return json.loads(r.stdout)
    except Exception:
        sys.exit("无法解析 lark-cli 输出:\n" + r.stdout[:2000])


def read_range(url, sid, rng):
    d = lark(["+csv-get", "--url", url, "--sheet-id", sid, "--range", rng])
    return d["data"]["annotated_csv"]


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
    ap.add_argument("--column", required=True, help="写入的列字母，如 F")
    ap.add_argument("--start-row", type=int, default=None,
                    help="plan 里没有 row 字段时，从这一行开始顺序填")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--scripts", default=None,
                    help="fetch_script.py 的输出，按 code 提供文案；plan 里已带 text 时可省")
    ap.add_argument("--out-map", default="write_map.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plan = json.load(open(args.plan, encoding="utf-8-sig"))
    scripts = {}
    if args.scripts:
        scripts = {s["code"]: s["text"]
                   for s in json.load(open(args.scripts, encoding="utf-8-sig"))}

    if all("row" in p for p in plan):
        plan.sort(key=lambda p: p["row"])
    elif args.start_row is not None:
        plan.sort(key=lambda p: p["code"])
    else:
        sys.exit("plan 里没有 row 字段时必须给 --start-row")

    col = args.column.upper()
    rows = []
    for i, p in enumerate(plan):
        row = p.get("row") or (args.start_row + i)
        text = p.get("text") or scripts.get(p["code"])
        if not text:
            sys.exit("第%s行 %s 没有内容：plan 里没给 text，scripts.json 里也没有该 code"
                     % (row, p.get("code", "?")))
        rows.append((row, p.get("code", ""), text))

    # 切成连续段，逐段写入（行号有可能不连续）
    segs, cur = [], []
    for r in rows:
        if cur and r[0] == cur[-1][0] + 1:
            cur.append(r)
        else:
            if cur:
                segs.append(cur)
            cur = [r]
    if cur:
        segs.append(cur)

    print("准备写入 %s!%s 列：%d 行，分 %d 段" % (args.sheet_id, col, len(rows), len(segs)))
    for r, code, text in rows:
        print("  第%-4d行 %-6s %s ..." % (r, code, text.replace("\n", " / ")[:44]))

    if args.dry_run:
        print("\n--dry-run：不写入。确认落区不会盖到相邻数据后，去掉 --dry-run 正式写。")
        return

    for seg in segs:
        rng = "%s%d:%s%d" % (col, seg[0][0], col, seg[-1][0])
        cells = [[{"value": t}] for _, _, t in seg]
        # lark-cli 的 @file 只接受「当前目录下的相对路径」，
        # 用 tempfile 写到系统临时目录会被拒（unsafe/absolute path not allowed）。
        payload = "._sheet_payload_%d.json" % os.getpid()
        json.dump(cells, open(payload, "w", encoding="utf-8"), ensure_ascii=False)
        try:
            res = lark(["+cells-set", "--url", args.url, "--sheet-id", args.sheet_id,
                        "--range", rng, "--cells", "@" + payload])
            print("写入 %s -> %s" % (rng, json.dumps(res.get("data", res), ensure_ascii=False)))
        finally:
            if os.path.exists(payload):
                os.remove(payload)

    # 逐行回读：读 A 列到目标列，取每行最后一个字段
    lo, hi = rows[0][0], rows[-1][0]
    got = parse_rows(read_range(args.url, args.sheet_id, "A%d:%s%d" % (lo, col, hi)))
    ok = bad = 0
    for row, code, text in rows:
        val = got.get(row, [])
        actual = val[len(val) - 1] if val else ""
        same = actual.strip() == text.strip()
        ok += same
        bad += (not same)
        if not same:
            print("  不一致 第%d行 %s\n    期望: %s\n    实际: %s" % (
                row, code, text.replace("\n", " / ")[:60], actual.replace("\n", " / ")[:60]))
    print("\n回读校验：一致 %d 条，不一致 %d 条" % (ok, bad))

    wm = [{"row": r, "code": c, "value": t} for r, c, t in rows]
    json.dump(wm, open(args.out_map, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("写入映射: " + args.out_map)

    if bad:
        sys.exit("存在不一致，请人工核对后再继续下一步")
    print("全部一致。下一步可用 sheet_ids.py 读表里的原片编号生成改名方案。")


if __name__ == "__main__":
    main()
