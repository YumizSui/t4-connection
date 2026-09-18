# Remote SSHでのVS Code / Cursorの実運用

対象は `t4-compute` 経由で確保済み計算ノードに接続するエディタ。GUIはPC、エディタサーバー・拡張ホスト・検索プロセスは計算ノードで動かす。ログインノードでは常駐させない。以下は利用機能に合わせて選ぶ設定であり、接続するだけで一括適用するものではない。

## 複数ディレクトリで使う設定の置き場所

- ディレクトリを変えても使う設定はエディタのUser設定へ置く。TSUBAME接続だけに限定したい場合はRemote設定を検討する。ローカルUser設定の変更は他の接続先やローカル編集にも影響する。
- フォルダ固有の例外は `.vscode/settings.json`、複数フォルダのワークスペースは `.code-workspace` の設定も確認する。User → Remote → Workspace → Workspace Folderなどの上書きと設定ごとの適用可能範囲を、設定画面で確認する。
- 現在のウィンドウのSSH接続先・開いているフォルダ・symlinkの実体を確認する。別フォルダへ移った後も以前のWorkspace設定が効くと考えない。
- 編集前に設定をバックアップし、JSONCのコメントと既存キーを保持して必要なキーだけ変更する。設定変更とエディタの再読み込みは分け、再読み込みが必要なら対象ウィンドウと未保存内容を確認する。

## 検索範囲を抑える共通設定例

多数の生成物や依存環境を含むディレクトリでは、まずignoreを尊重する設定を確認する。既存の `search.exclude` は置き換えずマージする。

```json
{
  "search.useIgnoreFiles": true,
  "search.useParentIgnoreFiles": true,
  "search.useGlobalIgnoreFiles": true,
  "search.followSymlinks": false,
  "search.exclude": {
    "**/.venv/**": true,
    "**/.pixi/**": true,
    "**/.cache/**": true,
    "**/__pycache__/**": true,
    "**/node_modules/**": true,
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true
  }
}
```

ignoreや除外に該当するファイルは検索・Quick Openの候補に出なくなることがある。直接開く操作とは区別する。除外領域の編集やsymlink先の検索が必要なプロジェクトでは、そのフォルダで必要な例外を設ける。`data`、`runs`、`output`や個人の研究ディレクトリを共通設定で一律に除外しない。

Cursorでは、インストール済みバージョンに存在することを確認して `"search.quickOpen.useVscodeSearch": true` を試せる。VS Code標準のQuick Open検索方式を選ぶCursor固有設定であり、VS Codeへそのまま追加しない。高速化やメモリ増加解消を保証する設定ではない。

検索除外・ファイル監視除外・CursorのAI向けignoreは用途が異なる。監視が負荷源なら `files.watcherExclude` に対象の生成物を限定して追加する。`"**": true` で監視を全面停止する設定は共通設定にしない。`.cursorignore` はAIが利用するファイルにも影響するため、検索除外の代用品として機械的に追加しない。

## 自動検出は利用機能に合わせる

| 設定候補 | 適用する状況と影響 |
| --- | --- |
| `"npm.autoDetect": "off"` | npmスクリプトの自動検出を使わない場合。広いフォルダでのpackage.json探索を抑えるが、自動検出されるタスクも減る。 |
| `"git.autoRepositoryDetection": "openEditors"` | 子ディレクトリのリポジトリ自動探索を抑えたい場合。開いたファイルに応じた検出は残る。ルートリポジトリのstatus実行を停止する設定ではない。 |
| `"git.enabled": false` | 巨大な親フォルダでGit処理が負荷源と確認できた場合、そのWorkspaceだけで検討する。Gitのエディタ連携が無効になるためUser全体には広げない。 |

実際の作業リポジトリを開けば、親フォルダにだけ置いた設定は通常そのWorkspace設定としては継承されない。Gitを必要とする各プロジェクトで連携が使えることも確認する。

