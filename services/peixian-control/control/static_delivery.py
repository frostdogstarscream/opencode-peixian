"""Static response policy for the co-packaged SPA; no authentication changes."""
from fastapi.staticfiles import StaticFiles

from shared.control_delivery import HASHED_ASSET


class DeliveryStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        delivery = getattr(scope["app"].state, "delivery", None)
        if response.status_code in (200, 304):
            known = delivery and "assets/" + path in delivery["files"]
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable" if known and HASHED_ASSET.search(path) else "no-cache")
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response
