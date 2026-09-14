#!/usr/bin/env python3
"""把 ASR 转写结果与脚本文案对号入座，并用拍摄时间做交叉验证。

用法:
    python match_and_plan.py --scripts scripts.json --asr work/asr_办公室.json \
        --media "D:\\...\\办公室" --section 办公室 --out plan_办公室.json

也支持按素材总表的行号生成编号（回填表格场景）：
    ... --row-start 192 --id-template "26.9.14-MJ-{row}-1"

输出 plan.json: [{old, new, code, section, score, uuid8, row?}]
可同时被 rename_atomic.py（改文件名）和 sheet_fill.py（回填表格）使用。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from difflib import SequenceMatcher

import numpy as np
from scipy.optimize import linear_sum_assignment

NOISE = re.compile(r"（[^）]*）|\([^)]*\)|【[^】]*】|\[[^\]]*\]")
ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def strip_punct(s):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9N+]", "", s)


def body(t):
    """归一化用于比对的正文。"""
    return strip_punct(NOISE.sub("", t).replace("\n", ""))


def headline(t, limit=24):
    """取文案首句做文件名。首句过短时补下一句；过长时按分句边界回退，不产生残字。"""
    t = NOISE.sub("", t).replace("\n", "。")
    sents = [strip_punct(x) for x in re.split(r"[。！？?!；;]", t)]
    sents = [x for x in sents if x]
    if not sents:
        return strip_punct(t)[:limit]
    s = sents[0]
    if len(s) < 8 and len(sents) > 1:
        s += sents[1]
    if len(s) <= limit:
        return s
    acc = ""
    for cl in [strip_punct(x) for x in re.split(r"[，,]", t) if strip_punct(x)]:
        if len(acc) + len(cl) > limit:
            break
        acc += cl
    return acc or s[:limit]


def score(sa, tb):
    """ASR 文本对脚本文案的最大滑窗相似度。用整体相似度而非逐字相等，容忍 ASR 错字。"""
    if not sa or not tb:
        return 0.0
    w = len(sa)
    if len(tb) < w * 0.4:      # 长度差太远，不可能是同一条
        return 0.0
    best, hi = 0.0, min(max(0, len(tb) - w), 80)
    for a in range(hi + 1):
        r = SequenceMatcher(None, sa, tb[a:a + w]).ratio()
        if r > best:
            best = r
    return best


def creation_time(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts", required=True, help="fetch_script.py 的输出")
    ap.add_argument("--asr", required=True, help="asr_batch.py 的输出")
    ap.add_argument("--media", default=None, help="素材目录（做拍摄时间交叉验证）")
    ap.add_argument("--section", default=None, help="限定章节；不传则用全部章节做池子")
    ap.add_argument("--template", default="{code}_{headline}.mov")
    ap.add_argument("--row-start", type=int, default=None, help="素材总表的起始行号")
    ap.add_argument("--id-template", default=None, help="如 '26.9.14-MJ-{row}-1'")
    ap.add_argument("--out", default="plan.json")
    ap.add_argument("--min-gap", type=float, default=0.08, help="最优与次优的最小分差，低于则标记需复核")
    args = ap.parse_args()

    scripts = json.load(open(args.scripts, encoding="utf-8-sig"))
    if args.section:
        scripts = [s for s in scripts if s["section"] == args.section]
    if not scripts:
        sys.exit("脚本文案池为空，检查 --section 名称是否与文档里的章节标题一致")

    asr = json.load(open(args.asr, encoding="utf-8-sig"))
    names = sorted(asr)
    A = [body(asr[n]) for n in names]
    B = [body(s["text"]) for s in scripts]

    print("脚本池 %d 条，素材 %d 条" % (len(scripts), len(names)))

    M = np.zeros((len(A), len(B)))
    for i, sa in enumerate(A):
        for j, tb in enumerate(B):
            M[i, j] = score(sa, tb)

    rows_idx, cols_idx = linear_sum_assignment(-M)
    assign = dict(zip(rows_idx.tolist(), cols_idx.tolist()))

    plan, review = [], []
    for i, n in enumerate(names):
        j = assign[i]
        top = sorted(range(len(B)), key=lambda k: -M[i, k])[:3]
        gap = M[i, top[0]] - M[i, top[1]] if len(top) > 1 else 1.0
        tpl = args.id_template
        row = (args.row_start + i) if args.row_start else None
        code, hl = scripts[j]["code"], headline(scripts[j]["text"])
        if tpl and row is not None:
            new = ILLEGAL.sub("", tpl.format(row=row, code=code, headline=hl, no=i + 1)) + ".mov"
        else:
            new = ILLEGAL.sub("", args.template.format(code=code, headline=hl, no=i + 1))
        item = {"old": n + ".mov", "new": new, "code": code, "section": scripts[j]["section"],
                "score": round(float(M[i, j]), 3), "uuid8": n[:8],
                "cands": [(scripts[k]["code"], round(float(M[i, k]), 3)) for k in top]}
        if row is not None:
            item["row"] = row
        plan.append(item)
        if M[i, j] < 0.55 or gap < args.min_gap:
            review.append((n, item, gap))

    plan.sort(key=lambda x: x["code"])
    used = {p["code"] for p in plan}
    missing = [s["code"] for s in scripts if s["code"] not in used]

    print("\n分配结果:")
    for p in plan:
        flag = ""
        gap = p["cands"][0][1] - p["cands"][1][1] if len(p["cands"]) > 1 else 1
        if p["score"] < 0.55 or gap < args.min_gap:
            flag = "  <== 需复核"
        print("  %-6s [%s] %.3f  %s  <- %s%s" % (
            p["code"], p["section"], p["score"], p["new"], p["uuid8"], flag))

    if missing:
        print("\n没有素材的脚本（缺拍）: " + " ".join(missing))

    if args.media:
        print("\n拍摄时间交叉验证:")
        rec = []
        for p in plan:
            path = os.path.join(args.media, p["old"])
            ct = creation_time(path) if os.path.exists(path) else ""
            rec.append((ct, p))
        rec.sort(key=lambda x: x[0])
        prev, bad = None, []
        for ct, p in rec:
            no = int(re.sub(r"\D", "", p["code"]) or 0)
            mark = ""
            if prev is not None and no < prev:
                mark = "   <<< 与拍摄时间逆序"
                bad.append(p["code"])
            print("  %s  %-6s  %s%s" % (ct.replace("Z", "")[:19], p["code"], p["uuid8"], mark))
            prev = max(prev, no) if prev is not None else no
        if bad:
            print("  逆序 %d 条: %s" % (len(bad), " ".join(bad)))
            print("  （少量逆序通常是当天补拍，属正常；大面积逆序说明匹配不可信）")
        else:
            print("  全部单调递增，与 ASR 匹配结果一致")

    json.dump(plan, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    csv_path = os.path.splitext(args.out)[0] + ".csv"
    with open(csv_path, "w", encoding="utf-8-sig") as f:
        f.write("脚本编号,章节,新文件名,原文件名,置信度\n")
        for p in plan:
            f.write("%s,%s,%s,%s,%.3f\n" % (p["code"], p["section"], p["new"], p["old"], p["score"]))

    print("\n写出 %s 与 %s" % (args.out, csv_path))
    if review:
        print("需人工确认 %d 条，请连同对照表一起交给用户。" % len(review))
    else:
        print("全部条目置信度充分。给出对照表，等用户确认后再落盘。")


if __name__ == "__main__":
    main()
