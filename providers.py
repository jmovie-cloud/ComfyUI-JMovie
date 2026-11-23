import base64

import aiohttp

from .transport import RequestError, api_key, client, request_json


OPENAI_MODELS = ("gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst")
SEEDREAM_MODELS = ("dola-seedream-5-0-pro-260628",)
MINIMAX_MODELS = ("MiniMax-H3-Image", "MiniMax-H3-Image-Highspeed")
MAX_IMAGE_BYTES = 40 * 1024 * 1024


def image_request(model, prompt, reference=None):
    if model in OPENAI_MODELS:
        url = "https://api.openai.com/v1/images/generations"
        key_name = "OPENAI_API_KEY"
        payload = {"model": model, "prompt": prompt}
        if reference is not None:
            url = "https://api.openai.com/v1/images/edits"
            payload = aiohttp.FormData()
            payload.add_field("model", model)
            payload.add_field("prompt", prompt)
            payload.add_field("image[]", reference, filename="reference.png", content_type="image/png")
        return url, key_name, payload

    if model in MINIMAX_MODELS:
        url = "https://api.minimax.io/v1/images/generations"
        payload = {"model": model, "prompt": prompt, "response_format": "b64_json", "area": "2K"}
        if reference is not None:
            url = "https://api.minimax.io/v1/images/edits"
            encoded = base64.b64encode(reference).decode("ascii")
            payload["images"] = [{"image_url": f"data:image/png;base64,{encoded}"}]
        return url, "MINIMAX_API_KEY", payload

    if model in SEEDREAM_MODELS:
        payload = {"model": model, "prompt": prompt, "response_format": "b64_json"}
        if reference is not None:
            encoded = base64.b64encode(reference).decode("ascii")
            payload["image"] = f"data:image/png;base64,{encoded}"
        return (
            "https://ark.ap-southeast.bytepluses.com/api/v3/images/generations",
            "ARK_API_KEY",
            payload,
        )

    raise ValueError("The selected image model is unsupported.")


async def generate_image(model, prompt, reference=None):
    if reference is not None and len(reference) > 30_000_000:
        raise ValueError("Reference image exceeds 30 MB after PNG encoding.")
    url, key_name, payload = image_request(model, prompt, reference)

    key = api_key(key_name)
    body = {"data": payload} if isinstance(payload, aiohttp.FormData) else {"json": payload}
    try:
        async with client(300) as session:
            limit = (MAX_IMAGE_BYTES * 4 // 3) + 65536
            _, result = await request_json(session, "POST", url, token=key, limit=limit, **body)
    except RequestError as error:
        if error.status is None or error.status >= 500:
            raise RuntimeError("Image request unconfirmed. Check provider usage before rerunning.") from None
        raise

    try:
        encoded = result["data"][0]["b64_json"]
        decoded = base64.b64decode(encoded, validate=True)
        if not decoded or len(decoded) > MAX_IMAGE_BYTES:
            raise ValueError("Invalid image length.")
        return decoded
    except (ValueError, KeyError, TypeError, IndexError):
        raise RuntimeError("Image provider did not return a usable image.") from None
