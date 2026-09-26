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
VERSION = 1

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
# 输出辅助（与既有脚本风格一致）
# ---------------------------------------------------------------------------
def info(msg):
    print("✅ " + msg)


def warn(msg):
    print("⚠️ " + msg)


def note(msg):
    print("📝 " + msg)


def skip(msg):
    print("⏭️ " + msg)


def err(msg):
    print("❌ " + msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 名称校验与 leak 发现
# ---------------------------------------------------------------------------
def validate_leak_name(name):
    """校验 leak 名字，返回错误描述字符串；合法则返回 None。"""
    if not name:
        return "名字不能为空"
    if name in (".", ".."):
        return "名字不能为 . 或 .."
    if len(name) > 64:
        return "名字长度不能超过 64 个字符"
    if any(ch in name for ch in "/\\"):
        return "名字不能包含路径分隔符"
    for ch in name:
        if not (ch.isalnum() or ch in "_-."):
            return f"名字包含非法字符：{ch!r}"
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
        err("当前目录下没有任何 leak，请先运行：anon_leak create <名字>")
    err("有多个 leak，请显式指定名字。候选：" + ", ".join(leaks))


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
        seed = getpass.getpass("请输入种子（seed，输入不回显）：").strip()
    except (EOFError, KeyboardInterrupt):
        err("未收到种子输入")
    if not seed:
        err("种子不能为空")
    try:
        confirm = getpass.getpass("请再次输入种子以确认：").strip()
    except (EOFError, KeyboardInterrupt):
        err("未收到确认输入")
    if seed != confirm:
        err("两次输入的种子不一致，已取消")
    return seed


def prompt_length():
    """交互式输入链长度（正整数），空输入默认 10。"""
    try:
        raw = input("请输入链长度（length，正整数，默认 10）：").strip()
    except (EOFError, KeyboardInterrupt):
        err("未收到链长度输入")
    if raw == "":
        return 10
    try:
        n = int(raw)
    except ValueError:
        err(f"链长度必须是整数，收到：{raw!r}")
    return n


def read_content_interactive(index):
    """交互式读取正文：多行粘贴，最后单独一行 EOF 结束。"""
    print(f"📝 请输入第 {index} 帖正文（多行粘贴，最后单独一行输入 EOF 结束）：")
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
        err(f"文件不存在：{path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().rstrip("\n")


def confirm(question, default=False):
    """交互确认；非 TTY（EOF）时返回 default。"""
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        ans = input(question + suffix + "：").strip().lower()
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
        err(f"非法 leak 名字 {name!r}：{err_msg}")
    if os.path.exists(leak_dir(name)):
        err(f"leak 已存在：{leak_dir(name)}（请换个名字，或先手动删除）")

    if random_seed:
        seed = os.urandom(32).hex()
        print("✅ 已用随机种子生成（请立即离线抄录保存，此后不再显示）：")
        print("   " + seed)
    elif seed is None:
        seed = prompt_seed()
    else:
        warn("你通过命令行显式传入了种子，注意 shell history 可能泄露它。")

    if length is None:
        length = prompt_length()
    if length < 1:
        err("链长度必须为正整数")

    chain_post.configure(leak_dir(name))
    chain_post.ensure_dirs()
    chain = chain_post.build_chain(seed, length)
    chain_post.save_secret(seed, length, chain)
    chain_post.save_state(0)

    save_meta(name, {
        "name": name,
        "scheme": chain_post.SCHEME,
        "hash": chain_post.HASH_NAME,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "version": VERSION,
        "length": length,
    })
    write_gitignore(name)

    print("")
    info(f"已创建 leak：{name}")
    info(f"链长度：{length}")
    info(f"根值（第 1 帖公开的 value）：{chain[0]}")
    note("请务必离线备份 secret/ 目录，丢失种子将无法继续发布后续帖子。")
    note(f"下一步：anon_leak start {name} 开始写第一篇爆料。")
    return name


def cmd_create(args):
    """create 子命令。"""
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
    """验证一组帖子文件，打印逐帖结果，返回是否全部通过。

    文件缺失/解析错误等由 chain_verify 打印 ❌ 并以 SystemExit(2) 退出，
    此处捕获并视为验证失败（返回 False）。
    """
    if not paths:
        print("❌ 没有可验证的帖子")
        return False
    try:
        posts = []
        for p in paths:
            content, payload = chain_verify.load_post_file(p)
            posts.append((os.path.basename(p), content, payload))
        return chain_verify.verify_chain(posts)
    except SystemExit:
        return False


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
        err(f"帖号越界：链长度为 {length}，无法生成第 {index} 帖")
    if index <= published:
        err(f"第 {index} 帖已生成过（posts/{index:02d}.txt 已存在），请勿重复生成")
    if index != published + 1:
        err(f"跳号：当前下一帖应为第 {published + 1} 帖，不能直接生成第 {index} 帖")
    return secret, published


def preview_post(name, index, content):
    """打印第 index 帖的完整渲染预览（不写入任何文件）。"""
    use_leak(name)
    secret = chain_post.load_secret()
    chain = secret["chain"]
    prev = "" if index == 1 else chain[index - 2]
    value = chain[index - 1]
    payload = chain_post.make_payload(index, prev, value, content)
    print("----- 预览（不会写入任何文件）-----")
    print(chain_post.render_post(content, payload), end="")
    print("----- 预览结束 -----")


def publish_with_rollback(name, index):
    """发布第 index 帖，随后对整条链自检；失败则回滚并报错。"""
    use_leak(name)
    chain_post.publish(index)  # 校验失败会自行报错退出
    if not verify_paths(collect_post_files(name)):
        warn(f"发布自检失败，回滚第 {index} 帖")
        os.remove(post_path(name, index))
        chain_post.save_state(index - 1)
        err(f"第 {index} 帖发布自检失败，已回滚，请检查草稿内容")


# ---------------------------------------------------------------------------
# list / status
# ---------------------------------------------------------------------------
def cmd_list(args):
    """list 子命令：列出所有 leak 及状态。"""
    leaks = discover_leaks()
    if not leaks:
        print("📝 当前目录下没有任何 leak。运行 anon_leak create <名字> 创建第一个。")
        return
    print(f"{'名称':<20} {'已发布':>6} {'链长度':>6} {'下一帖':>6}  状态")
    print("-" * 62)
    for name in leaks:
        use_leak(name)
        secret = chain_post.load_secret()
        length = secret["length"]
        published = chain_post.load_state().get("published", 0)
        nxt = published + 1
        if published >= length:
            status = "已用尽"
        elif os.path.exists(draft_path(name, nxt)):
            status = "有草稿待发布"
        else:
            status = "待写草稿"
        print(f"{name:<20} {published:>6} {length:>6} {nxt:>6}  {status}")


def cmd_status(args):
    """status 子命令：查看单个 leak 详情。"""
    name = resolve_leak(args.name)
    use_leak(name)
    secret = chain_post.load_secret()
    length = secret["length"]
    published = chain_post.load_state().get("published", 0)
    print(f"leak：{name}")
    print(f"链长度：{length}")
    print(f"已生成：{published}")
    print(f"下一帖：{published + 1}")
    print("--- 帖子状态 ---")
    for i in range(1, length + 1):
        if i <= published:
            print(f"第 {i} 帖：✅ 已生成（posts/{i:02d}.txt）")
        elif os.path.exists(draft_path(name, i)):
            print(f"第 {i} 帖：📝 有草稿（drafts/{i:02d}.txt）")
        else:
            print(f"第 {i} 帖：⬜ 无草稿")
    if published >= length:
        warn("该链已用尽，请用 anon_leak create 开新链（可做跨链声明）。")
    if args.check:
        print("--- 本地自检 ---")
        if verify_paths(collect_post_files(name)):
            info("本地验证通过")
        else:
            warn("本地验证未通过")


# ---------------------------------------------------------------------------
# add / start
# ---------------------------------------------------------------------------
def cmd_add(args):
    """add 子命令：非交互式添加并发布一帖。"""
    name = resolve_leak(args.name)
    use_leak(name)
    published = chain_post.load_state().get("published", 0)
    index = args.index if args.index is not None else published + 1
    validate_index(name, index)

    if args.file is not None:
        content = read_file_content(args.file)
    elif args.message is not None:
        content = args.message
    elif not sys.stdin.isatty():
        content = sys.stdin.read().rstrip("\n")
    else:
        content = read_content_interactive(index)

    if not content:
        warn("正文为空，未发布")
        return

    if args.dry_run:
        preview_post(name, index, content)
        return

    write_draft(name, index, content)
    publish_with_rollback(name, index)
    info(f"第 {index} 帖已发布：{post_path(name, index)}")
    print("📢 请把该文件全文通过匿名渠道公开（可用 anon_leak show 取出）。")


def cmd_start(args):
    """start 子命令：引导式写帖并发布。"""
    name = args.name
    if name is None:
        leaks = discover_leaks()
        if not leaks:
            print("当前目录下还没有 leak，先创建一个。")
            name = input("请输入新 leak 名字：").strip()
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
            skip(f"链 {name} 已用尽（共 {length} 帖）。")
            print("建议：anon_leak create <新名字> 开新链。")
            break

        print(f"\n=== 准备写第 {nxt} 帖（链长度 {length}，已发布 {published}）===")
        content = read_content_interactive(nxt)
        if not content.strip():
            if confirm("正文为空，是否结束爆料流程？", default=True):
                break
            continue

        preview_post(name, nxt, content)
        if not confirm("发布这一帖？", default=False):
            skip("已跳过，未发布。")
            if not confirm("继续写下一帖？", default=True):
                break
            continue

        write_draft(name, nxt, content)
        publish_with_rollback(name, nxt)
        print("📢 请把该文件全文通过匿名渠道公开：")
        print(f"   {post_path(name, nxt)}")
        print(f"   （anon_leak show {name} {nxt} 可打印全文）")

        if not confirm("继续写下一帖？", default=True):
            break

    info(f"爆料流程结束。用 anon_leak status {name} 查看进度。")


# ---------------------------------------------------------------------------
# verify / show / export
# ---------------------------------------------------------------------------
def cmd_verify(args):
    """verify 子命令：验证一个 leak 的帖子，或直接验证目录/文件。"""
    if args.dir:
        paths = chain_verify.collect_dir(args.dir)
    elif args.targets:
        if len(args.targets) == 1 and is_leak_name(args.targets[0]):
            paths = collect_post_files(args.targets[0])
        else:
            paths = args.targets
    else:
        name = resolve_leak(None)
        paths = collect_post_files(name)

    if verify_paths(paths):
        print("🎉 验证通过：所有帖子同源，顺序正确，正文未被篡改")
        sys.exit(0)
    print("⚠️ 验证失败，以上错误导致链条不可信")
    sys.exit(1)


def resolve_show(args):
    """解析 show 的「名字 + 帖号」两种写法，返回 (name, index)。"""
    if args.index is not None:
        name = resolve_leak(args.name)
        try:
            index = int(args.index)
        except ValueError:
            err(f"帖号必须是整数，收到：{args.index!r}")
        return name, index
    if args.name is None:
        err("用法：anon_leak show [<名字>] <帖号>")
    try:
        index = int(args.name)
    except ValueError:
        err(f"帖号必须是整数，收到：{args.name!r}")
    return resolve_leak(None), index


def cmd_show(args):
    """show 子命令：打印某帖全文。"""
    name, index = resolve_show(args)
    path = post_path(name, index)
    if not os.path.exists(path):
        err(f"未找到帖子：{path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if args.payload_only:
        _, payload_text = chain_verify.split_post(text)
        if payload_text is None:
            err("帖子缺少 ANON CHAIN 标记")
        print(payload_text)
    else:
        print(text, end="")


def cmd_export(args):
    """export 子命令：把公开帖子复制到导出目录（绝不复制 secret/）。"""
    name = resolve_leak(args.name)
    posts = collect_post_files(name)
    if not posts:
        err(f"leak {name} 还没有已发布的帖子")

    export_dir = args.out if args.out else os.path.join(leak_dir(name), EXPORT_DIR)
    os.makedirs(export_dir, exist_ok=True)

    for p in posts:
        shutil.copy2(p, os.path.join(export_dir, os.path.basename(p)))
    info(f"已导出 {len(posts)} 篇帖子到：{export_dir}")

    if args.single:
        out = os.path.join(export_dir, args.single)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            for i, p in enumerate(posts):
                if i:
                    f.write("\n\n========== 下一篇 ==========\n\n")
                with open(p, "r", encoding="utf-8") as src:
                    f.write(src.read())
        info(f"已生成阅读合集：{out}（仅阅读，验证请用分帖文件）")

    readme = os.path.join(export_dir, "README.txt")
    with open(readme, "w", encoding="utf-8", newline="\n") as f:
        f.write("读者验证说明\n============\n\n")
        f.write("本目录内的帖子来自同一条匿名哈希链。\n")
        f.write("请用本项目的 chain_verify.py 验证：\n\n")
        f.write("    python chain_verify.py --dir .\n")
        f.write("    或\n")
        f.write("    python chain_verify.py 01.txt 02.txt ...\n\n")
        f.write("验证通过会输出：🎉 验证通过：所有帖子同源，顺序正确，正文未被篡改\n")
    info(f"已生成读者验证说明：{readme}")


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

    print(f"leak：{name}")

    post_files = collect_post_files(name)
    if len(post_files) != published:
        warn(f"state 记录已发布 {published} 帖，但 posts/ 下有 {len(post_files)} 个文件")
        issues += 1
    else:
        info(f"posts/ 文件数（{published}）与 state 一致")

    expected = [post_path(name, i) for i in range(1, published + 1)]
    if post_files != expected:
        warn("posts/ 文件编号不连续或缺失")
        issues += 1

    if published:
        if verify_paths(post_files):
            info("已发布帖子全部通过验证")
        else:
            warn("存在无法通过验证的帖子")
            issues += 1

    drafts_dir = os.path.join(leak_dir(name), "drafts")
    if os.path.isdir(drafts_dir):
        for fn in sorted(os.listdir(drafts_dir)):
            if fn.endswith(".txt") and fn[:-4].isdigit():
                i = int(fn[:-4])
                if i > length:
                    warn(f"草稿 drafts/{fn} 超出链长度 {length}")
                    issues += 1
                elif i <= published:
                    note(f"草稿 drafts/{fn} 对应的帖子已生成，可删除")

    if gitignore_covers_secret(name):
        info(".gitignore 已忽略 secret/")
    else:
        warn("未在 .gitignore 中忽略 secret/，存在误提交风险")
        issues += 1

    if published >= length:
        warn("链已用尽，请开新链")

    print("")
    if issues == 0:
        info("自检通过，未发现问题")
        sys.exit(0)
    warn(f"发现 {issues} 个问题")
    sys.exit(1)


def cmd_guide(args):
    """guide 子命令：匿名发布检查清单。"""
    print("匿名发布检查清单")
    print("================")
    print("1. 渠道：使用可信的匿名渠道（多跳中继/一次性投递），别发到能关联你身份的平台。")
    print("2. 元数据：以纯文本粘贴「正文 + ANON CHAIN 块」，避免文件携带作者、路径、时间等元信息。")
    print("3. secret/ 绝不可公开：它含种子与整条链，泄露即失去「不可伪造」保证。")
    print("4. 离线备份：把 secret/ 备份到离线介质；丢失种子将无法继续发布后续帖子。")
    print("5. 链长度有限：用尽后 anon_leak create 开新链；跨链声明把旧链末帖 value 写进新链第 1 帖正文。")
    print("6. 发布前自检：anon_leak verify <名字>，确保读者能验证通过。")
    print("7. 别复用种子、别在联网设备明文保存 seed。")


def cmd_overview(args):
    """无子命令时的总览。"""
    leaks = discover_leaks()
    if not leaks:
        print("📝 当前目录下还没有 leak。")
        print("   快速开始：")
        print("     anon_leak create <名字>   创建一条爆料链")
        print("     anon_leak start <名字>    开始写第一篇爆料")
        print("     anon_leak guide           查看匿名发布清单")
        return
    print(f"发现 {len(leaks)} 个 leak：")
    cmd_list(args)
    print("")
    print("常用命令：create / list / status / start / add / verify / show / export / doctor / guide")


# ---------------------------------------------------------------------------
# 参数解析与入口
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    """解析命令行参数，返回 argparse.Namespace。"""
    parser = argparse.ArgumentParser(
        prog="anon_leak",
        description="anon-leak 一体化爆料工具：创建哈希链、写帖、发布、验证。",
    )
    parser.add_argument("--root", metavar="DIR", default=None,
                        help="leak 工作区根目录（默认：当前目录）")
    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", aliases=["new"], help="创建一条爆料链")
    p_create.add_argument("name", help="leak 名字（作为文件夹名）")
    p_create.add_argument("-n", "--length", type=int, default=None, help="链长度")
    p_create.add_argument("-s", "--seed", default=None, help="种子（不给则隐藏回显交互输入）")
    p_create.add_argument("--random-seed", action="store_true", help="用随机种子（仅显示一次）")

    sub.add_parser("list", aliases=["ls"], help="列出所有 leak 及状态")

    p_status = sub.add_parser("status", aliases=["st"], help="查看单个 leak 详情")
    p_status.add_argument("name", nargs="?", default=None, help="leak 名（省略则自动选中唯一的）")
    p_status.add_argument("--check", action="store_true", help="附带本地验证")

    p_start = sub.add_parser("start", aliases=["go"], help="引导式写帖并发布")
    p_start.add_argument("name", nargs="?", default=None, help="leak 名（省略则自动选中；无 leak 则引导创建）")

    p_add = sub.add_parser("add", aliases=["publish"], help="非交互式添加并发布一帖")
    p_add.add_argument("name", nargs="?", default=None, help="leak 名")
    p_add.add_argument("-f", "--file", default=None, help="从文件读取正文")
    p_add.add_argument("-m", "--message", default=None, help="直接给定正文")
    p_add.add_argument("-i", "--index", type=int, default=None, help="帖号（默认：下一帖）")
    p_add.add_argument("--dry-run", action="store_true", help="只预览不写入")

    p_verify = sub.add_parser("verify", aliases=["check"], help="验证帖子")
    p_verify.add_argument("targets", nargs="*", help="leak 名或帖子文件路径（可多个）")
    p_verify.add_argument("--dir", metavar="DIR", default=None, help="验证某个目录")

    p_show = sub.add_parser("show", aliases=["cat"], help="打印某帖全文")
    p_show.add_argument("name", nargs="?", default=None, help="leak 名（可省略）")
    p_show.add_argument("index", nargs="?", default=None, help="帖号")
    p_show.add_argument("--payload-only", action="store_true", help="只打印 ANON CHAIN 块")

    p_export = sub.add_parser("export", help="导出可公开的帖子")
    p_export.add_argument("name", nargs="?", default=None, help="leak 名")
    p_export.add_argument("--out", metavar="DIR", default=None, help="导出目录（默认 <leak>/export）")
    p_export.add_argument("--single", metavar="FILE", default=None, help="额外合并为一个阅读合集文件")

    p_doctor = sub.add_parser("doctor", help="自检并给出修复建议")
    p_doctor.add_argument("name", nargs="?", default=None, help="leak 名")

    sub.add_parser("guide", help="匿名发布检查清单")

    return parser.parse_args(argv)


def main(argv=None):
    """程序入口：按子命令分发。"""
    args = parse_args(argv)
    if args.root is not None:
        set_root(args.root)

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
