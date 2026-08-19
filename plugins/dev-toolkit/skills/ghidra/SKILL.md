---
name: ghidra
description: Ghidra を使った Windows バイナリ (DLL / EXE, x86 / x64) の逆解析・ソース復元。ソースが失われた／入手できないバイナリをデコンパイルし、RTTI から C++ クラス構造を、vtable から各メソッドの関数アドレスを復元し、C 相当のソースへ再構築する。吉里吉里プラグイン (V2Link 形式の TransHandler 等) の復元に最適だが、一般の PE バイナリ解析にも使える。文字列/エクスポート抽出、全関数デコンパイル、vtable→メソッド地図化、並列サブエージェントでの復元までの手順とヘルパスクリプトを同梱。同梱スクリプトは this skill の scripts/ にある。
---

# Ghidra バイナリ逆解析・ソース復元

ソースが失われた Windows バイナリ (PE: .dll / .exe) を Ghidra headless で解析し、
C 相当のソースへ復元するためのスキル。**まず「ツールの場所」を確認 → 「標準ワークフロー」
を上から実行** する。同梱ヘルパは `scripts/` にある (実行前に一度 Read して中身を把握してよい)。

> スクリプトの場所: プラグインとして導入した場合は `${CLAUDE_PLUGIN_ROOT}` が
> プラグインのルートを指す。この変数が使えない置き方をしている場合は、
> **この SKILL.md と同じ階層の `scripts/`** に読み替える。


## ツールの場所 (この環境)

- **objdump / strings / nm**: `/c/msys64/usr/bin/`。PATH 未追加なので毎回
  `export PATH=/c/msys64/usr/bin:$PATH`。
- **Ghidra**: `$HOME/scoop/apps/ghidra/current` (scoop, 12.x)。
- **JDK**: `$HOME/scoop/apps/temurin21-jdk/current` (Ghidra 12 は JDK 21)。
- headless 本体: `$GHIDRA_HOME/support/analyzeHeadless`。
- ⚠️ **Ghidra 12 の Python(.py)スクリプトは PyGhidra 必須**。headless の postScript は
  **必ず Java (.java) で書く** (同梱の DecompileExport.java / DumpVtables.java)。
- スクラッチ出力は作業用の一時ディレクトリ (例: セッションの scratchpad) に置く。デコンパイル C は
  数万行になるので、リポジトリには置かない。

## 標準ワークフロー

### 0. まず素性を掴む (Ghidra 不要・数秒)
```bash
export PATH=/c/msys64/usr/bin:$PATH
objdump -h TARGET.dll | grep -E '\.text|\.rdata|\.data'   # セクション/アーキ
dumpbin //EXPORTS TARGET.dll | grep -iE 'V2Link|<関心のexport>'  # エクスポート
strings -a TARGET.dll   | grep -iE 'TVP|Handler|Provider|<関心>'  # narrow: RTTI型名/関数名
strings -a -e l TARGET.dll | sort -u                              # wide: TJS文字列/オプション名
```
- **MSVC の RTTI 型名** `.?AV<class>@@` が narrow 文字列に残っていれば、クラス一覧がタダで手に入る。
- **wide 文字列** に GetName の戻り値やオプション名 (`L"time"` 等) が残る。

### 1. 全関数デコンパイル + vtable 地図 (Ghidra headless)
```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/ghidra/scripts/ghidra_analyze.sh"  /abs/path/TARGET.dll  <out_dir>
```
これで `<out>/TARGET_dll_decomp.c` (全関数の C) と `<out>/TARGET_dll_vtables.txt`
(RTTI vftable → 各仮想関数アドレス) が出る。プロジェクトは保持され、スクリプト再実行は高速。
- デコンパイル C は **文字列リテラルが `L"time"` 等そのまま可読**。
- vtable が空(スロット0行)なら fallback: `python "${CLAUDE_PLUGIN_ROOT}/skills/ghidra/scripts/read_vtables_from_dll.py"
  TARGET.dll <vtables.txt> --methods prov`  (DLL の生バイトから関数ポインタを直読み)。

