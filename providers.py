import base64

import aiohttp

from .credentials import api_key
from .transport import RequestError, client, request_json


HOSTED_GPT_IMAGE_MODELS = ("gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst")
OPENAI_MODELS = (*HOSTED_GPT_IMAGE_MODELS, "gpt-image-2.6-flare", "gpt-image-2.6-sunburst")
SEEDREAM_MODELS = ("dola-seedream-5-0-pro-260628",)
MAX_IMAGE_BYTES = 40 * 1024 * 1024


def image_request(model, prompt, reference=None):
    if model not in OPENAI_MODELS:
        raise ValueError("Choose a GPT Image model to use your OpenAI API key.")
    if reference is None:
        return "https://api.openai.com/v1/images/generations", {"model": model, "prompt": prompt}
    payload = aiohttp.FormData()
    payload.add_field("model", model)
    payload.add_field("prompt", prompt)
    payload.add_field("image[]", reference, filename="reference.png", content_type="image/png")
    return "https://api.openai.com/v1/images/edits", payload


async def generate_image(model, prompt, reference=None):
    if reference is not None and len(reference) > 30_000_000:
        raise ValueError("Reference image exceeds 30 MB after PNG encoding.")
    url, payload = image_request(model, prompt, reference)

    key, _ = api_key("openai")
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