## 遅延・メモリ増加を特定する

1. 対象ウィンドウ、フォルダ、接続先、拡張ホストPIDを対応付ける。2つ以上のウィンドウがある場合は別々に記録する。再接続後はPIDを確認し直す。
2. 同じフォルダ・同じ相対パスのQuick Openについて、入力から候補表示までと、選択からファイル表示までを分けて計測する。SSHの通信速度表示だけで検索性能を判断しない。
3. 計算ノードで対象PIDのRSS・CPU・経過時間と子プロセスの引数・作業ディレクトリを確認する。長時間の `rg --files --no-ignore`、package.json探索、`git status -z -uall` など、実際に走っている処理を特定する。
4. Cursorのルール・AI用探索は通常の検索設定とは別に動く場合がある。`search.followSymlinks: false` や検索除外を設定していても、子プロセスが `--follow` で走っていないか確認する。未確認の設定キーを作らない。
5. 必要なら対象拡張ホストのCPUプロファイルと割当サンプリングを取得する。検索結果のstdout解析でメモリが増える場合もあり、プロセス名が拡張ホストだからといって特定の拡張機能の不具合とは断定しない。

過去の調査では、大量のファイル列挙中にstdoutのデコード・行分割へ割当が集中し、対象検索の停止後に短時間のRSS増加が止まった。これは探索範囲を調べる根拠であり、すべての切断原因や特定拡張のメモリリークを証明するものではない。

プロファイル取得は既存割当の計算ノードで行う。Inspectorを使う場合は対象PIDを確認し、loopbackで一時的に開いて取得後に閉じ、接続不能になったことも確認する。プロファイルには個人のパスなどが含まれ得るため公開資料へコピーしない。フルheap snapshotは停止時間とメモリ負荷が大きく、最初の手段にしない。検索を取り消す場合も親PID・引数・作業ディレクトリを照合し、研究計算や他のウィンドウを巻き込まない。

## 放置中の切断を切り分ける

- **割当終了**: ジョブ状態と `h_rt` を確認する。時間制限で計算ノードを使えなくなった状態はSSH keepaliveでは直らない。
- **SSH経路**: 切断直後に `ssh t4-compute hostname` などの短い接続確認と `ssh -G` の実効設定を確認する。接続維持設定を変える前に、エディタだけの切断かSSH自体の切断かを分ける。共有masterをまとめて終了しない。
- **エディタサーバー・拡張ホスト**: ローカルのRemote SSH出力と、Cursorなら `~/.cursor-server/data/logs/<session>/remoteagent.log`、`exthost*/remoteexthost.log` を時刻で照合する。VS Codeでは対応する `.vscode-server` 側のログを確認する。
- `heap out of memory`、SIGABRT、拡張ホスト終了、その後のサーバーのidle shutdownを区別する。SSHと割当が生きていても、拡張ホストの異常終了を起点に接続不能になる場合がある。
- RSSとJavaScriptヒープ使用量・上限は別物。RSSが4GBを超えたという数字だけでOOMや原因を断定せず、メモリ上限の引き上げだけを恒久対策にしない。

検証は同じ条件で変更前後を比較し、以前に問題が再現した程度の時間と通常の操作を含める。再起動直後の低いRSSや数十秒の横ばいだけで「解消」としない。複数フォルダで使う場合は、別プロジェクトでも検索・Gitなど必要な機能が残ることを確認し、未検証の範囲を明示する。

## 効果音の調整

接続の性能設定とは分けて扱う。ユーザーが止めたい音を確認し、対応する `accessibility.signals.terminalBell`、`terminalCommandSucceeded`、`terminalCommandFailed`、`clear` などのsoundだけを調整する。進捗音を残したい場合は `accessibility.signalOptions.volume` の全体ミュートを使わない。接続やチャットの進捗音と、Codex・Claude Codeのユーザー入力待ち通知は同じものとは限らず、個別に発生元を確認する。
