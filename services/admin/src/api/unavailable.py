from fastapi import HTTPException


def dependency_not_configured(dependency: str, capability: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "NOT_CONFIGURED",
            "message": f"{dependency} does not expose the {capability} contract",
            "dependency": dependency,
            "capability": capability,
        },
    )
