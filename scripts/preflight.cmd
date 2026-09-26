@echo off
rem anon-leak 发布前检查脚本（Windows cmd）
rem 用法: scripts\preflight.cmd

setlocal
cd /d "%~dp0.."

set FAIL=0

rem 6/7/8. 必要文件存在
for %%f in (LICENSE CHANGELOG.md README.md pyproject.toml) do (
  if not exist "%%f" (
    echo FAIL: missing %%f
    set FAIL=1
  )
)

rem 2. secret/ 被 git 忽略
git check-ignore secret/ >nul 2>&1
if errorlevel 1 (
  echo FAIL: secret/ is not ignored by git
  set FAIL=1
)

rem 核心检查（emoji / 绝对路径 / 依赖）交给 Python
python -c "import re,ast,sys;files=['anon_leak.py','chain_post.py','chain_verify.py'];bad=[];emoji=re.compile(r'[\u2600-\u27BF\u2705\u274C\u26A0\U0001F300-\U0001FAFF]');absre=re.compile(r'/home/|C:[\\]');internal={'chain_post','chain_verify'};std=set(getattr(sys,'stdlib_module_names',set()));[bad.append('emoji '+f) for f in files if emoji.search(open(f,encoding='utf-8').read())];[bad.append('abs path '+f) for f in files if absre.search(open(f,encoding='utf-8').read())];[bad.append('import '+m+' in '+f) for f in files for n in ast.walk(ast.parse(open(f,encoding='utf-8').read())) for m in ([a.name.split('.')[0] for a in n.names] if isinstance(n,ast.Import) else [n.module.split('.')[0]] if isinstance(n,ast.ImportFrom) and n.module else []) if m not in internal and m not in std];print('FAIL: '+' ; '.join(bad) if bad else '');sys.exit(1 if bad else 0)"
if errorlevel 1 set FAIL=1

if "%FAIL%"=="0" (
  echo preflight: ok
) else (
  echo preflight: FAILED
  exit /b 1
)
