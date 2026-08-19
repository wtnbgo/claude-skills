---
name: msys2
description: Windows 上で **シェル操作 (POSIX コマンド / Unix ツール)** を行うときに必ず使う msys2 (C:/msys64) のリファレンス。`grep` / `sed` / `awk` / `find` / `tar` / `curl` / `ssh` / `make` / `gcc` / `cmake` / `pkg-config` / `pacman` などのコマンドを Bash ツール経由で実行する場面、シェルスクリプト (.sh) を書く・読む場面、msys2 環境上で動くツールチェーンを扱う場面、Windows ネイティブ exe を bash から呼ぶ場面で読む。**呼び出されたら最初に「起動コマンドの定型」と「PATH の落とし穴」を必ず確認**。MSYS / UCRT64 / MINGW64 サブシステムの違い、`cygpath` でのパス変換 (`C:\foo` ↔ `/c/foo`)、CRLF/LF、シンボリックリンク、pacman でのパッケージ導入、Windows ネイティブ exe を bash から呼ぶときのクォート、を網羅。PowerShell 固有のコマンドレットや WSL は対象外。
---

# msys2 シェル操作リファレンス

このマシンの shell 系作業は **msys2 (C:/msys64)** に寄せる。Git Bash も
入っているが PATH 順や提供コマンドが微妙に違うので、混在させずに msys2
側に統一する。

## 重要: 作業に入る前に

1. **下の「起動コマンドの定型」をそのまま使う**。Bash ツールを `bash` の
   つもりで素のまま呼ぶと、PowerShell から継承された PATH のせいで Git
   Bash のバイナリ (`/c/Program Files/Git/...`) が先に解決される。
2. **PATH の落とし穴** と **MSYSTEM 環境変数** はクロスカッティングなので
   最初に頭に入れておく ( 後述 )。
3. パッケージ管理 / ビルド / Windows ツール連携の詳細はそれぞれの節を
   参照。深く掘る前にまず「定型」が手癖になっているかを確認する。

## 起動コマンドの定型 ( これだけ覚えれば 9 割回る )

Bash ツール ( このスキルでは PowerShell ではなく Bash ツール経由 ) から
呼ぶときの **基本形**:

```sh
MSYSTEM=MSYS /c/msys64/usr/bin/bash.exe -lc '<コマンド>'
```

- `MSYSTEM=MSYS` を **必ず付ける**。これを省くとユーザ環境の `MSYSTEM`
  (例: `MINGW64`) が残り、`uname` や `$MSYSTEM` 依存スクリプトの挙動が
  ずれる。MSYS サブシステムでは POSIX 互換が最大化される。
- `-l` ( ログインシェル ) で `/etc/profile` が読まれ、PATH が `/usr/bin`
  → `/usr/local/bin` の順に整う。**`-l` なし** だと PATH は呼び出し元の
  Windows PATH のままで、Git Bash のバイナリが先に来る ( ハマる )。
- **★`-l` を付けると `$HOME` へ cd される**。Bash ツールの cwd は引き継が
  れないので、**リポジトリ相対でファイルを触るなら明示的に `cd` する**:
  `MSYSTEM=MSYS /c/msys64/usr/bin/bash.exe -lc 'cd /d/work/proj && ./x.sh'`。
  cwd を保ちたいからと `-l` を落とすと Git Bash に落ちる ( 下記「作業
  ディレクトリ」参照 )。両立させるには `-lc` + 明示 cd が正解。
- `-c '...'` のシングルクォート優先。中に変数展開や `$(...)` を入れる
  ときは bash 側で展開させる。PowerShell 経由ではなく Bash ツール直接
  呼びなので、外側の二重展開を気にしなくてよい。

### ★ビルド定型 ( VCPKG_ROOT 等の Windows 環境変数が要る作業 )

上の基本形 (Bash ツール = Git Bash 起点) は **Windows 環境変数がほぼ全損
する** (VCPKG_ROOT どころか LOCALAPPDATA まで消える。`-c` でも `-lc` でも
同じ。msys ランタイム違いの msys→msys 直接 spawn が原因、2026-08-11 実測)。
grep/sed 等の POSIX 作業には影響しないが、vcpkg / SDK 系ビルドは失敗する。

環境変数が要る作業は **native 親起点** で呼ぶ:

```powershell
# PowerShell ツールから ( 推奨 )
$env:MSYSTEM='MSYS'; & C:\msys64\usr\bin\bash.exe -c 'cd /d/... && make ...'
```

