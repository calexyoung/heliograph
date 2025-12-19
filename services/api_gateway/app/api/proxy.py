"""Proxy routes for backend services."""

from fastapi import APIRouter, Depends, Request, Response

from services.api_gateway.app.middleware.auth import CurrentUser
from services.api_gateway.app.routing.proxy import ServiceProxy

router = APIRouter(tags=["Backend Services"])


def get_service_proxy() -> ServiceProxy:
    """Get service proxy dependency."""
    return ServiceProxy()


# Document Registry routes
@router.api_route(
    "/documents",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_documents_base(
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy requests to Document Registry service (base path)."""
    return await proxy.forward_request(
        service="document-registry",
        path="/registry/documents",
        request=request,
    )


@router.api_route(
    "/documents/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
    include_in_schema=False,
)
async def proxy_documents(
    path: str,
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy requests to Document Registry service."""
    return await proxy.forward_request(
        service="document-registry",
        path=f"/registry/documents/{path}",
        request=request,
    )


# Ingestion Service routes (search/import)
@router.api_route(
    "/search",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_search_base(
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy search requests to Ingestion Service (base path)."""
    return await proxy.forward_request(
        service="ingestion",
        path="/api/v1/search",
        request=request,
    )


@router.api_route(
    "/search/{path:path}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_search(
    path: str,
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy search requests to Ingestion Service."""
    return await proxy.forward_request(
        service="ingestion",
        path=f"/api/v1/search/{path}",
        request=request,
    )


@router.api_route(
    "/import",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_import_base(
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy import requests to Ingestion Service (base path)."""
    return await proxy.forward_request(
        service="ingestion",
        path="/api/v1/import",
        request=request,
    )


@router.api_route(
    "/import/{path:path}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_import(
    path: str,
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy import requests to Ingestion Service."""
    return await proxy.forward_request(
        service="ingestion",
        path=f"/api/v1/import/{path}",
        request=request,
    )


# Query Orchestrator routes
@router.api_route(
    "/query",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_query_base(
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy query requests to Query Orchestrator (base path)."""
    return await proxy.forward_request(
        service="query-orchestrator",
        path="/api/v1/query",
        request=request,
    )


@router.api_route(
    "/query/{path:path}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_query(
    path: str,
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy query requests to Query Orchestrator."""
    return await proxy.forward_request(
        service="query-orchestrator",
        path=f"/api/v1/query/{path}",
        request=request,
    )


# Knowledge Extraction routes (graph)
@router.api_route(
    "/graph",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_graph_base(
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy graph requests to Knowledge Extraction Service (base path)."""
    return await proxy.forward_request(
        service="knowledge-extraction",
        path="/api/v1/graph",
        request=request,
    )


@router.api_route(
    "/graph/{path:path}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def proxy_graph(
    path: str,
    request: Request,
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> Response:
    """Proxy graph requests to Knowledge Extraction Service."""
    return await proxy.forward_request(
        service="knowledge-extraction",
        path=f"/api/v1/graph/{path}",
        request=request,
    )


# Circuit breaker status (admin only)
@router.get("/admin/circuit-breakers")
async def get_circuit_breaker_status(
    current_user: CurrentUser,
    proxy: ServiceProxy = Depends(get_service_proxy),
) -> dict:
    """Get circuit breaker status for all services (admin only)."""
    if not current_user.is_superuser:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return proxy.get_circuit_states()
