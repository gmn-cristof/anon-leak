# anon-leak

一个只依赖 Python 标准库的匿名哈希链爆料工具。它让匿名爆料人把多篇帖子通过一条 SHA-256 哈希链绑定成可验证的链条：读者仅凭公开的帖子正文，即可验证「所有帖子来自同一爆料人」「帖子顺序正确」「正文未被篡改」，并且攻击者无法伪造后续帖子。全程不联网、不用区块链、不依赖任何第三方服务。

## 目录结构

```
anon-leak/
├── anon_leak.py         # 一体化 CLI（推荐）：多 leak 管理 + 引导式爆料
├── anon_leak            # POSIX 启动器（Linux / macOS，可放进 PATH）
├── anon_leak.cmd        # Windows 启动器
├── chain_post.py        # 底层生成脚本（单链用法）
├── chain_verify.py      # 底层验证脚本（读者端）
├── README.md            # 使用说明（本文件）
├── .gitignore           # 内容为 secret/
├── secret/              # 私有目录（运行时生成，绝不可公开）
│   ├── chain_secret.json   # 只存种子与长度（方案 B：{"version":2, seed, length, created_at}）
│   └── chain_state.json    # 已发布数量 {"published": n}
├── drafts/              # 原始正文（NN.txt，NN 为两位零填充）
│   ├── 01.txt
│   ├── 02.txt
│   └── 03.txt
└── posts/               # 生成的完整帖子（运行时生成）
    ├── 01.txt
    ├── 02.txt
    └── 03.txt
```

> 一体化 CLI 会在**当前目录**（可用 `--root DIR` 指定）下为每个爆料维护一个
> `<leak_name>/` 文件夹，每个文件夹内含 `secret/`、`drafts/`、`posts/`、`leak.json`
> 与自己的 `.gitignore`，彼此互不干扰。下面先介绍一体化 CLI（推荐），
> 之后是底层脚本 `chain_post.py` / `chain_verify.py` 的单链用法。

## 一体化 CLI（anon_leak）

把「创建链 → 写帖 → 发布 → 自检 → 导出」打包成一条命令，适合同时管理多条爆料。

### 快速开始

```bash
python anon_leak.py create demo -n 3          # 创建一条长度 3 的爆料链（交互输入种子）
python anon_leak.py start demo                # 引导式写第一篇并发布
python anon_leak.py verify demo               # 本地验证
```

> `-n` 默认值为 **1000000**（一百万），不写也能创建一条几乎用不完的链；
> 链值按需现算，`secret/` 文件始终只有几百字节。

- 种子默认用 `getpass` **隐藏回显**并二次确认；也可 `-s 种子` 或 `--random-seed`。
- 命令都带**别名**：`create=new`、`list=ls`、`status=st`、`start=go`、`add=publish`、
  `verify=check`、`show=cat`。
- 目录里只有一个 leak 时，`status / start / add / verify / show / doctor` 可以省略名字自动选中。

### 常用命令

| 命令 | 作用 |
|---|---|
| `anon_leak` | 无参数总览：列出所有 leak 与状态 |
| `anon_leak create <名> [-n 长度] [-s 种子] [--random-seed]` | 创建爆料链 |
| `anon_leak list` | 表格列出所有 leak |
| `anon_leak status [名] [--check]` | 单链详情，`--check` 附带本地验证 |
| `anon_leak start [名]` | 引导式写帖并发布（正文以单独一行 `EOF` 结束） |
| `anon_leak add [名] [-f 文件 \| -m 文本 \| 管道] [-i 帖号] [--dry-run]` | 非交互式发布一帖 |
| `anon_leak verify [名] [--dir DIR] [文件...]` | 验证（leak / 目录 / 文件三种方式） |
| `anon_leak show [名] <帖号> [--payload-only]` | 打印某帖全文 |
| `anon_leak export [名] [--single 合集.txt]` | 导出公开帖子 + 读者验证说明 |
| `anon_leak doctor [名]` | 自检一致性 / 可验证性 / .gitignore / 链是否用尽 |
| `anon_leak guide` | 匿名发布检查清单 |

### 输出示例

