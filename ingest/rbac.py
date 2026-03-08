"""RBAC helpers do BPFRON com papéis em português e compatibilidade legada."""

from enum import Enum
from typing import List

from fastapi import HTTPException, Request


class Role(str, Enum):
    """Papéis oficiais do sistema."""

    ADMIN = "admin"
    OPERADOR = "operador"
    VISUALIZADOR = "visualizador"


ROLE_ALIASES = {
    "admin": Role.ADMIN.value,
    "administrador": Role.ADMIN.value,
    "operador": Role.OPERADOR.value,
    "operador(a)": Role.OPERADOR.value,
    "visualizador": Role.VISUALIZADOR.value,
    # Compatibilidade com valores antigos
    "operator": Role.OPERADOR.value,
    "viewer": Role.VISUALIZADOR.value,
    "visualizacao": Role.VISUALIZADOR.value,
    "visualização": Role.VISUALIZADOR.value,
}


VALID_ROLES = {Role.ADMIN.value, Role.OPERADOR.value, Role.VISUALIZADOR.value}


def normalize_role(role: str | None) -> str:
    """Normaliza papéis legados para os papéis oficiais."""

    key = str(role or "").strip().lower()
    return ROLE_ALIASES.get(key, Role.VISUALIZADOR.value)


def normalize_role_input(role: str | None) -> str:
    """Normaliza entrada de formulário/API sem fallback permissivo."""

    key = str(role or "").strip().lower()
    return ROLE_ALIASES.get(key, key)


# ============================================================
# VALIDAÇÃO DE AUTENTICAÇÃO E AUTORIZAÇÃO
# ============================================================

