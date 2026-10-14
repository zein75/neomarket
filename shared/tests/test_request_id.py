from shared.utils.request_id import RequestIdMiddleware


def test_request_id_middleware_is_available():
    assert RequestIdMiddleware is not None
