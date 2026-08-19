# claude-skills

[Claude Code](https://claude.com/claude-code) 用のスキル集です。Windows での開発作業で
繰り返し必要になる手順や落とし穴を、Claude が必要なときに自分で読みに行ける形にまとめています。

## インストール

```
/plugin marketplace add wtnbgo/claude-skills
/plugin install dev-toolkit@wtnbgo-skills
```

インストールするとどのリポジトリで作業していてもスキルが有効になります。
更新は `/plugin update dev-toolkit@wtnbgo-skills`。

## 収録スキル

### appctl — 制御対象アプリの PID 明示管理

エージェントが GUI アプリ / ビルド済みツール / テストサーバなどを Windows 上で
起動・停止・監視するための規約とヘルパー。

要点は **起動した本人が PID を記録し、停止はその PID のみ・実行ファイルパス照合付きで行う**
こと。`taskkill /IM <name>.exe` のようなイメージ名一括 kill は、並行して動いている別の
Claude セッションやユーザ自身のプロセスまで巻き添えにするため禁止しています。

同梱の `scripts/appctl.sh` が `start` / `stop` / `status` / `alive` / `list` を提供します
(pidfile に PID と exe パスを保存し、kill 直前に照合)。

### msys2 — Windows での POSIX シェル操作

MSYS2 (`C:/msys64`) 上で `grep` / `sed` / `awk` / `find` / `tar` / `make` / `gcc` /
`cmake` / `pacman` などを扱うときのリファレンス。

MSYS / UCRT64 / MINGW64 サブシステムの違い、`cygpath` によるパス変換
(`C:\foo` ↔ `/c/foo`)、CRLF/LF、シンボリックリンク、Windows ネイティブ exe を
bash から呼ぶときのクォートなど、Windows 固有のハマりどころを集めています。

### ghidra — Windows バイナリの逆解析・ソース復元

ソースが失われた DLL / EXE (x86 / x64) を Ghidra でデコンパイルし、RTTI から C++ の
クラス構造を、vtable から各メソッドの関数アドレスを復元して C 相当のソースへ
再構築するまでの手順。

文字列・エクスポート抽出、全関数デコンパイル、vtable のメソッド地図化、
並列サブエージェントでの復元までをカバーし、ヘルパスクリプト
(`DecompileExport.java` / `DumpVtables.java` / `ghidra_analyze.sh` ほか) を同梱します。

> Ghidra 12 の headless では postScript を **Java で書く必要があります**
> (Python スクリプトは PyGhidra 必須)。同梱スクリプトはその前提です。

### backlog — Backlog (ヌーラボ) の課題管理

[Backlog](https://backlog.com/) の API v2 クライアント。自分に割り当てられている課題の
一覧・詳細・コメント取得が主用途で、通知一覧、プロジェクト一覧、キーワード検索、
状態変更やコメント投稿にも対応します。

複数スペースを設定でき `--space all` で横断検索できます。すべての API 呼び出しは
同梱の `scripts/backlog.py` (Python 標準ライブラリのみ、追加パッケージ不要) が担当します。

**設定** — API キーは各スペースの [個人設定] → [API] で発行し、`~/.backlog.json` に置きます
(リポジトリ外なので誤コミットしません)。

```json
{
  "default": "work",
  "spaces": {
    "work":    { "space": "mycompany.backlog.jp", "api_key": "..." },
    "private": { "space": "myteam.backlog.com",   "api_key": "..." }
  }
}
```

環境変数 `BACKLOG_SPACE` / `BACKLOG_API_KEY` でも指定できます。
リポジトリごとの既定スペース・プロジェクトは `<repo>/.claude/backlog.json` に書けます
(API キーはここには書きません)。

## 動作環境

Windows を前提としています。`appctl` は PowerShell の `Start-Process` / `Get-Process` を、
`msys2` は MSYS2 の導入を、`ghidra` は Ghidra 12 と JDK 21 を使います。
`backlog` だけは Python 3 があればプラットフォームを問いません。

## ライセンス

MIT License. [LICENSE](LICENSE) を参照してください。