def require_auth(request: Request) -> dict:
    """
    Valida autenticação básica. Retorna payload do JWT.
    Lança 401 se não autenticado.
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    user["role"] = normalize_role(user.get("role"))
    return user


def require_role(request: Request, *allowed_roles: str) -> dict:
    """
    Valida autenticação e autorização por role.
    Aceita múltiplos roles permitidos.
    
    Exemplo:
        require_role(request, "admin", "operador")
        require_role(request, Role.ADMIN.value)
    """
    user = require_auth(request)
    user_role = normalize_role(user.get("role"))
    allowed_normalized = tuple(normalize_role(r) for r in allowed_roles)
    
    if user_role not in allowed_normalized:
        raise HTTPException(
            status_code=403,
            detail=f"Permissão negada. Perfis permitidos: {', '.join(allowed_normalized)}"
        )
    user["role"] = user_role
    return user


def is_admin(request: Request) -> bool:
    """Verifica se user é admin"""
    user = getattr(request.state, "user", {})
    return normalize_role(user.get("role")) == Role.ADMIN.value


def is_admin_or_operator(request: Request) -> bool:
    """Verifica se user é admin ou operador."""
    user = getattr(request.state, "user", {})
    role = normalize_role(user.get("role"))
    return role in (Role.ADMIN.value, Role.OPERADOR.value)


def is_operator(request: Request) -> bool:
    """Verifica se user é operador."""
    user = getattr(request.state, "user", {})
    return normalize_role(user.get("role")) == Role.OPERADOR.value


def is_viewer(request: Request) -> bool:
    """Verifica se user está autenticado em qualquer papel válido."""
    user = getattr(request.state, "user", {})
    return normalize_role(user.get("role")) in (
        Role.VISUALIZADOR.value,
        Role.OPERADOR.value,
        Role.ADMIN.value,
    )


def assert_admin(request: Request, message: str = "Acesso restrito a administradores"):
    """Lança 403 se não for admin"""
    if not is_admin(request):
        raise HTTPException(status_code=403, detail=message)


def assert_admin_or_operator(request: Request, message: str = "Acesso negado"):
    """Lança 403 se não for admin ou operador."""
    if not is_admin_or_operator(request):
        raise HTTPException(status_code=403, detail=message)


def assert_authenticated(request: Request, message: str = "Não autenticado"):
    """Lança 401 se não autenticado"""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail=message)


# ============================================================
# MAPA DE ACESSO POR ROTA (DOCUMENTAÇÃO)
# ============================================================

ROUTE_ACCESS_MAP = {
    # AUTH - Público + Autenticado
    "POST /api/auth/login": ["public"],
    "GET /api/auth/me": ["admin", "operador", "visualizacao"],
    "PUT /api/auth/password": ["admin", "operador", "visualizacao"],
    
    # USUÁRIOS - Admin only
    "GET /api/users": ["admin"],
    "POST /api/users": ["admin"],
    "PUT /api/users/{uid}": ["admin"],
    "DELETE /api/users/{uid}": ["admin"],
    
    # CÂMERAS - Leitura para todos, criar/editar/deletar apenas admin
    "GET /api/cameras": ["admin", "operador", "visualizacao"],
    "GET /api/cameras/status": ["admin", "operador", "visualizacao"],
    "POST /api/cameras": ["admin"],
    "PUT /api/cameras/{cam_id}": ["admin"],
    "DELETE /api/cameras/{cam_id}": ["admin"],
    
    # EVENTOS - Leitura para todos
    "GET /api/events": ["admin", "operador", "visualizacao"],
    "GET /api/events/{event_id}": ["admin", "operador", "visualizacao"],
    "GET /api/events/{event_id}/image": ["admin", "operador", "visualizacao"],
    "GET /api/events/{event_id}/thumbnail": ["admin", "operador", "visualizacao"],
    
    # STATS - Leitura para todos
    "GET /api/stats/*": ["admin", "operador", "visualizacao"],
    
    # ALVOS - Leitura para todos, criar/editar admin+operador, deletar admin
    "GET /api/alvos": ["admin", "operador", "visualizacao"],
    "GET /api/alvos/recentes": ["admin", "operador", "visualizacao"],
    "POST /api/alvos": ["admin", "operador"],
    "PUT /api/alvos/{aid}": ["admin", "operador"],
    "DELETE /api/alvos/{aid}": ["admin"],
    "POST /api/alvos/import-list/{list_id}": ["admin", "operador"],
    
    # VEÍCULOS/LISTAS - Leitura para todos, criar/editar admin+operador, deletar admin
    "GET /api/vehicles": ["admin", "operador", "visualizacao"],
    "GET /api/vehicles/allplates": ["admin", "operador", "visualizacao"],
    "GET /api/vehicles/lists": ["admin", "operador", "visualizacao"],
    "POST /api/vehicles": ["admin", "operador"],
    "PUT /api/vehicles/{vid}": ["admin", "operador"],
    "DELETE /api/vehicles/{vid}": ["admin"],
    "POST /api/vehicles/lists": ["admin", "operador"],
    "PUT /api/vehicles/lists/{list_id}": ["admin", "operador"],
    "DELETE /api/vehicles/lists/{list_id}": ["admin"],
    
    # BATEDOR - Leitura para todos
    "GET /api/batedor/*": ["admin", "operador", "visualizacao"],
    
    # TRAJETÓRIA, COMPANIONS - Leitura para todos
    "GET /api/vehicles/{plate}/trajectory": ["admin", "operador", "visualizacao"],
    "GET /api/vehicles/{plate}/companions": ["admin", "operador", "visualizacao"],
    
    # RELATÓRIOS - Leitura para todos, decisões admin+operador
    "GET /api/vehicle/report": ["admin", "operador", "visualizacao"],
    "POST /api/vehicle/report/decision": ["admin", "operador"],
    "GET /api/vehicle/report/decisions": ["admin", "operador", "visualizacao"],
    "GET /api/comboio/report": ["admin", "operador", "visualizacao"],
    "POST /api/comboio/confirm": ["admin", "operador"],
    "POST /api/comboio/false_positive": ["admin", "operador"],
    
    # ALARMES - Leitura para todos, criar/editar/deletar/testar admin
    "GET /api/alarmes": ["admin"],
    "POST /api/alarmes": ["admin"],
    "PUT /api/alarmes/{aid}": ["admin"],
    "DELETE /api/alarmes/{aid}": ["admin"],
    "POST /api/alarmes/{aid}/test": ["admin"],
    "GET /api/alarmes/historico": ["admin"],
    "POST /api/alarmes/historico/{alert_id}/read": ["admin"],
    
    # FCM - Próprio token + admin pode gerenciar
    "POST /api/fcm/register-token": ["admin", "operador", "visualizacao"],
    "GET /api/fcm/my-token-status": ["admin", "operador", "visualizacao"],
    "GET /api/fcm/status": ["admin"],
    "POST /api/fcm/send-alert": ["admin"],
}


def get_allowed_roles(route: str) -> List[str]:
    """Retorna roles permitidos para uma rota (consultivo)"""
    return ROUTE_ACCESS_MAP.get(route, ["admin"])
