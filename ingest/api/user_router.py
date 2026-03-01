# Camada de API (rota) para usuários
from fastapi import APIRouter, Request, Depends
from services.user_service import UserService
from main import CreateUserRequest, UpdateUserRequest

router = APIRouter(prefix="/api/v1/users", tags=["users"])

@router.get("/")
async def list_users(request: Request):
    return UserService.list_users(request)

@router.post("/", status_code=201)
async def create_user(body: CreateUserRequest, request: Request):
    return UserService.create_user(body, request)

@router.put("/{uid}")
async def update_user(uid: int, body: UpdateUserRequest, request: Request):
    return UserService.update_user(uid, body, request)

@router.delete("/{uid}", status_code=204)
async def delete_user(uid: int, request: Request):
    return UserService.delete_user(uid, request)
