#!/usr/bin/env python3
"""两阶段原子重命名 + 回滚清单。

用法:
    python rename_atomic.py plan.json --media "D:\\...\\办公室"            # 预演，只打印
    python rename_atomic.py plan.json --media "D:\\...\\办公室" --apply    # 执行

plan.json 由 match_and_plan.py 生成，也可手写：[{old, new, dir?}, ...]

为什么两阶段：若"新名"恰好等于另一个"待改的旧名"，直接改会互相覆盖。
先全体转临时名，再转终名，就能任意置换。
"""
import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--media", default=None, help="素材目录（plan 内未逐条指定 dir 时使用）")
    ap.add_argument("--apply", action="store_true", help="真正执行；不带则只预演")
    ap.add_argument("--rollback", default=None, help="回滚清单输出路径，默认 plan 同名 .rollback.csv")
    args = ap.parse_args()

    plan = json.load(open(args.plan, encoding="utf-8-sig"))
    if not plan:
        sys.exit("plan 为空")

    groups = {}
    for p in plan:
        d = p.get("dir") or args.media
        if not d:
            sys.exit("条目没有目录：请用 --media 指定，或在 plan 里给每条加 dir")
        groups.setdefault(d, []).append(p)

    for d, items in groups.items():
        olds = [p["old"] for p in items]
        news = [p["new"] for p in items]
        if len(set(news)) != len(news):
            sys.exit("%s: 目标名有重复" % d)
        present = set(os.listdir(d))
        for o in olds:
            if o not in present:
                sys.exit("%s: 缺少源文件 %s" % (d, o))
        clash = [n for n in news if n in present and n not in olds]
        if clash:
            sys.exit("%s: 目标名与已有文件冲突: %s" % (d, clash[:5]))

    if not args.apply:
        print("预演（未改动任何文件）:")
        for d, items in groups.items():
            print("\n[%s] %d 条" % (d, len(items)))
            for p in items:
                extra = "  (第%s行 %s)" % (p["row"], p["code"]) if p.get("row") else \
                        ("  (%s)" % p.get("code", ""))
                print("  %s  ->  %s%s" % (p["old"], p["new"], extra))
        print("\n确认无误后加 --apply 执行。")
        return

    rolled = []
    for d, items in groups.items():
        for i, p in enumerate(items):
            os.replace(os.path.join(d, p["old"]), os.path.join(d, "__t%02d.mov" % i))
        for i, p in enumerate(items):
            os.replace(os.path.join(d, "__t%02d.mov" % i), os.path.join(d, p["new"]))
            rolled.append((d, p["new"], p["old"], p.get("row", ""), p.get("code", "")))
        left = [f for f in os.listdir(d) if f.startswith("__t")]
        if left:
            sys.exit("%s: 残留临时文件 %s" % (d, left))
        n_mov = len([f for f in os.listdir(d) if f.lower().endswith((".mov", ".mp4", ".m4v"))])
        print("[%s] 完成，目录内视频 %d 个" % (d, n_mov))

    rb = args.rollback or (os.path.splitext(args.plan)[0] + ".rollback.csv")
    with open(rb, "w", encoding="utf-8-sig") as f:
        f.write("目录,新文件名,原文件名,表格行号,脚本编号\n")
        for d, n, o, row, code in rolled:
            f.write("%s,%s,%s,%s,%s\n" % (d, n, o, row, code))
    print("回滚清单: %s (%d 条)" % (rb, len(rolled)))


if __name__ == "__main__":
    main()
