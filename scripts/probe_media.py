#!/usr/bin/env python3
"""探测素材目录：文件数、大小、时长、分辨率、内嵌拍摄时间。

用法:
    python probe_media.py <目录> [输出.json]

为什么需要它：机内原始文件的文件名（UUID）和文件系统时间戳都不含顺序信息，
唯一可信的时间线索是容器内嵌的 creation_time。
"""
import json
import os
import subprocess
import sys


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration:format_tags=creation_time",
         "-show_entries", "stream=width,height",
         "-of", "json", path],
        capture_output=True, text=True, encoding="utf-8", errors="ignore")
    try:
        d = json.loads(r.stdout or "{}")
    except Exception:
        return {"duration": 0.0, "creation_time": "", "width": None, "height": None}
    fmt = d.get("format") or {}
    st = (d.get("streams") or [{}])[0]
    return {
        "duration": round(float(fmt.get("duration") or 0), 2),
        "creation_time": (fmt.get("tags") or {}).get("creation_time", ""),
        "width": st.get("width"),
        "height": st.get("height"),
    }


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.isdir(src):
        sys.exit("目录不存在: " + src)

    names = sorted(f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f)))
    rows = []
    for f in names:
        p = os.path.join(src, f)
        info = probe(p)
        info.update({"name": f, "size": os.path.getsize(p)})
        rows.append(info)

    total = sum(r["size"] for r in rows)
    print("目录: %s" % src)
    print("文件数: %d   总大小: %.2f GB   零字节: %d" % (
        len(rows), total / 1024 / 1024 / 1024, sum(1 for r in rows if r["size"] == 0)))

    durs = [r["duration"] for r in rows if r["duration"]]
    cts = [r["creation_time"] for r in rows if r["creation_time"]]
    if durs:
        print("时长范围: %.1fs ~ %.1fs" % (min(durs), max(durs)))
    if cts:
        days = sorted({c[:10] for c in cts})
        print("拍摄日期: " + ", ".join(
            "%s (%d 条)" % (d, sum(1 for c in cts if c.startswith(d))) for d in days))
    else:
        print("警告: 没有任何文件带 creation_time，交叉验证会失效")
    dims = {(r["width"], r["height"]) for r in rows if r["width"]}
    if dims:
        print("分辨率: " + ", ".join("%sx%s" % d for d in sorted(dims, key=str)))

    if out:
        json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("明细已写出: " + out)


if __name__ == "__main__":
    main()