- `-l` は付けない ( /etc/profile が PATH 先頭を組み替え、親で足した PATH が
  落ちる + HOME に cd される )。native 起点なら `-c` で PATH も環境変数も
  親のまま渡る。
- どうしても Bash ツールから呼ぶ場合は cmd を 1 段挟む ( 直接 spawn を
  切る )。ただし msys→cmd の引用符破壊があるので、一時 .cmd ファイルに
  `@C:\msys64\usr\bin\bash.exe -c "..."` を書いて `cmd //c` で実行する。

### 短縮版を使うとき

連続して叩く場合は alias 感覚で内部的に省略してよいが、**最終的に発行する
コマンド文字列には常に `MSYSTEM=MSYS` と `/c/msys64/usr/bin/bash.exe -lc` を含める**。
これを書かないと別シェルに落ちる事故が起きる。

### 作業ディレクトリ

**基本形 (`-lc`) はログインシェルなので `$HOME` に cd される。Bash ツールの
cwd は引き継がれない**。相対パスでスクリプトやファイルを指すと
`No such file or directory` になる ( 2026-08-19 に実際に踏んだ )。

```sh
# ✗ 相対パスは HOME 起点になって落ちる
MSYSTEM=MSYS /c/msys64/usr/bin/bash.exe -lc 'bash tools/x.sh'
# ✓ 明示的に cd する
MSYSTEM=MSYS /c/msys64/usr/bin/bash.exe -lc 'cd /d/work/proj && bash tools/x.sh'
```

**`-l` を外して cwd を保つ、はやってはいけない**。`-c` だと cwd は残るが
PATH が呼び出し元 (Git Bash) のままで、`sed` / `find` / `grep` が
`C:\Program Files\Git\usr\bin\*.exe` に解決される ( 実測 )。挙動差
( `find -printf`、`sed -i` のバックアップ拡張 等 ) を静かに踏む。

パスは Unix 表記 (`/d/test/xxx`)。Windows 表記が必要なら `cygpath -w` で
変換 ( 後述 )。

### 動作確認の 1 行

```sh
MSYSTEM=MSYS /c/msys64/usr/bin/bash.exe -lc 'echo "$MSYSTEM | $(uname -s) | $(cygpath -w "$(which sed)")"'
```

期待出力例: `MSYS | MSYS_NT-10.0-26200 | C:\msys64\usr\bin\sed.exe`

**★裸の `which` で判定してはいけない**。msys2 の mount table は `/usr/bin`
を自分の `C:\msys64\usr\bin` に写すため、Git Bash の PATH を引きずったまま
(`-l` 無し) でも `which sed` は `/usr/bin/sed` と表示する。**`cygpath -w` を
通して実体の Windows パスを見る**こと。`C:\Program Files\Git\...` が出たら
起動定型が崩れている ( `MSYSTEM` と `-l` を確認 )。

## PATH の落とし穴 ( 必読 )

このマシンでは **同名のコマンドが複数の場所に居る**:

| ツール | msys2 のパス | Git Bash のパス | Windows ネイティブ |
|---|---|---|---|
| `bash` | `/c/msys64/usr/bin/bash.exe` | `/c/Program Files/Git/usr/bin/bash.exe` | — |
| `git` | ( 通常入っていない or pacman 経由 ) | `/c/Program Files/Git/cmd/git.exe` | `git.exe` (PATH 経由) |
| `grep` / `sed` / `awk` | `/usr/bin/...` (msys2) | `/usr/bin/...` (Git Bash) | — |
| `python` | pacman で入れた場合 `/usr/bin/python` | — | `python.exe` (PATH 経由) |
| `make` / `gcc` | `/usr/bin/make` `/usr/bin/gcc` (msys2) | — | — |

- **Git Bash の bash を msys2 と思い込まない**。`uname -s` が `MINGW64_NT`
  なら Git Bash、`MSYS_NT` なら msys2 MSYS サブシステム。
- **`git` はホスト側 (Windows) のを使う方が安全**な場合が多い ( credential
  helper、SSH 鍵管理が Windows 側設定に合っているため )。msys2 から
  `git` を叩くと **行末変換** や **SSH 認識** が違うことがある。必要に
  応じて `git.exe` をフルパス指定する。
- **`python` も同様**: pacman 経由の msys2 python は POSIX ライク、Windows
  python は WindowsAPI ネイティブ。プロジェクトの venv がどちら向きかで
  揃える。
