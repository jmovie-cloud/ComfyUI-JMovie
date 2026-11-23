# JMovie production-platform plugin contract

The JMovie backend implements this contract behind `COMFY_CLOUD_ENABLED`. Local acceptance can run the real backend with its fake upstream mode. The standalone ComfyUI smoke test also supplies a fixture for this contract.

## Device authorization

The ComfyUI Python process is an OAuth public client with client ID `jmovie-cloud`. It defaults to the JMovie production platform at `https://j-movie.com`. Operators can override the origin with `JMOVIE_CLOUD_BASE_URL` for a compatible platform or local test. The browser signs in on that origin, displays the production account and permission request, and asks the user to verify the visible device code before approving. Use the OAuth 2.0 device authorization flow and token revocation semantics. [RFC 8628](https://www.rfc-editor.org/rfc/rfc8628), [RFC 7009](https://www.rfc-editor.org/rfc/rfc7009)

| Request under `/api/v1/comfy` | Contract |
| --- | --- |
| `POST /oauth/device/code` | Form fields `client_id` and `scope`. Returns `device_code`, `user_code`, same-origin `verification_uri`, integer `expires_in` and `interval` seconds. |
| `POST /oauth/token` | Form fields `client_id`, `device_code`, and `grant_type=urn:ietf:params:oauth:grant-type:device_code`. Returns `access_token`, `token_type=Bearer`, granted `scope`, stable `account_id` and `expires_in` (up to 86,400 seconds). Pending, slowdown, denial and expiration use HTTP 400 OAuth errors. |
| `GET /connection` | Accepts only an active plugin grant and returns 200. Use 401 for invalid, expired or revoked grants. |
| `POST /oauth/revoke` | Form fields `client_id` and `token`. Revokes the plugin grant. Returns 200 or 204 for a valid request, including an already revoked token. |

The base scopes are `image:generate video:generate tasks:read`. Supporting plugins also request `audio:generate`, which covers audio submission and access to their audio results after consent. Previously approved image and video grants retain their original scopes. Bind grants to one production account and the plugin API audience. Enforce per-operation scope, grant expiration, account status, task ownership and revocation on every request. Signed-in users revoke grants on the platform's `/api/v1/comfy/authorizations` page. The ComfyUI process holds the token in memory and the browser receives the consent URL, visible code and status only.

## Generation

| Request under `/api/v1/comfy` | Contract |
| --- | --- |
| `POST /tasks` | Bearer grant, `Idempotency-Key` and a JSON request. Returns a task `id`. Replaying the same key with the same request under the same account returns the original task. |
| `GET /tasks/{id}` | Bearer grant. Returns `kind` and `status` (`queued`, `running`, `succeeded`, `failed`, `cancelled` or `expired`). |
| `GET /tasks/{id}/result` | Bearer grant. Streams the result bytes of a completed task on the same origin. Images use PNG, JPEG or WebP, video uses MP4 and audio uses WAV. |

Create requests send `kind` (`image`, `video` or `audio`), `model` and `prompt`. Image and video requests may send PNG data URIs with a `role` in `images`. Video requests also send `resolution`, `ratio`, integer `duration`, and `generate_audio`. Audio requests use `seed-audio-1.0-global` with a prompt and integer target `duration` of 1–120 seconds. The platform resolves models through the account's permitted route catalog and owns price validation, reservations, settlement, task history and entitlements. Repeated requests and reauthorization preserve the same native task and billing history.

The independent developer API at `api.j-movie.com` is outside this contract.
