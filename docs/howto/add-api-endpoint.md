# APIのendpointの追加

この文書は、FastAPIにendpointを追加し、webから呼べるようにする手順を示します。

前提として、[アーキテクチャ](../architecture.md)と
[エラー処理とログ](../reference/error-handling-and-logging.md)を読んでおいてください。

## 1. routerを書く

用途に依存しないendpointは`apps/api/agent/`か`apps/api/core/`に、サンプル固有のendpointは
`apps/api/sample/`に置きます。

```python
router = APIRouter(prefix="/api", tags=["orders"])


@router.get("/orders/{order_id}")
async def read_order(order_id: str) -> OrderResponse:
    """注文を1件返す."""
    ...
```

- requestとresponseはpydanticのmodelで型を付けます。responseに秘密値や内部のURLを含めません
- 利用者の入力が原因の失敗は`HTTPException`で返し、機械が読む分類が要る場合は
  `detail={"error_code": ..., "message": ...}`を渡します。応答の形は共通のhandlerが揃えます
- DBやmodelなどのresourceは、requestの中で作らず、runtimeから取ります（`runtime_of(request)`）

## 2. applicationに登録する

`apps/api/application.py`の`create_app()`で`app.include_router(...)`を呼びます。共通部分から`sample/`の
routerを読むのは`application.py`だけにします。

## 3. webから呼ぶ

browserからFastAPIを直接呼ばず、Next.jsのRoute Handlerを経由します。

- `apps/web/src/app/api/<path>/route.ts`を作り、`apps/web/src/lib/chat-relay.ts`の中継関数を使います。
  JSONを返すGETは`relayJsonGet`、streamを返すPOSTは`relayChatStream`が例です
- 中継はFastAPIの失敗応答をそのまま画面へ渡さず、固定の文言に置き換えます

## 4. テストを書く

- APIは`TestClient`（Small）か`httpx.AsyncClient`と`ASGITransport`（Medium）で呼び、status、応答の形、
  エラー応答の`code`と`request_id`を確かめます
- Route Handlerは、FastAPIの応答を差し替えたVitestで、中継の規則（成功時の素通し、失敗時の固定文言）を
  確かめます。`apps/web/src/app/api/chat/route.test.ts`が例です

## 確認

```sh
make check-all
```

画面から使う場合は`make test-e2e`も実行します。