```text
$ python anon_leak.py create demo -n 2 -s s1
seed:    ****************
length:  2
root:    7861710f76ab0b7777a0b1ed1596e3f4...
created: demo
backup:  demo/secret/ (offline, never publish)

next:
  anon_leak start demo      # write post 1
  anon_leak guide           # anonymous publishing checklist

$ python anon_leak.py add demo -m "第一篇爆料正文"
published demo/posts/01.txt  (1/2)

next:
  anon_leak add demo -m "..."   # write next post
  anon_leak verify demo         # verify locally

$ python anon_leak.py verify demo
POST   HASH   BIND   CHAIN
01     ok     ok     ok

verify: pass (1 posts, same origin, order ok, no tamper)

next:
  anon_leak show demo 1      # view a post
  anon_leak export demo      # export for readers
```

> 输出为纯 ASCII 紧凑风格：成功一行摘要、表格对齐、每条命令结尾给出 `next:` 提示。
> 颜色仅在终端（TTY）下启用，重定向到文件时自动无色；`create` / `guide` / 无参数总览
> 会在 TTY 下显示极简 banner。全局选项：`--quiet`（只打印结果行）、`--no-banner`、
> `--verbose`（`verify`/`status` 打印逐帖详情）、`--version`。退出码：成功 0、
> 验证失败 1、其他错误 2。

### 安装到 PATH（可选）

```bash
# Linux / macOS：把启动器软链到 PATH 中的目录，即可直接敲 anon_leak
ln -s "$(pwd)/anon_leak" ~/.local/bin/anon_leak

# Windows：把 anon_leak.cmd 所在目录加入 PATH，或直接双击/调用 anon_leak.cmd
```

---

## 底层脚本用法（单链）

## 爆料人用法

### 1. 初始化私密链

```bash
python chain_post.py init
```

按提示输入种子（seed）和链长度（length）。脚本会生成 `secret/chain_secret.json` 与 `secret/chain_state.json`，并自动创建 `secret/`、`drafts/`、`posts/` 三个目录。

```text
enter seed: test-seed
enter chain length (default 1000000, empty to use default): 3
ok: chain created: length 3, seed 'test-seed'
ok: wrote secret/chain_secret.json and secret/chain_state.json (published=0)
warn: never publish secret/; write drafts as drafts/NN.txt (NN two-digit).
```

> 现在 `secret/chain_secret.json` 只存种子、长度与创建时间（方案 B），
> **不再预存整条链**；链长度可以直接回车取默认的一百万，几乎无需担心用尽。

> 若 `secret/chain_secret.json` 已存在，脚本会提示覆盖，必须输入全大写 `YES` 才会覆盖。

### 2. 写草稿

把每一帖的正文写入 `drafts/NN.txt`（`NN` 为两位零填充序号）：

```bash
# drafts/01.txt、drafts/02.txt、drafts/03.txt
```

### 3. 生成帖子

生成第 N 帖，或一次性连续生成：

```bash
python chain_post.py build --index 2     # 只生成第 2 帖
python chain_post.py build --all         # 从下一帖起连续生成，直到无草稿或达链长上限
```

```text
ok: generated posts/01.txt (post 1, published 1/3)
ok: generated posts/02.txt (post 2, published 2/3)
ok: generated posts/03.txt (post 3, published 3/3)
skip: chain length limit reached (3 posts), all generated
```

跳号、越界、找不到草稿、重复生成都会给出清晰的 `error:` 错误并退出。

### 4. 查看状态

```bash
python chain_post.py status
```

```text
length:    3
published: 3
next:      4
--- post status ---
post 01: ok  generated (posts/01.txt)
post 02: ok  generated (posts/02.txt)
post 03: ok  generated (posts/03.txt)
```

最后只需把 `posts/` 下的 `.txt` 全文通过匿名渠道公开即可（渠道自理，本工具不联网）。

## 读者用法

### 方式一：验证一个目录下的所有帖子

```bash
python chain_verify.py --dir posts/
```

脚本会自动收集目录下所有 `.txt` 文件，按文件名排序后验证。

### 方式二：指定文件验证

```bash
python chain_verify.py posts/01.txt posts/02.txt posts/03.txt
```

若传入顺序与 `index` 不符，会自动按 `index` 排序后再验证。

## 输出示例

### 成功

```text
POST   HASH   BIND   CHAIN
01     ok     ok     ok
02     ok     ok     ok
03     ok     ok     ok

verify: pass (3 posts, same origin, order ok, no tamper)
```

（退出码 0）

> 加 `--verbose`（或 `-v`）可打印每帖的详细验证过程；`--quiet`（或 `-q`）只打印结果行。

### 失败（正文被篡改）

