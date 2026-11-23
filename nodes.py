from comfy_api.latest import io

from .managed import managed_media
from .media import decode_audio, decode_image, decode_video, png_image
from .providers import MAX_IMAGE_BYTES, OPENAI_MODELS, SEEDREAM_MODELS, generate_image
from .video import (
    H3, MAX_INLINE_BYTES, MAX_VIDEO_BYTES, VIDEO_MODELS,
    inline_media, video_settings,
)


MANAGED_IMAGE_MODELS = (*SEEDREAM_MODELS, *OPENAI_MODELS)
MAX_AUDIO_BYTES = 32 * 1024 * 1024
CATEGORY = "JMovie Cloud"
ADVANCED_CATEGORY = f"{CATEGORY}/Advanced"
BYOK_CATEGORY = f"{ADVANCED_CATEGORY}/BYOK"
JMOVIE = "JMovie"
DIRECT = "BYOK"


def image_inputs(models):
    return [
        io.Combo.Input("model", options=list(models)),
        io.String.Input("prompt", multiline=True),
        io.Image.Input("reference_image", optional=True),
    ]


def run_input(*, advanced=False):
    return io.Int.Input(
        "run_number", display_name="Run number", default=0, min=0, max=2**31 - 1,
        tooltip="Keep the number to resume the same request. Change it to submit a new paid task.",
        advanced=advanced,
    )


class CloudImage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieCloudImage",
            display_name="GPT Image (OpenAI BYOK)",
            category=BYOK_CATEGORY,
            description="Generate or edit images with an OpenAI API key from the ComfyUI server environment.",
            inputs=image_inputs(OPENAI_MODELS),
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
            display_name="JMovie Image",
            category=CATEGORY,
            description="Generate or edit an image through the authorized JMovie API account.",
            inputs=[*image_inputs(MANAGED_IMAGE_MODELS), run_input(advanced=True)],
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


def video_controls(*, advanced=False):
    return [
        io.Combo.Input("model", options=list(VIDEO_MODELS)),
        io.String.Input("prompt", multiline=True),
        io.Int.Input("duration", default=5, min=4, max=30),
        io.Combo.Input("ratio", options=["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]),
        io.Combo.Input(
            "resolution", options=["model default", "768P", "2K", "480p", "720p", "1080p", "4k"],
            advanced=advanced,
        ),
    ]


def video_reference_inputs():
    return [
        io.Image.Input("first_frame", optional=True),
        io.Image.Input("last_frame", optional=True),
        io.Image.Input("reference_images", optional=True),
    ]


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


def video_request(model, prompt, duration, ratio, resolution, generate_audio, first_frame, last_frame, reference_images):
    frames, references = video_images(model, first_frame, last_frame, reference_images)
    return video_settings(model, prompt, duration, ratio, resolution, generate_audio, frames, references)


class JMovieVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieManagedVideo",
            display_name="JMovie Video",
            category=CATEGORY,
            description="Generate video through your JMovie account. Connect frames or reference images.",
            inputs=[*video_controls(advanced=True), run_input(advanced=True), *video_reference_inputs()],
            outputs=video_outputs(),
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    async def execute(
        cls, model, prompt, duration, ratio, resolution, run_number,
        first_frame=None, last_frame=None, reference_images=None,
    ):
        settings = video_request(
            model, prompt, duration, ratio, resolution, True, first_frame, last_frame, reference_images,
        )
        data, remote_id = await managed_media("video", settings, MAX_VIDEO_BYTES, run_number)
        return io.NodeOutput(decode_video(data), remote_id)


class CloudVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieCloudVideo",
            display_name="Cloud Video (Legacy)",
            category=ADVANCED_CATEGORY,
            is_dev_only=True,
            description="Run saved JMovie video workflows created with the original node.",
            inputs=[
                io.Combo.Input("connection", options=[JMOVIE, DIRECT]),
                *video_controls(),
                io.Boolean.Input("generate_audio", default=True),
                run_input(),
                *video_reference_inputs(),
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
        if connection != JMOVIE:
            raise ValueError("Choose the JMovie connection for video. OpenAI BYOK is available for GPT Image.")
        settings = video_request(
            model, prompt, duration, ratio, resolution, generate_audio, first_frame, last_frame, reference_images,
        )
        data, remote_id = await managed_media("video", settings, MAX_VIDEO_BYTES, run_number)
        return io.NodeOutput(decode_video(data), remote_id)


class ResumeVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieResumeVideo",
            display_name="Resume Cloud Video",
            category=ADVANCED_CATEGORY,
            description="Download an existing JMovie video task.",
            inputs=[
                io.Combo.Input("service", options=[JMOVIE]),
                io.String.Input("task_id"),
            ],
            outputs=video_outputs(),
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    async def execute(cls, service, task_id):
        if service != JMOVIE:
            raise ValueError("Enter a task ID from JMovie.")
        task_id = task_id.strip()
        if not task_id:
            raise ValueError("Enter the existing task ID.")
        data, remote_id = await managed_media("video", {}, MAX_VIDEO_BYTES, resume_id=task_id)
        return io.NodeOutput(decode_video(data), remote_id)


class JMovieAudio(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieManagedAudio",
            display_name="JMovie Audio",
            category=CATEGORY,
            description="Generate dialogue, voice or sound with Seed Audio through your JMovie account.",
            inputs=[
                io.String.Input("prompt", multiline=True),
                io.Int.Input("duration", display_name="Target seconds", default=10, min=1, max=120,
                    tooltip="A prompt hint. The JMovie API wallet settles the supplier’s original generated duration."),
                run_input(advanced=True),
            ],
            outputs=[io.Audio.Output(), io.String.Output("task_id")],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return float("nan")

    @classmethod
    async def execute(cls, prompt, duration, run_number):
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 2900:
            raise ValueError("Enter an audio prompt between 1 and 2,900 characters.")
        payload = {"model": "seed-audio-1.0", "prompt": prompt, "duration": duration}
        data, remote_id = await managed_media("audio", payload, MAX_AUDIO_BYTES, run_number)
        return io.NodeOutput(decode_audio(data), remote_id)
