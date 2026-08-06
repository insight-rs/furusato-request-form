# クラウドフォーム運用

クラウドでは `cloud_app.py` を起動し、固定PC専用のTSV取得・OTP・Playwright処理は実行しません。

## ログイン方式

Googleアカウントを持たない社外利用者にも対応するため、Auth0のUniversal Loginを使用します。
利用者はメールアドレスと、自分で設定したパスワードでログインします。ログイン時のメールOTPは使用しません。
パスワードはAuth0が管理し、アプリやGoogleスプレッドシートには保存しません。

公開URLはインターネットから到達可能ですが、認証が完了するまでフォームや商品情報は表示されません。
Google Sitesへ埋め込む方式はStreamlit認証の対象外になるため、Google Sitesを使う場合はアプリへのリンクを掲載します。

## 必須の秘密情報

- `GOOGLE_SERVICE_ACCOUNT_JSON`: GoogleサービスアカウントJSON全文

## 任意の環境変数

- `CONFIG_SPREADSHEET_ID`
- `PRODUCT_SPREADSHEET_ID`
- `REQUEST_UPLOAD_DIRECTORY`
- `REVISION_EXPORT_DIRECTORY`

Backlogの接続情報は現在の設定スプレッドシートから読み込みます。クラウドの実行環境には、設定・商品スプレッドシートを読み書きできるGoogleサービスアカウントを設定してください。

## 推奨：Streamlit Community Cloud

1. このフォルダを非公開GitHubリポジトリへ登録します。
2. Streamlit Community Cloudで `cloud_app.py` を指定してアプリを作成します。
3. Auth0でRegular Web Applicationを作成し、Database Connection（メールアドレス・パスワード）を有効にします。
4. Auth0のAllowed Callback URLsとAllowed Logout URLsへ、StreamlitアプリのURLを登録します。
5. Advanced settings の Secrets に次を登録します。

```toml
GOOGLE_SERVICE_ACCOUNT_JSON = '''
{GoogleサービスアカウントJSON全文}
'''

[auth]
redirect_uri = "https://APP_NAME.streamlit.app/oauth2callback"
cookie_secret = "十分に長いランダム文字列"

[auth.auth0]
client_id = "Auth0のClient ID"
client_secret = "Auth0のClient Secret"
server_metadata_url = "https://YOUR_AUTH0_DOMAIN/.well-known/openid-configuration"
client_kwargs = { prompt = "login" }
```

6. Community Cloud上は公開アプリとして動かし、アプリ内のAuth0認証でアクセスを制御します。

ローカル確認時だけ認証を迂回する場合は、起動前に `APP_AUTH_BYPASS=true` を設定します。この環境変数はクラウドには設定しません。

将来はログインメールアドレスと自治体IDの対応表をGoogleスプレッドシートで管理し、利用者ごとに選択・閲覧できる自治体を制限します。

秘密情報、ローカルTSV、添付ファイル、実行ログは `.gitignore` でGitHubへの登録対象外にしています。

## Cloud Runを利用する場合

```text
docker build -t furusato-form .
docker run --rm -p 8080:8080 -e GOOGLE_SERVICE_ACCOUNT_JSON="..." furusato-form
```

本番公開時はAuth0の接続情報を必ず設定し、ローカル用の認証迂回環境変数を設定しないでください。