```text
POST   HASH   BIND   CHAIN
01     ok     ok     ok
02     FAIL   ok     ok
03     ok     ok     ok

verify: FAIL
  02.txt: content_hash mismatch (post tampered)
  expected  a1b2c3...
  actual    9f8e7d...
```

（退出码 1）

### 失败（prev 被篡改 / 链值不连续）

```text
POST   HASH   BIND   CHAIN
01     ok     ok     ok
02     ok     ok     ok
03     ok     ok     FAIL

verify: FAIL
  03.txt: SHA256(value) != prev
  expected  <上一帖的 value>
  actual    <本帖的 prev>
```

（退出码 1）

## 原理说明

1. **哈希链**：从种子出发反复计算 `SHA256`，得到一串值；按「后计算的先发布」的顺序公开，使第 k 帖满足 `SHA256(value_k) == prev_k`。这样拿到公开值无法反推出下一帖的值（需破解 SHA-256 原像），保证后续帖子不可伪造。第 k 帖的链值不再预存，而是发布时现场计算：`value_k = get_value(seed, length, k)`（从种子哈希 `length - k + 1` 次），`prev_k = SHA256(value_k)`。
2. **同源判定**：相邻帖子通过 `prev = 上一帖的 value` 串联，只有持有同一 seed 的人才能连续公布合法值。
3. **顺序判定**：`index` 从 1 开始连续递增，且第 1 帖的 `prev` 必须为空字符串（锚点）。
4. **防篡改**：每帖记录 `content_hash = SHA256(正文)`，正文任何一处改动都会导致哈希不匹配。
5. **内容绑定**：`bind = SHA256(value + "|" + content_hash)` 把链值与正文绑定，防止「拿 A 帖的正文配 B 帖的链值」这类拼接攻击。

## 为什么链长度可以设很大

方案 B 不再预存整条链，只保存种子与长度，因此 `length` 可以放心设成一百万（甚至更大）：

- **存储恒定**：`secret/chain_secret.json` 始终只有几百字节，与 `length` 无关。
- **按需现算**：第 k 帖的链值 = 从种子出发哈希 `length - k + 1` 次，只在发布该帖时计算。
- **速度递减**：第 1 帖最慢（约 0.5 秒 @ 100 万次 SHA-256），之后每篇少一次哈希，越往后越快。
- **内存恒定**：生成过程不缓存、不写中间文件，内存占用与 `length` 无关。

## 从旧版本迁移

旧版本会把整条链存进 `secret/chain_secret.json`（JSON 数组，或 dict 里的 `chain` 字段）。升级后：

- 运行**任意命令**（`status` / `add` / `build` / …）读取旧文件时，会提示检测到旧格式。
- 裸数组无法反推种子，因此需要你**手动提供原种子**来校验并迁移；
  旧 dict 若自带 `seed` 且校验通过，会**自动迁移**，无需输入。
- 迁移前会先把旧文件**备份为 `secret/chain_secret.json.bak`**（绝不删除旧文件），
  校验通过后写入新的 v2 格式（只存种子与长度）。
- 若种子与旧链不匹配或你放弃迁移，程序会报错退出，提示手动备份后重新 `init`。

## 安全提醒

- **`secret/` 绝不可公开**：它包含种子。**种子泄露 = 整条链泄露**，包括所有未来帖子，任何人都能冒充爆料人。项目自带 `.gitignore` 已忽略 `secret/`。
- **链长度仍有限**：默认 100 万，理论上仍可能用尽；用尽后需重新 `init` 开新链，且**不要复用同一 seed**。
- **跨链方法**：若需开新链并让读者知道新旧链条同源，可在新链第 1 帖正文里公开旧链最后一帖的 `value` 作为声明锚点。
- **匿名渠道自理**：本工具只负责「绑定与验证」，帖子的匿名发布、投递渠道、时效性由爆料人自行选择，请务必使用安全的匿名渠道。

## 依赖说明

- Python 3.6+，**仅使用标准库**，无任何第三方依赖、无需联网。
- 底层脚本 `chain_post.py` / `chain_verify.py` 仅用 `hashlib`、`json`、`os`、`sys`、`argparse`。
- 一体化 CLI `anon_leak.py` 额外使用 `getpass`（种子隐藏回显）、`datetime`（创建时间）、`shutil`（导出复制）等标准库模块。
- 命令名：Windows 下通常为 `python`，Linux / macOS 若没有 `python` 别名则用 `python3`。
