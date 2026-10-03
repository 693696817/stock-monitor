from fastapi import HTTPException, Request

from auth import get_current_user

def require_admin(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
