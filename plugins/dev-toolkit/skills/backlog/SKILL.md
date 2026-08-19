---
name: backlog
description: Backlog (ヌーラボ) の課題管理に API v2 経由でアクセスするためのスキル。**自分に割り当てられている課題 (担当課題) の一覧・詳細・コメントを取得する**のが主用途で、通知一覧、プロジェクト一覧、キーワード検索、状態変更/コメント投稿 (書込は要確認) にも対応する。「Backlog の自分の担当を見せて」「この課題の内容を教えて」「未対応のタスクは？」「BLG-123 の詳細」「Backlog に進捗コメントを入れて」といった依頼、および課題キー (例 `PROJ-123`) や `*.backlog.jp` / `*.backlog.com` の URL が出てきた場面で使う。**複数の Backlog スペースを設定でき、`--space all` で横断検索できる**。同梱 `scripts/backlog.py` (Python 標準ライブラリのみ) がすべての API 呼び出しを担う。GitHub Issues や Jira とは別物なので混同しないこと。
---

# backlog — Backlog API v2 アクセス

## 使い方の原則

- **API は必ず同梱スクリプト経由で叩く**。`curl` を直接組み立てない
  (API キーがコマンドラインとログに露出するため)。
- 出力は既定で人間可読の整形テキスト。**構造を機械的に処理したいときだけ `--json`**。
- **書き込み (コメント投稿・状態変更) はユーザの明示的な指示があるときだけ**。
  スクリプト側でも `--yes` を必須にしてある。読み取り依頼のついでに書き込まない。
- 課題キーは大文字 (`PROJ-123`)。URL しか分からない場合は `/view/PROJ-123` の末尾がキー。

## 起動コマンドの定型

