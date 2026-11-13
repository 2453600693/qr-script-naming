#!/usr/bin/env python3
"""用「表格里已有的脚本文案」当锚点，反查每条原片该落到哪一行。

解决的是这一类情况：运营提的需求（比如志良）已经在表里占了一行、脚本内容也填好了，
我们后来才拍，缺的只是原片编号。这时不能新建行、也不能删行，只能回到那一行去补。

用法:
    python locate_rows.py --url "<表格URL>" --sheet-id Amvc8S --range A170:N195 \
        --asr work/asr_all.json --min-score 0.45 --out plan_located.json

铁律：已经有「最终视频成品」的行一律不动。
    这些行是已交付的内容，脚本文案照样能当锚点参考，但默认不会被命中——
    命中并把编号/文案写回去，会打乱成品与原片的对应关系，而且不可逆。
    确实要覆盖时显式加 --allow-finished，并且应当先问过用户。
    同理，第 1 行表头不参与锚点。

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
# 成品列识别：表头里带这两个词就算
FINISH_WORDS = ("最终视频成品", "成品", "成片")


def lark(args):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI, "sheets"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    if r.returncode != 0:
        sys.exit("lark-cli 失败:\n" + (r.stderr or r.stdout))
    return json.loads(r.stdout.lstrip("\ufeff"))


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


def find_finish_cols(header):
    """按表头找出所有「成品」相关列的索引。

    实测表头是 K=成片时间、L=最终视频成品。只认「成品」会漏掉只填了成片时间的情况，
    所以两个词都收，任一非空就视为该行已交付。
    """
    idxs = []
    for i, name in enumerate(header):
        n = (name or "").strip()
        if any(w in n for w in FINISH_WORDS):
            idxs.append(i)
    return idxs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--range", default=None,
                    help="锚点区域，如 A170:N195；不传则扫全表（A1:N2000），"
                         "这样不管脚本属于哪个拍摄人都能命中")
    ap.add_argument("--asr", required=True, help="asr_batch.py 的输出")
    ap.add_argument("--text-column", default="F", help="已有脚本文案的列")
    ap.add_argument("--id-column", default="I", help="原片编号列")
    ap.add_argument("--who-column", default="A", help="需求创建人列")
    ap.add_argument("--finish-column", default=None,
                    help="成品列字母，如 L；不传则按表头自动识别（推荐）")
    ap.add_argument("--allow-finished", action="store_true",
                    help="允许命中已有最终成品的行。默认禁止——那会打乱已交付的成品")
    ap.add_argument("--header-row", type=int, default=1, help="表头行号，默认 1")
    ap.add_argument("--min-score", type=float, default=0.45)
    ap.add_argument("--only-empty-id", action="store_true",
                    help="只考虑编号列为空的行（补编号场景）")
    ap.add_argument("--out", default="plan_located.json")
    args = ap.parse_args()

    tc, ic, wc = col_idx(args.text_column), col_idx(args.id_column), col_idx(args.who_column)
    scan_range = args.range or "A1:N2000"
    print("扫描范围：%s%s" % (scan_range, "" if args.range else "（全表）"))

    rows = read_rows(args.url, args.sheet_id, scan_range)

    if args.finish_column:
        finish_cols = [col_idx(args.finish_column)]
    else:
        header = next((f for r, f in rows if r == args.header_row), [])
        finish_cols = find_finish_cols(header)
        if finish_cols:
            names = ["%s(%s)" % (chr(65 + i) if i < 26 else "?", (header[i] or "").strip())
                     for i in finish_cols]
            print("成品列：%s -> %s" % (
                " ".join(names),
                "允许命中" if args.allow_finished else "有值的行一律不动"))
        else:
            print("警告：表头里没认出成品列，无法保护已交付的行。"
                  "建议用 --finish-column 显式指定（如 L）")

    anchors, skipped_finished = [], 0
    for row, f in rows:
        if row == args.header_row:
            continue
        while len(f) <= max([tc, ic, wc] + finish_cols):
            f.append("")
        if not f[tc].strip():
            continue
        if not args.allow_finished and any(f[i].strip() for i in finish_cols):
            skipped_finished += 1
            continue
        if args.only_empty_id and f[ic].strip():
            continue
        anchors.append({"row": row, "who": f[wc].strip(), "text": f[tc].strip(),
                        "id": f[ic].strip(), "raw": f})

    if skipped_finished:
        print("已跳过 %d 行：这些行已有最终成品，不动" % skipped_finished)
    if not anchors:
        sys.exit("锚点区域里没有可用的脚本文案，检查 --range 和 --text-column；"
                 "若全表都已有成品，说明这批素材应当新开行（走 match_and_plan.py 路线 A）")

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
    ambiguous = []
    for p in plan:
        tail = ""
        if p.get("second"):
            r2, s2 = p["second"]
            gap = p["score"] - s2
            tail = "   次优=第%d行 %.3f" % (r2, s2)
            if gap < 0.08:
                tail += "  <== 分差仅 %.2f，需人工确认" % gap
                ambiguous.append(p)
        print("  第%-4d行 [%s] %-20s 第%d/%d条 %.3f%s  该行编号=%s" % (
            p["row"], p["who"] or "?", p["old"][:20], p["rank"], p["of"],
            p["score"], tail, p["existing_id"] or "(空)"))

    if ambiguous:
        print("\n有 %d 条命中同一脚本的多处历史行，请确认该落哪一行：" % len(ambiguous))
        for p in ambiguous:
            print("  %-20s -> 第%d行(%.3f) vs 第%d行(%.3f)" % (
                p["old"][:20], p["row"], p["score"], p["second"][0], p["second"][1]))

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
