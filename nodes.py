from comfy_api.latest import io

from .extras import generate_music, upscale_image
from .managed import managed_media
from .media import decode_image, decode_music, decode_video, png_image
from .providers import MAX_IMAGE_BYTES, MINIMAX_MODELS, OPENAI_MODELS, SEEDREAM_MODELS, generate_image
from .video import (
    ARK_ENDPOINT, H3, H3_ENDPOINT, MAX_INLINE_BYTES, MAX_VIDEO_BYTES, VIDEO_MODELS,
    inline_media, provider_payload, provider_video, regenerate_h3, video_settings,
)


MANAGED_IMAGE_MODELS = (*OPENAI_MODELS, *SEEDREAM_MODELS)
IMAGE_MODELS = (*MANAGED_IMAGE_MODELS, *MINIMAX_MODELS)
CATEGORY = "JMovie Cloud"
JMOVIE = "JMovie"
DIRECT = "BYOK"


def image_inputs(models):
    return [
        io.Combo.Input("model", options=list(models)),
        io.String.Input("prompt", multiline=True),
        io.Image.Input("reference_image", optional=True),
    ]


def run_input():
    return io.Int.Input(
        "run_number", default=0, min=0, max=2**31 - 1,
        tooltip="Keep the number to resume the same request. Change it to submit a new paid task.",
    )


class CloudImage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieCloudImage",
            display_name="Cloud Image",
            category=CATEGORY,
            description="Generate or edit an image with a provider API key from the ComfyUI server environment.",
            inputs=image_inputs(IMAGE_MODELS),
            outputs=[io.Image.Output()],
        )

    @classmethod
    async def execute(cls, model, prompt, reference_image=None):
        if not prompt.strip():
            raise ValueError("Enter an image prompt.")
        reference = png_image(reference_image) if reference_image is not None else None
        return io.NodeOutput(decode_image(await generate_image(model, prompt, reference)))


class JMovieImage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieManagedImage",
            display_name="Cloud Image (JMovie)",
            category=CATEGORY,
            description="Generate or edit an image through the authorized JMovie production account.",
            inputs=[*image_inputs(MANAGED_IMAGE_MODELS), run_input()],
            outputs=[io.Image.Output(), io.String.Output("task_id")],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    async def execute(cls, model, prompt, run_number, reference_image=None):
        if model not in MANAGED_IMAGE_MODELS or not prompt.strip():
            raise ValueError("Select an image model and enter a prompt.")
        payload = {"model": model, "prompt": prompt.strip()}
        if reference_image is not None:
            png = png_image(reference_image)
            if len(png) >= 30_000_000:
                raise ValueError("Reference image exceeds 30 MB after PNG encoding.")
            payload["images"] = [{"role": "reference_image", "data": inline_media("image/png", png)}]
        data, remote_id = await managed_media("image", payload, MAX_IMAGE_BYTES, run_number)
        return io.NodeOutput(decode_image(data), remote_id)


def video_outputs():
    return [io.Video.Output(), io.String.Output("task_id")]


def video_images(model, first_frame, last_frame, reference_images):
    frames, references = [], []
    minimum, maximum = (256, 5760) if model == H3 else (300, 6000)
    if reference_images is not None and (first_frame is not None or last_frame is not None):
        raise ValueError("Use frame anchors or reference images in a single run.")
    if reference_images is not None and not 1 <= len(reference_images) <= (9 if model == H3 else 30):
        raise ValueError("The reference IMAGE batch exceeds the model's image count.")
    inputs = [("first_frame", first_frame), ("last_frame", last_frame)]
    if reference_images is not None:
        inputs.extend(("reference_image", image.unsqueeze(0)) for image in reference_images)
    size = 0
    for role, image in inputs:
        if image is None:
            continue
        height, width = image.shape[1:3]
        if not minimum <= min(height, width) <= max(height, width) <= maximum or not 0.4 <= width / height <= 2.5:
            raise ValueError(f"Video images need {minimum}–{maximum} pixels per side and a 2:5 to 5:2 ratio.")
        png = png_image(image)
        size += len(png)
        if size > MAX_INLINE_BYTES:
            raise ValueError("The reference images would exceed the request size limit.")
        target = references if role == "reference_image" else frames
        target.append((role, png))
    return frames, references


class CloudVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieCloudVideo",
            display_name="Cloud Video",
            category=CATEGORY,
            description="Generate video with MiniMax H3 or BytePlus Seedance. Connect frames or reference images.",
            inputs=[
                io.Combo.Input("connection", options=[JMOVIE, DIRECT]),
                io.Combo.Input("model", options=list(VIDEO_MODELS)),
                io.String.Input("prompt", multiline=True),
                io.Int.Input("duration", default=5, min=4, max=30),
                io.Combo.Input("ratio", options=["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]),
                io.Combo.Input("resolution", options=["model default", "768P", "2K", "480p", "720p", "1080p", "4k"]),
                io.Boolean.Input("generate_audio", default=True),
                run_input(),
                io.Image.Input("first_frame", optional=True),
                io.Image.Input("last_frame", optional=True),
                io.Image.Input("reference_images", optional=True),
            ],
            outputs=video_outputs(),
        )

    @classmethod
    def fingerprint_inputs(cls, connection, **kwargs):
        return float("nan") if connection == JMOVIE else None

    @classmethod
    async def execute(
        cls, connection, model, prompt, duration, ratio, resolution, generate_audio, run_number,
        first_frame=None, last_frame=None, reference_images=None,
    ):
        frames, references = video_images(model, first_frame, last_frame, reference_images)
        settings = video_settings(model, prompt, duration, ratio, resolution, generate_audio, frames, references)
        if connection == JMOVIE:
            data, remote_id = await managed_media("video", settings, MAX_VIDEO_BYTES, run_number)
        else:
            endpoint = H3_ENDPOINT if model == H3 else ARK_ENDPOINT
            data, remote_id = await provider_video(endpoint, provider_payload(settings), run_number)
        return io.NodeOutput(decode_video(data), remote_id)


class ResumeVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieResumeVideo",
            display_name="Resume Cloud Video",
            category=CATEGORY,
            description="Poll and download an existing task using its original connection.",
            inputs=[
                io.Combo.Input("service", options=[JMOVIE, "MiniMax", "BytePlus"]),
                io.String.Input("task_id"),
            ],
            outputs=video_outputs(),
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    async def execute(cls, service, task_id):
        task_id = task_id.strip()
        if not task_id:
            raise ValueError("Enter the existing task ID.")
        if service == JMOVIE:
            data, remote_id = await managed_media("video", {}, MAX_VIDEO_BYTES, resume_id=task_id)
        else:
            endpoint = H3_ENDPOINT if service == "MiniMax" else ARK_ENDPOINT
            data, remote_id = await provider_video(endpoint, {}, resume_id=task_id)
        return io.NodeOutput(decode_video(data), remote_id)


class CloudMusic(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieCloudMusic",
            display_name="Cloud Music",
            category=CATEGORY,
            description="Generate an instrumental track or a song with lyrics using MiniMax Music 3.0 BYOK.",
            inputs=[
                io.String.Input("prompt", multiline=True),
                io.Boolean.Input("instrumental", default=True),
                io.String.Input("lyrics", multiline=True, default=""),
            ],
            outputs=[io.Audio.Output()],
        )

    @classmethod
    async def execute(cls, prompt, instrumental, lyrics):
        return io.NodeOutput(decode_music(await generate_music(prompt, lyrics, instrumental)))


class CloudImageUpscale(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieCloudImageUpscale",
            display_name="Cloud Image Upscale",
            category=CATEGORY,
            description="Upscale one image using Stability AI Fast Upscale BYOK.",
            inputs=[io.Image.Input("image")],
            outputs=[io.Image.Output()],
        )

    @classmethod
    async def execute(cls, image):
        height, width = image.shape[1:3]
        if not (32 <= height <= 1536 and 32 <= width <= 1536 and height * width <= 1_048_576):
            raise ValueError("Fast Upscale requires 32–1536 pixels per side and up to 1,048,576 input pixels.")
        return io.NodeOutput(decode_image(await upscale_image(png_image(image))))


class H3Upscale(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieH3Upscale",
            display_name="H3 Video Upscale",
            category=CATEGORY,
            description="Regenerate a completed MiniMax H3 768P BYOK task at 2K. Requires MiniMax account allowlisting.",
            inputs=[io.String.Input("source_task_id"), run_input()],
            outputs=video_outputs(),
        )

    @classmethod
    async def execute(cls, source_task_id, run_number):
        data, remote_id = await regenerate_h3(source_task_id, run_number)
        return io.NodeOutput(decode_video(data), remote_id)
