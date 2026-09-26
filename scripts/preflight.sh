#!/bin/sh
# anon-leak 发布前检查脚本（POSIX sh）
# 用法: bash scripts/preflight.sh   （或 chmod +x scripts/preflight.sh 后 ./scripts/preflight.sh）

set -u
cd "$(dirname "$0")/.." || { echo "FAIL: cannot cd to project root"; exit 1; }

FAIL=0
fail() { echo "FAIL: $1"; FAIL=1; }
PY="${PYTHON:-python3}"

# 1. 三个 .py 文件无 emoji
if grep -P '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}\x{2705}\x{274C}\x{26A0}]' \
     anon_leak.py chain_post.py chain_verify.py >/dev/null 2>&1; then
  fail "emoji found in .py files"
fi

# 2. secret/ 被 git 忽略
if [ -z "$(git check-ignore secret/ 2>/dev/null)" ]; then
  fail "secret/ is not ignored by git"
fi

# 3. 无硬编码绝对路径（/home/ 或 C:\）
if grep -En '/home/|C:\\' anon_leak.py chain_post.py chain_verify.py >/dev/null 2>&1; then
  fail "hardcoded absolute path found"
fi

# 4. 无第三方依赖（只标准库 + 内部模块 chain_post / chain_verify）
"$PY" - <<'PY'
import ast, sys
INTERNAL = {"chain_post", "chain_verify"}
try:
    STDLIB = set(sys.stdlib_module_names)
except AttributeError:  # Python < 3.10
    STDLIB = {
        "argparse", "datetime", "getpass", "hashlib", "json", "os", "shutil", "sys",
        "re", "math", "time", "platform", "subprocess", "pathlib", "collections",
        "functools", "itertools", "typing", "abc", "enum", "io", "codecs", "struct",
        "textwrap", "contextlib", "dataclasses", "random", "string", "uuid", "base64",
        "binascii", "hmac", "secrets", "socket", "tempfile", "threading", "traceback",
    }
bad = []
for fn in ("anon_leak.py", "chain_post.py", "chain_verify.py"):
    tree = ast.parse(open(fn, encoding="utf-8").read())
    for node in ast.walk(tree):
        tops = []
        if isinstance(node, ast.Import):
            tops = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            tops = [node.module.split(".")[0]] if node.module else []
        for t in tops:
            if t not in INTERNAL and t not in STDLIB:
                bad.append((fn, t))
if bad:
    for fn, t in bad:
        print("FAIL: third-party import %r in %s" % (t, fn))
    sys.exit(1)
PY
[ $? -ne 0 ] && FAIL=1

# 5. 版本号一致（三个 .py 的 VERSION == pyproject.toml == CHANGELOG.md）
"$PY" - <<'PY'
import re, sys
def version_of(path, pattern):
    m = re.search(pattern, open(path, encoding="utf-8").read(), re.M)
    return m.group(1) if m else None
vals = {}
for fn in ("anon_leak.py", "chain_post.py", "chain_verify.py"):
    vals[fn] = version_of(fn, r'^VERSION\s*=\s*["\']([^"\']+)["\']')
vals["pyproject.toml"] = version_of("pyproject.toml", r'^version\s*=\s*["\']([^"\']+)["\']')
vals["CHANGELOG.md"] = version_of("CHANGELOG.md", r'^## \[([^\]]+)\]')
missing = [k for k, v in vals.items() if not v]
if missing or len(set(vals.values())) != 1:
    print("FAIL: version mismatch ->", vals)
    sys.exit(1)
PY
[ $? -ne 0 ] && FAIL=1

# 6/7/8. 必要文件存在
for f in LICENSE CHANGELOG.md README.md pyproject.toml; do
  [ -f "$f" ] || fail "missing $f"
done

if [ "$FAIL" -eq 0 ]; then
  echo "preflight: ok"
else
  echo "preflight: FAILED"
  exit 1
fi
