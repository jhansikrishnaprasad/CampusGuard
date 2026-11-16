from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .. import config
from ..database import get_db
from ..models import User
from ..security import (admin_user, create_session, current_user, drop_session, hash_password,
                        throttle_check, throttle_clear, throttle_fail, verify_password)
from .common import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)
    role: str = Field(default="reviewer", pattern="^(admin|reviewer)$")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else 'local'}:{body.username.lower()}"
    throttle_check(key)
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        throttle_fail(key)
        audit(db, body.username[:64], "login_failed"); db.commit()
        raise HTTPException(401, "Invalid username or password")
    throttle_clear(key)
    token = create_session(db, user)
    response.set_cookie("session", token, httponly=True, samesite="lax", secure=config.COOKIE_SECURE,
                        max_age=config.SESSION_HOURS * 3600)
    audit(db, user.username, "login"); db.commit()
    return {"username": user.username, "role": user.role}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    t = request.cookies.get("session")
    if t:
        drop_session(db, t)
    response.delete_cookie("session")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"username": user.username, "role": user.role, "login_required": config.REQUIRE_LOGIN, "can_shutdown": bool(config.ALLOW_SHUTDOWN)}


@router.post("/users", status_code=201)
def create_user(body: UserIn, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, "Username already exists")
    db.add(User(username=body.username, password_hash=hash_password(body.password), role=body.role))
    audit(db, admin.username, "user_created", body.username, body.role)
    db.commit()
    return {"username": body.username, "role": body.role}
