# t4-connection

TSUBAME4の計算ノードで code-server とユーザー権限の sshd を起動し、Mac / Linux / WSL から接続する Bash スクリプト集。
起動用PCと接続用PCは別でも使えます。各PCで同じTSUBAMEアカウントへのSSH接続を設定してください。

## 構成

- `local/`: PC側。ジョブ起動、SSH接続、ブラウザ用転送、リモート配置。
- `remote/`: TSUBAME側。既に確保した計算ノードでサーバーを起動。
- `lib/`: 共通設定と状態ファイル管理。
- `config.example`: 公開可能な設定例。個人設定はリポジトリ外へ保存。
- `skills/t4-connection/`: coding agent向けの運用手順。
- `docs/scrapbox.txt`: Scrapboxに貼り付ける説明。

通常実行にはBash 3.2以降、OpenSSH、基本的なUnixコマンドを使います。配置にはtar、テストにはPython 3が必要です。
ブラウザ版を使う場合だけ、TSUBAMEにcode-serverを別途導入してください。sshdは `/usr/sbin/sshd` を使います。

## 初回設定

PCで:

```bash
git clone https://github.com/YumizSui/t4-connection.git
cd t4-connection
mkdir -p ~/.config/t4-connection
cp config.example ~/.config/t4-connection/config
chmod 600 ~/.config/t4-connection/config
```

`~/.ssh/config` に接続先を設定します。ユーザー名は自分のものに変更します。

```sshconfig
Host tsubame4
    HostName login.t4.gsic.titech.ac.jp
    User YOUR_USERNAME
    IdentityFile ~/.ssh/id_ed25519
```

`T4_LOGIN` で別のSSH aliasも指定できます。configはBashとして読み込むので、自分で管理するファイルを指定します。
`T4_CONFIG` で設定ファイルの場所を変更できます。

```bash
./local/deploy
```

配置先はTSUBAMEの `~/.local/share/t4-connection/` です。`lib/`、`remote/`、設定例だけを転送し、個人設定・秘密鍵・Git履歴は転送しません。`~/.local/bin/` に `start-session`・`start-user-sshd`・`start-code-server` の入口も作成します。TSUBAME側でも `~/.local/bin` をPATHに含めてください。再実行でスクリプトと入口を更新できます。実行中のサーバーは自動再起動しません。

TSUBAMEで `~/.config/t4-connection/config` を作ります。

```bash
mkdir -p ~/.config/t4-connection
cp ~/.local/share/t4-connection/config.example ~/.config/t4-connection/config
chmod 600 ~/.config/t4-connection/config
```

`T4_CODE_SERVER` にcode-server実行ファイルの絶対パスを指定します。PATHにある場合は不要です。
ポートは `T4_CODE_PORT` と `T4_SSH_PORT` を利用可能な1024–65535の値に設定します。同じノードで競合した場合は次の番号を順に試します。既定では指定番号から最大20ポート、65535までを試し、競合以外の起動エラーでは停止します。`T4_PORT_ATTEMPTS`（1–100）で試行数を変更できます。
ポート番号は認証情報ではありません。公開サンプルには既定値だけを含めます。

sshd用に、接続する各PCの公開鍵をTSUBAMEの `~/.ssh/authorized_keys` に登録してください。
sshdは公開鍵認証のみ、code-serverはパスワード認証で起動します。code-serverの初回起動時に生成される `~/.config/code-server/config.yaml` でパスワードを確認し、ファイル権限を600にしてください。

## PCのPATHに導入

```bash
./local/install
```

スクリプトを `~/.local/share/t4-connection/` にコピーし、4つのコマンドを `~/.local/bin/` に作ります。更新時も再実行します。既存コマンドは `*.before.*` にバックアップします。
`~/.zshrc`（Mac）または `~/.bashrc`（WSL）に `export PATH="$HOME/.local/bin:$PATH"` を追加してください。同名の古いaliasや関数がある場合はバックアップ後に削除し、新しいシェルを開きます。以後 `t4-start`、`t4-shell`、`t4-forward`、`t4-ssh-config` を直接呼べます。

## 起動と接続

