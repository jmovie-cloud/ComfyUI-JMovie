# JMovie Cloud

JMovie Cloud provides cloud media nodes for ComfyUI. Connect a JMovie production account to run managed image and video tasks on a compatible JMovie platform, or set a provider API key on the ComfyUI server to use BYOK.

## Install and run

Copy or link this repository to `ComfyUI/custom_nodes/ComfyUI-JMovie` and restart ComfyUI. Use ComfyUI 0.36.0 or later with its standard Python environment. The plugin uses the media libraries supplied by ComfyUI and does its inference in the cloud.

| Node | Connection | Output |
| --- | --- | --- |
| Cloud Image (JMovie) | JMovie production account. GPT Image 2, GPT Image 2.5 and Seedream 5.0 Pro | `IMAGE`, task ID |
| Cloud Image | OpenAI, BytePlus or MiniMax BYOK | `IMAGE` |
| Cloud Video | JMovie or BYOK. MiniMax H3 or Dreamina Seedance 2.5 | `VIDEO`, task ID |
| Resume Cloud Video | Original JMovie, MiniMax or BytePlus connection | `VIDEO`, task ID |
| Cloud Music | MiniMax Music 3.0 BYOK | `AUDIO` |
| Cloud Image Upscale | Stability AI Fast Upscale BYOK | `IMAGE` |
| H3 Video Upscale | MiniMax H3 768P → 2K regeneration, BYOK with provider allowlisting | `VIDEO`, task ID |

Drag [Cloud Image](workflows/cloud-image.json), [Cloud Video](workflows/cloud-video.json), or [Cloud Image (JMovie)](workflows/jmovie-image.json) into ComfyUI. The examples connect to ComfyUI's native Save Image or Save Video. The music output connects to Save Audio and other native audio nodes. Queueing with a configured real account or key can incur charges.

## Connect JMovie

Run a single-user ComfyUI server on loopback with the default same-origin protections. Set `JMOVIE_CLOUD_BASE_URL` to the trusted JMovie production-platform origin implementing the [plugin contract](docs/jmovie-platform-contract.md). Open **Connect JMovie** on a managed node, select **Connect JMovie** in the dialog, and sign in and confirm the code on the platform page. Back in ComfyUI, use **Cloud Image (JMovie)** or select **JMovie** on **Cloud Video**.

The grant covers plugin image and video generation and task access. The platform manages tasks, prices, and usage on the authorized production account. Use **Disconnect** to revoke the grant or revoke it on the platform. The ComfyUI server keeps the grant in memory, so restart or expiration requires reconnecting. Account connections are intended for a local, unshared ComfyUI process. The JMovie backend implements the endpoints behind `COMFY_CLOUD_ENABLED`. Local verification uses the JMovie backend with simulated suppliers. Availability on a deployed platform depends on its configuration. The independent developer API is a separate product.

## BYOK

Set only the keys for the routes you use in the ComfyUI server environment, then restart it. BYOK requests are billed directly by the corresponding provider.

| Environment variable | Routes |
| --- | --- |
| `OPENAI_API_KEY` | GPT Image 2, GPT Image 2.5 Flare and Sunburst |
| `ARK_API_KEY` | Seedream 5.0 Pro and Dreamina Seedance 2.5 |
| `MINIMAX_API_KEY` | H3 Image and Image Highspeed, H3 video, Music 3.0 and eligible H3 regeneration |
| `STABILITY_API_KEY` | Fast Upscale |

Cloud Image accepts one optional reference image. Cloud Video supports text-to-video, frame anchors, or an `IMAGE` batch for visual references. Seedance requires a first frame when a last frame is connected. Cloud Video returns the generated audio track inside the native video when enabled and present. Interchange of input reference video and reference audio is outside this version's video inputs. [MiniMax H3 API](https://platform.minimax.io/docs/api-reference/video/generation/api/v2-video-generation.json), [BytePlus Seedance 2.5](https://docs.byteplus.com/en/docs/ModelArk/seedance-2-5)

Use **H3 Video Upscale** with the task ID of a successful, same-account MiniMax H3 768P generation within its seven-day query window. Use **Cloud Image Upscale** on one image up to 1,048,576 input pixels. [MiniMax regeneration](https://platform.minimax.io/docs/api-reference/video-generation-v2-regeneration), [Stability Fast Upscale](https://docs.stability.ai/api-reference/upscale/fast)

## Resume tasks

Keep the same inputs and `run_number` to resume a video, H3 upscale, or managed image request. Change `run_number` for an intentional new submission. If a JMovie response is lost, queue the same run to recover its task ID with the original idempotency key. If a video submission was interrupted before the cloud returned its ID, check the task history for that account and use **Resume Cloud Video** with the recovered ID. After a ComfyUI restart, use the original provider key or reconnect the same JMovie account to resume. The local SQLite journal stores request fingerprints and task IDs. Availability of old task results follows provider retention. The synchronous BYOK image, music and image upscale endpoints return media in their response, so check provider usage before manually rerunning after a connection failure.

## Verification and Registry

The local acceptance test requires a ComfyUI checkout with this repository installed as `custom_nodes/ComfyUI-JMovie`, its Python environment with Playwright, Chrome, and FFmpeg. Run `python tests/comfy_smoke.py /absolute/path/to/ComfyUI` from the plugin repository. The test starts isolated loopback servers and uses synthetic credentials, prices and media. Workflows and node output types are exercised in the actual ComfyUI runtime. Real provider accounts, live content moderation outcomes, and NSFW generation have yet to be verified on any plugin route.

Registry metadata uses display name **JMovie Cloud**, ID `jmovie-cloud`, and initial version `0.1.0`. Set `[tool.comfy].PublisherId` to the assigned publisher before publishing. [Comfy Registry publishing](https://docs.comfy.org/registry/publishing)
