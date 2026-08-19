#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backlog.py — Backlog (Nulab) API v2 の最小 CLI。

Claude Code skill `backlog` の実体。標準ライブラリのみで動く (依存なし)。

認証情報は以下の順で解決する:
  1. 環境変数 BACKLOG_SPACE / BACKLOG_API_KEY
  2. ~/.backlog.json  {"space": "xxx.backlog.jp", "api_key": "..."}
  3. ~/.config/backlog/config.json  (同じ形式)

API キーは絶対に標準出力へ出さない (URL もマスクして表示する)。
"""

import argparse
import json
import os
import re
import sys
import traceback
import urllib.error
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Windows のコンソールでも日本語を壊さない
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CONFIG_PATHS = [
    Path.home() / ".backlog.json",
    Path.home() / ".config" / "backlog" / "config.json",
]

# ひな型のまま (未編集) を検出するための値
PLACEHOLDERS = {"PASTE_YOUR_API_KEY_HERE", "example.backlog.jp", "xxxxxxxxxxxxxxxx", ""}

# 案件 (作業ディレクトリ) ごとの既定設定。cwd から上に向かって探す。
PROJECT_CONFIG_NAMES = [Path(".claude") / "backlog.json", Path(".backlog-project.json")]

# 状態プリセットの最終フォールバック (標準 4 状態しか無いプロジェクト用)。
# 実際には presets_for_project() がプロジェクトの状態一覧を API から引いて
# カスタム状態込みで組み立てる。 ここはプロジェクトを特定できない場面
# (--space all など) だけで使われる。
STATUS_PRESETS = {
    "open": ["1", "2", "3"],      # 未対応 / 処理中 / 処理済み
    "todo": ["1"],
    "doing": ["2"],
    "review": ["3"],
    "done": ["4"],
    "all": [],
}

# Backlog 組み込み状態の id (プロジェクトを跨いで固定)。 カスタム状態は
# これ以外の大きな id を持ち、 一覧の並び (displayOrder 順) の中に差し込まれる。
BUILTIN_TODO, BUILTIN_DOING, BUILTIN_DONE_WORK, BUILTIN_CLOSED = 1, 2, 3, 4

# プロジェクト状態一覧のキャッシュ (API 呼び出しを減らす)。 既定 24 時間。
STATUS_CACHE_DIR = Path.home() / ".claude" / "tmp" / "backlog"
STATUS_CACHE_TTL = 24 * 60 * 60

NOTIFY_REASON = {
    1: "担当者に設定",
    2: "課題にコメント",
    3: "課題を更新",
    4: "ファイルを追加",
    5: "プロジェクトユーザを追加",
    6: "その他",
    7: "PRの担当者に設定",
    8: "PRにコメント",
    9: "PRを更新",
    10: "コメントで返信",
}

_profiles = None      # {name: (space, api_key, src)}
_default_name = None  # 明示指定がないときに使うプロファイル名
_current = None       # 現在選択中のプロファイル名
_stale = []           # ひな型のままで無視したエントリ
_pjcfg = None         # 案件設定 (.claude/backlog.json) の内容
_status_cache = {}      # (host, project) -> statuses
_cfg_presets = set()   # .claude/backlog.json で明示指定されたプリセット名
_pjpath = None        # 同ファイルのパス


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def norm_space(s):
    s = (s or "").replace("https://", "").replace("http://", "").strip().rstrip("/")
    if s and "." not in s:
        s += ".backlog.jp"
    return s


def _add_profile(profs, name, space, key, src):
    space, key = norm_space(space), (key or "").strip()
    if not space or not key or space in PLACEHOLDERS or key in PLACEHOLDERS:
        _stale.append(f"{name} ({src})")
        return
    profs[name] = (space, key, src)


def load_profiles():
    """設定ファイル / 環境変数から全プロファイルを読む。

    単一スペース形式:  {"space": ..., "api_key": ...}
    複数スペース形式:  {"default": "work", "spaces": {"work": {...}, "private": {...}}}
    """
    global _profiles, _default_name
    if _profiles is not None:
        return _profiles
    profs = {}
    default = None
    for p in CONFIG_PATHS:
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            die(f"{p} の読み込みに失敗 (JSON 構文エラー?): {e}")
        spaces = d.get("spaces")
        if isinstance(spaces, dict):
            for name, e in spaces.items():
                if name.startswith("_") or not isinstance(e, dict):
                    continue
                _add_profile(profs, name, e.get("space") or e.get("host"),
                             e.get("api_key") or e.get("apiKey"), str(p))
            want = d.get("default")
            default = want if want in profs else (next(iter(profs), None))
        else:
            _add_profile(profs, "default", d.get("space") or d.get("host"),
                         d.get("api_key") or d.get("apiKey"), str(p))
            default = default or ("default" if "default" in profs else None)
        break  # 最初に見つかったファイルだけを使う
    if os.environ.get("BACKLOG_SPACE") and os.environ.get("BACKLOG_API_KEY"):
        _add_profile(profs, "env", os.environ["BACKLOG_SPACE"],
                     os.environ["BACKLOG_API_KEY"], "env")
        if "env" in profs:
            default = "env"
    env_prof = os.environ.get("BACKLOG_PROFILE")
    if env_prof and env_prof in profs:
        default = env_prof
    if not profs:
        hint = ""
        if _stale:
            hint = ("\n  ひな型のまま未編集のエントリ: " + ", ".join(_stale) +
                    "\n  space と api_key を実際の値に書き換えてください。")
        die(
            "認証情報が見つかりません。" + hint + "\n"
            "  ~/.backlog.json.example をひな型として ~/.backlog.json を作り、\n"
            "  space (例 mycompany.backlog.jp) と api_key を設定してください。\n"
            "  API キーは Backlog の [個人設定] → [API] で発行します。"
        )
    _profiles, _default_name = profs, default
    return profs


def find_project_config(start=None):
    """cwd から上位ディレクトリへ .claude/backlog.json (または .backlog-project.json) を探す。"""
    here = Path(start or Path.cwd()).resolve()
    for d in [here] + list(here.parents):
        for name in PROJECT_CONFIG_NAMES:
            p = d / name
            if p.is_file():
                try:
                    return json.loads(p.read_text(encoding="utf-8")), p
                except Exception as e:
                    die(f"{p} の読み込みに失敗 (JSON 構文エラー?): {e}")
    return None, None


def apply_project_config(cfg):
    """案件設定の status_presets を取り込む (値は文字列に正規化)。

    ここで入れたものは「明示指定」として扱い、 API 由来の自動導出より優先する
    (presets_for_project が _cfg_presets を見て上書きを尊重する)。
    """
    global _cfg_presets
    for name, ids in (cfg.get("status_presets") or {}).items():
        STATUS_PRESETS[name] = [str(i) for i in ids]
        _cfg_presets.add(name)


# ---------------------------------------------------------------- 状態プリセット
#
# プロジェクトごとにカスタム状態 (例 "アサイン済み" / "修正確認待ち") が
# 追加されていることがあり、 その id はプロジェクト固有。 素の open (1,2,3) で
# 絞ると **カスタム状態の課題を丸ごと取りこぼす** ので、 プロジェクトの状態
# 一覧を API から引いて組み立てる。
#
# 区分けは Backlog 組み込み状態 (1=未対応 / 2=処理中 / 3=処理済み / 4=完了) を
# 区切りに使う。 API は displayOrder 順 (= ボードの列順) で返すので、
#   todo   … 先頭 〜 「処理中」の手前
#   doing  … 「処理中」〜 「処理済み」の手前
#   review … 「処理済み」〜 「完了」の手前
#   done   … 「完了」以降
#   open   … done 以外すべて
# とすると、 カスタム状態が「どの組み込み状態の後ろに置かれているか」で
# 自然に振り分けられる。
#
# 例: 未対応 / アサイン済み / 処理中 / 処理済み / 修正確認待ち / 完了 という並びなら
#   → todo=[未対応, アサイン済み] doing=[処理中] review=[処理済み, 修正確認待ち]

def _status_cache_path(project_key):
    host = (space_host() or "unknown").replace(":", "_")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_key)
    return STATUS_CACHE_DIR / f"statuses-{host}-{safe}.json"


def fetch_project_statuses(project_key, refresh=False):
    """プロジェクトの状態一覧 (displayOrder 順)。 24 時間ディスクキャッシュ。"""
    key = (space_host(), project_key)
    if not refresh and key in _status_cache:
        return _status_cache[key]
    p = _status_cache_path(project_key)
    if not refresh and p.is_file():
        try:
            if time.time() - p.stat().st_mtime < STATUS_CACHE_TTL:
                ss = json.loads(p.read_text(encoding="utf-8"))
                _status_cache[key] = ss
                return ss
        except Exception:
            pass          # キャッシュ破損は無視して引き直す
    ss = api("GET", f"/projects/{urllib.parse.quote(project_key)}/statuses")
    _status_cache[key] = ss
    try:
        STATUS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(ss, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass              # キャッシュが書けなくても動作には影響しない
    return ss


def derive_presets(statuses):
    """状態一覧 (displayOrder 順) から open/todo/doing/review/done を組み立てる。"""
    ids = [str(s["id"]) for s in statuses]
    # 組み切り位置 (見つからない組み込み状態があっても壊れないようにする)
    def pos(builtin):
        t = str(builtin)
        return ids.index(t) if t in ids else None
    i_doing, i_rev, i_done = (pos(BUILTIN_DOING), pos(BUILTIN_DONE_WORK),
                              pos(BUILTIN_CLOSED))
    n = len(ids)
    e_todo = i_doing if i_doing is not None else n
    e_doing = i_rev if i_rev is not None else e_todo
    e_rev = i_done if i_done is not None else e_doing
    done = ids[i_done:] if i_done is not None else []
    return {
        "todo":   ids[:e_todo],
        "doing":  ids[e_todo:e_doing],
        "review": ids[e_doing:e_rev],
        "done":   done,
        "open":   [i for i in ids if i not in set(done)],
        "all":    [],
    }


def presets_for_project(project_key, refresh=False):
    """プロジェクトの状態から導いたプリセット。 案件設定の明示指定が最優先。"""
    if not project_key:
        return dict(STATUS_PRESETS)
    try:
        d = derive_presets(fetch_project_statuses(project_key, refresh))
    except Exception:
        return dict(STATUS_PRESETS)      # 取得できなければ従来どおり
    for name in _cfg_presets:            # .claude/backlog.json の明示指定が勝つ
        d[name] = STATUS_PRESETS[name]
    return d


PRESET_NAMES = ("open", "todo", "doing", "review", "done", "all")


def status_filter(a, projs):
    """--status を (サーバへ渡す statusId のリスト, クライアント側の絞り込み関数)
    に解決する。

    プロジェクトが 1 つに定まるなら、 その状態一覧から導いた id をサーバへ渡す
    (効率が良く、 件数も正確)。

    **複数プロジェクト / --space all で 1 つに定まらない場合**は、 プロジェクト
    ごとにカスタム状態の id が違うので固定 id を渡すと取りこぼす。 そこで
    statusId は渡さず全件取得し、 各課題の projectId から**その課題のプロジェクト
    の**状態一覧を引いて判定する。 id 直指定 (--status 415194 等) はそのまま渡す。
    """
    refresh = getattr(a, "refresh_statuses", False)
    if a.status not in PRESET_NAMES:          # 数値 id 等はそのまま
        return [a.status], None
    if a.status == "all":
        return [], None

    key = projs[0] if projs and len(projs) == 1 else None
    if key:
        return presets_for_project(key, refresh).get(a.status, []), None

    # プロジェクト不定 → クライアント側で判定する
    def keep(issue):
        pid = issue.get("projectId")
        sid = str(dget(issue, "status", "id") or "")
        if pid is None or not sid:
            return True
        try:
            table = derive_presets(fetch_project_statuses(str(pid), refresh))
        except Exception:
            table = STATUS_PRESETS
        return sid in table.get(a.status, [])
    return None, keep


def apply_status_params(a, projs, params):
    """status_filter の結果を params へ載せ、 クライアント側フィルタを返す。"""
    ids, keep = status_filter(a, projs)
    for sid in (ids or []):
        params.append(("statusId[]", sid))
    return keep


def default_projects(a):
    """--project 未指定なら案件設定のプロジェクトを使う。"""
    if a.project:
        return a.project
    if _pjcfg and not (a.space and a.space.lower() == "all"):
        p = _pjcfg.get("project")
        if p:
            return [p] if isinstance(p, str) else list(p)
    return None


def select_profile(name):
    """--space の指定を解決する。別名 / ドメイン前方一致のどちらでも引ける。"""
    global _current
    profs = load_profiles()
    if not name:
        _current = _default_name
        return _current
    if name in profs:
        _current = name
        return name
    hit = [n for n, (sp, _, _) in profs.items()
           if sp == norm_space(name) or sp.split(".")[0] == name]
    if len(hit) == 1:
        _current = hit[0]
        return hit[0]
    die(f"スペース '{name}' が設定にありません。利用可能: {', '.join(profs)}")


def load_config():
    profs = load_profiles()
    return profs[_current or _default_name]


def check_path(path):
    """Git Bash / MSYS のパス変換で `/issues/count` が `C:/Program Files/Git/issues/count`
    に化ける事故を検出する (raw コマンドでのみ起きうる)。"""
    p = (path or "").strip()
    if re.match(r"^[A-Za-z]:[\\/]", p) or "\\" in p or " " in p:
        die("API パスに Windows パスが混ざっています (MSYS/Git Bash のパス変換):\n"
            f"  受け取った値: {p}\n"
            "  → 先頭を `//` にする (例: raw //issues/count) か、\n"
            "     MSYS2_ARG_CONV_EXCL='*' を付けて実行してください。")
    return p


def api(method, path, params=None, data=None, soft=False):
    """params は (key, value) のリスト (statusId[] 等の繰り返しに対応)。

    soft=True のときは HTTP エラーで終了せず None を返す (スペース跨ぎの探索用)。
    """
    space, key, _ = load_config()
    path = check_path(path)
    q = [("apiKey", key)] + list(params or [])
    url = f"https://{space}/api/v2/{path.lstrip('/')}?" + urllib.parse.urlencode(q)
    safe_url = url.replace(key, "***")
    body = None
    headers = {"Accept": "application/json", "User-Agent": "claude-backlog-skill/1.0"}
    if data:
        body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if soft:
            return None
        detail = e.read().decode("utf-8", "replace")[:1000]
        extra = ""
        if e.code == 401:
            extra = f"\n  → スペース {space} の API キーが不正か失効しています ({load_config()[2]})"
        elif e.code == 404:
            extra = f"\n  → スペース {space} に存在しないキーかもしれません (--space で他方を指定 / `projects` で確認)"
        die(f"HTTP {e.code} {method} {safe_url}{extra}\n{detail}")
    except urllib.error.URLError as e:
        if soft:
            return None
        die(f"接続失敗 {safe_url}: {str(e.reason).replace(key, '***')}")
    except Exception as e:
        # 想定外の例外でも API キーを絶対に出さない (トレースバックを抑止する)
        if soft:
            return None
        die(f"{type(e).__name__}: {str(e).replace(key, '***')}\n  URL={safe_url}")
    return json.loads(raw) if raw.strip() else None


def find_in_spaces(fetch):
    """全プロファイルを順に試し、最初に成功したものを (結果, プロファイル名) で返す。"""
    global _current
    order = [_current or _default_name]
    order += [n for n in load_profiles() if n not in order]
    for name in order:
        _current = name
        r = fetch()
        if r is not None:
            return r, name
    _current = order[0]
    return None, None


_json_bucket = None  # --space all + --json のときだけ集約する


def out_json(obj):
    if _json_bucket is not None:
        _json_bucket.append({"space": _current, "host": space_host(), "data": obj})
        return
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def space_host():
    return load_config()[0]


def issue_url(key):
    return f"https://{space_host()}/view/{key}"


def dget(d, *path, default=""):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or cur.get(k) is None:
            return default
        cur = cur[k]
    return cur


def fmt_date(s):
    return (s or "")[:10]


def myself_id():
    return api("GET", "/users/myself")["id"]


def print_issues(issues, show_url=True):
    if not issues:
        print("(該当なし)")
        return
    for i in issues:
        key = i.get("issueKey", "")
        status = dget(i, "status", "name")
        prio = dget(i, "priority", "name")
        due = fmt_date(i.get("dueDate"))
        upd = fmt_date(i.get("updated"))
        assignee = dget(i, "assignee", "name", default="-")
        line = f"{key:<16} [{status}] {i.get('summary','')}"
        print(line)
        meta = f"    優先度={prio} 担当={assignee} 期限={due or '-'} 更新={upd}"
        print(meta)
        if show_url:
            print(f"    {issue_url(key)}")
    print(f"\n計 {len(issues)} 件")


# ---------------------------------------------------------------- commands

def cmd_me(a):
    u = api("GET", "/users/myself")
    if a.json:
        return out_json(u)
    print(f"id={u['id']} userId={u.get('userId')} name={u.get('name')} mail={u.get('mailAddress')}")
    print(f"space={space_host()}  profile={_current or _default_name}  (認証情報: {load_config()[2]})")
    others = [n for n in load_profiles() if n != (_current or _default_name)]
    if others:
        print(f"他に設定済みのスペース: {', '.join(others)}  (--space <名前> / --space all)")


def cmd_mine(a):
    uid = myself_id()
    params = [("assigneeId[]", str(uid)), ("count", str(a.limit)),
              ("sort", a.sort), ("order", a.order)]
    projs = default_projects(a)
    _keep = apply_status_params(a, projs, params)
    if projs:
        for p in projs:
            pj = api("GET", f"/projects/{urllib.parse.quote(p)}")
            params.append(("projectId[]", str(pj["id"])))
    if a.keyword:
        params.append(("keyword", a.keyword))
    issues = api("GET", "/issues", params)
    if _keep:
        issues = [i for i in issues if _keep(i)]
    if a.json:
        return out_json(issues)
    scope = f" project={','.join(projs)}" if projs else ""
    print(f"== 自分が担当の課題 (status={a.status}{scope}) ==")
    print_issues(issues)


def cmd_created(a):
    uid = myself_id()
    params = [("createdUserId[]", str(uid)), ("count", str(a.limit)),
              ("sort", a.sort), ("order", a.order)]
    projs = default_projects(a)
    _keep = apply_status_params(a, projs, params)
    if projs:
        for p in projs:
            pj = api("GET", f"/projects/{urllib.parse.quote(p)}")
            params.append(("projectId[]", str(pj["id"])))
    issues = api("GET", "/issues", params)
    if _keep:
        issues = [i for i in issues if _keep(i)]
    if a.json:
        return out_json(issues)
    print(f"== 自分が登録した課題 (status={a.status}) ==")
    print_issues(issues)


def cmd_issue(a):
    path = f"/issues/{urllib.parse.quote(a.key)}"
    if a.space:  # スペース明示時は他を探しに行かない
        i = api("GET", path)
    else:
        i, prof = find_in_spaces(lambda: api("GET", path, soft=True))
        if i is None:
            die(f"課題 {a.key} が見つかりません (探したスペース: {', '.join(load_profiles())})")
        if len(load_profiles()) > 1:
            print(f"[{prof}: {space_host()}]")
    if a.json:
        return out_json(i)
    print(f"{i['issueKey']}  {i.get('summary','')}")
    print(f"  URL      : {issue_url(i['issueKey'])}")
    print(f"  種別     : {dget(i,'issueType','name')}   状態: {dget(i,'status','name')}   優先度: {dget(i,'priority','name')}")
    print(f"  担当者   : {dget(i,'assignee','name', default='-')}   登録者: {dget(i,'createdUser','name')}")
    print(f"  開始/期限: {fmt_date(i.get('startDate')) or '-'} / {fmt_date(i.get('dueDate')) or '-'}")
    print(f"  予定/実績: {i.get('estimatedHours') or '-'} / {i.get('actualHours') or '-'}")
    ms = ", ".join(m.get("name", "") for m in (i.get("milestone") or [])) or "-"
    cat = ", ".join(c.get("name", "") for c in (i.get("category") or [])) or "-"
    print(f"  マイルストーン: {ms}   カテゴリ: {cat}")
    print(f"  作成/更新: {i.get('created','')[:19]} / {i.get('updated','')[:19]}")
    desc = i.get("description") or ""
    if desc:
        print("  --- 説明 ---")
        if not a.full and len(desc) > 2000:
            desc = desc[:2000] + f"\n  ...(残り {len(i['description'])-2000} 文字、--full で全文)"
        for line in desc.splitlines():
            print("  " + line)


def cmd_comments(a):
    path = f"/issues/{urllib.parse.quote(a.key)}/comments"
    params = [("count", str(a.limit)), ("order", a.order)]
    if a.space:
        cs = api("GET", path, params)
    else:
        cs, prof = find_in_spaces(lambda: api("GET", path, params, soft=True))
        if cs is None:
            die(f"課題 {a.key} が見つかりません (探したスペース: {', '.join(load_profiles())})")
        if len(load_profiles()) > 1:
            print(f"[{prof}: {space_host()}]")
    if a.json:
        return out_json(cs)
    if not cs:
        print("(コメントなし)")
        return
    for c in cs:
        print(f"--- #{c['id']} {dget(c,'createdUser','name')}  {c.get('created','')[:19]}")
        body = c.get("content") or ""
        for line in body.splitlines():
            print("  " + line)
        for ch in c.get("changeLog") or []:
            def cut(v, n=100):
                v = " ".join(str(v or "").split())
                return v if len(v) <= n else v[:n] + f"…({len(v)}文字)"
            print(f"  [変更] {ch.get('field')}: {cut(ch.get('originalValue'))} -> {cut(ch.get('newValue'))}")


def cmd_notifications(a):
    ns = api("GET", "/notifications", [("count", str(a.limit))])
    if a.json:
        return out_json(ns)
    if not ns:
        print("(通知なし)")
        return
    for n in ns:
        reason = NOTIFY_REASON.get(n.get("reason"), f"reason={n.get('reason')}")
        mark = " " if n.get("alreadyRead") else "*"
        iss = n.get("issue") or {}
        key = iss.get("issueKey", "")
        print(f"{mark} [{reason}] {key} {iss.get('summary','')}")
        print(f"    from={dget(n,'sender','name')}  {n.get('created','')[:19]}  {issue_url(key) if key else ''}")
    print("\n(* = 未読)")


def cmd_spaces(a):
    profs = load_profiles()
    if a.json:
        return out_json({n: {"space": sp, "source": src, "default": n == _default_name}
                         for n, (sp, _, src) in profs.items()})
    for n, (sp, _, src) in profs.items():
        mark = "*" if n == _default_name else " "
        print(f"{mark} {n:<12} {sp:<28} ({src})")
    print("\n(* = 既定。--space <名前> で切替、--space all で全スペース横断)")
    if _stale:
        print(f"未設定のまま無視したエントリ: {', '.join(_stale)}")
    if _pjcfg:
        print(f"\n案件設定: {_pjpath}")
        print(f"  space={_pjcfg.get('space')}  project={_pjcfg.get('project')}")
        for name, ids in (_pjcfg.get("status_presets") or {}).items():
            names = _pjcfg.get("statuses") or {}
            label = ", ".join(f"{i}:{names.get(str(i), '?')}" for i in ids)
            print(f"  status プリセット '{name}' = {label}")
        print("  (--no-project-config で無効化)")


def cmd_projects(a):
    ps = api("GET", "/projects")
    if a.json:
        return out_json(ps)
    for p in ps:
        print(f"{p['projectKey']:<16} id={p['id']:<8} {p.get('name','')}")
    print(f"\n計 {len(ps)} プロジェクト")


def cmd_statuses(a):
    ss = fetch_project_statuses(a.project, getattr(a, "refresh_statuses", False))
    if a.json:
        return out_json(ss)
    names = {str(x["id"]): x.get("name", "") for x in ss}
    for x in ss:
        mark = "" if str(x["id"]).isdigit() and int(x["id"]) <= 4 else "  (カスタム)"
        print(f"id={x['id']:<8} {x.get('name','')}{mark}")
    # この一覧から自動導出したプリセット。 --status open 等がどれを拾うかの確認用。
    print()
    print("--status のプリセット (この一覧から自動導出):")
    table = presets_for_project(a.project, getattr(a, "refresh_statuses", False))
    for name in ("open", "todo", "doing", "review", "done"):
        ids = table.get(name, [])
        label = " / ".join(names.get(i, i) for i in ids) or "(なし)"
        src = " ※案件設定で明示指定" if name in _cfg_presets else ""
        print(f"  {name:<7} = {label}{src}")


def cmd_search(a):
    params = [("keyword", a.keyword), ("count", str(a.limit)),
              ("sort", a.sort), ("order", a.order)]
    _projs = default_projects(a) or []
    _keep = apply_status_params(a, _projs, params)
    for p in _projs:
        pj = api("GET", f"/projects/{urllib.parse.quote(p)}")
        params.append(("projectId[]", str(pj["id"])))
    if a.assignee_me:
        params.append(("assigneeId[]", str(myself_id())))
    issues = api("GET", "/issues", params)
    if _keep:
        issues = [i for i in issues if _keep(i)]
    if a.json:
        return out_json(issues)
    print_issues(issues)


def require_yes(a, what):
    if not a.yes:
        die(f"書き込み操作 ({what}) には --yes が必要です。ユーザの明示的な指示なしに実行しないこと。")


def cmd_comment(a):
    require_yes(a, "コメント投稿")
    body = a.text
    if body == "-":
        body = sys.stdin.read()
    r = api("POST", f"/issues/{urllib.parse.quote(a.key)}/comments", data={"content": body})
    print(f"投稿しました: comment #{r['id']} on {a.key}")
    print(issue_url(a.key))


def resolve_user_id(issue_key, who):
    """担当者指定を userId へ解決する。 数値ならそのまま、 それ以外は
    プロジェクト参加者の name から前方一致で引く。"""
    who = (who or "").strip()
    if who.isdigit():
        return who
    proj = issue_key.rsplit("-", 1)[0]
    users = api("GET", f"/projects/{proj}/users")
    hit = [u for u in users if u.get("name") == who]
    if not hit:
        hit = [u for u in users if who.lower() in (u.get("name") or "").lower()]
    if not hit:
        die(f"担当者 '{who}' が見つかりません: {[u.get('name') for u in users]}")
    if len(hit) > 1:
        die(f"担当者 '{who}' が複数該当します: {[u.get('name') for u in hit]}")
    return str(hit[0]["id"])


def cmd_update(a):
    require_yes(a, "課題更新")
    data = {}
    if a.status:
        if a.status.isdigit():
            data["statusId"] = a.status
        else:
            key = a.key.rsplit("-", 1)[0]
            ss = api("GET", f"/projects/{key}/statuses")
            hit = [s for s in ss if s["name"] == a.status]
            if not hit:
                die(f"状態 '{a.status}' が見つかりません: {[s['name'] for s in ss]}")
            data["statusId"] = str(hit[0]["id"])
    if a.comment:
        # cmd_comment と同じく "-" は標準入力から読む。
        # ここが素通しだったため本文がリテラル "-" のまま投稿され、
        # 説明文が相手へ一切届かない事故が起きた (2026-08-17)。
        body = sys.stdin.read() if a.comment == "-" else a.comment
        if not body.strip():
            die("コメント本文が空です ('-' は標準入力から読みます。本文を流し込んでください)")
        data["comment"] = body
    if a.assignee:
        data["assigneeId"] = resolve_user_id(a.key, a.assignee)
    if a.assignee_me:
        data["assigneeId"] = str(myself_id())
    if a.due:
        data["dueDate"] = a.due
    if not data:
        die("更新項目がありません (--status / --comment / --assignee-me / --due)")
    r = api("PATCH", f"/issues/{urllib.parse.quote(a.key)}", data=data)
    print(f"更新しました: {r['issueKey']} 状態={dget(r,'status','name')}")
    print(issue_url(r["issueKey"]))


def cmd_create(a):
    """[書込] 課題を新規作成する。

    projectId / issueTypeId / priorityId は API の必須項目だが、 毎回 id を
    調べるのは手間なので、 プロジェクトキーと種別名・優先度名から引く。
    プロジェクトは案件設定 (.claude/backlog.json) があれば省略できる。
    """
    require_yes(a, "課題作成")

    projs = [a.project] if a.project else (default_projects(a) or [])
    if not projs:
        die("プロジェクトが特定できません (--project PROJ か案件設定が要ります)")
    if len(projs) > 1:
        die(f"プロジェクトが複数あります: {projs} (--project で 1 つに絞ってください)")
    key = projs[0]
    pj = api("GET", f"/projects/{urllib.parse.quote(key)}")

    types = api("GET", f"/projects/{urllib.parse.quote(key)}/issueTypes")
    hit = [t for t in types if t["name"] == a.type] or           [t for t in types if str(t["id"]) == str(a.type)]
    if not hit:
        die(f"種別 '{a.type}' が見つかりません: {[t['name'] for t in types]}")
    type_id = str(hit[0]["id"])

    pris = api("GET", "/priorities")
    ph = [p for p in pris if p["name"] == a.priority] or          [p for p in pris if str(p["id"]) == str(a.priority)]
    if not ph:
        die(f"優先度 '{a.priority}' が見つかりません: {[p['name'] for p in pris]}")

    body = sys.stdin.read() if a.description == "-" else (a.description or "")

    data = {
        "projectId":   str(pj["id"]),
        "summary":     a.summary,
        "issueTypeId": type_id,
        "priorityId":  str(ph[0]["id"]),
    }
    if body.strip():
        data["description"] = body
    if a.due:
        data["dueDate"] = a.due
    if a.assignee:
        # resolve_user_id は課題キーからプロジェクトを引くので、 ここでは
        # プロジェクトキー + ダミー番号を渡して同じ経路を使う。
        data["assigneeId"] = resolve_user_id(f"{key}-1", a.assignee)
    if a.assignee_me:
        data["assigneeId"] = str(myself_id())
    if a.milestone:
        ms = api("GET", f"/projects/{urllib.parse.quote(key)}/versions")
        mh = [m for m in ms if m["name"] == a.milestone]
        if not mh:
            die(f"マイルストーン '{a.milestone}' が見つかりません: "
                f"{[m['name'] for m in ms if not m.get('archived')]}")
        data["milestoneId[]"] = str(mh[0]["id"])
    if a.category:
        cs = api("GET", f"/projects/{urllib.parse.quote(key)}/categories")
        ch = [c for c in cs if c["name"] == a.category]
        if not ch:
            die(f"カテゴリ '{a.category}' が見つかりません: {[c['name'] for c in cs]}")
        data["categoryId[]"] = str(ch[0]["id"])

    r = api("POST", "/issues", data=data)
    if a.json:
        return out_json(r)
    print(f"作成しました: {r['issueKey']}  {r.get('summary','')}")
    print(f"  種別={dget(r,'issueType','name')} 優先度={dget(r,'priority','name')} "
          f"状態={dget(r,'status','name')} 担当={dget(r,'assignee','name') or '-'}")
    print(issue_url(r["issueKey"]))


def cmd_raw(a):
    params = []
    for kv in a.query or []:
        k, _, v = kv.partition("=")
        params.append((k, v))
    data = None
    if a.data:
        data = {}
        for kv in a.data:
            k, _, v = kv.partition("=")
            data[k] = v
    r = api(a.method, a.path, params, data)
    out_json(r)


# ---------------------------------------------------------------- parser

def build_parser():
    p = argparse.ArgumentParser(prog="backlog.py", description="Backlog API v2 CLI")
    p.add_argument("--json", action="store_true", help="生 JSON を出力")
    p.add_argument("--space", metavar="NAME",
                   help="対象スペース (~/.backlog.json の spaces の名前 / ドメイン)。"
                        "'all' で設定済み全スペースを順に実行 (読み取り系のみ)")
    p.add_argument("--refresh-statuses", action="store_true",
                   help="プロジェクト状態一覧のキャッシュを無視して引き直す "
                        "(状態を追加/並べ替えた直後に使う。 既定は 24 時間キャッシュ)")
    p.add_argument("--no-project-config", action="store_true",
                   help="案件設定 (.claude/backlog.json) を無視して全スペース/全プロジェクトを対象にする")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_list_opts(sp, default_status="open"):
        sp.add_argument("--status", default=default_status,
                        help="open|todo|doing|done|all または statusId 数値 (既定: %(default)s)")
        sp.add_argument("--limit", type=int, default=50, help="最大件数 (既定: 50, API 上限 100)")
        sp.add_argument("--sort", default="updated",
                        help="created|updated|dueDate|priority など (既定: %(default)s)")
        sp.add_argument("--order", default="desc", choices=["asc", "desc"])

    s = sub.add_parser("me", help="自分のユーザ情報 (疎通確認用)")
    s.set_defaults(func=cmd_me)

    s = sub.add_parser("spaces", help="設定済みスペース一覧 (API を叩かない)")
    s.set_defaults(func=cmd_spaces)

    s = sub.add_parser("mine", help="自分が担当者の課題一覧")
    add_list_opts(s)
    s.add_argument("--project", action="append", help="プロジェクトキーで絞り込み (複数可)")
    s.add_argument("--keyword", help="キーワード絞り込み")
    s.set_defaults(func=cmd_mine)

    s = sub.add_parser("created", help="自分が登録した課題一覧")
    add_list_opts(s)
    s.add_argument("--project", action="append", help="プロジェクトキーで絞り込み (複数可)")
    s.set_defaults(func=cmd_created)

    s = sub.add_parser("issue", help="課題の詳細")
    s.add_argument("key", help="課題キー (例 PROJ-123)")
    s.add_argument("--full", action="store_true", help="説明を全文出力")
    s.set_defaults(func=cmd_issue)

    s = sub.add_parser("comments", help="課題のコメント一覧")
    s.add_argument("key")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--order", default="desc", choices=["asc", "desc"])
    s.set_defaults(func=cmd_comments)

    s = sub.add_parser("notifications", aliases=["notify"], help="自分宛の通知一覧")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_notifications)

    s = sub.add_parser("projects", help="参加プロジェクト一覧")
    s.set_defaults(func=cmd_projects)

    s = sub.add_parser("statuses", help="プロジェクトの状態一覧 (statusId 確認用)")
    s.add_argument("project", help="プロジェクトキー")
    s.set_defaults(func=cmd_statuses)

    s = sub.add_parser("search", help="キーワードで課題検索")
    s.add_argument("keyword")
    add_list_opts(s, "all")
    s.add_argument("--project", action="append")
    s.add_argument("--assignee-me", action="store_true", help="自分担当のみ")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("comment", help="[書込] 課題にコメント投稿")
    s.add_argument("key")
    s.add_argument("text", help="本文 ('-' で標準入力)")
    s.add_argument("--yes", action="store_true", help="実行確認 (必須)")
    s.set_defaults(func=cmd_comment)

    s = sub.add_parser("update", help="[書込] 課題の状態などを更新")
    s.add_argument("key")
    s.add_argument("--status", help="状態名 (例 処理中) または statusId")
    s.add_argument("--comment", help="同時に付けるコメント ('-' で標準入力から読む)")
    s.add_argument("--assignee", help="担当者 (プロジェクト参加者の名前 または userId)")
    s.add_argument("--assignee-me", action="store_true", help="担当者を自分にする")
    s.add_argument("--due", help="期限日 yyyy-MM-dd")
    s.add_argument("--yes", action="store_true", help="実行確認 (必須)")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("create", help="[書込] 課題を新規作成")
    s.add_argument("summary", help="件名")
    s.add_argument("--project", help="プロジェクトキー (省略時は案件設定)")
    s.add_argument("--type", default="タスク",
                   help="種別名または id (既定: %(default)s)")
    s.add_argument("--priority", default="中",
                   help="優先度名または id (既定: %(default)s)")
    s.add_argument("--description", "-d", help="説明 ('-' で標準入力から読む)")
    s.add_argument("--assignee", help="担当者 (プロジェクト参加者の名前 または userId)")
    s.add_argument("--assignee-me", action="store_true", help="担当者を自分にする")
    s.add_argument("--milestone", help="マイルストーン名")
    s.add_argument("--category", help="カテゴリ名")
    s.add_argument("--due", help="期限日 yyyy-MM-dd")
    s.add_argument("--yes", action="store_true", help="実行確認 (必須)")
    s.set_defaults(func=cmd_create)

    s = sub.add_parser("raw", help="任意の API v2 エンドポイントを叩く")
    s.add_argument("path", help="例 /issues/count")
    s.add_argument("-q", "--query", action="append", help="key=value (複数可)")
    s.add_argument("-d", "--data", action="append", help="POST/PATCH 用 key=value")
    s.add_argument("-X", "--method", default="GET")
    s.set_defaults(func=cmd_raw)

    return p


def scrub(text):
    """文字列中の API キーをすべて伏せる。"""
    for _, k, _ in (_profiles or {}).values():
        if k:
            text = text.replace(k, "***")
    return text


def _excepthook(t, v, tb):
    """未捕捉例外のトレースバックから API キーを除去して出力する。"""
    sys.stderr.write(scrub("".join(traceback.format_exception(t, v, tb))))


def main():
    global _json_bucket, _pjcfg, _pjpath
    sys.excepthook = _excepthook
    a = build_parser().parse_args()
    if not hasattr(a, "json"):
        a.json = False

    if not a.no_project_config:
        _pjcfg, _pjpath = find_project_config()
    if _pjcfg:
        apply_project_config(_pjcfg)
        if not a.space and _pjcfg.get("space"):
            a.space = _pjcfg["space"]
        if not a.json and a.cmd not in ("spaces",):
            scope = "/".join(x for x in [_pjcfg.get("space"), _pjcfg.get("project")] if x)
            print(f"[案件設定: {scope}  ({_pjpath})]")

    if a.space and a.space.lower() == "all":
        if hasattr(a, "yes"):
            die("書き込みコマンドに --space all は使えません。--space <名前> で対象を明示してください。")
        profs = load_profiles()
        if a.json:
            _json_bucket = []
        for idx, name in enumerate(profs):
            select_profile(name)
            if not a.json:
                if idx:
                    print()
                print(f"########## [{name}] {profs[name][0]} ##########")
            try:
                a.func(a)
            except SystemExit as e:
                if e.code:
                    print(f"  (スペース {name} はエラーのためスキップ)", file=sys.stderr)
        if _json_bucket is not None:
            print(json.dumps(_json_bucket, ensure_ascii=False, indent=2))
        return

    select_profile(a.space)
    a.func(a)


if __name__ == "__main__":
    main()