- **★`cmd` は PowerShell から必ず `cmd.exe` と明示する**: msys2 は
  `C:\msys64\usr\bin\cmd` という**拡張子なしの bash スクリプト**を同梱しており、
  PATH 先頭に msys64 がある環境の PowerShell では裸の `cmd` がこれに解決される。
  Windows は拡張子なしファイルを実行できず**「開くアプリの選択」ダイアログが出て
  無反応にハング**する (エージェント実行ではタイムアウトまで固まる)。`cmd.exe` なら
  system32 の本物に解決され出力・終了コードとも正常。bash から呼ぶ `cmd //c` は
  スクリプト経由で本物が起動するため動く (紛らわしいが正常)。

## パス変換 ( cygpath )

`cygpath` は **msys2 ↔ Windows パス** の唯一信頼できる変換。手で
`s/\\/\//g` してはいけない ( ドライブレターやスペースで壊れる )。

```sh
cygpath -u 'C:\Users\alice\Documents'    # → /c/Users/alice/Documents  (Unix形式)
cygpath -w '/c/msys64/usr/bin/bash'   # → C:\msys64\usr\bin\bash.exe (Windows形式, .exe 補完あり)
cygpath -m '/c/msys64/usr/bin/bash'   # → C:/msys64/usr/bin/bash.exe (Mixed形式, 前向きスラッシュ + ドライブレター)
cygpath -wa relative/path             # → 絶対化してから Windows 形式
```

主なオプション:
- `-u` Unix 形式 (`/c/...`)
- `-w` Windows 形式 (`C:\...`、バックスラッシュ)
- `-m` Mixed 形式 (`C:/...`、CMake や多くのツールに優しい)
- `-a` 絶対パス化
- `-s` 8.3 形式 ( 短縮、スペース回避用 )

### よく使うパターン

- **Windows ネイティブ exe にパスを渡す**: 必ず `cygpath -w` で変換。
  Unix 形式のまま渡すと exe 側で解釈できない (`bash.exe` 自身は MSYS パスを
  解釈するが、ネイティブの `python.exe` `cmake.exe` `git.exe` は理解しない )。

  ```sh
  python.exe "$(cygpath -w "$PWD/script.py")"
  cmake.exe -S "$(cygpath -m .)" -B "$(cygpath -m build)"
  ```

- **環境変数の自動変換** (`MSYS2_ARG_CONV_EXCL` / `MSYS2_ENV_CONV_EXCL`):
  msys2 bash は Windows exe を呼ぶときに引数中の `/foo/bar` を自動で
  Windows パスに変換することがある。これが裏目に出るとき
  ( 例: `git log --format=/%H/` の `/` をパスと誤認 ) は:

  ```sh
  MSYS2_ARG_CONV_EXCL='*' git.exe log --format=/%H/
  ```

- **`PATH` への追加**: `PATH=/c/foo:$PATH` のように Unix 形式で書く。
  Windows 形式 (`C:\foo`) を入れると `:` がドライブ区切りと衝突して壊れる。

### 落とし穴: シンボリックリンク

msys2 のシンボリックリンクは デフォルトで「Windows のショートカット風
コピー」になる。`MSYS=winsymlinks:nativestrict` を環境に入れておくと本物の
NTFS シンボリックリンクを作るが、**管理者権限か Developer Mode が必要**。
スクリプトが symlink を期待するなら冒頭で:

```sh
export MSYS=winsymlinks:nativestrict
```

を入れておく。`ln -s` で失敗する場合この設定を疑う。

### 落とし穴: CRLF / LF

msys2 のテキストファイルは **LF** が標準。Windows 側エディタや git の
`core.autocrlf=true` が CRLF を混ぜると `bash` がスクリプトの shebang を
読めず `bad interpreter` で落ちる。症状が出たら:

```sh
file ./script.sh                 # → 'ASCII text, with CRLF line terminators' か確認
sed -i 's/\r$//' ./script.sh     # 修正
# あるいは
dos2unix ./script.sh             # 入っていれば
```

git 側で防ぐなら repo に `.gitattributes` で `*.sh text eol=lf`。

## pacman パッケージ管理

msys2 のパッケージ管理は **pacman** ( Arch Linux 由来 )。リポジトリは
`/etc/pacman.conf` に定義され、このマシンでは `[ucrt64]` と `[msys]` が
有効 ( mingw64 リポジトリは無効、現在の推奨は ucrt64 )。

### よく使うコマンド