> スクリプトの場所: プラグインとして導入した場合は `${CLAUDE_PLUGIN_ROOT}` が
> プラグインのルートを指す。この変数が使えない置き方をしている場合は、
> **この SKILL.md と同じ階層の `scripts/`** に読み替える。

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/backlog/scripts/backlog.py" <サブコマンド> [オプション]
```

Windows (PowerShell ツール) から呼ぶ場合:

```powershell
python "$env:USERPROFILE\.claude\skills\backlog\scripts\backlog.py" mine
```

## 初期設定 (認証)

API キーは各スペースの **[個人設定] → [API] → 登録** で発行する
(**スペースごとに別のキーが必要**)。置き場所は `~/.backlog.json`
(リポジトリ外なので誤コミットしない)。ひな型は `~/.backlog.json.example`。

**複数スペース (推奨形式)**:

```json
{
  "default": "work",
  "spaces": {
    "work":    { "space": "mycompany.backlog.jp",  "api_key": "..." },
    "private": { "space": "myteam.backlog.com",    "api_key": "..." }
  }
}
```

`spaces` のキー (`work` / `private`) は自分で決める呼び名で、`--space` に渡す名前。
`default` は `--space` 省略時に使うスペース。

**単一スペース**なら簡略形式でも動く: `{ "space": "...", "api_key": "..." }`

環境変数 `BACKLOG_SPACE` / `BACKLOG_API_KEY` があればそれが最優先
(プロファイル名 `env`)。`BACKLOG_PROFILE=work` で既定を上書きできる。

疎通確認: `backlog.py spaces` (設定の確認、API を叩かない) → `backlog.py me`。

## スペースの指定 (`--space`)

`--space` はサブコマンドの**前**に置く (`backlog.py --space work mine`)。

- `--space <名前>` — `spaces` の呼び名。ドメイン前方一致でも可 (`--space myteam`)
- `--space all` — **設定済み全スペースを順に実行**。「自分の担当を全部見せて」はこれ。
  `--json` と併用すると `[{space, host, data}, ...]` の配列に集約される。
  **書き込み系では使えない** (スクリプトが拒否する)
- 省略時 — `default` のスペース。ただし `issue` / `comments` は
  **課題キーが既定スペースに無ければ他スペースを自動で探しに行く**
  (どのスペースで見つかったかを `[private: myteam.backlog.com]` と先頭に表示)。
  `--space` を明示した場合は探索しない

## 案件ごとの既定設定 (`.claude/backlog.json`)

作業ディレクトリから**上位に向かって `.claude/backlog.json`
(または `.backlog-project.json`) を探し**、見つかればスペース・プロジェクト・
状態プリセットの既定として使う。これがあると `--space` / `--project` を省略できる。

```json
{
  "space": "work",
  "project": "PROJ"
}
```

**状態はここに書かない。** スキルが API から自動取得する (上の `--status` の節)。
自動導出が意図と合わないときだけ `status_presets` を足せば、そちらが優先される。

- 適用時は `[案件設定: work/PROJ (パス)]` の形で先頭に表示する
- `spaces` で現在効いている案件設定の内容を確認できる
- **`--no-project-config`** で無効化 (他プロジェクトも含めて見たいとき)。
  `--project` を明示した場合もそちらが優先
- `--space all` のときは案件のプロジェクト絞り込みを自動で外す
  (他スペースに同じプロジェクトキーは無いため)
- **状態 id はプロジェクト固有**。カスタム状態は自動取得されるので手書き不要
- 置き場所は案件リポジトリのルート (`<repo>/.claude/backlog.json`) が基本。
  API キーはここには書かない (`~/.backlog.json` 側)

## サブコマンド

| コマンド | 用途 |
| --- | --- |
| `spaces` | 設定済みスペース一覧 (API を叩かない。設定確認用) |
| `me` | 自分のユーザ情報。疎通確認・自分の userId 確認 |
| `mine` | **自分が担当者の課題一覧** (既定: 未対応/処理中/処理済み) |
| `created` | 自分が登録した課題一覧 |
| `issue <KEY>` | 課題の詳細 (種別/状態/担当/期限/説明) |
| `comments <KEY>` | 課題のコメントと変更履歴 |
| `notifications` | 自分宛の通知一覧 (担当に設定された/コメントが付いた 等) |
| `projects` | 参加プロジェクト一覧 (プロジェクトキーと id) |
| `statuses <PROJ>` | そのプロジェクトの状態一覧 (statusId 確認用) |
| `search <KEYWORD>` | キーワード検索 |
| `comment <KEY> <本文>` | **[書込]** コメント投稿 (`--yes` 必須) |
| `update <KEY> --status ...` | **[書込]** 状態/担当/期限の更新 (`--yes` 必須) |
| `create <件名>` | **[書込]** 課題を新規作成 (`--yes` 必須) |
| `raw <PATH>` | 任意の API v2 エンドポイント (エスケープハッチ) |

### よく使う例

```bash
S="${CLAUDE_PLUGIN_ROOT}/skills/backlog/scripts/backlog.py"

python "$S" spaces                              # 設定済みスペースの確認
python "$S" me                                  # 疎通確認 (既定スペース)
python "$S" mine                                # 自分の担当 (既定スペース・未完了)
python "$S" --space all mine                    # 全スペース横断で自分の担当
python "$S" --space private mine                # スペースを指定
python "$S" mine --status todo                  # 未対応のみ
python "$S" mine --status all --limit 100       # 完了含む全部
python "$S" mine --project PROJ --sort dueDate --order asc   # 期限が近い順
python "$S" issue PROJ-123 --full               # 説明を全文
python "$S" comments PROJ-123 --order asc       # 古い順にコメント
python "$S" notifications                       # 自分宛の通知 (* が未読)
python "$S" search "クラッシュ" --assignee-me
python "$S" --json mine | ...                   # 機械処理したいときだけ JSON
```

書き込み (ユーザが明示的に依頼したときのみ):

```bash
python "$S" comment PROJ-123 "修正を r975 でコミットしました" --yes
python "$S" comment PROJ-123 - --yes < body.txt          # 長文は標準入力
python "$S" update PROJ-123 --status 処理中 --comment "着手します" --yes

