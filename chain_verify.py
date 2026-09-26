#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anon-leak 读者端脚本。

读者只凭公开的帖子内容，即可验证：
    1. 所有帖子来自同一条哈希链（同源）；
    2. 帖子顺序正确；
    3. 正文未被篡改；
    4. 攻击者无法伪造后续帖子。

用法：
    python chain_verify.py file1.txt file2.txt ...   # 按指定文件验证
    python chain_verify.py --dir posts/              # 验证目录下所有 .txt 帖子
"""

import argparse
import hashlib
import json
import os
import sys

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SCHEME = "anon-hash-chain-v1"
HASH_NAME = "sha256"
BEGIN_MARK = "-----BEGIN ANON CHAIN-----"
END_MARK = "-----END ANON CHAIN-----"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def sha256_hex(data):
    """计算字节数据的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    """计算字符串（按 UTF-8 编码）的 SHA-256 十六进制摘要。"""
    return sha256_hex(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# 帖子解析
# ---------------------------------------------------------------------------
def split_post(raw_text):
    """把帖子文件文本拆成 (正文, payload 文本)。

    正文取 BEGIN 标记之前的内容（去掉末尾换行），payload 取两个标记之间的内容。
    找不到两个标记时返回 (None, None)。
    """
    lines = raw_text.split("\n")
    begin_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s == BEGIN_MARK:
            begin_idx = i
        elif s == END_MARK:
            end_idx = i
            break
    if begin_idx is None or end_idx is None or begin_idx >= end_idx:
        return None, None
    content = "\n".join(lines[:begin_idx]).rstrip("\n")
    payload_text = "\n".join(lines[begin_idx + 1:end_idx])
    return content, payload_text


def load_post_file(path):
    """读取并解析单个帖子文件，返回 (正文, payload 字典)。

    文件不存在、编码错误、缺少 ANON CHAIN 标记或 JSON 解析失败时，
    打印中文错误并以退出码 2 退出。
    """
    if not os.path.exists(path):
        print(f"❌ 无法读取文件：{path}（文件不存在）")
        sys.exit(2)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"❌ 无法读取文件：{path}（{exc}）")
        sys.exit(2)

    content, payload_text = split_post(raw)
    if content is None:
        print(f"❌ 未找到 ANON CHAIN 标记：{path}")
        sys.exit(2)

    try:
        payload = json.loads(payload_text)
    except ValueError as exc:
        print(f"❌ payload JSON 解析失败：{path}（{exc}）")
        sys.exit(2)

    return content, payload


# ---------------------------------------------------------------------------
# 帖子校验
# ---------------------------------------------------------------------------
def verify_post(name, content, payload, expected_prev):
    """校验单帖，逐条打印结果，返回 (ok, value, index)。

    name 为用于展示的文件名；expected_prev 为上一帖公开的 value
    （第 1 帖或单帖验证缺失上一帖时传 None）。
    """
    ok = True
    index = payload.get("index", "?")
    print(f"--- 第 {index} 帖（{name}）---")

    required = ["scheme", "hash", "index", "prev", "value", "content_hash", "bind"]
    missing = [k for k in required if k not in payload]
    if missing:
        print(f"  ❌ payload 缺少字段：{', '.join(missing)}")
        return False, None, None

    if payload["scheme"] != SCHEME:
        print(f"  ❌ scheme 不匹配：期望 {SCHEME!r}，实际 {payload['scheme']!r}")
        return False, None, None
    if payload["hash"] != HASH_NAME:
        print(f"  ❌ hash 算法不匹配：期望 {HASH_NAME!r}，实际 {payload['hash']!r}")
        return False, None, None

    idx = payload["index"]
    value = payload["value"]
    prev = payload["prev"]

    # 正文哈希：content_hash == SHA256(正文)
    expected_content_hash = sha256_text(content)
    if payload["content_hash"] == expected_content_hash:
        print("  ✅ 正文哈希匹配")
    else:
        print("  ❌ 正文哈希不匹配（content_hash 与正文的 SHA-256 不一致）")
        ok = False

    # 内容绑定：bind == SHA256(value + "|" + content_hash)
    expected_bind = sha256_text(value + "|" + payload["content_hash"])
    if payload["bind"] == expected_bind:
        print("  ✅ 内容绑定匹配")
    else:
        print('  ❌ 内容绑定不匹配（bind != SHA256(value + "|" + content_hash)）')
        ok = False

    # 链值连续 / 锚点
    if idx == 1:
        if prev == "":
            print("  ✅ 锚点正常")
        else:
            print("  ❌ 锚点异常：第 1 帖的 prev 必须为空字符串")
            ok = False
    else:
        if expected_prev is None:
            print(f"  ❌ 缺失上一帖（第 {idx - 1} 帖）：index 不连续，无法验证链值连续性")
            ok = False
        elif prev == expected_prev and sha256_text(value) == prev:
            print("  ✅ 链值连续")
        else:
            print("  ❌ 链值不连续：SHA256(value) ≠ prev（prev 不匹配）")
            ok = False

    return ok, value, idx


