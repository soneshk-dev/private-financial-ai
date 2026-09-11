"""Optional Cloudflare Access verification.

When the API is published through a Cloudflare Tunnel behind Access, Cloudflare
adds a ``Cf-Access-Jwt-Assertion`` header to every request. Verifying it here
means the process itself refuses anything that did not come through Access, even
if something else on the box can reach the port.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import Config


class AccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, cfg: Config):
        super().__init__(app)
        self.cfg = cfg
        self.team = cfg.access.team_domain
        self.aud = cfg.access.aud
        self._jwks = None

    def _client(self):
        import jwt
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(f"https://{self.team}.cloudflareaccess.com/cdn-cgi/access/certs")
        return self._jwks

    def verify(self, token: str) -> dict:
        import jwt
        key = self._client().get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], audience=self.aud,
                          issuer=f"https://{self.team}.cloudflareaccess.com")

    async def dispatch(self, request: Request, call_next):
        token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
        if not token:
            return JSONResponse({"detail": "Cloudflare Access token required"}, status_code=401)
        try:
            claims = self.verify(token)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"detail": f"Access token rejected: {type(e).__name__}"}, status_code=401)
        request.state.user = claims.get("email")
        return await call_next(request)
