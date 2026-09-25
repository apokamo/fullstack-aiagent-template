# セキュリティ

この文書は、秘密値の置き場所、ログとartifactの扱い、browserに渡さないもの、書き込みtoolの承認、認証を
足すときの方針を決めます。設定、ログ、tool、APIを追加するときに読みます。エラー応答とログの形は
[エラー処理とログ](error-handling-and-logging.md)を参照してください。

## 秘密値の置き場所

- 秘密値は`secrets/*.env`に置きます。directoryは700、fileは600にし、gitに入れません。雛形は
  `make env-secrets-template`で作り、`make env-secrets-check`で権限と必須のkeyを値を表示せずに確かめます
- rootの`.env`には秘密でない設定だけを置きます。何をどのfileに置くかは`.env.example`の先頭が正本です
- provider credentialのenv名は、`apps/api/core/llm_profiles.py`のprofileが決めます
- コードとテストに秘密値を書きません。テストの値は、実在しない値だと分かる形にします

## commit前の検査

- pre-commitのgitleaksが、stageした変更に秘密値が含まれていないかを検査します。導入は
  [開発環境](../howto/development-environment.md)を参照してください
- 検出されたら、値をcommitから外し、漏れた可能性がある値は無効にして作り直します

## ログ、artifact、evalの扱い

- ログに秘密値、会話の本文、接続文字列を出しません。詳細は
  [エラー処理とログ](error-handling-and-logging.md#ログに出さないもの)を参照してください
- runの記録には会話を保存します。DBの接続はSQLのbind parameterをログに出さない設定にしています
- evalの観測と採点の証跡は、URL、認証情報の形をした文字列、指定した秘密値を伏せてから保存し、ジャッジに
  渡します。規則は`apps/api/agent/evals/privacy.py`が正本です
- lane recordとeval artifactには、profileの名前と接続先の表示用の値だけを残し、credentialは残しません

## browserに渡さないもの

- provider credential、providerの接続先、内部のservice URL
- FastAPIのエラー応答の`detail`と`errors`。webの中継が固定の文言に置き換えます
- browserはFastAPIを直接呼ばず、Next.jsのRoute Handlerを経由します

## HTTPの設定

- CORSで許可するoriginは`ALLOWED_ORIGINS`で設定します。security headerは`apps/api/core/security.py`が
  付けます
- APIのschemaとdocsの画面は、`DEBUG`が有効なときだけ公開します

## 書き込みtoolの承認

- 書き込みや外部への副作用を伴うtoolは`mutates=True`で登録し、利用者が承認するまで実行しません
- 承認はrequestごとの判断です。承認を省く設定や、一度の承認で以後のtoolをまとめて許す仕組みを足す場合は、
  その影響を設計で決めます

## 認証を足すときの方針

テンプレートは認証を持ちません。公開する前に認証を足します。

- 利用者のsessionはNext.jsの側で持ちます。FastAPIとは、browserに渡さない内部のtokenでつなぎます。
  差し込み口は`apps/web/src/lib/chat-relay.ts`です
- 会話はclientが送る履歴で動かしています。保存した会話を読み出す機能は、認証と、会話の所有者の確認を
  足してから作ります。`client_chat_id`はclientが決める値なので、所有者の確認には使えません

## 依存の更新

- 依存はlockfile（`uv.lock`、`package-lock.json`、`apps/web/package-lock.json`）で固定します。更新したら
  `make check-all`と`make test-e2e`を実行します
- pre-commitのhookとcontainerのimageも、同じように定期的に更新します
