---
name: appctl
description: エージェントが制御対象アプリ (GUI アプリ / ビルド済みツール / テストサーバ / ゲーム exe 等) を Windows 上で起動・停止・監視するときの共通ルールとヘルパー。**起動した本人が PID を記録し、停止はその PID のみ・実行ファイルパス照合付きで行う**。`taskkill /IM <name>.exe` のようなイメージ名一括 kill は並行セッション (別の Claude セッションやユーザ自身のプロセス) を全滅させるため**絶対禁止**。同梱 `scripts/appctl.sh` が start/stop/status/alive/list を提供する。アプリを起動・再起動・強制終了・生存確認する場面、テスト用にプロセスを繰り返し立ち上げる場面、バックグラウンドで走らせたアプリのログを回収する場面で必ず参照する。本スキルが扱うのはプロセスのライフサイクルのみで、アプリ固有の操作方法は対象外。
---

# appctl — 制御対象アプリの PID 明示管理

## 原則 (これだけは守る)

1. **起動時に PID を取得して記録する** (PowerShell `Start-Process -PassThru`)。
   bash の `&` + `$!` は msys の中間 PID になることがあるため使わない。
2. **停止は記録した PID のみ**。kill 直前に `Get-Process -Id` で
   **実行ファイルパスが自分の起動したものと一致するか照合**する
   (PID 再利用事故と他人のプロセスの誤殺を防ぐ)。
3. **イメージ名での一括操作禁止**: `taskkill /IM xxx.exe`、
   `Get-Process xxx | Stop-Process`、`Stop-Process -Name` は使わない。
   並行する別セッション・ユーザ自身が同名 exe を使っていることが常にありうる。
4. 予期しない死 (自分の PID が消えている) を見つけたら、まず**外部要因
   (並行セッションの kill、ユーザ操作) を疑う**。自分のコード変更の回帰と
   即断してデバッグに突入しない (2026-08-01 に長時間の誤誘導が実際に発生)。
5. 他プロセスの調査は **読み取り専用** (`list`) のみ行ってよい。

## ヘルパー: scripts/appctl.sh

```
bash <このスキル>/scripts/appctl.sh start  <tag> <exe絶対パス> [引数...]
bash <このスキル>/scripts/appctl.sh stop   <tag>
bash <このスキル>/scripts/appctl.sh status <tag>
bash <このスキル>/scripts/appctl.sh alive  <tag>        # 終了コード 0=生存
bash <このスキル>/scripts/appctl.sh list   <名前や部分パス>  # 読み取り専用の列挙
```

- `<tag>` は用途別の識別子 (例: `app` / `test-server`)。tag ごとに
  pidfile (`PID + exe パス`) を保存する。
- **状態ディレクトリ**: 環境変数 `APPCTL_DIR`。セッションの scratchpad
  ディレクトリ配下 (例: `$SCRATCHPAD/appctl`) を指定するのが基本
  (セッションごとに分離され、他セッションの pidfile と衝突しない)。
  未指定時は `~/.claude/tmp/appctl`。
- ログ: `start` は stdout/stderr を `$APPCTL_DIR/<tag>.log` / `<tag>.err.log` に
  リダイレクトする。`APPCTL_LOG=<path>` で上書き可。
- 作業ディレクトリ: 既定は exe のあるディレクトリ。`APPCTL_CWD=<path>` で上書き可。

### 使用例

> スクリプトの場所: プラグインとして導入した場合は `${CLAUDE_PLUGIN_ROOT}` が
> プラグインのルートを指す。この変数が使えない置き方をしている場合は、
> **この SKILL.md と同じ階層の `scripts/`** に読み替える。

```bash
export APPCTL_DIR="$SCRATCHPAD/appctl"
S="${CLAUDE_PLUGIN_ROOT}/skills/appctl/scripts/appctl.sh"

bash "$S" start app "C:/path/to/MyApp.exe" --some-flag --port=8080
bash "$S" alive app && echo "起動している"
# ... テスト ...
bash "$S" stop app
```

## 落とし穴

- **stop で見つからない場合**: 自分の PID が既に死んでいる = 外部 kill か
  クラッシュ。ログ末尾を確認し、必要ならそのまま `start` し直す (原則 4)。
- **GUI アプリのウィンドウ位置**: 解像度の異なるセカンドディスプレイへ
  `setPos` 等で送ると、アプリによってはリサイズ無限ループで暴走する
  (実際に発生した事例あり)。ウィンドウ退避はしない。
- **多重起動テスト**: 同じ tag で start すると古い pidfile を上書きする。
  複数インスタンスが必要なら tag を分ける (`app-1` / `app-2`)。
- exe パスにスペースが含まれる場合もそのまま渡してよい (スクリプト側で処理)。
- リダイレクト先ログを `tail -f` で読む場合、PowerShell の RedirectStandardOutput
  はバッファリングされることがある。リアルタイム性が必要なら、アプリ自身の
  ログ出力機構 (ログレベル指定やコンソール出力オプション) を使う。
