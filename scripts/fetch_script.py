#!/usr/bin/env python3
"""从飞书文档拉取拍摄脚本，切分章节与条目，清洗出可用的口播正文。

用法:
    python fetch_script.py <飞书文档URL> 输出.json [--cache script_full.xml]

关键设计：全篇 XML 只拉一次并缓存，所有章节都从缓存里切。
不要为每个章节各调一次 lark-cli。
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys

# Windows 上 lark-cli 是 .cmd 包装，必须用 which 解析出真实路径
CLI = shutil.which("lark-cli") or "lark-cli"

TAG = re.compile(r"<[^>]+>")
TOK = re.compile(r"<(h2|h3|h4)[^>]*>(.*?)</\1>|<p[^>]*>(.*?)</p>", re.S)
# 条目标题：01劳纠 / 43团购 / 逾期1 / 脚本01
ITEM = re.compile(r"^(\d{2})(劳纠|团购)$|^(逾期\d+)$|^脚本\s*(\d+)$")
# 需要丢掉的拍摄提示行
DROP = re.compile(r"^[（(【\[].*[）)】\]]$|人脸尽量不要离镜头太近")


def fetch(url, cache):
    if cache and os.path.exists(cache):
        return open(cache, encoding="utf-8-sig").read()
    r = subprocess.run(
        [CLI, "docs", "+fetch", "--doc", url, "--detail", "with-ids"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        sys.exit("lark-cli 取文档失败:\n" + (r.stderr or r.stdout))
    doc = json.loads(r.stdout)
    if not doc.get("ok"):
        sys.exit("取文档失败: %s" % doc.get("error"))
    content = doc["data"]["document"]["content"]
    if cache:
        open(cache, "w", encoding="utf-8").write(content)
    return content


def strip(t):
    return html.unescape(TAG.sub("", t)).strip()


def clean_paragraphs(paras):
    """丢掉拍摄提示、标记，返回正文行。"""
    out = []
    for p in paras:
        p = re.sub(r"（[^）]*）|\([^)]*\)|【[^】]*】|\[[^\]]*\]", "", p).strip()
        if p and not DROP.search(p):
            out.append(re.sub(r"[ \t]+$", "", p))
    return out


def parse(content):
    """按 h2 切章节、按 h3/h4 切条目。"""
    items = []
    section = cur = paras = None
    for m in TOK.finditer(content):
        if m.group(1):
            lvl, title = m.group(1), strip(m.group(2))
            if lvl == "h2":
                section, cur, paras = title, None, None
            else:
                hit = ITEM.match(title)
                if hit:
                    g = hit.groups()
                    no = g[0] or g[3]
                    typ = g[1] or ("加拍" if g[2] else "脚本")
                    cur = {"section": section, "code": title, "type": typ,
                           "no": int(no) if no else None,
                           "lines": []}
                    items.append(cur)
                    paras = cur["lines"]
        else:
            if paras is None:
                continue
            for line in clean_paragraphs([strip(m.group(3))]):
                paras.append(line)

    for it in items:
        it["text"] = "\n".join(it.pop("lines"))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+",
                    help="一个或多个脚本文档 URL；多个文档时自动加 D1- / D2- 前缀以区分同名条目")
    ap.add_argument("out")
    ap.add_argument("--cache", default="script_full.xml")
    args = ap.parse_args()

    multi = len(args.urls) > 1
    items = []
    for k, url in enumerate(args.urls, 1):
        cache = ("script_full_%d.xml" % k) if multi else args.cache
        sub = parse(fetch(url, cache))
        tag = "D%d" % k if multi else ""
        for it in sub:
            if tag:
                it["doc"] = tag
            # code 必须全局唯一：不同文档、甚至同一文档的不同章节都可能有同名条目
            #（比如 MJ 和 FF 下都叫"脚本01"），不带章节前缀会互相覆盖。
            prefix = [p for p in (tag, it["section"]) if p]
            it["code"] = "-".join(prefix + [it["code"]])
            items.append(it)
        if multi:
            print("文档%d: %d 条" % (k, len(sub)))

    json.dump(items, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    secs = {}
    for it in items:
        secs.setdefault(it["section"], []).append(it["code"])
    print("共 %d 条，分 %d 个章节:" % (len(items), len(secs)))
    for s, codes in secs.items():
        print("  [%s] %s" % (s, " ".join(codes)))
    bad = [it["code"] for it in items if not it["text"]]
    if bad:
        print("警告: 以下条目文案为空 -> " + " ".join(bad))
    print("写出: " + args.out)


if __name__ == "__main__":
    main()
