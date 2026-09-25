# エラー処理とログ

この文書は、APIのエラー応答の形、stream中のエラー、ログに出すものと出さないものを決めます。エラーを返す
処理やログを追加するときに読みます。秘密値の扱い全体は[セキュリティ](security.md)を参照してください。

## エラー応答の契約

APIのエラー応答はRFC 9457（Problem Details）互換のJSONに揃えます。組み立ては
`apps/api/core/error_contract.py`が行い、routerは例外を投げるだけにします。

| field | 内容 |
|---|---|
| `type`、`title`、`status`、`detail` | Problem Detailsの基本の項目。`detail`は利用者に見せてよい文言 |
| `code` | 機械が読む分類。付く場合だけ含まれる |
| `errors` | 入力検査の失敗の一覧。各項目は`pointer`（JSON Pointer）と`code`だけを持つ |
| `request_id` | 相関のためのID。応答headerの`X-Request-ID`と同じ値 |

- 入力検査の失敗は422、`HTTPException`はそのstatus、想定外の例外は500にします
- `HTTPException`の`detail`に`{"error_code": ..., "message": ...}`を渡すと、`error_code`が`code`になります
- 応答には、受け取った入力値、pydanticの生のmessage、例外の本文を入れません。入力をそのまま返すと、
  秘密値が応答に混ざるおそれがあるためです
- clientは`status`でHTTPの結果を判断し、`code`からstatusを推測しません

## streamの途中のエラー

- stream（SSE）を返し始めた後の例外は、HTTPのstatusでは返せません。agentの例外はAI SDKの`error` partに
  変わってclientへ届きます
- 例外はrunの記録に`failed`として残します。記録する文字列は長さを制限し、DBに入らない文字を置き換えます
- ブラウザの切断はrunを`running`のまま残します。切断を失敗として記録しません

## providerのエラー

- providerの接続失敗や上限の超過もstream中のエラーとして扱い、runを`failed`にします。記録するのは例外の
  型名と、長さを制限した本文です
- 選んだprofileのcredentialが無いときは、providerへrequestを送る前に503（`chat_profile_unavailable`）を
  返します。どのenvが欠けているかは応答に含めません

## webでのエラーの表示

- 中継（`apps/web/src/lib/chat-relay.ts`）は、FastAPIの失敗応答から`code`だけを読み、固定の文言に
  置き換えて返します。`detail`、`errors`、`request_id`は画面に渡しません
- 画面は、中継が返した文言だけを表示します。対応は`apps/web/src/lib/chat-profiles.ts`にあります

## request IDによる追跡

- APIは、requestの`X-Request-ID` headerを引き継ぐか、無ければ新しく作ります。応答header、エラー応答、
  ログ、runの記録に同じIDを載せます
- 利用者から報告を受けたときは、エラー応答の`request_id`でAPIのログとrunの記録を探します

## 構造化ログ

- APIは`apps/api/core/logging.py`のstructlogでJSONを1行ずつ標準出力に出します。event名を第1引数、値を
  `extra`で渡します
- webのserver側は`apps/web/src/lib/logger.ts`のpinoでJSONを出します。値をobject、event名を文字列で
  渡します
- 1回のrequestで何が起きたかを、request IDとevent名で追えるように出します。起動と終了、profileの解決、
  想定外の例外はすでにログに出しています

## ログに出さないもの

- 秘密値（API key、password、token、接続文字列）
- 会話の本文、toolの入力と出力、requestとresponseのbody
- 設定の値そのもの。設定の誤りは、keyの名前とfile名だけを出します

webのloggerは、名前が秘密値を表すkey（`password`、`token`など）の値を伏せます。伏せる規則は
`apps/web/src/lib/logger.ts`が正本です。APIでは、例外を記録するときに型名だけで足りるかを先に考えます。
想定外の例外のログには例外の本文が含まれるので、例外のmessageに秘密値を入れないようにします。
