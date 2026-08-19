#!/bin/bash
# Ghidra headless で対象バイナリ(.dll/.exe)を解析し、
#   <out>/<name>_decomp.c     … 全関数の C デコンパイル
#   <out>/<name>_vtables.txt   … RTTI vftable → 仮想関数アドレス地図
# を生成する。プロジェクトは保持し、2回目以降のスクリプト実行は再解析なしで高速。
#
# usage: ghidra_analyze.sh <binary> [<out_dir>]
# env  : GHIDRA_HOME / JAVA_HOME を上書き可 (未設定なら scoop の既定を探す)
set -e

BIN="$1"; OUT="${2:-.}"
[ -z "$BIN" ] && { echo "usage: ghidra_analyze.sh <binary> [<out_dir>]"; exit 1; }
BINABS="$(cd "$(dirname "$BIN")" && pwd)/$(basename "$BIN")"
NAME="$(basename "$BIN" | tr -c 'A-Za-z0-9' _)"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"

# ---- Ghidra / JDK の場所を解決 ----
GH="${GHIDRA_HOME:-}"
[ -z "$GH" ] && GH="$(ls -d /c/Users/*/scoop/apps/ghidra/current 2>/dev/null | head -1)"
[ -z "$JAVA_HOME" ] && export JAVA_HOME="$(ls -d /c/Users/*/scoop/apps/temurin21-jdk/current /c/Users/*/scoop/apps/*jdk*/current 2>/dev/null | head -1)"
[ -z "$GH" ] && { echo "GHIDRA_HOME が見つかりません。環境変数で指定してください。"; exit 1; }
export PATH="$JAVA_HOME/bin:$PATH"

mkdir -p "$OUT"
PROJ="$OUT/ghproj"; mkdir -p "$PROJ"
HL="$GH/support/analyzeHeadless"

echo "== import + analyze + decompile =="
"$HL" "$PROJ" "$NAME" -import "$BINABS" \
    -scriptPath "$SCRIPTS" -postScript DecompileExport.java "$OUT/${NAME}_decomp.c" \
    2>&1 | grep -iE "DECOMPILED_FUNCTIONS|RTTI|ERROR|Exception" || true

echo "== dump vtables =="
"$HL" "$PROJ" "$NAME" -process "$(basename "$BINABS")" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript DumpVtables.java "$OUT/${NAME}_vtables.txt" \
    2>&1 | grep -iE "VTABLE_DUMP_DONE|ERROR|Exception" || true

echo "----"
echo "decomp : $OUT/${NAME}_decomp.c   ($(grep -c '^// ======' "$OUT/${NAME}_decomp.c" 2>/dev/null) funcs)"
echo "vtables: $OUT/${NAME}_vtables.txt ($(grep -c '^VTABLE' "$OUT/${NAME}_vtables.txt" 2>/dev/null) classes)"
