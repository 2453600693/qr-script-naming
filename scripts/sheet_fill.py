#!/usr/bin/env python3
"""把脚本文案回填到飞书素材总表，并逐行回读校验。

用法:
    python sheet_fill.py --url "<表格URL>" --sheet-id Amvc8S --column F --start-row 192 \
        --plan plan_办公室.json --scripts scripts.json --dry-run
    # 去掉 --dry-run 正式写

规矩（都是踩过的坑）：
- 先读后写：先 +workbook-info 拿 sheet_id，读表头确认"脚本内容"是哪一列。
- 先 --dry-run 看落区，再真写。
- 写完逐行回读比对，不抽查。多行文本最容易整体偏移。
- 走 +cells-set 的 JSON payload，不走 +csv-put，避免 CSV 转义把整块写错位。
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
import tempfile

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
    ap.add_argument("--start-row", type=int, required=True)
    ap.add_argument("--plan", required=True, help="match_and_plan.py 的输出，按顺序逐行填")
    ap.add_argument("--scripts", required=True, help="fetch_script.py 的输出，提供文案")
    ap.add_argument("--out-map", default="write_map.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plan = json.load(open(args.plan, encoding="utf-8-sig"))
    scripts = {s["code"]: s["text"] for s in json.load(open(args.scripts, encoding="utf-8-sig"))}

    col = args.column.upper()
    start, end = args.start_row, args.start_row + len(plan) - 1
    rng = "%s%d:%s%d" % (col, start, col, end)

    rows, cells, wm = [], [], []
    for i, p in enumerate(plan):
        row = start + i
        text = scripts.get(p["code"])
        if not text:
            sys.exit("scripts.json 里没有 %s 的文案" % p["code"])
        rows.append((row, p["code"], text))
        cells.append([{"value": text}])
        wm.append({"row": row, "code": p["code"], "value": text,
                   "id": p.get("id", "")})

    print("准备写入 %s!%s：%d 行（第 %d 到 %d 行）" % (args.sheet_id, rng, len(rows), start, end))
    for row, code, text in rows[:3]:
        print("  第%d行 %s: %s ..." % (row, code, text.replace("\n", " / ")[:52]))
    print("  ...")
    for row, code, text in rows[-1:]:
        print("  第%d行 %s: %s ..." % (row, code, text.replace("\n", " / ")[:52]))

    if args.dry_run:
        print("\n--dry-run：不写入。确认落区不会盖到相邻数据后，去掉 --dry-run 正式写。")
        return

    fd, payload = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    json.dump(cells, open(payload, "w", encoding="utf-8"), ensure_ascii=False)
    try:
        res = lark(["+cells-set", "--url", args.url, "--sheet-id", args.sheet_id,
                    "--range", rng, "--cells", "@" + payload])
        print("写入返回: %s" % json.dumps(res.get("data", res), ensure_ascii=False))
    finally:
        os.remove(payload)

    # 逐行回读：读 A 列到目标列，取每行最后一个字段
    got = parse_rows(read_range(args.url, args.sheet_id, "A%d:%s%d" % (start, col, end)))
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

    json.dump(wm, open(args.out_map, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("写入映射: " + args.out_map)

    if bad:
        sys.exit("存在不一致，请人工核对后再继续下一步")
    print("全部一致。若接下来要按表编号重命名视频，可用 plan 里的 row 生成编号。")


if __name__ == "__main__":
    main()
