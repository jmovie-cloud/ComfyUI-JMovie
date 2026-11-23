# JMovie API contract for ComfyUI

The plugin defaults to `https://api.j-movie.com`. For local development, set `JMOVIE_CLOUD_BASE_URL` to a compatible HTTPS origin or an HTTP loopback origin. The local smoke test uses synthetic accounts and media.

## Device authorization

The client ID is `jmovie-cloud`. The browser signs in at `/comfy/authorize`, where the user enters the visible code and approves wallet-funded generation. The ComfyUI process keeps the resulting grant in memory. The browser shows active connections and can revoke them on the same page. [Device authorization](https://www.rfc-editor.org/rfc/rfc8628) · [Token revocation](https://www.rfc-editor.org/rfc/rfc7009)

| Request under `/api/v1/comfy` | Contract |
| --- | --- |
| `POST /oauth/device/code` | Form fields `client_id` and `scope`. Returns `device_code`, `user_code`, same-origin `verification_uri`, and integer `expires_in` and `interval` in seconds. |
| `POST /oauth/token` | Form fields `client_id`, `device_code`, and `grant_type=urn:ietf:params:oauth:grant-type:device_code`. Successful exchange is single-use and returns `access_token`, `token_type`, `scope`, stable `account_id`, and `expires_in`. Pending, slowdown, denial and expiration use HTTP 400 OAuth errors. |
| `GET /connection` | Active plugin grant required. Invalid, expired and revoked grants return 401. |
| `POST /oauth/revoke` | Form fields `client_id` and `token`. Returns 204 for a valid request, including an already revoked token. |

The grant lasts 24 hours and covers `audio:generate image:generate tasks:read video:generate`. It is scoped to plugin generation and task retrieval for the approving API account.

## Wallet and generation

| Request under `/api/v1/comfy` | Contract |
| --- | --- |
| `POST /tasks` | Bearer grant and a 64-character lowercase hex `Idempotency-Key`. Returns 202 with `id`, `kind`, and `status`. The same key and inputs return the original task for the account, including after reconnecting. |
| `GET /tasks/{id}` | Bearer grant. Returns `id`, `kind`, `status` (`queued`, `running`, `succeeded`, `failed` or `expired`) and `expires_at`, once known. |
| `GET /tasks/{id}/result` | Bearer grant. Once settled, returns either `{"url":"…"}` with the original supplier HTTPS link or `{"base64":"…"}` with original inline output. Returns 410 after expiration. |

Send `kind`, `model`, and `prompt`. Image and video can attach PNG data URIs as `images`, with a `role` and `data` for each image. Video additionally accepts `resolution`, `ratio`, integer `duration`, and `generate_audio`. Audio uses `seed-audio-1.0` with a target duration of 1–120 seconds. Its target is a prompt hint. The API reserves for the model's maximum and settles by the supplier's `original_duration`. The API applies its existing account rates, balance reservations, and usage settlement. **MiniMax H3** settles the supplier’s generated seconds at the chosen resolution plus reference images beyond the first five. Hosted **GPT Image 2, 2.5 Flare, and 2.5 Sunburst** use the official Images API at 1024×1024, medium quality, and settle the returned text input, image input and image output token counters. [MiniMax pricing](https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise) · [OpenAI pricing](https://developers.openai.com/api/docs/pricing)

## Result delivery and replay

| Model | Supplier fields | Retrieval window |
| --- | --- | --- |
| Seedream 5.0 Pro | `data[].url` or `data[].b64_json` | Up to 24 hours. [Seedream response](https://docs.byteplus.com/en/docs/ModelArk/image-generation-api) |
| Seedance 2.5 | `content.video_url` | Up to 24 hours, subject to the supplier's download limit. [Seedance response](https://docs.byteplus.com/en/docs/ModelArk/list-video-generation-tasks-api) |
| MiniMax H3 | `task.content.url` | The plugin API offers retrieval for up to 24 hours, subject to the supplier link. [H3 task API](https://platform.minimax.io/docs/api-reference/video-generation-v2-query) |
| GPT Image | `data[].b64_json` | Up to 24 hours through the plugin API. [Images API](https://developers.openai.com/api/reference/resources/images/methods/generate) |
| Seed Audio 1.0 | WAV in `audio`, with `url` as fallback | Inline results up to 24 hours through the plugin API. Supplier links are valid for up to 2 hours. [Seed Audio response](https://docs.byteplus.com/en/docs/byteplusvoice/seedaudio-01?lang=en) |

The ComfyUI server downloads supplier URLs directly without the JMovie grant. The API returns inline media unchanged and does not archive plugin outputs in Spaces. A supplier URL may expire sooner than the API's retrieval window. Download and save results promptly. A repeated run uses the original task, and an expired result does not initiate a new paid request. Change the run number to explicitly request a new generation.

Ordinary `/api/v3` jobs continue to use private signed Spaces downloads with their existing retention policy.
