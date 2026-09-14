#!/usr/bin/env python3
"""批量抽音频 + ASR 转写。多个目录在同一个进程里处理，模型只加载一次。

用法:
    python asr_batch.py <目录1> [目录2 ...] --work-dir work [--seconds 18] [--model small]

设计要点：
- 只转开头 N 秒。文案开头区分度最高，18 秒足够定名；转全程只是成倍耗时。
- 模型加载往往比推理还慢，所以绝不按目录分多次调用。
- 输出 work/asr_<目录名>.json，供 match_and_plan.py 使用。
"""
import argparse
import json
import os
import subprocess
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", str(os.cpu_count() or 8))

PROMPT = ("劳动仲裁，违法辞退，经济补偿，双倍工资，社保，劳动合同法，调岗降薪，工伤，"
          "末位淘汰，试用期，离职，视频号团购，佣金，保证金，扣点，营业执照，核销，本地生活。")


def cache_ready(model_name):
    """本地是否已有该模型的 HF 缓存。没有就别设离线，否则首次使用会直接失败。"""
    hub = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    if not os.path.isdir(hub):
        return False
    return any(d.startswith("models--") and model_name in d for d in os.listdir(hub))


def extract_audio(src, dst, seconds):
    os.makedirs(dst, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(src)):
        if not f.lower().endswith((".mov", ".mp4", ".m4v", ".avi", ".mkv")):
            continue
        base = os.path.splitext(f)[0]
        out = os.path.join(dst, base + ".wav")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-t", str(seconds), "-i", os.path.join(src, f),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out],
            capture_output=True)
        if os.path.exists(out):
            n += 1
        else:
            print("  抽音频失败: " + f, file=sys.stderr)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--work-dir", default="work")
    ap.add_argument("--seconds", type=int, default=18)
    ap.add_argument("--model", default="small")
    ap.add_argument("--compute", default="int8")
    args = ap.parse_args()

    # 有缓存才离线（省掉联网校验的等待）；没有缓存就允许下载，
    # 否则换台电脑第一次跑会直接失败。
    if cache_ready(args.model):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        print("[模型] 本地已有 %s 缓存，离线加载" % args.model)
    else:
        print("[模型] 本地无 %s 缓存，首次运行会联网下载（small 约 500MB）" % args.model)

    from faster_whisper import WhisperModel, BatchedInferencePipeline

    jobs = []
    for src in args.dirs:
        if not os.path.isdir(src):
            sys.exit("目录不存在: " + src)
        tag = os.path.basename(os.path.normpath(src))
        audio = os.path.join(args.work_dir, "audio_" + tag)
        print("[抽音频] %s -> %s" % (src, audio))
        n = extract_audio(src, audio, args.seconds)
        print("  抽出 %d 条" % n)
        jobs.append((tag, audio, os.path.join(args.work_dir, "asr_%s.json" % tag)))

    total = sum(len([f for f in os.listdir(a) if f.endswith(".wav")]) for _, a, _ in jobs)
    print("\n[加载模型] %s (%s, cpu) — 只加载这一次，共 %d 条待转写" % (args.model, args.compute, total))
    t0 = time.time()
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute,
                         cpu_threads=max(4, os.cpu_count() or 8))
    pipe = BatchedInferencePipeline(model=model)

    for tag, audio, out in jobs:
        files = sorted(f for f in os.listdir(audio) if f.endswith(".wav"))
        res = {}
        print("\n[转写] %s (%d 条)" % (tag, len(files)))
        for i, f in enumerate(files, 1):
            segs, _ = pipe.transcribe(os.path.join(audio, f), language="zh", beam_size=1,
                                      batch_size=8, initial_prompt=PROMPT,
                                      condition_on_previous_text=False)
            text = "".join(s.text for s in segs).strip()
            res[f[:-4]] = text
            print("  [%d/%d] %s %s" % (i, len(files), f[:8], text[:70]), flush=True)
        json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出: " + out)

    print("\n全部完成 %.1fs" % (time.time() - t0))
    print("提示: ASR 专有名词会出错（理亏→李魁），匹配阶段用的是整体相似度，不必逐字纠正。")


if __name__ == "__main__":
    main()