```sh
pacman -Syu                       # 全パッケージ更新 ( 初回は pacman 自身が更新され、シェル再起動を要求してくる )
pacman -Sy                        # リポジトリ DB だけ更新
pacman -S <pkg>                   # 導入
pacman -R <pkg>                   # 削除 ( 依存は残す )
pacman -Rs <pkg>                  # 削除 + 不要になった依存も削除
pacman -Ss <regex>                # リポジトリ検索
pacman -Qs <regex>                # 既導入の中から検索
pacman -Qi <pkg>                  # 詳細表示 ( 依存・サイズ・インストール日時 )
pacman -Ql <pkg>                  # そのパッケージが置いたファイル一覧
pacman -Qo <path>                 # ファイルがどのパッケージ由来か
pacman -F <file>                  # まだ入れていないパッケージから files を検索 ( 事前に pacman -Fy 必要 )
```

### パッケージの命名規則

| プレフィックス | サブシステム | 例 |
|---|---|---|
| ( なし ) | MSYS ( POSIX ツール ) | `git`, `make`, `vim`, `openssh` |
| `mingw-w64-ucrt-x86_64-` | UCRT64 ( ネイティブ Windows, 新 CRT ) | `mingw-w64-ucrt-x86_64-gcc`, `mingw-w64-ucrt-x86_64-python` |
| `mingw-w64-x86_64-` | MINGW64 ( ネイティブ Windows, MSVCRT ) | この環境では非推奨 |
| `mingw-w64-clang-x86_64-` | CLANG64 | 同上 |

- 「**POSIX ユーティリティ** ( sed/awk/grep/tar/... )」「ビルド時にしか
  使わないツール」は MSYS 側 ( プレフィックスなし )。
- 「**Windows 上で動く成果物バイナリを作りたい** / ネイティブな実行ファイル
  を入れたい」は `mingw-w64-ucrt-x86_64-...`。
- **MSYS の `python` で Windows GUI ライブラリを使うと動かない**ことが多い
  ( 互換 layer 経由のため )。Windows ネイティブな処理が必要なら UCRT64 版を
  入れるか Windows 側 python を使う。

### キーリング・署名エラー

`pacman -Syu` で署名エラーが出たら:

```sh
pacman -S msys2-keyring           # キーリング更新
pacman-key --refresh-keys         # 鍵の再取得
```

