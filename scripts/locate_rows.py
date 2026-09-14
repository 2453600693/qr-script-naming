#!/usr/bin/env python3
"""用「表格里已有的脚本文案」当锚点，反查每条原片该落到哪一行。

解决的是这一类情况：运营提的需求（比如志良）已经在表里占了一行、脚本内容也填好了，
我们后来才拍，缺的只是原片编号。这时不能新建行、也不能删行，只能回到那一行去补。

用法:
    python locate_rows.py --url "<表格URL>" --sheet-id Amvc8S --range A170:N195 \
        --asr work/asr_all.json --min-score 0.45 --out plan_located.json

输出 plan.json，可直接喂给 sheet_fill.py（补编号）或 rename_atomic.py（改名）。
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from match_and_plan import body, score   # 复用同一套归一化与滑窗相似度

CLI = shutil.which("lark-cli") or "lark-cli"
CJK = re.compile(r"[\u4e00-\u9fff]")


def lark(args):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI, "sheets"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    if r.returncode != 0:
        sys.exit("lark-cli 失败:\n" + (r.stderr or r.stdout))
    return json.loads(r.stdout)


def col_idx(letter):
    n = 0
    for ch in letter.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def read_rows(url, sid, rng):
    d = lark(["+csv-get", "--url", url, "--sheet-id", sid, "--range", rng])
    parts = re.split(r"\[row=(\d+)\] ", d["data"]["annotated_csv"])
    out = []
    for i in range(1, len(parts), 2):
        body_ = parts[i + 1]
        body_ = body_[:-1] if body_.endswith("\n") else body_
        f = next(csv.reader(io.StringIO(body_)))
        out.append((int(parts[i]), f))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--range", required=True, help="锚点区域，如 A170:N195")
    ap.add_argument("--asr", required=True, help="asr_batch.py 的输出")
    ap.add_argument("--text-column", default="F", help="已有脚本文案的列")
    ap.add_argument("--id-column", default="I", help="原片编号列")
    ap.add_argument("--who-column", default="A", help="需求创建人列")
    ap.add_argument("--min-score", type=float, default=0.45)
    ap.add_argument("--only-empty-id", action="store_true",
                    help="只考虑编号列为空的行（补编号场景）")
    ap.add_argument("--out", default="plan_located.json")
    args = ap.parse_args()

    tc, ic, wc = col_idx(args.text_column), col_idx(args.id_column), col_idx(args.who_column)
    anchors = []
    for row, f in read_rows(args.url, args.sheet_id, args.range):
        while len(f) <= max(tc, ic, wc):
            f.append("")
        if not f[tc].strip():
            continue
        if args.only_empty_id and f[ic].strip():
            continue
        anchors.append({"row": row, "who": f[wc].strip(), "text": f[tc].strip(),
                        "id": f[ic].strip(), "raw": f})
    if not anchors:
        sys.exit("锚点区域里没有可用的脚本文案，检查 --range 和 --text-column")

    asr = json.load(open(args.asr, encoding="utf-8-sig"))
    print("锚点行 %d 个，待定位原片 %d 条\n" % (len(anchors), len(asr)))

    plan, weak = [], []
    for name, raw in sorted(asr.items()):
        t = body(raw or "")
        if len(CJK.findall(t)) < 12:
            weak.append((name, "有效语音太少（可能是纯场记板）", None))
            continue
        sc = sorted(((score(t, body(a["text"])), a) for a in anchors), key=lambda x: -x[0])
        top = sc[0]
        if top[0] < args.min_score:
            weak.append((name, "最高分 %.3f 低于阈值" % top[0], top[1]))
            continue
        a = top[1]
        plan.append({"old": name, "row": a["row"], "who": a["who"], "score": round(top[0], 3),
                     "existing_id": a["id"], "code": a["text"][:18],
                     "second": (sc[1][1]["row"], round(sc[1][0], 3)) if len(sc) > 1 else None})

    # 同一条脚本可能多条原片：按行分组统计
    per = {}
    for p in plan:
        per.setdefault(p["row"], []).append(p)
    for row, lst in per.items():
        lst.sort(key=lambda x: -x["score"])
        for k, p in enumerate(lst, 1):
            p["rank"], p["of"] = k, len(lst)

    plan.sort(key=lambda p: (p["row"], p["rank"]))
    print("定位成功 %d 条：" % len(plan))
    for p in plan:
        print("  第%-3d行 [%s] %-20s 第%d/%d条  %.3f  该行现有编号=%s" % (
            p["row"], p["who"] or "?", p["old"][:20], p["rank"], p["of"],
            p["score"], p["existing_id"] or "(空)"))

    if weak:
        print("\n没能定位 %d 条：" % len(weak))
        for name, why, best in weak:
            extra = "  最接近: 第%d行" % best["row"] if best else ""
            print("  %-24s %s%s" % (name[:24], why, extra))

    json.dump(plan, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n写出: " + args.out)
    print("下一步：该行编号为空 -> 用 sheet_fill.py 补；已有编号 -> 直接 rename_atomic.py 改名")


if __name__ == "__main__":
    main()