以下はPATH設定済みの環境で実行します。repoのディレクトリへ移動する必要はありません。

```bash
t4-start
```

引数は省略でき、既定は20時間・sshdのみです。VS Code / CursorのRemote SSHで `t4-compute` に接続できます。PCの `~/.config/t4-connection/config` で省略時の動作を変更できます。

```bash
T4_START_HOURS=20
T4_START_SERVICE=sshd  # sshd / code-server / both
```

コマンドラインで指定した引数は、この設定より優先します。時間だけを指定した場合、サービスは設定値を使います。

```bash
t4-start 1              # 1時間、サービスは設定値（既定sshd）
t4-start 1 sshd         # 設定によらずsshdのみ
t4-start 1 both         # sshdとcode-serverの両方
t4-start 1 code-server  # code-serverのみ
t4-start --dry-run      # 起動せず実行内容を確認
```

以前のように両方を既定にするには `T4_START_SERVICE=both` を設定してください。設定は起動するPCごとに読みます。
実行時間は1–24時間です。時間制限はスケジューラの `h_rt` で設定し、割当待ち時間は含みません。
`both` / `code-server` では起動したPCへのSSH転送も自動で開始し、ブラウザ用URLを表示します。PC側のポートは既定8890（`T4_LOCAL_PORT`で変更可能）です。`sshd` のみでは転送しません。
起動用ターミナルは開いたままにし、Ctrl-Cで終了します。片方が終了した場合はもう片方も停止します。

起動したPCでは表示されたURLをそのまま使えます。別PCから接続する場合は:

```bash
t4-shell
t4-forward
# ローカルの8890番が使用中なら:
t4-forward 8892
```

`t4-forward` が表示する `http://127.0.0.1:ポート` をブラウザで開き、code-serverのパスワードでログインします。
リモート側が例えば8891に変わっても、PC側は `localhost:8890 → 計算ノード:8891` のように8890のまま転送します。PC側の競合では自動変更せず、上のようにポートを明示します。
転送はローカルのloopbackだけにバインドします。手動転送の終了はCtrl-Cです。自動転送は起動用ジョブの接続終了とともに閉じます。自動転送がポート競合などで失敗した場合はジョブを維持するため、別ターミナルで `t4-forward 8892` などを実行できます。
sshdの初回接続時には、起動ログに表示されたホスト鍵fingerprintと照合してください。

接続先はTSUBAMEホームの `~/.local/state/t4-connection/{sshd,code-server}` から取得します。
ホスト名・ポート・ユーザー名を保存し、パスワードは保存しません。別PCでポートを同期する必要はありません。
サーバー自身の待受開始ログを確認してから状態ファイルを公開します。起動確認の待ち時間は既定30秒、`T4_STARTUP_TIMEOUT`（1–300秒）で変更できます。起動ログは同じディレクトリの `<service>.log` に保存し、起動試行ごとに更新します。
サービスごとに同時起動は1つです。状態ファイルは接続先の案内であり、接続成功による稼働確認とは別です。

## VS Code / CursorからRemote SSHで接続

PCで `local/install` を実行すると、`~/.ssh/config` に `Host t4-compute` を登録します。VS Code / CursorのRemote SSHで `t4-compute` を選んでください。SSH Targetsにも同じ名前で表示されます。GUIはPCで、エディタのサーバーやターミナルは割当済み計算ノードで動きます。ログインノードはSSHの踏み台としてのみ使います。code-serverやRemote Tunnelsは不要です。

接続のたびに `ProxyCommand` がTSUBAME側のsshd状態ファイルを読み、最新のノード・ポートへ中継します。別PCで `t4-start` した場合や、手動割当内でsshdを起動した場合も、接続先設定の再更新は不要です。接続する各PCには、このバージョンの `local/install` を一度実行してください。

既存の静的な設定を移行する場合や、SSHアカウントを変更した場合は次を実行します。登録時に計算ノードを起動しておく必要はありません。

```bash
t4-ssh-config
```

