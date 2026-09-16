"""Independent browser cookie jars sharing one application's real test lifespan.

Nested Starlette TestClients normally start another event loop and overwrite
app.state pools. The outer client owns startup/shutdown; sibling clients reuse
its blocking portal, exactly as browsers share one running Control process.
"""
from fastapi.testclient import TestClient as BaseTestClient
import uuid


class TestClient(BaseTestClient):
    __test__ = False
    _owner_attribute = "_peixian_test_lifespan_owner"

    def request(self, method, url, **kwargs):
        # Simulate the upgraded browser/Python client. Tests of missing keys use
        # an explicit empty header or BaseTestClient; no server check is bypassed.
        if method.upper() not in ("GET", "HEAD", "OPTIONS"):
            headers = dict(kwargs.pop("headers", None) or {})
            if not any(name.lower() == "idempotency-key" for name in headers):
                headers["Idempotency-Key"] = uuid.uuid4().hex
            kwargs["headers"] = headers
        return super().request(method, url, **kwargs)

    def __init__(self, app, *args, **kwargs):
        super().__init__(app, *args, **kwargs)
        self._lifespan_owner = None
        self._siblings = []
        owner = getattr(self.app, self._owner_attribute, None)
        if owner is not None:
            self._share(owner)

    def _share(self, owner):
        if owner.portal is None:
            raise RuntimeError("The canonical test lifespan is no longer running")
        self._lifespan_owner = owner
        self.portal = owner.portal
        self.app_state = owner.app_state
        # Starlette captures this dictionary when constructing its transport.
        self._transport.app_state = owner.app_state
        if self not in owner._siblings:
            owner._siblings.append(self)

    def __enter__(self):
        if self.is_closed:
            raise RuntimeError("A closed test browser cannot be reopened")
        owner = getattr(self.app, self._owner_attribute, None)
        if owner is not None:
            if owner is not self:
                self._share(owner)
            return self
        super().__enter__()
        setattr(self.app, self._owner_attribute, self)
        return self

    def __exit__(self, *args):
        if self._lifespan_owner is not None:
            self.close()
            self.portal = None
            return
        if getattr(self.app, self._owner_attribute, None) is not self:
            self.close()
            return
        try:
            for sibling in self._siblings:
                sibling.close()
                sibling.portal = None
            super().__exit__(*args)
        finally:
            delattr(self.app, self._owner_attribute)
            self.close()