### 2. クラス→メソッド→FUN_アドレスの地図を作る
`vtables.txt` で各クラスの vtable スロット並びが分かる。例 (吉里吉里 iTVP*):
- **TransHandlerProvider**: +0 AddRef, +4 Release, +8 GetName, +c StartTransition
- **DivisibleTransHandler**: +c StartProcess, +10 EndProcess, +14 Process, +18 MakeFinalImage
`ghidra_analyze.sh` の DumpVtables.java は既に関数名付きで並びを出す。これで
「どの FUN_ が Process/StartTransition か」が確定する。

### 3. 関数を読む
```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/ghidra/scripts/extract_func.sh" FUN_10017cd0 <decomp.c>   # 1関数を抜き出す
```
- `options->GetValue(L"name",&v)` は `(**(code**)(*opt + 0x10))(opt, L"name", &v)` の形で現れる。
- コンストラクタは `*(this)=vftable; ... operator new(サイズ)` → **構造体バイト数**が分かる。
  メンバは `*(int*)(this + 0xNN)` のオフセットで読み解く。
- `MakeFinalImage` 等の共通/自明関数、`TVPAddLog` 相当のログは無視してよい。

### 4. 復元して書く
- **同型の既存ソースを雛形に**する (吉里吉里なら extrans/wave.cpp 等)。エンジン API アクセスは
  デコンパイルの生インデックスでなく **現行エンジンの正しい方式に合わせる** (例: スキャンラインは
  `GetScanLineForWrite(DestTop+n)` / `dest+DestLeft-Left`)。
- **32bit inline asm / MMX は C 等価に置換** (x64 で動かすため)。移植規約は別スキル/メモリ参照。
- **x87 FPU の中間値は Ghidra が落としがち** → sqrt/sin/pow/丸め等の厳密式は復元困難。構造・整数・
  制御フローは忠実に、数式は仕様書＋類似実装から再構成し、**近似はコメントで正直に明記**。

### 5. 規模が大きければ並列サブエージェント
1バイナリに多数の独立クラス(トランジション等)がある場合、**1クラス=1サブエージェント**に分割:
- 各エージェントへ渡す: `decomp.c` パス + そのクラスの FUN_アドレス群(vtables から) + 仕様/ドキュメント
  該当節 + **基準テンプレート(.cpp)** + 共通ヘルパ表 (GetValue のオフセット等)。
- 制約を明示: **共有ファイル(Main/CMake/共通ヘッダ)は変更しない・ビルドしない**。自分の 2 ファイルのみ。
- 親が Main/CMakeLists 配線 → まとめてビルド → 修正。良いテンプレート + 明確なアドレス指定なら
  多数を一発でコンパイル通過させられる。

## 同梱スクリプト (scripts/)
- `ghidra_analyze.sh <bin> [out]` — import+解析+全関数デコンパイル と vtable ダンプを一括実行。
- `DecompileExport.java` — 全関数を C デコンパイルして 1 ファイルへ (headless postScript)。
- `DumpVtables.java` — RTTI vftable と各スロットの仮想関数(アドレス+名前)を出力 (headless postScript)。
- `extract_func.sh <FUN_> <decomp.c>` — デコンパイル C から 1 関数を抜き出す。
- `read_vtables_from_dll.py <bin> <vtables.txt> [--methods prov|hand|N]` — DLL 生バイトから
  vtable の関数ポインタを直読みする fallback (PE の ImageBase/セクションを正しく解釈)。

## 注意・限界
- 逆解析は **自分が権利を持つ／解析が許されるバイナリ** に対して行うこと (ソース紛失した自作物の復元等)。
- 完全なピクセル一致・バイナリ等価は保証できない。**構造/整数/制御フローは高確信、浮動小数の厳密式は
  近似** という切り分けを常にコメントで残す。
- Ghidra 12 特有: Python は PyGhidra 必須 → Java スクリプトを使う。JDK21 が要る。
