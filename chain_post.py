#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anon-leak 爆料人端脚本。

让爆料人在本地生成一条「匿名哈希链」，并把多篇帖子依次发布。
只有爆料人掌握 seed，因此能按顺序公布链上的 value；读者拿到公开帖子后
即可验证：所有帖子同源、顺序正确、正文未被篡改、且无法伪造后续帖子。

用法：
    python chain_post.py init                 # 初始化私密链
    python chain_post.py build --index N      # 生成第 N 帖
    python chain_post.py build --all          # 从下一帖起连续生成
    python chain_post.py status               # 查看状态
"""

import argparse
import hashlib
import json
import os
import sys

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SCHEME = "anon-hash-chain-v1"          # 方案标识
HASH_NAME = "sha256"                    # 哈希算法
BEGIN_MARK = "-----BEGIN ANON CHAIN-----"
END_MARK = "-----END ANON CHAIN-----"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_DIR = os.path.join(BASE_DIR, "secret")
DRAFTS_DIR = os.path.join(BASE_DIR, "drafts")
POSTS_DIR = os.path.join(BASE_DIR, "posts")
SECRET_FILE = os.path.join(SECRET_DIR, "chain_secret.json")
STATE_FILE = os.path.join(SECRET_DIR, "chain_state.json")


def configure(base_dir):
    """把工作目录切换到 base_dir，并据此重新计算所有子目录与文件路径。

    供外部（如 anon_leak.py）在操作某个 leak 工作区前调用；
    本脚本自身运行时默认以脚本所在目录作为工作目录。
    """
    global BASE_DIR, SECRET_DIR, DRAFTS_DIR, POSTS_DIR, SECRET_FILE, STATE_FILE
    BASE_DIR = os.path.abspath(base_dir)
    SECRET_DIR = os.path.join(BASE_DIR, "secret")
    DRAFTS_DIR = os.path.join(BASE_DIR, "drafts")
    POSTS_DIR = os.path.join(BASE_DIR, "posts")
    SECRET_FILE = os.path.join(SECRET_DIR, "chain_secret.json")
    STATE_FILE = os.path.join(SECRET_DIR, "chain_state.json")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def sha256_hex(data):
    """计算字节数据的 SHA-256，返回十六进制字符串。"""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    """计算字符串（按 UTF-8 编码）的 SHA-256 十六进制摘要。"""
    return sha256_hex(text.encode("utf-8"))


def ensure_dirs():
    """确保 secret/、drafts/、posts/ 三个目录存在（不存在则创建）。"""
    for directory in (SECRET_DIR, DRAFTS_DIR, POSTS_DIR):
        os.makedirs(directory, exist_ok=True)


def save_json(path, data):
    """以统一格式（UTF-8、indent=2、按 key 排序、末尾换行）写 JSON 文件。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def load_json(path):
    """读取 JSON 文件（UTF-8），返回解析后的对象。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 哈希链
# ---------------------------------------------------------------------------
def build_chain(seed, length):
    """由种子 seed 生成长度为 length 的哈希链，按「发布顺序」返回。

    计算过程（与需求一致）：
        cur = seed.encode("utf-8")
        重复 length 次：cur = SHA256(cur).hexdigest()，每次结果存入 chain 列表

    存储顺序说明：为满足验证规则「第 k 帖满足 SHA256(value) == prev」，
    同时保证「拿到公开 value 无法推出下一帖 value（需求 SHA-256 原像），
    攻击者无法伪造后续帖子」，计算完成后按「发布顺序」排列：
        chain[0] = 第 1 帖公开的根值（最后一次计算的结果）
        chain[1] = 第 2 帖公开的值
        ……依此类推，chain[-1] = 第一次计算的结果。
    """
    chain = []
    cur = seed.encode("utf-8")
    for _ in range(length):
        cur = sha256_hex(cur)
        chain.insert(0, cur)
        cur = cur.encode("utf-8")
    return chain


# ---------------------------------------------------------------------------
# 私密链与状态读写
# ---------------------------------------------------------------------------
def load_secret():
    """读取 secret/chain_secret.json，不存在或损坏时给出中文错误并退出。"""
    if not os.path.exists(SECRET_FILE):
        print("❌ 未找到私密链文件 secret/chain_secret.json，请先运行：python chain_post.py init")
        sys.exit(1)
    try:
        return load_json(SECRET_FILE)
    except (OSError, ValueError) as exc:
        print(f"❌ 读取私密链文件失败（secret/chain_secret.json）：{exc}")
        sys.exit(1)


def save_secret(seed, length, chain):
    """把种子、长度与整条链写入 secret/chain_secret.json。"""
    save_json(SECRET_FILE, {
        "scheme": SCHEME,
        "hash": HASH_NAME,
        "seed": seed,
        "length": length,
        "chain": chain,
    })


def load_state():
    """读取 secret/chain_state.json，返回 {"published": n}；不存在时视为 0。"""
    if not os.path.exists(STATE_FILE):
        return {"published": 0}
    try:
        return load_json(STATE_FILE)
    except (OSError, ValueError):
        print("❌ 读取状态文件失败（secret/chain_state.json），文件可能已损坏")
        sys.exit(1)


def save_state(published):
    """把已发布数量写入 secret/chain_state.json。"""
    save_json(STATE_FILE, {"published": published})


# ---------------------------------------------------------------------------
# 帖子构造
# ---------------------------------------------------------------------------
def make_payload(index, prev, value, content):
    """构造第 index 帖的 payload（JSON 字典），字段严格按方案定义。"""
    content_hash = sha256_text(content)
    bind = sha256_text(value + "|" + content_hash)
    return {
        "scheme": SCHEME,
        "hash": HASH_NAME,
        "index": index,
        "prev": prev,
        "value": value,
        "content_hash": content_hash,
        "bind": bind,
    }


def render_post(content, payload):
    """把正文与 payload 拼成完整帖子文本。

    格式：<正文><空行><BEGIN 标记><payload JSON><END 标记><末尾换行>。
    """
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return "\n".join([content, "", BEGIN_MARK, payload_text, END_MARK, ""])


def read_draft(index):
    """读取 drafts/NN.txt（NN 为两位零填充），返回去掉末尾换行的正文。

    草稿不存在时返回 None。
    """
    path = os.path.join(DRAFTS_DIR, f"{index:02d}.txt")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().rstrip("\n")


def publish(index):
    """生成并发布第 index 帖（写 posts/NN.txt 并更新 state）。

    依次做越界、重复生成、跳号、缺草稿等校验，任一不满足则报错退出。
    """
    secret = load_secret()
    length = secret["length"]
    chain = secret["chain"]
    published = load_state().get("published", 0)

    if index < 1 or index > length:
        print(f"❌ 帖号越界：链长度为 {length}，无法生成第 {index} 帖")
        sys.exit(1)
    if index <= published:
        print(f"❌ 第 {index} 帖已生成过（posts/{index:02d}.txt 已存在），请勿重复生成")
        sys.exit(1)
    if index != published + 1:
        print(f"❌ 跳号：当前下一帖应为第 {published + 1} 帖，不能直接生成第 {index} 帖")
        sys.exit(1)

    content = read_draft(index)
    if content is None:
        print(f"❌ 未找到草稿 drafts/{index:02d}.txt，请先写入正文")
        sys.exit(1)

    prev = "" if index == 1 else chain[index - 2]
    value = chain[index - 1]
    payload = make_payload(index, prev, value, content)
    post_text = render_post(content, payload)

    post_path = os.path.join(POSTS_DIR, f"{index:02d}.txt")
    with open(post_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(post_text)

    save_state(index)
    print(f"✅ 已生成 posts/{index:02d}.txt（第 {index} 帖，已发布 {index}/{length}）")


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------
def cmd_init(args):
    """init 子命令：生成私密链并初始化状态（支持参数直传或交互输入）。"""
    ensure_dirs()

    seed = args.seed
    length = args.length

    if os.path.exists(SECRET_FILE):
        if args.yes:
            answer = "YES"
        else:
            print("⚠️ 已存在 secret/chain_secret.json，覆盖将丢失原有私密链。")
            try:
                answer = input("请输入 YES 确认覆盖：").strip()
            except (EOFError, KeyboardInterrupt):
                print("❌ 未收到确认输入，已取消覆盖")
                sys.exit(1)
        if answer != "YES":
            print("⚠️ 未输入 YES，已取消覆盖")
            sys.exit(0)

    if seed is None:
        try:
            seed = input("请输入种子（seed）：").strip()
        except (EOFError, KeyboardInterrupt):
            print("❌ 未收到种子输入")
            sys.exit(1)
    if not seed:
        print("❌ 种子不能为空")
        sys.exit(1)

    if length is None:
        try:
            length_raw = input("请输入链长度（length，正整数）：").strip()
        except (EOFError, KeyboardInterrupt):
            print("❌ 未收到链长度输入")
            sys.exit(1)
        try:
            length = int(length_raw)
        except ValueError:
            print(f"❌ 链长度必须是整数，收到：{length_raw!r}")
            sys.exit(1)
    if length < 1:
        print("❌ 链长度必须为正整数")
        sys.exit(1)

    chain = build_chain(seed, length)
    save_secret(seed, length, chain)
    save_state(0)

    print(f"✅ 已生成私密链：长度 {length}，种子 {seed!r}")
    print("✅ 已写入 secret/chain_secret.json 与 secret/chain_state.json（published=0）")
    print("⚠️ secret/ 目录绝不可公开；接下来请在 drafts/NN.txt 写入正文（NN 为两位序号）。")


def cmd_build(args):
    """build 子命令：--index N 生成第 N 帖，--all 从下一帖起连续生成。"""
    ensure_dirs()

    if args.index is not None:
        publish(args.index)
        return

    # --all：从 published+1 开始，依次生成直到无草稿或达链长度上限
    secret = load_secret()
    length = secret["length"]
    published = load_state().get("published", 0)

    nxt = published + 1
    if nxt > length:
        print(f"⏭️ 已达链长度上限（{length} 帖），没有可生成的帖子")
        return

    while nxt <= length:
        if read_draft(nxt) is None:
            print(f"⏭️ 第 {nxt} 帖无草稿（drafts/{nxt:02d}.txt），停止生成")
            return
        publish(nxt)
        nxt += 1

    print(f"⏭️ 已达链长度上限（{length} 帖），全部生成完毕")


def cmd_status(args):
    """status 子命令：打印链长度、已生成数、下一帖 index 及每帖草稿状态。"""
    secret = load_secret()
    length = secret["length"]
    published = load_state().get("published", 0)

    print(f"链长度：{length}")
    print(f"已生成：{published}")
    print(f"下一帖：{published + 1}")

    print("--- 草稿状态 ---")
    for i in range(1, length + 1):
        if i <= published:
            print(f"第 {i} 帖：✅ 已生成（posts/{i:02d}.txt）")
        elif os.path.exists(os.path.join(DRAFTS_DIR, f"{i:02d}.txt")):
            print(f"第 {i} 帖：📝 有草稿（drafts/{i:02d}.txt）")
        else:
            print(f"第 {i} 帖：⬜ 无草稿")

    # 超出链长度的草稿提醒（存在时）
    if os.path.isdir(DRAFTS_DIR):
        extra = []
        for name in sorted(os.listdir(DRAFTS_DIR)):
            if name.endswith(".txt") and name[:-4].isdigit():
                idx = int(name[:-4])
                if idx > length:
                    extra.append(idx)
        for idx in extra:
            print(f"⚠️ 第 {idx} 帖草稿（drafts/{idx:02d}.txt）超出链长度 {length}，将被忽略")


# ---------------------------------------------------------------------------
# 参数解析与入口
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    """解析命令行参数，返回 argparse.Namespace。"""
    parser = argparse.ArgumentParser(
        prog="chain_post.py",
        description="anon-leak 爆料人端：生成匿名哈希链帖子",
    )
    parser.add_argument("--base", metavar="DIR", default=None,
                        help="工作目录（默认：脚本所在目录）")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="初始化私密哈希链（输入种子与长度）")
    p_init.add_argument("--seed", default=None, help="种子（不给则交互输入）")
    p_init.add_argument("--length", type=int, default=None, help="链长度（不给则交互输入）")
    p_init.add_argument("--yes", action="store_true", help="已存在时直接覆盖（等同输入 YES）")

    p_build = sub.add_parser("build", help="生成帖子")
    group = p_build.add_mutually_exclusive_group(required=True)
    group.add_argument("--index", type=int, metavar="N", help="只生成第 N 帖")
    group.add_argument("--all", action="store_true", help="从下一帖起连续生成")

    sub.add_parser("status", help="查看链长度、已生成数与草稿状态")

    return parser.parse_args(argv)


def main(argv=None):
    """程序入口：按子命令分发。"""
    args = parse_args(argv)
    if args.base is not None:
        configure(args.base)
    if args.command == "init":
        cmd_init(args)
    elif args.command == "build":
        cmd_build(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        print("❌ 缺少子命令，请使用 init / build / status", file=sys.stderr)
        print("运行 python chain_post.py --help 查看帮助", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
