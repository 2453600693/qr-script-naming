---
name: qr-script-naming
version: 2.0.0
description: "QR脚本命名工具（口播原片脚本对号与编号命名）。把一批视频原片快速对应到脚本条目，把脚本内容回填到飞书素材总表的对应行，再用表里的原片编号给视频文件批量改名，并给出缺拍清单。也支持只做前半段（只分清哪个视频是哪条脚本）。当用户提到 QR脚本命名工具、按脚本命名原片、原片对号、分不清哪个视频是哪条脚本、回填素材总表、按原片编号改名时使用。"
---

# QR脚本命名工具

> skill 的技术标识是 `qr-script-naming`（平台要求 kebab-case）。中文名就叫 **QR脚本命名工具**，
> 用户用中文名提到它时，指的就是本 skill。

把"一堆分不清谁是谁的原片"变成"带正确编号、表格也已同步的素材"。

## 开工第一步：先发信息表

用户说"用 QR脚本命名工具"时，**不要先动手，先把下面这张表原样发给用户**，等他填完再开工。

```
===== QR脚本命名工具 · 开工信息表 =====

一、脚本从哪来（必填）
   原脚本文档链接：
   要处理的章节：            （文档若按场景分节就写章节名，如 办公室；
                             只有一份平铺脚本就写"全部"）

二、给哪些文件夹命名（必填，可多个，一行一个）
   目录路径：
   该目录对应章节：
   目录路径：
   该目录对应章节：

三、结果回填哪张表（不回填表格就整段留空）
   素材总表链接：
   sheet 名：                （如 9月）
   从第几行开始往下填：      （如 192）
   脚本内容列 / 原片编号列： （不确定就留空，我去读表头认）

四、文件怎么命名（必填，二选一）
   [ ] A. 用表格里已有的原片编号    → 26.9.14-MJ-192-1.mov
   [ ] B. 用 脚本编号_文案首句      → 01劳纠_公司不签合同赔你.mov

五、其他要求（可选）
   比如：某些条目不用处理 / 同一脚本有多版本要区分 / 编号第四段要不要递增
```

三项信息缺一不可：**原脚本、素材路径、目标表格**。用户只给了视频目录时，主动问脚本和表格在哪。

## 这个工具干四件事

1. **分清哪个视频是哪条脚本** —— 转写音频与脚本文案做文本匹配，产出对照表。
2. **把脚本内容填到表里对应行** —— 按脚本顺序写进"脚本内容"列。
3. **把表里的原片编号命名到视频上** —— 文件名变成 `26.9.14-MJ-192-1.mov`。
4. **告诉用户还差哪些没拍** —— 对照脚本清单输出缺拍条目。

只做第 1 件事也合法：用户不填表，就停在对照表。

## 主线流程

```bash
# $SK 指本 skill 的 scripts 目录的绝对路径，按对方的机器拼：
#   Windows:      C:\Users\<用户名>\.agents\skills\qr-script-naming\scripts
#   macOS/Linux:  ~/.agents/skills/qr-script-naming/scripts

# 0) 有表格时，先读表结构：哪张 sheet、哪列是脚本内容、哪列是编号、目标行现在什么样
python "$SK/sheet_probe.py" --url "<表格URL>" --sheet-id <sheetId> --start-row 192 --rows 25

# 1) 摸底数
python "$SK/probe_media.py" "<素材目录>" media.json
python "$SK/fetch_script.py" "<脚本文档URL>" scripts.json --cache script_full.xml

# 2) 听声音（可一次给多个目录）
python "$SK/asr_batch.py" "<目录1>" "<目录2>" --work-dir work

# 3) 对号入座，产出对照表
python "$SK/match_and_plan.py" --scripts scripts.json --asr work/asr_<目录名>.json \
    --media "<素材目录>" --section "<章节>" --out plan.json

#    —— 把对照表发给用户确认，这一步不能省 ——

# 4) 回填表格（用户确认后）
python "$SK/sheet_fill.py" --url "<表格URL>" --sheet-id <sheetId> --column F \
    --start-row 192 --plan plan.json --scripts scripts.json --dry-run
python "$SK/sheet_fill.py" --url "<表格URL>" --sheet-id <sheetId> --column F \
    --start-row 192 --plan plan.json --scripts scripts.json

# 5) 读表格里的编号，生成最终改名方案
python "$SK/sheet_ids.py" --url "<表格URL>" --sheet-id <sheetId> --id-column I \
    --sheet-column F --start-row 192 --plan plan.json --out plan_rename.json

# 6) 改名：先预演，再执行
python "$SK/rename_atomic.py" plan_rename.json --media "<素材目录>"
python "$SK/rename_atomic.py" plan_rename.json --media "<素材目录>" --apply
```

