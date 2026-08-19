#!/bin/bash
# デコンパイル C (DecompileExport.java の出力) から 1関数の本体を取り出す。
# usage: extract_func.sh <FUN_addr|関数名> <decomp.c>
#   例: extract_func.sh FUN_10017cd0 out/extNagano_dll_decomp.c
awk -v f="$1" '
  $0 ~ "^// ======== "f"  @" {p=1}
  p {print}
  p && /^\/\/ ======== / && $0 !~ f {c++; if(c>1) exit}
' "$2"