# 課題を新規作成 (プロジェクトは案件設定から。種別・優先度は名前で指定)
python "$S" create "件名" --type バグ --priority 高 --yes
python "$S" create "件名" -d - --milestone "β版" --assignee 山田太郎 --yes < body.txt
```

### `--status` の指定

`open` / `todo` / `doing` / `review` / `done` / `all`、または statusId 数値。

**プリセットの中身はプロジェクトごとに自動で組み立てられる。** プロジェクトは
カスタム状態 (例 "アサイン済み" / "修正確認待ち") を持つことがあり、その id は
プロジェクト固有なので、素の 1/2/3 で絞ると**カスタム状態の課題を丸ごと取りこぼす**。
スキルは `/projects/:key/statuses` を引き、組み込み状態 (1=未対応 / 2=処理中 /
3=処理済み / 4=完了) を区切りとして表示順どおりに振り分ける:

| プリセット | 中身 |
| --- | --- |
| `todo` | 先頭 〜「処理中」の手前 |
| `doing` | 「処理中」〜「処理済み」の手前 |
| `review` | 「処理済み」〜「完了」の手前 |
| `done` | 「完了」以降 |
| `open` | `done` 以外すべて |

例: 状態が 未対応 / アサイン済み / 処理中 / 処理済み / 修正確認待ち / 完了 なら
`todo`=未対応+アサイン済み / `review`=処理済み+修正確認待ち。

- **どう振り分けられたかは `statuses <PROJ>` が表示する**。まずこれで確認する
- 状態一覧は **24 時間ディスクキャッシュ** (`~/.claude/tmp/backlog/`)。
  状態を追加・並べ替えた直後は **`--refresh-statuses`** で引き直す
- 自動導出が意図と違うときだけ、案件設定に `status_presets` を書けばそちらが優先される
- `--space all` などでプロジェクトが 1 つに定まらない場合は、statusId をサーバへ
  渡さず全件取得してから**課題ごとにそのプロジェクトの状態表で判定**する。
  取りこぼしは無いが、`--limit` は絞り込み前の件数に効くので余裕をもって指定する

### `raw` (未実装エンドポイント用)

```bash
python "$S" raw /issues/count -q "assigneeId[]=12345" -q "statusId[]=1"
python "$S" raw /projects/PROJ/issues/count
python "$S" raw /users/myself/recentlyViewedIssues -q count=10
```

API リファレンス: https://developer.nulab.com/ja/docs/backlog/

## ハマりどころ

- **ユーザ id はスペースごとに違う**。`assigneeId` を跨いで使い回さない
  (スクリプトは各スペースで `/users/myself` を引き直している)。
- **API キーもスペースごとに別**。片方のキーで他方を叩くと 401 になる。
- **Git Bash / MSYS から `raw` を呼ぶとパスが化ける**。`raw /issues/count` の `/issues/...` が
  `C:/Program Files/Git/issues/count` に変換される。**`raw //issues/count` と `//` で書く**
  (スクリプトが検出してエラーにする)。または `MSYS2_ARG_CONV_EXCL='*'` を付ける。
- **`count` の上限は 100**。それ以上は `-q offset=100` でページングする
  (`raw` を使うか、必要なら `--limit 100` を複数回)。
- **配列パラメータは `key[]` 形式**。`assigneeId[]=1&assigneeId[]=2` のように繰り返す。
  `raw` で `-q "statusId[]=1"` と書くときは `[]` ごとクォートする (シェルのグロブ回避)。
- **課題キーとプロジェクトキーの大小文字は区別される**。`proj-123` は 404 になる。
- API キーはクエリ文字列に載る。エラー表示時はスクリプトが `***` にマスクするが、
  **`raw` の結果をそのまま貼るときも URL を含めない**こと。
- **レート制限**は 1 分あたり API キー単位。一覧を舐めるループを書くなら間隔を空ける。
- `notifications` の `reason` は数値コード。スクリプトが日本語に変換して表示する。
- 期限切れ課題を出したいときは `dueDateUntil` を使う:
  `raw /issues -q "assigneeId[]=<id>" -q dueDateUntil=2026-08-14 -q "statusId[]=1" -q "statusId[]=2"`

## 関連

- 認証情報の置き場所は `~/.backlog.json` (ホーム直下)。ひな型は `~/.backlog.json.example`。
  **プロジェクトリポジトリには置かない**。
- 設定に無いスペースを一時的に叩くなら環境変数を都度渡す:
  `BACKLOG_SPACE=other.backlog.jp BACKLOG_API_KEY=... python "$S" mine`