更新するのはファイル先頭の専用コメントで囲んだブロックだけで、変更前の設定は `~/.ssh/config.before-t4.*` にバックアップします。管理ブロック外の `Host t4-compute` がある場合、またはconfigがsymlinkの場合は上書きせずエラーを表示します。`t4-start` のsshd起動時にも登録を確認し、登録に失敗してもジョブは継続します。

計算ノードの割当が終わると接続できなくなります。別の割当へ切り替えたら、エディタの接続を閉じて同じ `t4-compute` へ再接続してください。開いている接続の自動移行はしません。状態ファイルがない場合や不正な場合は接続を中止します。状態ファイルが残っていてもサービスが停止済みなら接続は失敗します。

ホスト鍵は安定した名前 `t4-compute` で照合します。計算ノードが変わっても同じユーザーsshd鍵を使うため、通常は再確認不要です。静的設定からの移行後は初回のホスト鍵確認が出ることがあります。起動ログのfingerprintと照合してください。ホスト鍵の検証を無効にする設定は追加しません。

## 既存の割当を確認する

AIによる再利用判断は [skill](skills/t4-connection/SKILL.md#起動済みかを判断するai向け) を参照してください。`iqstat` と `qstat` の両方を確認し、状態ファイルのジョブID・ノードと照合します。`qrsh -g` で確保した通常キューの割当も対象です。利用可能なサービスがあれば再利用し、不要な二重確保を避けます。

## 手動で確保したノードで起動

```bash
# TSUBAMEのログインノードで:
iqrsh -l h_rt=1:00:00
# 割当後の計算ノードで、必要なものを1つ選ぶ:
start-user-sshd
start-code-server
start-session
```

通常キューで `qrsh -g <group> -l <resource>=1 -l h_rt=<time>` により確保した割当内でも、同じremoteスクリプトを使えます。`t4-start` 自体はiqrsh用です。

各サーバーは前面で動きます。個別に2つ起動する場合は、同じ割当内の別ターミナルを使ってください。
`JOB_ID` と計算ノード名を確認し、ログインノードでの誤起動を防ぎます。
`t4-shell` は通常のSSHログイン環境です。元のiqrshの環境変数やmodule設定をそのまま複製するものではありません。

## 既存環境からの移行

1. 既存のスクリプト、symlinkの実体、稼働中ジョブ、ポート、ホスト鍵の場所を確認します。
2. `local/deploy` で専用ディレクトリに配置します。共有領域のcode-server本体や起動スクリプトは変更しません。
3. TSUBAME側のconfigで既存のポートを設定します。既存のユーザーsshd鍵を再利用する場合は `T4_SSHD_DIR="$HOME/.ssh/user-sshd"` のように指定します。
4. 既存サーバーと競合しない状態で新しい起動・接続を検証します。
5. `~/code_server` などの旧入口はバックアップし、新しいremoteスクリプトへのwrapperに切り替えます。

コマンドの入口は `local/` と `remote/` です。個人設定や秘密情報はリポジトリ外で管理してください。

## 停止と復旧

通常終了では子プロセスと状態ファイル・ロックを片付けます。
強制終了やノード障害ではロックが残ることがあります。`~/.local/state/t4-connection/<service>.lock/owner` にノード・ジョブID・PIDが記録されています。
`iqstat` / `qstat` と対象ノードのプロセスを確認し、サービスが停止済みの場合だけ、そのサービスの状態ファイルとlockディレクトリを削除して再起動します。

SSH転送は共有ControlMasterから独立しており、転送失敗やCtrl-Cで既存のSSH masterを終了しません。
利用者の他のジョブを止める `qdel` や、master全体に対する `ssh -O exit` は実行しません。

## 開発

```bash
python3 -m unittest discover -s tests -v
```

coding agent向けskillは `skills/t4-connection/` にあります。導入・更新・移行の手順は [installation.md](skills/t4-connection/references/installation.md) を参照してください。

## 参照

- [TSUBAME4 ジョブとインタラクティブ利用](https://www.t4.cii.isct.ac.jp/docs/handbook.ja/jobs/)
- [code-server 設定](https://coder.com/docs/code-server/FAQ)

インタラクティブ専用キューは対話的な用途向けです。連続的に計算資源を占有する処理は適切な通常キューのジョブへ分けてください。
