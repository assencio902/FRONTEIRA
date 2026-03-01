# Camada de serviço para usuários
from repositories.user_repository import UserRepository
from fastapi import Request, HTTPException

class UserService:
    @staticmethod
    def list_users(request: Request):
        user = getattr(request.state, "user", {})
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
        return UserRepository.list_users()

    @staticmethod
    def create_user(body, request: Request):
        user = getattr(request.state, "user", {})
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
        return UserRepository.create_user(body)

    @staticmethod
    def update_user(uid: int, body, request: Request):
        requester = getattr(request.state, "user", {})
        if requester.get("role") != "admin" and requester.get("sub") != uid:
            raise HTTPException(status_code=403, detail="Acesso negado")
        return UserRepository.update_user(uid, body)

    @staticmethod
    def delete_user(uid: int, request: Request):
        requester = getattr(request.state, "user", {})
        if requester.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
        return UserRepository.delete_user(uid)
