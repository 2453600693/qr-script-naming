#!/usr/bin/env python3
"""批量抽音频 + ASR 转写。多个目录在同一个进程里处理，模型只加载一次。

用法:
    python asr_batch.py <目录1> [目录2 ...] --work-dir work [--seconds 20] [--model small]

设计要点：
- 只转开头一小段。文案开头区分度最高，够定名就行；转全程只是成倍耗时。
- 很多素材开头有场记板（"三二一走"），会干扰解码导致正文被吞。
  所以结果里中文字数过少时，自动补转后一段再取更长的结果。
- 模型加载往往比推理还慢，所以绝不按目录分多次调用。
- 输出 work/asr_<目录名>.json，供 match_and_plan.py 使用。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", str(os.cpu_count() or 8))

PROMPT = ("劳动仲裁，违法辞退，经济补偿，双倍工资，社保，劳动合同法，调岗降薪，工伤，"
          "末位淘汰，试用期，离职，视频号团购，佣金，保证金，扣点，营业执照，核销，本地生活，"
          "逾期，负债，债务帮扶，催收，网贷，信用卡。")

MEDIA = (".mov", ".mp4", ".m4v", ".avi", ".mkv")
CJK = re.compile(r"[\u4e00-\u9fff]")


def cache_ready(model_name):
    """本地是否已有该模型的 HF 缓存。没有就别设离线，否则首次使用会直接失败。"""
    hub = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    if not os.path.isdir(hub):
        return False
    return any(d.startswith("models--") and model_name in d for d in os.listdir(hub))


def media_files(src):
    return sorted(f for f in os.listdir(src) if f.lower().endswith(MEDIA))


def clip(src, out, start, dur):
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-t", str(dur), "-i", src, "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", out]
    subprocess.run(cmd, capture_output=True)
    return os.path.exists(out)


def cjk_len(t):
    return len(CJK.findall(t or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--work-dir", default="work")
    ap.add_argument("--seconds", type=int, default=20, help="首段截取时长")
    ap.add_argument("--retry-start", type=int, default=15,
                    help="首段结果过短时，从第几秒开始补转")
    ap.add_argument("--min-cjk", type=int, default=12,
                    help="中文字数低于此值视为被场记板干扰，触发补转")
    ap.add_argument("--model", default="small")
    ap.add_argument("--compute", default="int8")
    args = ap.parse_args()

    if cache_ready(args.model):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        print("[模型] 本地已有 %s 缓存，离线加载" % args.model)
    else:
        print("[模型] 本地无 %s 缓存，首次运行会联网下载（small 约 500MB）" % args.model)

    from faster_whisper import WhisperModel

    jobs = []
    for src in args.dirs:
        if not os.path.isdir(src):
            sys.exit("目录不存在: " + src)
        tag = os.path.basename(os.path.normpath(src))
        jobs.append((tag, src, os.path.join(args.work_dir, "audio_" + tag),
                     os.path.join(args.work_dir, "asr_%s.json" % tag)))

    total = sum(len(media_files(s)) for _, s, _, _ in jobs)
    print("[加载模型] %s (%s, cpu) — 只加载这一次，共 %d 条待转写"
          % (args.model, args.compute, total))
    t0 = time.time()
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute,
                         cpu_threads=max(4, os.cpu_count() or 8))

    def asr(path):
        segs, _ = model.transcribe(path, language="zh", beam_size=1, initial_prompt=PROMPT)
        return "".join(s.text for s in segs).strip()

    for tag, srcdir, audio, out in jobs:
        os.makedirs(audio, exist_ok=True)
        files = media_files(srcdir)
        res, retried = {}, 0
        print("\n[转写] %s (%d 条)" % (tag, len(files)))
        for i, f in enumerate(files, 1):
            base = os.path.splitext(f)[0]
            path = os.path.join(srcdir, f)
            wav = os.path.join(audio, base + ".wav")
            if not clip(path, wav, 0, args.seconds):
                print("  抽音频失败: " + f, file=sys.stderr)
                continue
            text = asr(wav)
            note = ""
            if cjk_len(text) < args.min_cjk:
                wav2 = os.path.join(audio, base + ".__retry.wav")
                if clip(path, wav2, args.retry_start, args.seconds):
                    t2 = asr(wav2)
                    if cjk_len(t2) > cjk_len(text):
                        text, note = t2, "  (已补转 %ds 起)" % args.retry_start
                        retried += 1
                    os.remove(wav2)
            # key 用原始媒体文件名（含扩展名），下游才能拿到真实文件名和扩展名
            res[f] = text
            print("  [%d/%d] %s %s%s" % (i, len(files), f[:10], text[:66], note), flush=True)
        json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出: %s   补转 %d 条" % (out, retried))

    print("\n全部完成 %.1fs" % (time.time() - t0))
    print("提示: ASR 专有名词会出错（理亏→李魁），匹配阶段用的是整体相似度，不必逐字纠正。")


if __name__ == "__main__":
    main()
