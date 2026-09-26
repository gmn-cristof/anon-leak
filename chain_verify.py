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
# 输出层（只改展示，不改变任何验证逻辑）
# ---------------------------------------------------------------------------
GREEN = "32"
RED = "31"
YELLOW = "33"
DIM = "2"
RESET = "0"

COLOR_ENABLED = True
VERBOSE = False
QUIET = False


def color(s, code):
    """仅在 TTY 且未禁用颜色时输出 ANSI 颜色；否则原样返回。"""
    if not COLOR_ENABLED or not sys.stdout.isatty():
        return s
    return f"\x1b[{code}m{s}\x1b[0m"


def set_output(verbose=False, quiet=False, color_enabled=True):
    """设置输出层全局开关（由 main 调用）。"""
    global VERBOSE, QUIET, COLOR_ENABLED
    VERBOSE = verbose
    QUIET = quiet
    COLOR_ENABLED = color_enabled


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
        print(f"error: cannot read file: {path} (not found)", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read file: {path} ({exc})", file=sys.stderr)
        sys.exit(2)

    content, payload_text = split_post(raw)
    if content is None:
        print(f"error: missing ANON CHAIN markers: {path}", file=sys.stderr)
        sys.exit(2)

    try:
        payload = json.loads(payload_text)
    except ValueError as exc:
        print(f"error: payload JSON parse failed: {path} ({exc})", file=sys.stderr)
        sys.exit(2)

    return content, payload


# ---------------------------------------------------------------------------
# 帖子校验
# ---------------------------------------------------------------------------
def verify_post(name, content, payload, expected_prev):
    """校验单帖，返回结构化结果（不直接打印）。

    name 为展示用文件名；expected_prev 为上一帖公开的 value（第 1 帖或
    缺失上一帖时传 None）。返回字典：
      name, index, ok, value, checks:{hash,bind,chain}, errors, detail
    校验规则与原实现完全一致。
    """
    index = payload.get("index", "?")
    result = {
        "name": name,
        "index": index,
        "ok": True,
        "value": None,
        "checks": {"hash": True, "bind": True, "chain": True},
        "errors": [],
        "detail": [],
    }

    required = ["scheme", "hash", "index", "prev", "value", "content_hash", "bind"]
    missing = [k for k in required if k not in payload]
    if missing:
        result["ok"] = False
        result["errors"].append({"code": "missing", "msg": f"payload missing fields: {', '.join(missing)}"})
        result["detail"].append((False, f"payload missing fields: {', '.join(missing)}"))
        return result

    if payload["scheme"] != SCHEME:
        result["ok"] = False
        result["errors"].append({"code": "scheme", "msg": f"scheme mismatch: expected {SCHEME!r}, got {payload['scheme']!r}"})
        result["detail"].append((False, "scheme mismatch"))
        return result
    if payload["hash"] != HASH_NAME:
        result["ok"] = False
        result["errors"].append({"code": "hash", "msg": f"hash mismatch: expected {HASH_NAME!r}, got {payload['hash']!r}"})
        result["detail"].append((False, "hash algorithm mismatch"))
        return result

    idx = payload["index"]
    value = payload["value"]
    prev = payload["prev"]
    result["value"] = value

    # 正文哈希：content_hash == SHA256(正文)
    expected_content_hash = sha256_text(content)
    if payload["content_hash"] == expected_content_hash:
        result["detail"].append((True, "content hash ok"))
    else:
        result["ok"] = False
        result["checks"]["hash"] = False
        result["detail"].append((False, "content hash mismatch"))
        result["errors"].append({
            "code": "content_hash",
            "msg": "content_hash mismatch (post tampered)",
            "expected": expected_content_hash,
            "actual": payload["content_hash"],
        })

    # 内容绑定：bind == SHA256(value + "|" + content_hash)
    expected_bind = sha256_text(value + "|" + payload["content_hash"])
    if payload["bind"] == expected_bind:
        result["detail"].append((True, "bind ok"))
    else:
        result["ok"] = False
        result["checks"]["bind"] = False
        result["detail"].append((False, "bind mismatch"))
        result["errors"].append({
            "code": "bind",
            "msg": "bind mismatch",
            "expected": expected_bind,
            "actual": payload["bind"],
        })

    # 链值连续 / 锚点
    if idx == 1:
        if prev == "":
            result["detail"].append((True, "anchor ok"))
        else:
            result["ok"] = False
            result["checks"]["chain"] = False
            result["detail"].append((False, "anchor broken: post 1 prev must be empty"))
            result["errors"].append({"code": "anchor", "msg": "anchor broken: post 1 prev must be empty"})
    else:
        if expected_prev is None:
            result["ok"] = False
            result["checks"]["chain"] = False
            result["detail"].append((False, f"missing post {idx - 1}: index not continuous"))
            result["errors"].append({"code": "chain", "msg": f"missing post {idx - 1}: index not continuous"})
        elif prev == expected_prev and sha256_text(value) == prev:
            result["detail"].append((True, "chain continuous"))
        else:
            result["ok"] = False
            result["checks"]["chain"] = False
            result["detail"].append((False, "chain broken: SHA256(value) != prev"))
            result["errors"].append({
                "code": "chain",
                "msg": "SHA256(value) != prev",
                "expected": expected_prev,
                "actual": prev,
            })

    return result


# ---------------------------------------------------------------------------
# 链条校验
# ---------------------------------------------------------------------------
def verify_chain(posts):
    """对已载入的帖子列表按 index 排序后整体校验，返回 (all_ok, results)。

    posts 为 [(name, content, payload), ...] 列表；results 为按展示顺序排列的
    每个帖子的 verify_post 结果字典。
    """
    results = []
    if not posts:
        return False, results

    try:
        ordered = sorted(posts, key=lambda t: t[2]["index"])
    except (KeyError, TypeError):
        return False, results

    all_ok = True
    expected_prev = None
    expect_index = 1
    for name, content, payload in ordered:
        idx = payload.get("index")
        if idx != expect_index:
            res = verify_post(name, content, payload, None)
            res["ok"] = False
            res["errors"].insert(0, {"code": "gap", "msg": f"index not continuous: expected {expect_index}, got {idx}"})
            res["detail"].insert(0, (False, f"index not continuous: expected {expect_index}, got {idx}"))
            results.append(res)
            all_ok = False
            if isinstance(idx, int):
                expect_index = idx + 1
            continue
        res = verify_post(name, content, payload, expected_prev)
        results.append(res)
        all_ok = all_ok and res["ok"]
        expected_prev = res.get("value")
        expect_index += 1

    return all_ok, results


# ---------------------------------------------------------------------------
# 结果渲染
# ---------------------------------------------------------------------------
def print_results(results, ok):
    """打印紧凑验证表格与总结（ASCII，颜色仅在 TTY 生效）。"""
    if not results:
        print(color("verify: FAIL", RED))
        print("  no posts to verify")
        return

    def cell(text, good):
        return color(text.ljust(6), GREEN if good else RED)

    print(f"{'POST':<6} {'HASH':<6} {'BIND':<6} {'CHAIN':<6}")
    for r in results:
        idx = r["index"]
        post = f"{idx:02d}" if isinstance(idx, int) else str(idx)
        c = r["checks"]
        print(f"{post:<6} {cell('ok' if c['hash'] else 'FAIL', c['hash'])} "
              f"{cell('ok' if c['bind'] else 'FAIL', c['bind'])} "
              f"{cell('ok' if c['chain'] else 'FAIL', c['chain'])}")
    print()
    print_summary(ok, results)


def print_summary(ok, results):
    """打印验证总结（不含表格）；失败时附带错误详情。"""
    if ok:
        n = len(results)
        print(color(f"verify: pass ({n} posts, same origin, order ok, no tamper)", GREEN))
    else:
        print(color("verify: FAIL", RED))
        for r in results:
            for e in r["errors"]:
                print(f"  {r['name']}: {e['msg']}")
                if e.get("expected") is not None:
                    print(f"  expected  {e['expected']}")
                    print(f"  actual    {e['actual']}")


def print_verbose(results):
    """逐帖打印详细验证过程（--verbose 时使用，ASCII）。"""
    for r in results:
        idx = r["index"]
        print(f"--- post {idx} ({r['name']}) ---")
        for good, text in r["detail"]:
            mark = "ok" if good else "FAIL"
            print(f"  {color(mark, GREEN if good else RED)}  {text}")


# ---------------------------------------------------------------------------
# 目录收集与入口
# ---------------------------------------------------------------------------
def collect_dir(dirpath):
    """收集目录下所有 .txt 文件路径，按文件名排序返回。

    目录不存在或无 .txt 文件时打印中文错误并以退出码 2 退出。
    """
    if not os.path.isdir(dirpath):
        print(f"error: directory not found: {dirpath}", file=sys.stderr)
        sys.exit(2)
    names = sorted(n for n in os.listdir(dirpath) if n.endswith(".txt"))
    if not names:
        print(f"error: no .txt post files in directory: {dirpath}", file=sys.stderr)
        sys.exit(2)
    return [os.path.join(dirpath, n) for n in names]


def parse_args(argv=None):
    """解析命令行参数，返回 argparse.Namespace。"""
    parser = argparse.ArgumentParser(
        prog="chain_verify.py",
        description="anon-leak reader: verify anonymous hash-chain posts",
    )
    parser.add_argument("files", nargs="*", help="post files to verify")
    parser.add_argument("--dir", dest="directory", metavar="DIR", help="verify all .txt files in DIR")
    parser.add_argument("-v", "--verbose", action="store_true", help="print per-post detail")
    parser.add_argument("-q", "--quiet", action="store_true", help="print only the result line")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    return parser.parse_args(argv)


def main(argv=None):
    """程序入口：载入帖子、整体校验、按结果打印并设置退出码。"""
    args = parse_args(argv)
    set_output(verbose=args.verbose, quiet=args.quiet, color_enabled=not args.no_color)

    if args.directory:
        paths = collect_dir(args.directory)
    elif args.files:
        paths = args.files
    else:
        print("error: provide post files or --dir DIR", file=sys.stderr)
        print("usage: chain_verify.py file1.txt [file2.txt ...]  or  chain_verify.py --dir DIR", file=sys.stderr)
        sys.exit(2)

    posts = []
    for p in paths:
        content, payload = load_post_file(p)
        posts.append((os.path.basename(p), content, payload))

    ok, results = verify_chain(posts)
    if VERBOSE:
        print_verbose(results)
        print()
    if QUIET:
        print("verify: pass" if ok else "verify: FAIL")
    else:
        print_results(results, ok)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
