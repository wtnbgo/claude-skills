#!/bin/bash
# appctl.sh — 制御対象アプリの PID 明示管理ランチャ (skill: appctl)
# 原則: 起動した本人が PID を記録し、停止はその PID のみ + exe パス照合付き。
#       taskkill /IM 等のイメージ名一括 kill は絶対に使わない。
#
# usage:
#   appctl.sh start  <tag> <exe絶対パス> [引数...]
#   appctl.sh stop   <tag>
#   appctl.sh status <tag>
#   appctl.sh alive  <tag>      (exit 0 = 生存)
#   appctl.sh list   <pattern>  (読み取り専用列挙; 名前 or パス部分一致)
#
# 環境変数:
#   APPCTL_DIR  pidfile/ログ置き場 (既定 ~/.claude/tmp/appctl。セッション scratchpad 推奨)
#   APPCTL_CWD  作業ディレクトリ (既定 = exe のディレクトリ)
#   APPCTL_LOG  stdout ログパス (既定 = $APPCTL_DIR/<tag>.log)

set -u
DIR="${APPCTL_DIR:-$HOME/.claude/tmp/appctl}"
mkdir -p "$DIR"

towin() { cygpath -w "$1" 2>/dev/null | sed 's|\\|/|g' || printf '%s' "$1"; }

cmd="${1:-}"; shift || true
case "$cmd" in
start)
  tag="$1"; shift
  exe="$1"; shift
  exew="$(towin "$exe")"
  cwd="${APPCTL_CWD:-$(dirname "$exew")}"
  log="${APPCTL_LOG:-$DIR/$tag.log}"
  logw="$(towin "$log")"
  errw="${logw%.log}.err.log"
  # 引数を PowerShell の ArgumentList 用にシングルクォートで連結
  arglist=""
  for a in "$@"; do
    esc="${a//\'/\'\'}"
    arglist="$arglist,'$esc'"
  done
  arglist="${arglist#,}"
  if [ -n "$arglist" ]; then
    ps_args="-ArgumentList $arglist"
  else
    ps_args=""
  fi
  # [注意] $(powershell ...) のコマンド置換で PID を受けると、起動した子プロセスが
  # パイプハンドルを継承して EOF 待ちハングする。PID はファイル経由で受け取ること
  pidtmp="$DIR/$tag.pidtmp"
  rm -f "$pidtmp"
  powershell -NoProfile -Command \
    "\$p = Start-Process -FilePath '$exew' $ps_args -WorkingDirectory '$(towin "$cwd")' -RedirectStandardOutput '$logw' -RedirectStandardError '$errw' -PassThru; Set-Content -Path '$(towin "$pidtmp")' -Value \$p.Id" </dev/null >/dev/null 2>&1
  pid="$(tr -d '[:space:]' < "$pidtmp" 2>/dev/null)"
  rm -f "$pidtmp"
  if [ -z "$pid" ]; then echo "appctl: start failed (PID 取得不能)" >&2; exit 1; fi
  printf '%s\n%s\n' "$pid" "$exew" > "$DIR/$tag.pid"
  echo "appctl: started tag=$tag pid=$pid exe=$exew log=$logw"
  ;;
stop)
  tag="$1"
  f="$DIR/$tag.pid"
  if [ ! -f "$f" ]; then echo "appctl: no pidfile for tag=$tag"; exit 1; fi
  pid="$(sed -n 1p "$f")"; exew="$(sed -n 2p "$f")"
  # PID 再利用/他人のプロセス誤殺防止: 実行ファイルパスを照合してから kill
  ok=$(powershell -NoProfile -Command \
    "\$p = Get-Process -Id $pid -ErrorAction SilentlyContinue; if (\$p -and \$p.Path -ieq '$exew'.Replace('/','\\')) { 'OK' } elseif (\$p) { 'MISMATCH:' + \$p.Path } else { 'GONE' }")
  case "$ok" in
    OK*)      taskkill //F //PID "$pid" >/dev/null 2>&1 && echo "appctl: killed tag=$tag pid=$pid" ;;
    GONE*)    echo "appctl: tag=$tag pid=$pid は既に終了 (外部 kill/クラッシュの可能性。ログ末尾を確認)" ;;
    MISMATCH*) echo "appctl: tag=$tag pid=$pid は別プロセスに再利用されている ($ok) — kill しません" ;;
    *)        echo "appctl: 照合失敗 ($ok) — kill しません"; exit 1 ;;
  esac
  rm -f "$f"
  ;;
status|alive)
  tag="$1"
  f="$DIR/$tag.pid"
  if [ ! -f "$f" ]; then echo "appctl: no pidfile for tag=$tag"; exit 1; fi
  pid="$(sed -n 1p "$f")"; exew="$(sed -n 2p "$f")"
  r=$(powershell -NoProfile -Command \
    "\$p = Get-Process -Id $pid -ErrorAction SilentlyContinue; if (\$p -and \$p.Path -ieq '$exew'.Replace('/','\\')) { 'ALIVE' } else { 'DEAD' }")
  if [ "$cmd" = "status" ]; then echo "appctl: tag=$tag pid=$pid $r ($exew)"; fi
  [ "${r#ALIVE}" != "$r" ] || [ "$r" = "ALIVE" ]
  ;;
list)
  pat="${1:-}"
  powershell -NoProfile -Command \
    "Get-Process | Where-Object { \$_.Path -and (\$_.Path -like '*$pat*' -or \$_.ProcessName -like '*$pat*') } | ForEach-Object { \$_.Id.ToString() + ' ' + \$_.ProcessName + ' ' + \$_.Path }"
  ;;
*)
  echo "usage: appctl.sh start|stop|status|alive|list ..." >&2
  exit 2
  ;;
esac
