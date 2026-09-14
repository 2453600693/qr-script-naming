#!/usr/bin/env python3
"""把 ASR 转写结果与脚本文案对号入座，并用拍摄时间做交叉验证。

用法:
    # 一对一：素材与脚本本来一一对应（一批素材对应一批脚本）
    python match_and_plan.py --scripts scripts.json --asr work/asr_办公室.json \
        --media "D:\\...\\办公室" --section 办公室 --out plan.json

    # 多对一：素材池比脚本多，要挑出属于这些脚本的素材
    #（同一条脚本可能拍了好几条原片，这就是"原片数"的来源）
    python match_and_plan.py --scripts scripts.json --asr work/asr_all.json \
        --section MJ --mode match --min-score 0.45 --out plan.json

也支持按素材总表的行号生成编号：
    ... --row-start 192 --id-template "26.9.14-MJ-{row}-1"

输出 plan.json: [{old, new, code, section, score, rank?, of?, uuid8, row?}]
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
    if len(tb) < w * 0.4:
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
    ap.add_argument("--mode", choices=["assign", "match"], default="assign",
                    help="assign=一对一（素材与脚本一一对应）；"
                         "match=多对一（同一条脚本可有多条原片）")
    ap.add_argument("--min-score", type=float, default=0.45,
                    help="match 模式下的采纳阈值，低于它的素材视为不属于本脚本池")
    ap.add_argument("--template", default="{code}_{headline}.mov")
    ap.add_argument("--row-start", type=int, default=None)
    ap.add_argument("--id-template", default=None, help="如 '26.9.14-MJ-{row}-1'")
    ap.add_argument("--out", default="plan.json")
    ap.add_argument("--min-gap", type=float, default=0.08)
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

    print("脚本池 %d 条，素材 %d 条，模式 %s" % (len(scripts), len(names), args.mode))

    M = np.zeros((len(A), len(B)))
    for i, sa in enumerate(A):
        for j, tb in enumerate(B):
            M[i, j] = score(sa, tb)

    def make_item(n, j, sc, cands, rank=None, of=None):
        tpl = args.id_template
        row = (args.row_start + len(plan)) if (tpl and args.row_start) else None
        code, hl = scripts[j]["code"], headline(scripts[j]["text"])
        if tpl and row is not None:
            new = ILLEGAL.sub("", tpl.format(row=row, code=code, headline=hl, no=row)) + ".mov"
        else:
            new = ILLEGAL.sub("", args.template.format(code=code, headline=hl, no=0))
        it = {"old": n, "new": new, "code": code, "section": scripts[j]["section"],
              "score": round(float(sc), 3), "uuid8": n[:8], "cands": cands}
        if rank is not None:
            it["rank"], it["of"] = rank, of
        if row is not None:
            it["row"] = row
        return it

    plan, review, unmatched = [], [], []

    if args.mode == "match":
        # 每条素材取最高分脚本，够阈值就采纳，允许多条素材落到同一脚本
        picked = {}
        for i, n in enumerate(names):
            j = int(np.argmax(M[i]))
            top = sorted(range(len(B)), key=lambda k: -M[i, k])[:3]
            cands = [(scripts[k]["code"], round(float(M[i, k]), 3)) for k in top]
            if M[i, j] < args.min_score:
                unmatched.append({"old": n, "uuid8": n[:8],
                                  "best": round(float(M[i, j]), 3), "cands": cands})
                continue
            picked.setdefault(j, []).append((float(M[i, j]), n, cands))
        for j, lst in picked.items():
            lst.sort(key=lambda x: -x[0])
            for k, (sc, n, cands) in enumerate(lst, 1):
                plan.append(make_item(n, j, sc, cands, rank=k, of=len(lst)))
        plan.sort(key=lambda p: (p["code"], p["rank"]))
    else:
        rows_idx, cols_idx = linear_sum_assignment(-M)
        assign = dict(zip(rows_idx.tolist(), cols_idx.tolist()))
        for i, n in enumerate(names):
            top = sorted(range(len(B)), key=lambda k: -M[i, k])[:3]
            cands = [(scripts[k]["code"], round(float(M[i, k]), 3)) for k in top]
            if i not in assign:
                unmatched.append({"old": n, "uuid8": n[:8],
                                  "best": round(float(M[i, top[0]]), 3), "cands": cands})
                continue
            j = assign[i]
            plan.append(make_item(n, j, M[i, j], cands))
        plan.sort(key=lambda x: x["code"])

    used = {p["code"] for p in plan}
    missing = [s["code"] for s in scripts if s["code"] not in used]

    print("\n分配结果:")
    for p in plan:
        gap = p["cands"][0][1] - p["cands"][1][1] if len(p["cands"]) > 1 else 1
        flag = "  <== 需复核" if (p["score"] < 0.55 or gap < args.min_gap) else ""
        tag = " [原片%d/%d]" % (p["rank"], p["of"]) if "rank" in p else ""
        print("  %-9s %.3f%s  %s%s" % (p["code"], p["score"], tag, p["old"], flag))

    if missing:
        print("\n没有素材的脚本（缺拍）: " + " ".join(missing))

    if unmatched:
        print("\n未匹配到本脚本池的素材 %d 个（可能是别的拍摄人/别章节的）:" % len(unmatched))
        for u in unmatched:
            print("  %-22s 最高分 %.3f  %s" % (
                u["old"][:22], u["best"], ", ".join("%s %.3f" % c for c in u["cands"][:2])))

    if args.media:
        print("\n拍摄时间交叉验证:")
        rec = []
        for p in plan:
            path = os.path.join(args.media, p["old"])
            ct = creation_time(path) if os.path.exists(path) else ""
            rec.append((ct, p))
        rec.sort(key=lambda x: x[0])
        for ct, p in rec:
            print("  %s  %-9s  %s" % (ct.replace("Z", "")[:19], p["code"], p["old"][:30]))

    json.dump(plan, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    csvp = os.path.splitext(args.out)[0] + ".csv"
    with open(csvp, "w", encoding="utf-8-sig") as f:
        f.write("脚本编号,章节,原片序号,该脚本原片数,置信度,原素材\n")
        for p in plan:
            f.write("%s,%s,%s,%s,%.3f,%s\n" % (
                p["code"], p["section"], p.get("rank", 1), p.get("of", 1), p["score"], p["old"]))

    print("\n写出 %s 与 %s" % (args.out, csvp))
    if review:
        print("需人工确认 %d 条。" % len(review))


if __name__ == "__main__":
    main()
