#!/usr/bin/env python3
"""从素材总表已有的行里，学出「拍摄人代号 -> 摄像师 / 需求创建人 / 剪辑师」。

不猜、不硬编码：扫描表里所有已填编号的行，按编号前缀分组统计众数。
某个代号在表里没有先例时，才需要问用户。

用法:
    python learn_people.py --url "<表格URL>" --sheet-id Amvc8S --out people.json

输出:
    {"MJ": {"需求创建人":"美君","摄像师":"美君","剪辑师":"孟导"}, "FF": {...}}
"""
import argparse
import collections
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys

CLI = shutil.which("lark-cli") or "lark-cli"
# 编号形如 26.9.14-MJ-182-1 / 26.9.14-FF-175
CODE = re.compile(r"^\d{2}\.\d+\.\d+-([A-Za-z\u4e00-\u9fff]+)-")
FIELDS = [("需求创建人", 0), ("摄像师", 6), ("剪辑师", 9)]


def lark(args):
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1",
               LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    r = subprocess.run([CLI, "sheets"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=env)
    if r.returncode != 0:
        sys.exit("lark-cli 失败:\n" + (r.stderr or r.stdout))
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--range", default="A1:N500")
    ap.add_argument("--out", default="people.json")
    ap.add_argument("--min-agree", type=float, default=0.9,
                    help="众数占比低于此值时警告")
    args = ap.parse_args()

    d = lark(["+csv-get", "--url", args.url, "--sheet-id", args.sheet_id,
              "--range", args.range])
    annotated = d["data"]["annotated_csv"]
    parts = re.split(r"\[row=(\d+)\] ", annotated)

    stat = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    rows_seen = 0
    for i in range(1, len(parts), 2):
        body = parts[i + 1]
        body = body[:-1] if body.endswith("\n") else body
        f = next(csv.reader(io.StringIO(body)))
        while len(f) < 10:
            f.append("")
        m = CODE.match(f[8].strip())
        if not m:
            continue
        rows_seen += 1
        code = m.group(1)
        for name, idx in FIELDS:
            v = f[idx].strip()
            if v and v != "/":
                stat[code][name][v] += 1

    people, warnings = {}, []
    for code, keys in sorted(stat.items()):
        people[code] = {}
        for name, _ in FIELDS:
            c = keys.get(name)
            if not c:
                warnings.append("[%s] %s 在表里没有先例，需要问用户" % (code, name))
                continue
            best, n = c.most_common(1)[0]
            ratio = n / sum(c.values())
            people[code][name] = best
            if ratio < args.min_agree:
                warnings.append("[%s] %s 众数 %s 只占 %d/%d，建议人工确认" % (
                    code, name, best, n, sum(c.values())))

    print("扫到带编号的行 %d 行，识别出 %d 个拍摄人代号\n" % (rows_seen, len(people)))
    for code, mp in people.items():
        print("  [%s] %s" % (code, "  ".join("%s=%s" % (k, v) for k, v in mp.items())))
    if warnings:
        print("\n注意事项:")
        for w in warnings:
            print("  - " + w)

    json.dump(people, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n写出: " + args.out)


if __name__ == "__main__":
    main()