それでも駄目なときは [https://www.msys2.org/](https://www.msys2.org/) の
「Updating after a long break」セクションが手順を出している。

## ビルド系ツール ( make / gcc / cmake )

### MSYS vs UCRT64 の使い分け

- **MSYS の gcc** は **MSYS バイナリ** ( msys-2.0.dll に依存 ) を作る。
  msys2 環境内でしか動かない。
- **UCRT64 の gcc** ( `mingw-w64-ucrt-x86_64-gcc` ) は **ネイティブ
  Windows バイナリ** を作る。配布物・最終成果物はこっち。
- **両者を混ぜない**。途中まで MSYS で `./configure` してから UCRT64 で
  `make` すると、ヘッダ・ライブラリの解決がぐちゃぐちゃになる。

ネイティブビルドが必要なときは MSYSTEM を切り替える:

```sh
MSYSTEM=UCRT64 /c/msys64/usr/bin/bash.exe -lc 'gcc --version; which gcc'
# → /ucrt64/bin/gcc, x86_64-w64-mingw32-gcc 系の出力
```

### 典型的なビルド

```sh
# autotools 系
MSYSTEM=UCRT64 /c/msys64/usr/bin/bash.exe -lc './configure --prefix=/ucrt64 && make -j$(nproc) && make install'

# cmake 系 ( Ninja を使うのが速い、pacman -S mingw-w64-ucrt-x86_64-ninja で入る )
MSYSTEM=UCRT64 /c/msys64/usr/bin/bash.exe -lc 'cmake -G Ninja -S . -B build && cmake --build build -j'
```

### pkg-config の罠

`pkg-config` が探す `.pc` ファイルの場所が MSYS / UCRT64 で違う:
- MSYS: `/usr/lib/pkgconfig`
- UCRT64: `/ucrt64/lib/pkgconfig`

MSYSTEM を正しく切替えていれば `$PKG_CONFIG_PATH` が自動で揃う。**症状: 
「ライブラリは入っているのに `pkg-config --cflags foo` が空」** のときは
MSYSTEM がずれている疑いが濃い。

### 並列ビルド

`make -j$(nproc)` / `cmake --build build -j` で OK。`nproc` は msys2 に
入っている ( coreutils )。Windows のコア数を見てくれる。

## Windows ネイティブ exe との連携

msys2 bash から `git.exe` `python.exe` `code.exe` `explorer.exe` などを呼ぶ
ときの注意点。

### パス引数は Windows 形式に変換

```sh
git.exe -C "$(cygpath -w "$PWD")" status
python.exe "$(cygpath -w ./script.py)" --output "$(cygpath -w ./out.txt)"
```

bash 側のパス (`/d/test/xxx`) を直接渡しても、msys2 の自動変換が効くケース
もあるが、効かないツール ( 自前で引数を解釈する CLI ) もあるので **明示的に
`cygpath -w` を通すのが安全**。

### 引数の自動変換を止めたいとき

`/foo/bar` 形式の文字列を引数に渡すと msys2 が「これパスでは?」と判断して
勝手に `C:\foo\bar` に置換することがある。

- **個別**: 引数自体に `;` を挟む ( `--opt=/literal;` ) 、または変数経由で渡す。
- **全面停止**: `MSYS2_ARG_CONV_EXCL='*'` を環境変数で。
- **特定パターン除外**: `MSYS2_ARG_CONV_EXCL='--format=;-D'` のように接頭辞列。

### Windows GUI を開く

```sh
explorer.exe "$(cygpath -w .)"             # 現在ディレクトリを explorer で開く
start "" "$(cygpath -w ./report.html)"     # 既定アプリで開く ( start は cmd.exe builtin なので注意 )
cmd.exe /c start "" "$(cygpath -w ./x)"    # 上が動かないときの確実版
```

### stdout のエンコーディング

Windows ネイティブ exe が CP932 (Shift_JIS) で出してきて bash 側が UTF-8
前提だと文字化けする。`chcp 65001` を事前に投げる、もしくは exe 側に UTF-8
オプションがあればそれを使う ( 例: `python.exe -X utf8` )。

### Process Substitution との相性

`<(...)` `>(...)` は MSYS bash でも動くが、**Windows ネイティブ exe に
渡すと `/dev/fd/63` を解決できず失敗**する。ネイティブ exe には一時ファイル
経由で渡す:

```sh
tmp=$(mktemp); some_unix_cmd > "$tmp"; native.exe "$(cygpath -w "$tmp")"; rm "$tmp"
```

## デバッグ / 困ったときの確認順

1. `MSYSTEM` と `uname -s` を出力する。期待値とずれていないか。
2. `cygpath -w "$(which <コマンド>)"` で実体パスを見る。Git Bash 側 /
   Windows 側を踏んでいないか。裸の `which` は mount table のせいで
   Git Bash のものでも `/usr/bin/...` と出るため判定に使えない。
3. `echo "$PATH" | tr : '\n' | head` で PATH の先頭を見る。`/usr/bin` や
   `/ucrt64/bin` が先頭に近いか。
4. ファイルが絡む話なら `file <path>` `ls -la <path>` で実体と権限と
   line ending を確認。
5. シンボリックリンクは `readlink -f` で実体を辿る。
6. pacman 由来の不整合は `pacman -Qkk <pkg>` でファイル整合性チェック、
   `pacman -S <pkg>` で再導入。

## やってはいけないこと

- **`MSYSTEM` を付けずに長いセッションを始める**。ユーザ環境の `MSYSTEM`
  ( このマシンでは MINGW64 ) に引きずられて、MSYS 想定のスクリプトが
  ずれる。
- **`bash` を `/c/msys64/usr/bin/bash.exe` 以外で呼ぶ**。`bash` 素呼びは
  Git Bash を引く可能性がある。
- **cwd を保ちたいからと `-l` を落とす**。PATH が Git Bash のままになる。
  `-lc` + 明示 `cd` が正解 ( 「作業ディレクトリ」参照 )。
- **手で `\` を `/` に置換してパス変換した気になる**。`cygpath` を使う。
- **`pacman -Syu` を実行して途中で止める**。pacman 自身が更新された場合
  シェルを閉じて再起動が要求される ( メッセージに従う )。
- **`mingw64` リポジトリのパッケージを新規導入する**。このマシンは ucrt64
  推奨。`mingw-w64-ucrt-x86_64-*` を選ぶ。
- **msys2 と Git Bash のコマンドを 1 セッションで混ぜる**。挙動が違う
  ( 例: `find -printf` のフォーマット差、`sed -i` のバックアップ拡張要否 )。
