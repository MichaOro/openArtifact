"""Static file serving with revalidation instead of heuristic caching."""

from __future__ import annotations

from typing import Any

from starlette.staticfiles import StaticFiles


class RevalidatingStaticFiles(StaticFiles):
    """Serve assets with ``Cache-Control: no-cache``.

    The assets are not fingerprinted. Without an explicit policy browsers may reuse a stale
    ``main.js`` for a while (heuristic freshness) and combine it with newer HTML, which
    breaks the UI after a deployment. ``no-cache`` makes the browser revalidate on every
    load; the ETag / Last-Modified headers turn that into a cheap ``304 Not Modified``.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
