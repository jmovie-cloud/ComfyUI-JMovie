from aiohttp import web
from comfy.cli_args import args
from yarl import URL


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def local_comfy():
    return (
        not args.multi_user
        and args.enable_cors_header is None
        and all(host.strip() in LOOPBACK for host in args.listen.split(","))
    )


def require_local_request(request):
    try:
        origin = URL(f"{request.scheme}://{request.host}")
        if (
            local_comfy() and origin.host in LOOPBACK
            and request.remote in {"127.0.0.1", "::1"}
            and request.headers.get("Origin") == str(origin.origin())
            and request.headers.get("Sec-Fetch-Site", "same-origin") == "same-origin"
        ):
            return
    except ValueError:
        pass
    raise web.HTTPForbidden()
