"""Run local ComfyUI and a browser against synthetic media and account endpoints."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

import aiohttp
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def launch_comfy(args):
    platform = f"http://127.0.0.1:{args.platform_port}"
    comfy = f"http://127.0.0.1:{args.comfy_port}"
    providers = {
        "api.openai.com": "openai", "api.minimax.io": "minimax",
        "ark.ap-southeast.bytepluses.com": "byteplus", "api.stability.ai": "stability",
    }
    original_request = aiohttp.ClientSession._request

    async def request(self, method, url, **kwargs):
        parsed = urlsplit(str(url))
        if parsed.hostname in providers:
            url = f"{platform}/provider/{providers[parsed.hostname]}{parsed.path}"
        elif parsed.hostname == "mock-media.invalid":
            url = f"{platform}{parsed.path}"
        elif not str(url).startswith((f"{platform}/", f"{comfy}/")):
            raise RuntimeError("Only synthetic local endpoints are permitted in the smoke test.")
        return await original_request(self, method, url, **kwargs)

    aiohttp.ClientSession._request = request
    os.environ.update({
        "JMOVIE_CLOUD_BASE_URL": platform, "OPENAI_API_KEY": "mock-openai", "MINIMAX_API_KEY": "mock-minimax",
        "ARK_API_KEY": "mock-byteplus", "STABILITY_API_KEY": "mock-stability",
    })
    entry = args.comfy / "main.py"
    sys.path.insert(0, str(args.comfy))
    sys.argv = [
        str(entry), "--cpu", "--listen", "127.0.0.1", "--port", str(args.comfy_port),
        "--disable-auto-launch", "--disable-api-nodes", "--disable-all-custom-nodes",
        "--whitelist-custom-nodes", "ComfyUI-JMovie",
        "--user-directory", str(args.fixtures / "user"),
        "--input-directory", str(args.fixtures / "input"),
        "--output-directory", str(args.fixtures / "output"),
    ]
    # Set a shorter polling interval in the test runner after the real extension is loaded.
    import comfy.options
    comfy.options.enable_args_parsing()
    import nodes

    load = nodes.load_custom_node

    async def shortened_poll(*call_args, **kwargs):
        success = await load(*call_args, **kwargs)
        for name, module in tuple(sys.modules.items()):
            if name.endswith("ComfyUI-JMovie.tasks"):
                module.POLL_SECONDS = 0.15
        return success

    nodes.load_custom_node = shortened_poll
    runpy.run_path(entry, run_name="__main__")


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def json_request(url, body=None, headers=None):
    if body is not None:
        headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, json.dumps(body).encode() if body is not None else None, headers or {})
    with urlopen(request, timeout=10) as response:
        return json.load(response) if response.status != 204 else None


@contextmanager
def process(command, log):
    with log.open("w") as file:
        child = subprocess.Popen(command, cwd=ROOT, stdout=file, stderr=subprocess.STDOUT)
        try:
            yield child
        finally:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)


def ready(url, child):
    for _ in range(960):
        if child.poll() is not None:
            raise RuntimeError(f"Server exited before readiness ({url}).")
        try:
            return json_request(url)
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}.")


def node(class_type, **inputs):
    return {"class_type": class_type, "inputs": inputs}


def run_graph(base, graph, *, error=None):
    prompt_id = json_request(f"{base}/prompt", {"prompt": graph})["prompt_id"]
    for _ in range(240):
        item = json_request(f"{base}/history/{prompt_id}").get(prompt_id)
        if item:
            if error is not None:
                issues = [msg[1]["exception_message"] for msg in item["status"]["messages"] if msg[0] == "execution_error"]
                assert any(error in issue for issue in issues), item
            else:
                assert item["status"]["status_str"] == "success", item
                assert item["outputs"], item
            return item
        time.sleep(0.25)
    raise RuntimeError(f"ComfyUI execution timed out for {prompt_id}.")


def video_graph(generator, extra=None):
    return {"1": generator, "2": node("SaveVideo", video=["1", 0], filename_prefix="smoke/video", format="auto"),
            **(extra or {})}


def image_graph(generator):
    return {"1": generator, "2": node("SaveImage", images=["1", 0], filename_prefix="smoke/image")}


def save_fixtures(fixtures):
    (fixtures / "input").mkdir()
    (fixtures / "user").mkdir()
    Image.new("RGB", (320, 320), "orange").save(fixtures / "input" / "reference.png")
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=320x320:r=24:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(fixtures / "movie.mp4"),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libmp3lame", str(fixtures / "music.mp3"),
    ], check=True)


def browser_checks(base, platform, video, load_image, fixtures):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("JMOVIE_SMOKE_BROWSER", "chrome"))
        context = browser.new_context()
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith((base, platform)) else route.abort())
        page = context.new_page()
        frontend_errors = []
        page.on("pageerror", lambda error: frontend_errors.append(str(error)))
        page.goto(base)
        page.wait_for_function("!!window.app?.graph")
        page.wait_for_function("!!window.LiteGraph?.registered_node_types?.JMovieCloudVideo")

        workflow = json.loads((ROOT / "workflows" / "cloud-image.json").read_text())
        graph = page.evaluate("""async workflow => {
            await window.app.handleFile(new File([JSON.stringify(workflow)], 'cloud-image.json', {type: 'application/json'}));
            return (await window.app.graphToPrompt()).output;
        }""", workflow)
        assert graph["1"]["class_type"] == "JMovieCloudImage" and graph["2"]["inputs"]["images"] == ["1", 0]
        run_graph(base, graph)
        print("Browser imported and executed the original Cloud Image example.", flush=True)

        for name in ("cloud-video.json", "jmovie-image.json"):
            workflow = json.loads((ROOT / "workflows" / name).read_text())
            serialized = page.evaluate("""async ([workflow, name]) => {
                await window.app.handleFile(new File([JSON.stringify(workflow)], name, {type: 'application/json'}));
                const output = (await window.app.graphToPrompt()).output;
                return {output, graph: window.app.graph.serialize()};
            }""", [workflow, name])
            assert serialized["output"]["1"]["class_type"] == workflow["nodes"][0]["type"]
            values = serialized["graph"]["nodes"][0]["widgets_values"]
            assert len(values) == len(workflow["nodes"][0]["widgets_values"]), values

        try:
            json_request(f"{base}/jmovie-cloud/connection/start", {}, {"Origin": "https://wrong.invalid"})
        except HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("Cross-origin authorization request was accepted.")
        page.evaluate("""() => {
            window.app.graph.getNodeById(1).widgets.find(widget => widget.name === 'Connect JMovie').callback();
        }""")
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_role("button", name="Connect JMovie")).to_be_visible()
        page.screenshot(path=fixtures / "connection.png")
        with page.expect_popup() as popup:
            dialog.get_by_role("button", name="Connect JMovie").click()
        auth = popup.value
        auth.wait_for_url(f"{platform}/authorize")
        expect(dialog.get_by_role("status")).to_contain_text("JMV-2206")
        auth.get_by_label("Account").fill("test-creator")
        auth.get_by_label("Password").fill("test-password")
        auth.get_by_role("button", name="Sign in").click()
        auth.get_by_label("Device code").fill("JMV-2206")
        auth.get_by_role("button", name="Authorize").click()
        expect(auth.get_by_text("Authorized. Return to ComfyUI.")).to_be_visible()
        expect(dialog.get_by_role("status")).to_have_text("Connected to the JMovie production platform.")

        managed_image = image_graph(node("JMovieManagedImage", model="gpt-image-2", prompt="Local managed image",
                                         run_number=0, reference_image=["3", 0]))
        managed_image["3"] = load_image
        managed_video = video_graph(node("JMovieCloudVideo", **{**video, "connection": "JMovie"}))
        run_graph(base, managed_image)
        run_graph(base, managed_video)
        run_graph(base, managed_video)
        stats = json_request(f"{platform}/stats")
        assert stats["counts"]["jmovie_submit"] == 2 and stats["cost"] == 9, stats

        page.request.post(f"{platform}/permissions/revoke")
        run_graph(base, managed_video, error="HTTP 401")
        dialog.get_by_role("button", name="Close").click()
        page.evaluate("""() => {
            window.app.graph.getNodeById(1).widgets.find(widget => widget.name === 'Connect JMovie').callback();
        }""")
        expect(dialog.get_by_role("status")).to_contain_text("Connect your JMovie production account")
        with page.expect_popup() as reconnect:
            dialog.get_by_role("button", name="Connect JMovie").click()
        second = reconnect.value
        second.wait_for_url(f"{platform}/authorize")
        second.get_by_label("Account").fill("test-creator")
        second.get_by_label("Password").fill("test-password")
        second.get_by_role("button", name="Sign in").click()
        second.get_by_label("Device code").fill("JMV-2206")
        second.get_by_role("button", name="Authorize").click()
        expect(dialog.get_by_role("status")).to_have_text("Connected to the JMovie production platform.")
        run_graph(base, managed_video)
        assert json_request(f"{platform}/stats")["cost"] == 9
        dialog.get_by_role("button", name="Disconnect").click()
        expect(dialog.get_by_role("status")).to_contain_text("Connect your JMovie production account")
        run_graph(base, managed_image, error="Use Connect JMovie")
        assert not [error for error in frontend_errors if "JMovie" in error], frontend_errors

        browser.close()
        print("Browser signed in, authorized, ran managed tasks, handled revocation and reconnected without a second charge.", flush=True)


def smoke(args):
    qa = ROOT / ".qa"
    qa.mkdir(exist_ok=True)
    fixtures = Path(tempfile.mkdtemp(prefix="smoke-", dir=qa))
    print(f"Smoke test logs and outputs: {fixtures}", flush=True)
    args.comfy_port, args.platform_port = port(), port()
    base, platform = f"http://127.0.0.1:{args.comfy_port}", f"http://127.0.0.1:{args.platform_port}"
    save_fixtures(fixtures)
    comfy_cmd = [
        sys.executable, __file__, str(args.comfy), "--server", "--fixtures", str(fixtures),
        "--comfy-port", str(args.comfy_port), "--platform-port", str(args.platform_port),
    ]
    platform_cmd = [sys.executable, str(ROOT / "tests" / "mock_platform.py"), str(fixtures), str(args.platform_port)]
    video = dict(connection="BYOK", model="MiniMax-H3", prompt="Synthetic cup dolly", duration=5,
                 ratio="16:9", resolution="model default", generate_audio=True, run_number=0)
    load_image = node("LoadImage", image="reference.png")
    h3 = video_graph(node("JMovieCloudVideo", **video))
    with process(platform_cmd, fixtures / "platform.log") as mock:
        ready(f"{platform}/stats", mock)
        with process(comfy_cmd, fixtures / "comfy.log") as comfy:
            info = ready(f"{base}/object_info", comfy)
            installed = {key for key in info if key.startswith("JMovie")}
            assert len(installed) == 7, installed
            for model in ("gpt-image-2", "dola-seedream-5-0-pro-260628", "MiniMax-H3-Image"):
                run_graph(base, image_graph(node("JMovieCloudImage", model=model, prompt="Ceramic cup")))
            edit = image_graph(node("JMovieCloudImage", model="gpt-image-2.5-flare", prompt="Glaze the cup",
                                     reference_image=["3", 0]))
            edit["3"] = load_image
            run_graph(base, edit)
            run_graph(base, h3)
            source_id = json_request(f"{platform}/stats")["tasks"][-1]
            run_graph(base, video_graph(node("JMovieResumeVideo", service="MiniMax", task_id=source_id)))
            run_graph(base, video_graph(node("JMovieH3Upscale", source_task_id=source_id, run_number=0)))
            seedance = {**video, "model": "dreamina-seedance-2-5-260628",
                        "first_frame": ["3", 0], "last_frame": ["3", 0]}
            run_graph(base, video_graph(node("JMovieCloudVideo", **seedance), {"3": load_image}))
            run_graph(base, {"1": node("JMovieCloudMusic", prompt="Acoustic background", instrumental=True, lyrics=""),
                             "2": node("SaveAudio", audio=["1", 0], filename_prefix="smoke/music")})
            upscale = image_graph(node("JMovieCloudImageUpscale", image=["3", 0]))
            upscale["3"] = load_image
            result = run_graph(base, upscale)["outputs"]["2"]["images"][0]
            with Image.open(fixtures / "output" / result["subfolder"] / result["filename"]) as image:
                assert image.size == (1280, 1280)

            ambiguous = video_graph(node("JMovieCloudVideo", **{**video, "prompt": "simulate-unknown"}))
            run_graph(base, ambiguous, error="Submission unconfirmed")
            before_retry = json_request(f"{platform}/stats")
            run_graph(base, ambiguous, error="unconfirmed submission")
            assert json_request(f"{platform}/stats") == before_retry
            recovered = before_retry["tasks"][-1]
            run_graph(base, video_graph(node("JMovieResumeVideo", service="MiniMax", task_id=recovered)))
            print("BYOK image, edit, H3, Seedance frames, music and both upscale nodes saved native media.", flush=True)
            browser_checks(base, platform, video, load_image, fixtures)
            before_restart = json_request(f"{platform}/stats")
        with process(comfy_cmd, fixtures / "comfy-restart.log") as comfy:
            ready(f"{base}/object_info", comfy)
            run_graph(base, h3)
            assert json_request(f"{platform}/stats") == before_restart
            run_graph(base, ambiguous, error="unconfirmed submission")
            assert json_request(f"{platform}/stats") == before_restart
        print("Restart preserved known and ambiguous task submissions without reposting.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("comfy", type=lambda path: Path(path).resolve())
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--comfy-port", type=int)
    parser.add_argument("--platform-port", type=int)
    arguments = parser.parse_args()
    if arguments.server:
        launch_comfy(arguments)
    else:
        smoke(arguments)
