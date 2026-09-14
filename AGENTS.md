# AGENTS.md — QR脚本命名工具操作手册

读完这份文件，你就能独立完成"给原片对号 + 回填表格 + 按编号改名"的全流程。
本文件不依赖任何特定 AI 平台，假设你只能读文件、执行命令、和用户对话。

---

## 第一步：先问用户三件事，别急着动手

把下面这张卡片**原样发给用户**，等他填完再开始：

```
===== QR脚本命名工具 · 开工三行 =====

① 脚本：
   （这次要拍的脚本在哪？粘贴飞书文档链接）

② 原片：
   （视频放在哪个文件夹？粘贴路径，多个就一行一个）

③ 表格：
   （结果要填到哪张表？粘贴素材总表链接；只分类不填表就写"不用"）

—— 其余我来查。方案出来先给你过目，你点头我才动文件。
```

只问这三样，其余自己查：

| 不用用户填 | 你怎么知道 |
|---|---|
| 文档里的章节名 | 文件夹名通常就是章节名，自动匹配；对不上再问 |
| 表格的 sheet | 链接里通常带 `?sheet=xxx`；没带就看日期列或最新月份 |
| 脚本内容列、原片编号列 | 读表头行认。含"脚本/文案"的是脚本列，含"编号/原片"的是编号列 |
| 从第几行开始填 | 找"编号已排好、脚本内容还空着"的起始行 |
| 文件叫什么名 | 表里有编号就用编号；表里没有才问用户要哪种命名法 |

## 第二步：环境自检

```bash
ffmpeg -version
python -c "import faster_whisper, scipy, numpy; print('ok')"
lark-cli --version
```

缺什么就告诉用户装什么，不要自己乱装：

- `ffmpeg` → `winget install Gyan.FFmpeg`（Windows）/ `brew install ffmpeg`（macOS）
- python 包 → `pip install faster-whisper scipy numpy`
- `lark-cli` → `npm i -g @larksuite/cli`，然后 `lark-cli config init` 和 `lark-cli auth login`（必须用户本人授权）

`$SK` 指本目录下 `scripts/` 的绝对路径，按用户机器拼。

## 第三步：先回报探测结果，等用户点头

```bash
# 探测素材目录
python "$SK/probe_media.py" "<原片目录>" media.json

# 拉脚本文档（全篇只拉一次，缓存到本地，后续章节都从缓存切）
python "$SK/fetch_script.py" "<脚本文档URL>" scripts.json --cache script_full.xml

# 探测表格结构（有表格时）
python "$SK/sheet_probe.py" --url "<表格URL>" --sheet-id <sheetId> --start-row 192 --rows 25
```

然后把结果报给用户确认，例如：

```
脚本：识别出 72 条，分 4 个章节（办公室 40 / 室内 14 / 室外 16 / 加拍 2）
表格：9 月这张表，脚本内容 = F 列，原片编号 = I 列，
      从第 192 行开始，那里编号已排好、脚本内容还空着
原片：办公室 40 个文件，09-07 拍 16 条、09-11 拍 24 条
```

用户说"对"，再往下走。

## 第四步：转写与匹配

```bash
# 抽音频 + 转写（多个目录一次给，模型只加载一次）
python "$SK/asr_batch.py" "<目录1>" "<目录2>" --work-dir work

# 对号入座
python "$SK/match_and_plan.py" --scripts scripts.json --asr work/asr_<目录名>.json \
    --media "<原片目录>" --section "<章节>" --out plan.json
```

`match_and_plan.py` 会输出：

- 每条素材分配到的脚本编号、置信度、前三候选
- 标出"需复核"的条目（最优与次优分差过小）
- **缺拍清单**（哪些脚本没有素材）
- 按拍摄时间排序的单调性检查（逆序点通常是当天补拍，属正常）

**把对照表发给用户确认，这一步不能省，也不能改成"我先改了你有意见再说"。**

## 第五步：回填表格

```bash
# 先 dry-run 看落区
python "$SK/sheet_fill.py" --url "<表格URL>" --sheet-id <sheetId> --column F \
    --start-row 192 --plan plan.json --scripts scripts.json --dry-run

# 用户确认后正式写
python "$SK/sheet_fill.py" --url "<表格URL>" --sheet-id <sheetId> --column F \
    --start-row 192 --plan plan.json --scripts scripts.json
```

脚本会自动逐行回读校验，不一致会非零退出。

## 第六步：读表格编号，改名

```bash
python "$SK/sheet_ids.py" --url "<表格URL>" --sheet-id <sheetId> --id-column I \
    --sheet-column F --start-row 192 --plan plan.json --out plan_rename.json

# 先预演
python "$SK/rename_atomic.py" plan_rename.json --media "<原片目录>"

# 用户确认后执行
python "$SK/rename_atomic.py" plan_rename.json --media "<原片目录>" --apply
```

`sheet_ids.py` 会从表里读出真实编号（如 `26.9.14-MJ-192-1`）。
**绝不要自己拼编号**——表里第四段为什么是 1、行号怎么排，只有读出来才作数。

如果用户选的是"脚本编号_文案首句"命名法，跳过 `sheet_ids.py`，直接用 `plan.json` 走 `rename_atomic.py`。

多目录时第四到六步每个目录各走一遍。

## 铁律

1. **画面通常没有字幕**，别抽帧读字，直接抽音频。
2. **文件系统时间戳是拷贝时间**，没有顺序信息。能用的只有视频内嵌 `creation_time`。
3. **ASR 专有名词一定会错**（理亏→李魁、裁员→财源）。匹配用整体相似度，不要用逐字相等。
4. **素材数 ≠ 脚本数**。缺拍、多拍、跨章节都正常，别按数量相等假设一一对应。
5. **文件名一律以表格为准**，不要自己拼编号、不要顺推。
6. **对照表必须给用户过目**，确认后才动文件。
7. **改名一定先预演**，执行后保留 `rollback.csv`。

## 顺序约定（最容易错的地方）

第五、六步依赖一个约定：**plan 按脚本编号升序排列，表格行按同一顺序排布**，
于是"第 `start_row + i` 行"对应"plan 第 i 条"。

用户说"从第 192 行开始填"，含义是 192 行放第一条脚本、193 行放第二条，依次往下。
动手前用 `sheet_probe.py` 看一眼目标行区间，确认那里是空的、且编号列已经排好号。

## 坑清单

- **Python 里调 lark-cli 要用 `shutil.which("lark-cli")`**：Windows 上它是 `.cmd` 包装，
  直接写 `["lark-cli", ...]` 会 FileNotFoundError。脚本内部已处理。
- **PowerShell 里 `@payload.json` 会被当 splatting**：写成 `--cells '@payload.json'`。
- **`Out-File -Encoding utf8` 的 JSON 带 BOM**：python 一律用 `encoding="utf-8-sig"` 读。
- **文案含引号和换行**：走 `+cells-set` 的 JSON payload，不要用 `+csv-put` 拼 CSV。
- **漏读表的行会致命**：定位行号只认返回里的 `[row=N]` 前缀，不要自己数、不要拿"序号"列推。

## 交付时要说清的

- 哪些脚本**没有素材**（缺拍清单）
- 哪些素材**不属于本章节**（可能是加拍或别的章节，命名规则要单独定）
- 文案高度相似的近似对，说明靠什么区分的
- 改完给了哪些文件、回滚清单在哪
