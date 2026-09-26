#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anon_leak 一体化命令行工具。

在「每个 leak 一个文件夹」的基础上，把爆料人的完整工作流打包成一条命令：
创建哈希链、写草稿、发布帖子、本地自检、导出公开产物、验证等。

所有密码学逻辑（哈希链构造、payload 生成、帖子渲染、验证）都复用
chain_post.py 与 chain_verify.py，本文件只负责「多 leak 管理 + 交互/简化操作」。

用法：
    anon_leak                                   # 总览
    anon_leak create <名字> [-n 长度] [-s 种子]   # 创建爆料链
    anon_leak list / status / start / add / verify / show / export / doctor / guide
"""

import argparse
import datetime
import getpass
import json
import os
import shutil
import sys

# 让脚本无论从何处运行都能 import 同目录的底层模块
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import chain_post
import chain_verify


# ---------------------------------------------------------------------------
# 常量与全局
# ---------------------------------------------------------------------------
META_FILE = "leak.json"
GITIGNORE_FILE = ".gitignore"
EXPORT_DIR = "export"
VERSION = "0.2.0"

GREEN = "32"
RED = "31"
YELLOW = "33"
CYAN = "36"
DIM = "2"
RESET = "0"

# banner 专用
BRIGHT_CYAN = "96"
BRIGHT_BLUE = "94"
BRIGHT_MAGENTA = "95"
BRIGHT_WHITE = "97"
BOLD = "1"

_QUIET = False
_NO_BANNER = False
_VERBOSE = False

_ROOT = os.getcwd()  # 工作区根目录，main() 里可用 --root 覆盖


def set_root(path):
    """设置工作区根目录（绝对路径）。"""
    global _ROOT
    _ROOT = os.path.abspath(path)


def root_dir():
    """返回工作区根目录。"""
    return _ROOT


def leak_dir(name):
    """返回某个 leak 的文件夹绝对路径。"""
    return os.path.join(root_dir(), name)


def meta_path(name):
    return os.path.join(leak_dir(name), META_FILE)


def draft_path(name, index):
    return os.path.join(leak_dir(name), "drafts", f"{index:02d}.txt")


def post_path(name, index):
    return os.path.join(leak_dir(name), "posts", f"{index:02d}.txt")


def use_leak(name):
    """把 chain_post 的工作目录切换到指定 leak 文件夹。"""
    chain_post.configure(leak_dir(name))


# ---------------------------------------------------------------------------
# 输出辅助（专业 CLI 输出层）
# ---------------------------------------------------------------------------
def color(s, code):
    """仅在 TTY 下输出 ANSI 颜色；否则原样返回。"""
    if not sys.stdout.isatty():
        return s
    if os.environ.get("NO_COLOR"):
        return s
    if os.environ.get("TERM") == "dumb":
        return s
    return f"\x1b[{code}m{s}\x1b[0m"


def rel(path):
    """把绝对路径转成相对当前工作目录的路径（失败则原样返回）。"""
    try:
        return os.path.relpath(path, os.getcwd())
    except ValueError:
        return path


# ---------------------------------------------------------------------------
# 四级 banner（按命令频率选用不同炫酷程度）
# ---------------------------------------------------------------------------
_B1_W = 63  # 级别 1 方块内宽

_B1_ART = [
    "     ▄▀█ █▄ █ █▀█ █▄ █   █   █▀▀ ▄▀█ █▄▀",
    "     █▀█ █ ▀█ █▄█ █ ▀█   █▄▄ ██▄ █▀█ █ █",
]
_B1_SLOGAN1 = "     anonymous hash-chain leak tool  ·  "
_B1_SLOGAN2 = "     verify origin without revealing identity"

_B2_ART = [ 
" █████╗ ███╗   ██╗ ██████╗ ███╗   ██╗    ██╗     ███████╗ █████╗ ██╗  ██╗",
"██╔══██╗████╗  ██║██╔═══██╗████╗  ██║    ██║     ██╔════╝██╔══██╗██║ ██╔╝",
"███████║██╔██╗ ██║██║   ██║██╔██╗ ██║    ██║     █████╗  ███████║█████╔╝ ",
"██╔══██║██║╚██╗██║██║   ██║██║╚██╗██║    ██║     ██╔══╝  ██╔══██║██╔═██╗ ",
"██║  ██║██║ ╚████║╚██████╔╝██║ ╚████║    ███████╗███████╗██║  ██║██║  ██╗",
"╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═══╝    ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝",
]

                                                                                                          
                                                                                                                                                                                     
                                                                                                               



_B2_VER = f"  anon-leak  v{VERSION}"

_B3_LINE1 = "  anon-leak · anonymous hash-chain leak tool"
_B3_RULE = "  " + "─" * 45

_B4_LINE = f"anon-leak v{VERSION}"


def _b1_line(segments):
    """把 (text, code|None) 段拼成一行，右补空格到 _B1_W，加亮青边框。"""
    visible = sum(len(t) for t, _ in segments)
    body = "".join(color(t, c) if c else t for t, c in segments)
    body += " " * max(0, _B1_W - visible)
    bar = color("║", BRIGHT_CYAN)
    return bar + body + bar


def _banner_text(level):
    """返回指定级别 banner 的完整文本（不含尾随空行）。"""
    if level == 1:
        art_code = f"{BOLD};{BRIGHT_CYAN}"
        lines = [
            color("╔" + "═" * _B1_W + "╗", BRIGHT_CYAN),
            _b1_line([]),
        ]
        for a in _B1_ART:
            lines.append(_b1_line([(a, art_code)]))
        lines.append(_b1_line([]))
        lines.append(_b1_line([(_B1_SLOGAN1, DIM), (f"v{VERSION}", BRIGHT_WHITE)]))
        lines.append(_b1_line([(_B1_SLOGAN2, DIM)]))
        lines.append(_b1_line([]))
        lines.append(color("╚" + "═" * _B1_W + "╝", BRIGHT_CYAN))
        return "\n".join(lines)
    if level == 2:
        art_code = f"{BOLD};{BRIGHT_CYAN}"
        lines = [color(a, art_code) for a in _B2_ART]
        lines.append("")
        lines.append(color(_B2_VER, DIM))
        return "\n".join(lines)
    if level == 3:
        return "\n".join([
            color(_B3_LINE1, DIM),
            color(_B3_RULE, DIM),
            color("  v" + VERSION, BRIGHT_WHITE),
        ])
    if level == 4:
        return _B4_LINE
    return ""


def print_banner(level):
    """打印指定级别 banner；非 TTY、quiet/no-banner 或 level 为空时静默跳过。"""
    if not level or _QUIET or _NO_BANNER:
        return
    if not sys.stdout.isatty():
        return
    print(_banner_text(level))
    print()


def next_block(lines):
    """命令结尾的 next: 提示；--quiet 时整体不输出。"""
    if _QUIET:
        return
    print()
    print("next:")
    for ln in lines:
        print("  " + ln)


def ok(msg):
    print(color("ok", GREEN) + "  " + msg)


def warn(msg):
    print(color("warn:", YELLOW) + " " + msg)


def err(msg):
    print(color("error:", RED) + " " + msg, file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# 名称校验与 leak 发现
# ---------------------------------------------------------------------------
def validate_leak_name(name):
    """校验 leak 名字，返回错误描述字符串；合法则返回 None。"""
    if not name:
        return "name cannot be empty"
    if name in (".", ".."):
        return "name cannot be . or .."
    if len(name) > 64:
        return "name too long (max 64 characters)"
    if any(ch in name for ch in "/\\"):
        return "name cannot contain path separators"
    for ch in name:
        if not (ch.isalnum() or ch in "_-."):
            return f"name contains invalid character: {ch!r}"
    return None


def is_leak_name(name):
    """判断一个字符串是否为当前工作区下已存在的 leak 名字。"""
    return (
        os.path.isdir(leak_dir(name))
        and os.path.exists(os.path.join(leak_dir(name), "secret", "chain_secret.json"))
    )


def discover_leaks():
    """扫描工作区，返回所有 leak 名字（按名称排序）。"""
    root = root_dir()
    leaks = []
    if not os.path.isdir(root):
        return leaks
    for name in sorted(os.listdir(root)):
        if is_leak_name(name):
            leaks.append(name)
    return leaks


def resolve_leak(name):
    """解析 leak 名字：未给时若仅有一个则自动选中，否则报错并列出候选。"""
    if name:
        return name
    leaks = discover_leaks()
    if len(leaks) == 1:
        return leaks[0]
    if not leaks:
        err("no leak here; run: anon_leak create <name>")
    err("multiple leaks, specify a name. candidates: " + ", ".join(leaks))


# ---------------------------------------------------------------------------
# 元信息与 .gitignore
# ---------------------------------------------------------------------------
def save_meta(name, meta):
    """写入 leak.json（公开元信息，不含 seed/chain）。"""
    with open(meta_path(name), "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def write_gitignore(name):
    """在 leak 目录写入 .gitignore（忽略 secret/）。"""
    with open(os.path.join(leak_dir(name), GITIGNORE_FILE), "w", encoding="utf-8", newline="\n") as f:
        f.write("secret/\n")


def gitignore_covers_secret(name):
    """检查 leak 目录或工作区根目录的 .gitignore 是否忽略了 secret/。"""
    for directory in (leak_dir(name), root_dir()):
        gi = os.path.join(directory, GITIGNORE_FILE)
        if os.path.isfile(gi):
            with open(gi, "r", encoding="utf-8") as f:
                if any(line.strip() == "secret/" for line in f):
                    return True
    return False


# ---------------------------------------------------------------------------
# 输入辅助
# ---------------------------------------------------------------------------
def prompt_seed():
    """用 getpass 隐藏回显输入种子，并要求二次确认。"""
    try:
        seed = getpass.getpass("seed (input hidden): ").strip()
    except (EOFError, KeyboardInterrupt):
        err("no seed input")
    if not seed:
        err("seed cannot be empty")
    try:
        confirm = getpass.getpass("confirm seed: ").strip()
    except (EOFError, KeyboardInterrupt):
        err("no confirmation input")
    if seed != confirm:
        err("seed mismatch, cancelled")
    return seed


def prompt_length():
    """交互式输入链长度（正整数），空输入默认 1000000。"""
    try:
        raw = input("length (positive integer, default 1000000): ").strip()
    except (EOFError, KeyboardInterrupt):
        err("no length input")
    if raw == "":
        return 1000000
    try:
        n = int(raw)
    except ValueError:
        err(f"length must be an integer, got: {raw!r}")
    return n


def read_content_interactive(index):
    """交互式读取正文：多行粘贴，最后单独一行 EOF 结束。"""
    print("content (end with EOF):")
    lines = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip() == "EOF":
            break
        lines.append(line)
    return "\n".join(lines).rstrip("\n")


def read_file_content(path):
    """读取正文文件，返回去掉末尾换行的内容。"""
    if not os.path.exists(path):
        err(f"file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().rstrip("\n")


def confirm(question, default=False):
    """交互确认；非 TTY（EOF）时返回 default。"""
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        ans = input(question + suffix + ": ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if ans == "":
        return default
    return ans in ("y", "yes")


def write_draft(name, index, content):
    """把正文写入 drafts/NN.txt（UTF-8、末尾换行）。"""
    with open(draft_path(name, index), "w", encoding="utf-8", newline="\n") as f:
        f.write(content + "\n")


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
def do_create(name, seed=None, length=None, random_seed=False):
    """创建一条 leak：建目录、生成链、写元信息与 .gitignore。返回名字。"""
    err_msg = validate_leak_name(name)
    if err_msg:
        err(f"invalid leak name {name!r}: {err_msg}")
    if os.path.exists(leak_dir(name)):
        err(f"leak already exists: {leak_dir(name)} (rename or remove first)")

    show_full_seed = False
    if random_seed:
        seed = os.urandom(32).hex()
        show_full_seed = True
    elif seed is None:
        seed = prompt_seed()
    else:
        warn("seed passed on command line; shell history may leak it.")

    if length is None:
        length = prompt_length()
    if length < 1:
        err("length must be a positive integer")

    chain_post.configure(leak_dir(name))
    chain_post.ensure_dirs()
    chain_post.save_secret(seed, length)
    chain_post.save_state(0)

    root_value = chain_post.get_value(seed, length, 1)

    save_meta(name, {
        "name": name,
        "scheme": chain_post.SCHEME,
        "hash": chain_post.HASH_NAME,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "version": VERSION,
        "length": length,
    })
    write_gitignore(name)

    if show_full_seed:
        print(f"seed:    {seed}   (store offline now; shown once)")
    else:
        print(f"seed:    {'*' * 16}")
    print(f"length:  {length}")
    print(f"root:    {root_value[:32]}...")
    print(f"created: {name}")
    print(f"backup:  {rel(os.path.join(leak_dir(name), 'secret'))}/ (offline, never publish)")
    next_block([
        f"anon_leak start {name}      # write post 1",
        "anon_leak guide             # anonymous publishing checklist",
    ])
    return name


def cmd_create(args):
    """create 子命令。"""
    first = not os.path.isdir(os.path.join(leak_dir(args.name), "secret"))
    print_banner(4 if first else None)
    do_create(args.name, seed=args.seed, length=args.length, random_seed=args.random_seed)


# ---------------------------------------------------------------------------
# 验证复用
# ---------------------------------------------------------------------------
def collect_post_files(name):
    """返回某 leak 的 posts/ 目录下所有 .txt 文件（按文件名排序）。"""
    directory = os.path.join(leak_dir(name), "posts")
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, n) for n in os.listdir(directory) if n.endswith(".txt"))


def verify_paths(paths):
    """验证一组帖子文件，返回 (all_ok, results)，不打印任何内容。

    文件缺失/解析错误等由 chain_verify 打印错误并以 SystemExit(2) 退出，
    此处捕获并视为验证失败（返回 (False, [])）。
    """
    if not paths:
        return False, []
    try:
        posts = []
        for p in paths:
            content, payload = chain_verify.load_post_file(p)
            posts.append((os.path.basename(p), content, payload))
        return chain_verify.verify_chain(posts)
    except SystemExit:
        return False, []


# ---------------------------------------------------------------------------
# 发布相关
# ---------------------------------------------------------------------------
def validate_index(name, index):
    """校验帖号（越界/重复/跳号），通过则返回 (secret, published)。"""
    use_leak(name)
    secret = chain_post.load_secret()
    length = secret["length"]
    published = chain_post.load_state().get("published", 0)
    if index < 1 or index > length:
        err(f"post index out of range: length {length}, cannot generate post {index}")
    if index <= published:
        err(f"post {index} already generated (posts/{index:02d}.txt exists)")
    if index != published + 1:
        err(f"skip detected: next post is {published + 1}, cannot generate {index}")
    return secret, published


def preview_post(name, index, content):
    """打印第 index 帖的完整渲染预览（不写入任何文件）。"""
    use_leak(name)
    secret = chain_post.load_secret()
    prev, value = chain_post.compute_values(secret, index)
    payload = chain_post.make_payload(index, prev, value, content)
    print("----- preview (nothing written) -----")
    print(chain_post.render_post(content, payload), end="")
    print("----- end preview -----")


def publish_with_rollback(name, index):
    """发布第 index 帖，随后对整条链自检；失败则回滚并报错。"""
    use_leak(name)
    chain_post.publish(index, quiet=True)  # 校验失败会自行报错退出
    okv, _ = verify_paths(collect_post_files(name))
    if not okv:
        warn(f"post {index} self-check failed, rolling back")
        os.remove(post_path(name, index))
        chain_post.save_state(index - 1)
        err(f"post {index} self-check failed, rolled back; check draft content")


# ---------------------------------------------------------------------------
# list / status
# ---------------------------------------------------------------------------
def leak_status(name):
    """读取某个 leak 的状态，返回 (name, published, length, next, status)。"""
    use_leak(name)
    secret = chain_post.load_secret()
    length = secret["length"]
    published = chain_post.load_state().get("published", 0)
    nxt = published + 1
    if published >= length:
        status = "exhausted"
    elif os.path.exists(draft_path(name, nxt)):
        status = "drafting"
    else:
        status = "idle"
    return name, published, length, nxt, status


_TABLE = {"name": 16, "pub": 10, "len": 10, "next": 6, "status": 10}


def _table_header():
    w = _TABLE
    return (f"{'NAME'.ljust(w['name'])}  {'PUBLISHED'.rjust(w['pub'])}  "
            f"{'LENGTH'.rjust(w['len'])}  {'NEXT'.rjust(w['next'])}  {'STATUS'.ljust(w['status'])}")


def _table_row(name, published, length, nxt, status):
    w = _TABLE
    return (f"{name.ljust(w['name'])}  {str(published).rjust(w['pub'])}  "
            f"{str(length).rjust(w['len'])}  {str(nxt).rjust(w['next'])}  {status.ljust(w['status'])}")


def cmd_list(args):
    """list 子命令：列出所有 leak 及状态。"""
    leaks = discover_leaks()
    if not leaks:
        print("no leaks yet. run: anon_leak create <name>")
        return
    print(_table_header())
    for name in leaks:
        n, published, length, nxt, status = leak_status(name)
        print(_table_row(n, published, length, nxt, status))


def cmd_status(args):
    """status 子命令：查看单个 leak 详情。"""
    name = resolve_leak(args.name)
    _, published, length, nxt, status = leak_status(name)
    print(_table_header())
    print(_table_row(name, published, length, nxt, status))
    if _VERBOSE:
        draft_dir = os.path.join(leak_dir(name), "drafts")
        shown = chain_post.status_indices(length, published, draft_dir)
        for i in shown:
            if i <= published:
                print(f"post {i:02d}: ok  generated (posts/{i:02d}.txt)")
            elif os.path.exists(draft_path(name, i)):
                print(f"post {i:02d}: -   draft (drafts/{i:02d}.txt)")
            else:
                print(f"post {i:02d}: -   no draft")
    if published >= length:
        warn(f"chain {name} exhausted; open a new chain with anon_leak create")
    if args.check:
        okv, _ = verify_paths(collect_post_files(name))
        print("verify: " + ("pass" if okv else "FAIL"))
    next_block([
        f"anon_leak start {name}          # write posts",
        f"anon_leak verify {name}         # verify locally",
    ])


# ---------------------------------------------------------------------------
# add / start
# ---------------------------------------------------------------------------
def cmd_add(args):
    """add 子命令：非交互式添加并发布一帖。"""
    name = resolve_leak(args.name)
    use_leak(name)
    published = chain_post.load_state().get("published", 0)
    index = args.index if args.index is not None else published + 1
    secret, _ = validate_index(name, index)
    length = secret["length"]

    if args.file is not None:
        content = read_file_content(args.file)
    elif args.message is not None:
        content = args.message
    elif not sys.stdin.isatty():
        content = sys.stdin.read().rstrip("\n")
    else:
        content = read_content_interactive(index)

    if not content:
        warn("empty content, not published")
        return

    if args.dry_run:
        preview_post(name, index, content)
        return

    write_draft(name, index, content)
    publish_with_rollback(name, index)
    print(f"published {rel(post_path(name, index))}  ({index}/{length})")
    next_block([
        f'anon_leak add {name} -m "..."   # write next post',
        f"anon_leak verify {name}         # verify locally",
    ])


def cmd_start(args):
    """start 子命令：引导式写帖并发布。"""
    name = args.name
    if name is None:
        leaks = discover_leaks()
        if not leaks:
            print("no leak yet; create one.")
            name = input("new leak name: ").strip()
            do_create(name)
        else:
            name = resolve_leak(None)

    while True:
        use_leak(name)
        secret = chain_post.load_secret()
        length = secret["length"]
        published = chain_post.load_state().get("published", 0)
        nxt = published + 1
        if nxt > length:
            warn(f"chain {name} exhausted ({length} posts).")
            print("suggest: anon_leak create <name>")
            break

        print(f"post {nxt}/{length}")
        content = read_content_interactive(nxt)
        if not content.strip():
            if confirm("content empty, finish?", default=True):
                break
            continue

        write_draft(name, nxt, content)
        publish_with_rollback(name, nxt)
        okv, _ = verify_paths(collect_post_files(name))
        print(f"published {rel(post_path(name, nxt))}")
        print("verify: " + ("pass" if okv else "FAIL"))

        if not confirm("write next post?", default=True):
            break

    next_block([
        f'anon_leak add {name} -m "..."   # write next post',
        f"anon_leak status {name}         # view progress",
    ])
    print("done.")


# ---------------------------------------------------------------------------
# verify / show / export
# ---------------------------------------------------------------------------
def cmd_verify(args):
    """verify 子命令：验证一个 leak 的帖子，或直接验证目录/文件。"""
    verify_name = None
    if args.dir:
        paths = chain_verify.collect_dir(args.dir)
    elif args.targets:
        if len(args.targets) == 1 and is_leak_name(args.targets[0]):
            verify_name = args.targets[0]
            paths = collect_post_files(args.targets[0])
        else:
            paths = args.targets
    else:
        verify_name = resolve_leak(None)
        paths = collect_post_files(verify_name)

    okv, results = verify_paths(paths)
    if _VERBOSE:
        chain_verify.print_verbose(results)
        print()
        chain_verify.print_summary(okv, results)
    elif _QUIET:
        print("verify: " + ("pass" if okv else "FAIL"))
    else:
        chain_verify.print_results(results, okv)
    if okv and verify_name:
        next_block([
            f"anon_leak show {verify_name} 1      # view a post",
            f"anon_leak export {verify_name}      # export for readers",
        ])
    sys.exit(0 if okv else 1)


def resolve_show(args):
    """解析 show 的「名字 + 帖号」两种写法，返回 (name, index)。"""
    if args.index is not None:
        name = resolve_leak(args.name)
        try:
            index = int(args.index)
        except ValueError:
            err(f"index must be an integer, got: {args.index!r}")
        return name, index
    if args.name is None:
        err("usage: anon_leak show [<name>] <index>")
    try:
        index = int(args.name)
    except ValueError:
        err(f"index must be an integer, got: {args.name!r}")
    return resolve_leak(None), index


def cmd_show(args):
    """show 子命令：打印某帖全文。"""
    name, index = resolve_show(args)
    path = post_path(name, index)
    if not os.path.exists(path):
        err(f"post not found: {rel(path)}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if args.payload_only:
        _, payload_text = chain_verify.split_post(text)
        if payload_text is None:
            err("post missing ANON CHAIN markers")
        print(payload_text)
        return
    print(f"post {index}  {rel(path)}")
    print("─" * 40)
    print(text, end="")
    next_block([
        f"anon_leak show {name} {index + 1}     # view next post",
    ])


def cmd_export(args):
    """export 子命令：把公开帖子复制到导出目录（绝不复制 secret/）。"""
    name = resolve_leak(args.name)
    posts = collect_post_files(name)
    if not posts:
        err(f"leak {name} has no published posts")

    export_dir = args.out if args.out else os.path.join(leak_dir(name), EXPORT_DIR)
    os.makedirs(export_dir, exist_ok=True)

    for p in posts:
        shutil.copy2(p, os.path.join(export_dir, os.path.basename(p)))

    if args.single:
        out = os.path.join(export_dir, args.single)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            for i, p in enumerate(posts):
                if i:
                    f.write("\n\n========== next ==========\n\n")
                with open(p, "r", encoding="utf-8") as src:
                    f.write(src.read())

    readme = os.path.join(export_dir, "README.txt")
    with open(readme, "w", encoding="utf-8", newline="\n") as f:
        f.write("reader verification\n===================\n\n")
        f.write("posts in this directory come from a single anonymous hash chain.\n")
        f.write("verify with chain_verify.py:\n\n")
        f.write("    python chain_verify.py --dir .\n")
        f.write("    # or\n")
        f.write("    python chain_verify.py 01.txt 02.txt ...\n\n")
        f.write("on success it prints: verify: pass (n posts, same origin, order ok, no tamper)\n")

    print(f"exported {len(posts)} posts to {rel(export_dir)}/")
    for p in posts:
        print(f"  {rel(os.path.join(export_dir, os.path.basename(p)))}")
    if args.single:
        print(f"  {rel(os.path.join(export_dir, args.single))}")
    print(f"  {rel(os.path.join(export_dir, 'README.txt'))}")
    next_block([
        f"# send {rel(export_dir)}/ to readers",
        f"# readers run: chain_verify.py --dir {rel(export_dir)}/",
    ])


# ---------------------------------------------------------------------------
# doctor / guide / overview
# ---------------------------------------------------------------------------
def cmd_doctor(args):
    """doctor 子命令：自检一致性、可验证性、.gitignore、链是否用尽。"""
    name = resolve_leak(args.name)
    use_leak(name)
    secret = chain_post.load_secret()
    length = secret["length"]
    published = chain_post.load_state().get("published", 0)
    issues = 0
    items = []  # (label, value, kind) kind in {ok, warn, note}

    post_files = collect_post_files(name)
    if len(post_files) != published:
        items.append(("posts/", f"{len(post_files)} files", "ok"))
        items.append(("state", f"records {published}, posts/ has {len(post_files)}", "warn"))
        issues += 1
    else:
        items.append(("posts/", f"{len(post_files)} files", "ok"))
        items.append(("state", f"{published} published", "ok"))

    expected = [post_path(name, i) for i in range(1, published + 1)]
    if post_files != expected:
        items.append(("posts/", "numbering not continuous or missing", "warn"))
        issues += 1

    if published:
        okv, _ = verify_paths(post_files)
        if okv:
            items.append(("verify", "all posts pass", "ok"))
        else:
            items.append(("verify", "some posts fail", "warn"))
            issues += 1

    if gitignore_covers_secret(name):
        items.append(("secret/", "ignored by .gitignore", "ok"))
    else:
        items.append(("secret/", "not in .gitignore", "warn"))
        issues += 1

    drafts_dir = os.path.join(leak_dir(name), "drafts")
    stale = 0
    if os.path.isdir(drafts_dir):
        for fn in sorted(os.listdir(drafts_dir)):
            if fn.endswith(".txt") and fn[:-4].isdigit():
                i = int(fn[:-4])
                if i > length:
                    items.append(("drafts/", f"{fn} beyond length {length}", "warn"))
                    issues += 1
                elif i <= published:
                    stale += 1
    if stale:
        items.append(("drafts/", f"{stale} stale (already published)", "note"))

    if published >= length:
        items.append(("chain", "exhausted, open a new chain", "warn"))
        issues += 1

    print(f"{name}: {'ok' if issues == 0 else color(str(issues) + ' issues', RED)}")
    mark_color = {"ok": GREEN, "warn": RED, "note": DIM}
    for label, value, kind in items:
        print(f"  {label.ljust(10)}  {color(value, mark_color[kind])}")
    if issues == 0:
        next_block([
            f"anon_leak start {name}          # write posts",
        ])
    sys.exit(0 if issues == 0 else 1)


def cmd_guide(args):
    """guide 子命令：匿名发布检查清单。"""
    print_banner(2)
    print("anonymous publishing checklist")
    print("  1. use a trusted anonymous channel")
    print("  2. paste plain text only, no file metadata")
    print("  3. never publish secret/")
    print("  4. back up secret/ offline")
    print("  5. open a new chain when exhausted")
    print("  6. run `anon_leak verify <name>` before publishing")
    print("  7. never reuse a seed")
    next_block([
        "anon_leak create <name>     # new chain",
        "anon_leak start <name>      # write posts",
    ])


def cmd_overview(args):
    """无子命令时的总览。"""
    print_banner(1)
    leaks = discover_leaks()
    if not leaks:
        print("no leaks yet.")
        print("  anon_leak create <name>    create a chain")
        print("  anon_leak start <name>     write first post")
        print("  anon_leak guide            publishing checklist")
        return
    print(_table_header())
    for name in leaks:
        n, published, length, nxt, status = leak_status(name)
        print(_table_row(n, published, length, nxt, status))
    next_block([
        "anon_leak create <name>    # new chain",
        "anon_leak start <name>     # write posts",
    ])


# ---------------------------------------------------------------------------
# 参数解析与入口
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    """解析命令行参数，返回 argparse.Namespace。"""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS, help="print only the result line")
    common.add_argument("--no-banner", action="store_true", default=argparse.SUPPRESS, help="suppress the banner")
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS, help="print per-post detail")

    parser = argparse.ArgumentParser(
        prog="anon_leak",
        description="anon-leak: create a hash chain, write posts, publish, verify.",
        parents=[common],
    )
    parser.add_argument("--root", metavar="DIR", default=None,
                        help="workspace root directory (default: current directory)")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", aliases=["new"], help="create a leak chain", parents=[common])
    p_create.add_argument("name", help="leak name (folder name)")
    p_create.add_argument("-n", "--length", type=int, default=1000000, help="chain length (default 1000000)")
    p_create.add_argument("-s", "--seed", default=None, help="seed (prompt if omitted)")
    p_create.add_argument("--random-seed", action="store_true", help="use a random seed (shown once)")

    sub.add_parser("list", aliases=["ls"], help="list leaks and status", parents=[common])

    p_status = sub.add_parser("status", aliases=["st"], help="show a leak's status", parents=[common])
    p_status.add_argument("name", nargs="?", default=None, help="leak name (auto-pick if omitted)")
    p_status.add_argument("--check", action="store_true", help="also verify locally")

    p_start = sub.add_parser("start", aliases=["go"], help="guided write and publish", parents=[common])
    p_start.add_argument("name", nargs="?", default=None, help="leak name (guided create if omitted)")

    p_add = sub.add_parser("add", aliases=["publish"], help="add and publish one post", parents=[common])
    p_add.add_argument("name", nargs="?", default=None, help="leak name")
    p_add.add_argument("-f", "--file", default=None, help="read content from file")
    p_add.add_argument("-m", "--message", default=None, help="content as argument")
    p_add.add_argument("-i", "--index", type=int, default=None, help="post index (default: next)")
    p_add.add_argument("--dry-run", action="store_true", help="preview only, do not write")

    p_verify = sub.add_parser("verify", aliases=["check"], help="verify posts", parents=[common])
    p_verify.add_argument("targets", nargs="*", help="leak name or post files")
    p_verify.add_argument("--dir", metavar="DIR", default=None, help="verify a directory")

    p_show = sub.add_parser("show", aliases=["cat"], help="print a post's full text", parents=[common])
    p_show.add_argument("name", nargs="?", default=None, help="leak name (optional)")
    p_show.add_argument("index", nargs="?", default=None, help="post index")
    p_show.add_argument("--payload-only", action="store_true", help="print only the ANON CHAIN block")

    p_export = sub.add_parser("export", help="export public posts", parents=[common])
    p_export.add_argument("name", nargs="?", default=None, help="leak name")
    p_export.add_argument("--out", metavar="DIR", default=None, help="export dir (default <leak>/export)")
    p_export.add_argument("--single", metavar="FILE", default=None, help="also merge into one reading file")

    p_doctor = sub.add_parser("doctor", help="self-check and suggestions", parents=[common])
    p_doctor.add_argument("name", nargs="?", default=None, help="leak name")

    sub.add_parser("guide", help="anonymous publishing checklist", parents=[common])

    return parser.parse_args(argv)


def main(argv=None):
    """程序入口：按子命令分发。"""
    args = parse_args(argv)
    global _QUIET, _NO_BANNER, _VERBOSE
    _QUIET = getattr(args, "quiet", False)
    _NO_BANNER = getattr(args, "no_banner", False)
    _VERBOSE = getattr(args, "verbose", False)
    if args.root is not None:
        set_root(args.root)

    if args.version:
        print_banner(3)
        sys.exit(0)

    if args.command == "create":
        cmd_create(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "guide":
        cmd_guide(args)
    else:
        cmd_overview(args)


if __name__ == "__main__":
    main()
