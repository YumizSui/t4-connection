# インストール・更新・移行

初回導入、スクリプトの更新、既存環境からの移行時に読む。
実装repoは https://github.com/YumizSui/t4-connection 。既にcheckoutがあればそれを使い、具体的な設定例はそのREADMEを参照する。

## 初回導入

1. 起動用PCと接続用PCそれぞれで、TSUBAMEへのSSH aliasと公開鍵認証を確認する。別PCを使う場合も接続先アカウントを揃える。
2. 各PCで実装repoの `config.example` を `~/.config/t4-connection/config` にコピーし、`T4_LOGIN` を設定する。既存configがあれば上書きせず差分を確認する。configはBashとして読み込むため、自分で管理するファイルを使う。
3. 実装repoの `local/install` を実行する。配置先は `~/.local/share/t4-connection/`、コマンドの入口は `~/.local/bin/`。シェル設定でPATHを通し、同名の古い関数・aliasが優先されないことを確認する。既存設定を変更する前にバックアップする。
4. PCの `local/deploy` で `lib/`、`remote/`、設定例をTSUBAMEの `~/.local/share/t4-connection/` に配置する。`start-session`・`start-user-sshd`・`start-code-server` の入口も `~/.local/bin/` に作成される。TSUBAME側でもこのディレクトリをPATHに含める。
5. TSUBAME側の `~/.config/t4-connection/config` に `T4_CODE_SERVER`、`T4_CODE_PORT`、`T4_SSH_PORT` を設定する。code-server本体の導入は別途必要。
6. 接続する各PCの公開鍵をTSUBAMEの `~/.ssh/authorized_keys` に登録する。code-serverのパスワード設定ファイル `~/.config/code-server/config.yaml` は権限600で管理する。秘密情報をrepoへコピーしない。

## 既存環境からの移行

- 稼働中ジョブ、ポート、起動スクリプト、ホスト鍵の場所を確認する。
- ホームの起動スクリプトがsymlinkの場合は共有領域の実体を上書きしない。新しいスクリプトは専用ディレクトリへ配置し、ホーム側の入口をバックアップして切り替える。
- 既存ユーザーsshdの鍵は `T4_SSHD_DIR` で引き継ぐ。個人設定はconfigへ移し、旧 `env` は読み込まない。
- 稼働中サービスと競合しない条件で新しい起動・接続を確認してから、旧入口を切り替える。

## 更新と確認

- 各PCで更新した実装repoの `local/install` を再実行する。TSUBAME側は `local/deploy` で更新する。個人設定は保持し、稼働中サービスの再起動は別の操作として扱う。
- 新しいシェルで `command -v t4-start t4-shell t4-forward` と `t4-start --dry-run 1 both` を確認する。
- 必要なスモークテストではSSHログイン、HTTPの認証画面、別PCからの接続、終了後の状態ファイルを確認する。検証用ジョブIDを記録し、検証後はそのジョブを終了する。
