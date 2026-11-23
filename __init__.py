from comfy_api.latest import ComfyExtension

from .credentials import add_key_routes
from .managed import add_routes
from .nodes import CloudImage, CloudVideo, JMovieAudio, JMovieImage, JMovieVideo, MiniMaxH3, ResumeVideo


WEB_DIRECTORY = "./web"


class JMovieCloudExtension(ComfyExtension):
    async def on_load(self):
        from server import PromptServer

        if PromptServer.instance is not None:
            add_routes(PromptServer.instance)
            add_key_routes(PromptServer.instance)

    async def get_node_list(self):
        return [JMovieImage, JMovieVideo, JMovieAudio, ResumeVideo, CloudImage, MiniMaxH3, CloudVideo]


async def comfy_entrypoint():
    return JMovieCloudExtension()