# ---------------------------------------------------------------------------
# 链条校验
# ---------------------------------------------------------------------------
def verify_chain(posts):
    """对已载入的帖子列表按 index 排序后整体校验，返回是否全部通过。

    posts 为 [(name, content, payload), ...] 列表。
    """
    if not posts:
        print("❌ 没有可验证的帖子")
        return False

    try:
        ordered = sorted(posts, key=lambda t: t[2]["index"])
    except (KeyError, TypeError):
        print("❌ 存在缺少 index 字段的帖子，无法排序")
        return False

    original_indices = [t[2].get("index") for t in posts]
    sorted_indices = [t[2].get("index") for t in ordered]
    if original_indices != sorted_indices:
        print("⚠️ 传入顺序与 index 不符，已自动按 index 排序")

    all_ok = True
    expected_prev = None
    expect_index = 1
    for name, content, payload in ordered:
        idx = payload.get("index")
        if idx != expect_index:
            print(f"❌ index 不连续：期望第 {expect_index} 帖，实际第 {idx} 帖")
            all_ok = False
            ok, _, _ = verify_post(name, content, payload, None)
            all_ok = all_ok and ok
            if isinstance(idx, int):
                expect_index = idx + 1
            continue
        ok, value, _ = verify_post(name, content, payload, expected_prev)
        all_ok = all_ok and ok
        expected_prev = value
        expect_index += 1

    return all_ok


# ---------------------------------------------------------------------------
# 目录收集与入口
# ---------------------------------------------------------------------------
def collect_dir(dirpath):
    """收集目录下所有 .txt 文件路径，按文件名排序返回。

    目录不存在或无 .txt 文件时打印中文错误并以退出码 2 退出。
    """
    if not os.path.isdir(dirpath):
        print(f"❌ 目录不存在：{dirpath}")
        sys.exit(2)
    names = sorted(n for n in os.listdir(dirpath) if n.endswith(".txt"))
    if not names:
        print(f"❌ 目录中没有 .txt 帖子文件：{dirpath}")
        sys.exit(2)
    return [os.path.join(dirpath, n) for n in names]


def parse_args(argv=None):
    """解析命令行参数，返回 argparse.Namespace。"""
    parser = argparse.ArgumentParser(
        prog="chain_verify.py",
        description="anon-leak 读者端：验证匿名哈希链帖子",
    )
    parser.add_argument("files", nargs="*", help="待验证的帖子文件（可多个）")
    parser.add_argument("--dir", dest="directory", metavar="DIR", help="验证目录下所有 .txt 帖子")
    return parser.parse_args(argv)


def main(argv=None):
    """程序入口：载入帖子、整体校验、按结果打印并设置退出码。"""
    args = parse_args(argv)

    if args.directory:
        paths = collect_dir(args.directory)
    elif args.files:
        paths = args.files
    else:
        print("❌ 请提供帖子文件或使用 --dir 指定目录", file=sys.stderr)
        print("用法：python chain_verify.py file1.txt [file2.txt ...]  或  python chain_verify.py --dir posts/", file=sys.stderr)
        sys.exit(2)

    posts = []
    for p in paths:
        content, payload = load_post_file(p)
        posts.append((os.path.basename(p), content, payload))

    if verify_chain(posts):
        print("🎉 验证通过：所有帖子同源，顺序正确，正文未被篡改")
        sys.exit(0)
    else:
        print("⚠️ 验证失败，以上错误导致链条不可信")
        sys.exit(1)


if __name__ == "__main__":
    main()