选 B（脚本编号_文案首句）命名时，跳过第 5 步，直接拿 `plan.json` 走第 6 步。

多目录时第 3、4、5、6 步每个目录各走一遍，注意 `--start-row` 与章节要对应。

## 先记住这几条

1. **画面通常没有字幕**。别抽帧读字，直接抽音频。
2. **文件系统时间戳是拷贝时间**，把 1.8 GB 写进磁盘只要 45 秒，没有顺序信息。能用的只有 `.mov` 内嵌 `creation_time`。
3. **ASR 专有名词一定会错**（理亏→李魁、裁员→财源）。匹配用整体窗口相似度，不用逐字相等。
4. **素材数 ≠ 脚本数**。缺拍、多拍、跨章节都正常。别按"数量相等"假设一一对应，也别按序号顺推。
5. **文件名一律以表格为准**。表里 `I` 列写着 `26.9.14-MJ-192-1`，就用它，不要自己拼 `-192-1`、也不要顺推第四段。
6. **对照表必须给用户过目**再说"已改好"。

## 顺序约定（最容易错的地方）

第 4、5 步依赖一个约定：**plan 按脚本编号升序排列，表格行按同一顺序排布**，于是"第 `start_row + i` 行"对应"plan 第 i 条"。

所以：

- 用户说"从第 192 行开始填"，含义是 192 行放第一条脚本、193 行放第二条，依次往下。
- 动手前用 `sheet_probe.py` 看一眼目标行区间，确认那里是空的、且编号列已经排好号。
- 目标行还没排上编号，就先别改名，回头找用户确认。

## 坑清单

- **Python 里调 lark-cli 要 `shutil.which("lark-cli")`**：Windows 上它是 `.cmd` 包装，直接写 `["lark-cli", ...]` 会 FileNotFoundError。脚本已处理。
- **PowerShell 里 `@payload.json` 会被当 splatting**：写成 `--cells '@payload.json'`。
- **`Out-File -Encoding utf8` 的 JSON 带 BOM**：python 一律用 `encoding="utf-8-sig"` 读。
- **文案含引号和换行**：走 `+cells-set` 的 JSON payload，不要用 `+csv-put` 拼 CSV，转义会让整块错位。
- **`--cells` 维度必须与 `--range` 严格一致**。
- **文件名截断会产生残字**：按句读边界回退，不要硬切 N 个字符。
- **漏读表的行会致命**：定位行号只认 `annotated_csv` 里 `[row=N]` 前缀，不要自己数、不要拿"序号"列推。

## 这几步不能省

- **对照表人工过目**：文案相似的条目（同主题多版本）机器只给概率，判断要人做。
- **回滚清单**：改名不可逆，没有 `rollback.csv` 就得手工比对几百个 UUID。
- **拍摄时间交叉验证**：唯一独立于 ASR 的第二证据源。只有语音一个维度支持时，错配察觉不到。
- **写表后逐行回读**：多行文本字段最容易整体偏移，抽查会漏。

## 环境

```
ffmpeg / ffprobe     抽音频、读元数据
python 3.10+         faster-whisper, scipy, numpy
whisper 模型         首次运行自动下载 small（约 500MB）
lark-cli             读写飞书文档与表格（需 auth login，identity=user）
```

## 装到别人的电脑

1. **放 skill**：把整个 `qr-script-naming` 文件夹拷到对方的 skill 目录
   - Windows：`C:\Users\<用户名>\.agents\skills\`
   - macOS / Linux：`~/.agents/skills/`

2. **装依赖**（三条命令）

   ```
   ffmpeg        Windows: winget install Gyan.FFmpeg
                 macOS:   brew install ffmpeg
   python 包      pip install faster-whisper scipy numpy
   lark-cli      npm i -g @larksuite/cli
                 lark-cli config init
                 lark-cli auth login
   ```

3. **首次跑 ASR 会联网下载 whisper small 模型**（约 500MB）。之后走本地缓存，脚本会自动切离线模式。

4. **三件必须对方自己做的事**
   - `lark-cli auth login` 用他自己的飞书账号；文档和表格的访问权限也是他自己的
   - 表格链接要换成他自己的素材总表，不要用别人表里的编号
   - ffmpeg 要进 PATH（`ffmpeg -version` 能跑通）

5. **不绑机器**：脚本里没有写死任何用户名、盘符或表格 ID，全部靠命令行参数传入。

