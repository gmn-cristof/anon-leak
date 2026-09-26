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
import datetime
import hashlib
import json
import os
import shutil
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
def get_value(seed, length, index):
    """返回第 index 帖应公开的链值（index 从 1 开始）。

    等价于旧方案里的 chain[index - 1]。按需现场计算，不预存整条链：
    从种子出发，重复哈希 (length - index + 1) 次。
    """
    cur = seed.encode("utf-8")
    for _ in range(length - index + 1):
        cur = sha256_hex(cur).encode("utf-8")
    return cur.decode("utf-8")


def compute_values(secret, index):
    """返回第 index 帖的 (prev, value)。

    value 由 get_value 现算（计算量 length - index + 1 次哈希）；
    prev 由 SHA256(value) 一步得到（第 1 帖为锚点，prev 为空串）。
    满足验证关系：SHA256(value_k) == prev_k。
    """
    seed = secret["seed"]
    length = secret["length"]
    value = get_value(seed, length, index)
    prev = "" if index == 1 else sha256_text(value)
    return prev, value


def build_chain(seed, length):
    """由种子 seed 生成长度为 length 的哈希链，按「发布顺序」返回。

    注意：方案 B 的主路径不再预存整条链，此函数仅在「旧格式迁移」时
    用于校验旧文件里的链是否与种子匹配，属于兼容逻辑，请勿在正常发布
    流程中使用（会占用与 length 成正比的内存与时间）。
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
def _is_v2_secret(obj):
    """判断是否为方案 B 的 v2 格式：dict 且带 version==2、seed、length。"""
    return (
        isinstance(obj, dict)
        and obj.get("version") == 2
        and isinstance(obj.get("seed"), str)
        and isinstance(obj.get("length"), int)
    )


def _legacy_kind(obj):
    """判断旧格式类型，返回 None（非旧格式）或 'array' / 'dict'。"""
    if isinstance(obj, list):
        return "array"
    if isinstance(obj, dict) and isinstance(obj.get("chain"), list):
        return "dict"
    return None


def _migrate_secret(obj):
    """把旧格式（数组或 dict+chain）迁移为 v2，返回 v2 字典。

    迁移前先把旧文件备份为 secret/chain_secret.json.bak（绝不删除旧文件）。
    旧数组无法反推种子，因此需要用户提供原种子；旧 dict 若已带 seed 则先
    自动校验，校验不通过再向用户索要。校验通过才写入新格式。
    """
    kind = _legacy_kind(obj)
    if kind == "array":
        chain = obj
        length = len(chain)
        known_seed = None
    else:  # kind == "dict"
        chain = obj["chain"]
        length = obj.get("length", len(chain))
        known_seed = obj.get("seed")

    print("warn: legacy secret/chain_secret.json detected (" +
          ("JSON array" if kind == "array" else "dict with full chain") + ").")
    print("      new scheme (plan B) only stores seed + length; original seed is needed to verify and migrate.")

    seed = known_seed
    if seed is not None:
        if build_chain(seed, length) == chain:
            print(f"      seed {seed!r} recorded in file verified, migrating automatically.")
        else:
            print("      seed recorded in file does not match chain; please provide the original seed.")
            seed = None

    if seed is None:
        try:
            seed = input("enter original seed to migrate: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("error: no seed input, migration cancelled. back up secret/ and re-init.", file=sys.stderr)
            sys.exit(1)
        if not seed:
            print("error: seed cannot be empty, migration cancelled. back up secret/ and re-init.", file=sys.stderr)
            sys.exit(1)
        if build_chain(seed, length) != chain:
            print("error: seed does not match old chain, migration failed. back up secret/ and re-init.", file=sys.stderr)
            sys.exit(1)

    # 先备份旧文件，绝不删除
    backup_path = SECRET_FILE + ".bak"
    shutil.copy2(SECRET_FILE, backup_path)

    created_at = datetime.datetime.now().isoformat(timespec="seconds")
    new_secret = {
        "version": 2,
        "seed": seed,
        "length": length,
        "created_at": created_at,
    }
    save_secret(seed, length, created_at=created_at)
    print(f"ok: migrated to plan B format (seed + length only), old file backed up as secret/chain_secret.json.bak")
    return new_secret


def load_secret():
    """读取 secret/chain_secret.json；旧格式自动迁移，损坏则报错退出。"""
    if not os.path.exists(SECRET_FILE):
        print("error: no secret file secret/chain_secret.json, run: python chain_post.py init", file=sys.stderr)
        sys.exit(1)
    try:
        obj = load_json(SECRET_FILE)
    except (OSError, ValueError) as exc:
        print(f"error: failed to read secret file (secret/chain_secret.json): {exc}", file=sys.stderr)
        sys.exit(1)

    if _is_v2_secret(obj):
        return obj
    if _legacy_kind(obj) is not None:
        return _migrate_secret(obj)
    print("error: unrecognized secret/chain_secret.json format (not v2 nor legacy)", file=sys.stderr)
    sys.exit(1)


def save_secret(seed, length, created_at=None):
    """把种子与长度写入 secret/chain_secret.json（v2，只存种子与长度）。"""
    if created_at is None:
        created_at = datetime.datetime.now().isoformat(timespec="seconds")
    save_json(SECRET_FILE, {
        "version": 2,
        "seed": seed,
        "length": length,
        "created_at": created_at,
    })


def load_state():
    """读取 secret/chain_state.json，返回 {"published": n}；不存在时视为 0。"""
    if not os.path.exists(STATE_FILE):
        return {"published": 0}
    try:
        return load_json(STATE_FILE)
    except (OSError, ValueError):
        print("error: failed to read state file (secret/chain_state.json), file may be corrupted", file=sys.stderr)
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


def publish(index, quiet=False):
    """生成并发布第 index 帖（写 posts/NN.txt 并更新 state）。

    依次做越界、重复生成、跳号、缺草稿等校验，任一不满足则报错退出。
    quiet 为 True 时不打印成功信息（供 anon_leak 上层自行输出）。
    """
    secret = load_secret()
    length = secret["length"]
    published = load_state().get("published", 0)

    if index < 1 or index > length:
        print(f"error: post index out of range: length {length}, cannot generate post {index}", file=sys.stderr)
        sys.exit(1)
    if index <= published:
        print(f"error: post {index} already generated (posts/{index:02d}.txt exists)", file=sys.stderr)
        sys.exit(1)
    if index != published + 1:
        print(f"error: skip detected: next post is {published + 1}, cannot generate {index}", file=sys.stderr)
        sys.exit(1)

    content = read_draft(index)
    if content is None:
        print(f"error: draft not found: drafts/{index:02d}.txt", file=sys.stderr)
        sys.exit(1)

    prev, value = compute_values(secret, index)
    payload = make_payload(index, prev, value, content)
    post_text = render_post(content, payload)

    post_path = os.path.join(POSTS_DIR, f"{index:02d}.txt")
    with open(post_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(post_text)

    save_state(index)
    if not quiet:
        print(f"ok: generated posts/{index:02d}.txt (post {index}, published {index}/{length})")


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
            print("warn: secret/chain_secret.json exists, overwrite will lose the chain.")
            try:
                answer = input("enter YES to overwrite: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("error: no confirmation input, overwrite cancelled", file=sys.stderr)
                sys.exit(1)
        if answer != "YES":
            print("warn: not YES, overwrite cancelled")
            sys.exit(0)

    if seed is None:
        try:
            seed = input("enter seed: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("error: no seed input", file=sys.stderr)
            sys.exit(1)
    if not seed:
        print("error: seed cannot be empty", file=sys.stderr)
        sys.exit(1)

    if length is None:
        try:
            length_raw = input("enter chain length (default 1000000, empty to use default): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("error: no length input", file=sys.stderr)
            sys.exit(1)
        if length_raw == "":
            length = 1000000
        else:
            try:
                length = int(length_raw)
            except ValueError:
                print(f"error: length must be an integer, got: {length_raw!r}", file=sys.stderr)
                sys.exit(1)
    if length < 1:
        print("error: length must be a positive integer", file=sys.stderr)
        sys.exit(1)

    save_secret(seed, length)
    save_state(0)

    print(f"ok: chain created: length {length}, seed {seed!r}")
    print("ok: wrote secret/chain_secret.json and secret/chain_state.json (published=0)")
    print("warn: never publish secret/; write drafts as drafts/NN.txt (NN two-digit).")


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
        print(f"skip: chain length limit reached ({length} posts), nothing to generate")
        return

    while nxt <= length:
        if read_draft(nxt) is None:
            print(f"skip: no draft for post {nxt} (drafts/{nxt:02d}.txt), stopping")
            return
        publish(nxt)
        nxt += 1

    print(f"skip: chain length limit reached ({length} posts), all generated")


def status_indices(length, published, draft_dir, limit=20):
    """返回 status 需要展示的帖号列表（有界，避免长链刷屏）。

    展示：前 min(published, limit) 个已发布帖、drafts/ 里实际存在的草稿、
    以及下一帖。结果升序且限定在 [1, length] 范围内。
    对长度很小的链，输出与原「逐帖展示」一致。
    """
    indices = set()
    for i in range(1, min(published, limit) + 1):
        indices.add(i)
    if published + 1 <= length:
        indices.add(published + 1)
    if os.path.isdir(draft_dir):
        for name in os.listdir(draft_dir):
            if name.endswith(".txt") and name[:-4].isdigit():
                idx = int(name[:-4])
                if 1 <= idx <= length:
                    indices.add(idx)
    return sorted(i for i in indices if 1 <= i <= length)


def cmd_status(args):
    """status 子命令：打印链长度、已生成数、下一帖 index 及每帖草稿状态。"""
    secret = load_secret()
    length = secret["length"]
    published = load_state().get("published", 0)

    print(f"length:   {length}")
    print(f"published: {published}")
    print(f"next:     {published + 1}")

    print("--- post status ---")
    shown = status_indices(length, published, DRAFTS_DIR)
    for i in shown:
        if i <= published:
            print(f"post {i:02d}: ok  generated (posts/{i:02d}.txt)")
        elif os.path.exists(os.path.join(DRAFTS_DIR, f"{i:02d}.txt")):
            print(f"post {i:02d}: -   draft (drafts/{i:02d}.txt)")
        else:
            print(f"post {i:02d}: -   no draft")
    remaining = length - len(shown)
    if remaining > 0:
        print(f"({remaining} posts not shown, use add -i or drafts/NN.txt)")

    # 超出链长度的草稿提醒（存在时）
    if os.path.isdir(DRAFTS_DIR):
        extra = []
        for name in sorted(os.listdir(DRAFTS_DIR)):
            if name.endswith(".txt") and name[:-4].isdigit():
                idx = int(name[:-4])
                if idx > length:
                    extra.append(idx)
        for idx in extra:
            print(f"warn: draft {idx:02d} (drafts/{idx:02d}.txt) beyond length {length}, will be ignored")


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
        print("error: missing subcommand, use init / build / status", file=sys.stderr)
        print("run: python chain_post.py --help", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
