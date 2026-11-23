"""Video request validation for the JMovie connection."""

import base64


H3 = "MiniMax-H3"
SEEDANCE = "dreamina-seedance-2-5-260628"
VIDEO_MODELS = (SEEDANCE, H3)
MAX_VIDEO_BYTES = 192 * 1024 * 1024
MAX_INLINE_BYTES = 45_000_000
VIDEO_RATIOS = {
    H3: ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
    SEEDANCE: ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
}
VIDEO_RESOLUTIONS = {H3: ("768P", "2K"), SEEDANCE: ("720p", "480p", "1080p", "4k")}


def inline_media(mime, data):
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def video_settings(model, prompt, duration, ratio, resolution, generate_audio, frames, references):
    if model not in VIDEO_MODELS:
        raise ValueError("Select a supported video model.")
    prompt = prompt.strip()
    if not 1 <= len(prompt) <= 7000:
        raise ValueError("Enter a video prompt between 1 and 7000 characters.")
    if resolution == "model default":
        resolution = VIDEO_RESOLUTIONS[model][0]
    if resolution not in VIDEO_RESOLUTIONS[model]:
        raise ValueError(f"Select a resolution supported by {model}.")
    if not 4 <= duration <= (15 if model == H3 else 30):
        raise ValueError(f"Select a duration supported by {model}.")
    if frames:
        ratio = "adaptive"
    elif ratio not in VIDEO_RATIOS[model]:
        raise ValueError("Select a supported video aspect ratio.")
    if frames and references:
        raise ValueError("Use frame anchors or reference images in a single run.")
    if model == SEEDANCE and frames and frames[0][0] == "last_frame":
        raise ValueError("Connect a first frame to use a last frame with Seedance.")
    images = frames + references
    if any(len(data) >= 30_000_000 for _, data in images):
        raise ValueError("Each video reference image must be smaller than 30 MB.")
    if sum(len(data) for _, data in images) > MAX_INLINE_BYTES:
        raise ValueError("The reference images would exceed the request size limit.")
    return {
        "model": model, "prompt": prompt, "ratio": ratio, "resolution": resolution,
        "duration": duration, "generate_audio": generate_audio,
        "images": [{"role": role, "data": inline_media("image/png", png)} for role, png in images],
    }
