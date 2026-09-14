# QR脚本命名工具

把一堆分不清谁是谁的视频原片，变成带正确编号、表格也已同步的素材。

它干四件事：

1. **分清哪个视频是哪条脚本** —— 转写音频，和脚本文案做文本匹配，产出对照表
2. **把脚本内容填到素材总表的对应行** —— 按脚本顺序写进"脚本内容"列
3. **用表里的原片编号给视频改名** —— `xxx.mov` → `26.9.14-MJ-192-1.mov`
4. **告诉你还差哪些没拍** —— 对照脚本清单输出缺拍条目

## 它不依赖某个 AI 平台

`scripts/` 里是 8 个纯命令行 python 脚本，跟 AI 无关，你自己敲也能跑。
`AGENTS.md` 是写给 AI 看的操作手册，任何能读文件、能执行命令的 AI 都能照着做。

| 你在用什么 | 怎么用 |
|---|---|
| DSH | 直接说「用 QR脚本命名工具」，会自动加载 `SKILL.md` |
| Cursor / Claude Code / Codex 等 | 让它读 `AGENTS.md`，或把下面的启动词粘给它 |
| ChatGPT / 通义 / 豆包等 | 把 `AGENTS.md` 的内容粘进对话，配合脚本手动跑 |
| 不用 AI | 照 `AGENTS.md` 的命令自己敲 |

**给 AI 的启动词**（把 `<路径>` 换成实际位置）：

```
请先读 <路径>/AGENTS.md，然后按它开头的"开工三行"问我收集信息，
再按里面的命令一步步执行。需要跑脚本时用同一目录下 scripts/ 里的文件。
改动我的文件前必须先让我确认。
```

## 装什么

```
ffmpeg        Windows: winget install Gyan.FFmpeg
              macOS:   brew install ffmpeg
python 包      pip install faster-whisper scipy numpy
lark-cli      npm i -g @larksuite/cli
              lark-cli config init      # 首次配置
              lark-cli auth login       # 用你自己的飞书账号授权
```

`ffmpeg -version` 和 `lark-cli --version` 都能跑通才算装好。

首次跑转写会联网下载 whisper small 模型（约 500MB），之后走本地缓存。

Windows 和 macOS 都能跑，脚本里没有平台特定代码。

## 三件必须你自己做的事

- 用**你自己的**飞书账号 `auth login`，文档和表格的访问权限也是你自己的
- 表格链接换成**你自己的**素材总表，不要拿别人表里的编号去命名你的文件
- 改名不可逆，落盘前一定先看工具给你的对照表

## 目录结构

```
qr-script-naming/
├── SKILL.md           DSH 自动加载用
├── AGENTS.md          给任意 AI 看的操作手册
├── README.md          本文件
└── scripts/
    ├── probe_media.py       探测素材：数量/时长/分辨率/拍摄时间
    ├── fetch_script.py      拉飞书脚本文档，切章节、洗文案
    ├── asr_batch.py         抽音频 + 批量转写
    ├── match_and_plan.py    对号入座 + 拍摄时间交叉验证
    ├── sheet_probe.py       探测素材总表结构
    ├── sheet_fill.py        回填脚本内容 + 逐行回读校验
    ├── sheet_ids.py         读表里的原片编号，生成改名方案
    └── rename_atomic.py     两阶段原子改名 + 回滚清单
```

每天处理新素材时，把中间产物（`work/`、`*.json`、`*.csv`）丢在工作目录就行，
它们不该进版本库，`.gitignore` 已经排除了。

## 它靠什么保证不出错

视频文件名里没有任何语义，UUID 名和文件系统时间戳都是噪声。真正的锚点是**声音本身**。

- **双证据交叉验证**：ASR 文本匹配 + 视频内嵌拍摄时间单调性，两个独立维度都指向同一套编号才落盘
- **全局最优分配**：用匈牙利算法做一对一分配，不会两条素材抢同一条脚本
- **先预演后落盘**：改名分两阶段（先转临时名再转终名），避免互相覆盖，并留 `rollback.csv`
- **写表后逐行回读**：多行文本字段最容易整体偏移，抽查会漏
- **人工确认关卡**：对照表必须给人看过才动文件
