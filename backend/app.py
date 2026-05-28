import os
import secrets
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
import httpx

load_dotenv()

TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
TIKTOK_REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "")
TIKTOK_SCOPES = os.getenv(
    "TIKTOK_SCOPES", "user.info.basic,video.upload,video.list"
)

if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET or not TIKTOK_REDIRECT_URI:
    # Não levantamos erro aqui para permitir que você veja o app subindo,
    # mas as rotas de auth vão falhar com mensagem clara.
    print("[WARN] TikTok env vars not fully configured.")

app = FastAPI(title="XGPostiz TikTok backend")

# Armazenamento em memória apenas para demo/sandbox.
STATE_TOKENS = set()
LATEST_ACCESS_TOKEN: Optional[str] = None
LATEST_OPEN_ID: Optional[str] = None


@app.get("/")
async def root():
    return {"status": "ok", "message": "XGPostiz TikTok backend running"}


@app.get("/auth")
async def auth():
    if not (TIKTOK_CLIENT_KEY and TIKTOK_REDIRECT_URI):
        raise HTTPException(
            status_code=500,
            detail="TikTok client key/redirect URI not configured. Check .env.",
        )

    state = secrets.token_urlsafe(16)
    STATE_TOKENS.add(state)

    # Conforme Login Kit Web docs
    # https://developers.tiktok.com/doc/login-kit-web/
    params = {
        "client_key": TIKTOK_CLIENT_KEY,
        "scope": TIKTOK_SCOPES,
        "response_type": "code",
        "redirect_uri": TIKTOK_REDIRECT_URI,
        "state": state,
    }

    from urllib.parse import urlencode

    query = urlencode(params)
    url = f"https://www.tiktok.com/v2/auth/authorize/?{query}"
    return RedirectResponse(url)


@app.get("/callback")
async def callback(request: Request):
    global LATEST_ACCESS_TOKEN, LATEST_OPEN_ID

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return JSONResponse({"error": error}, status_code=400)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state.")

    if state not in STATE_TOKENS:
        raise HTTPException(status_code=400, detail="Invalid state.")

    STATE_TOKENS.discard(state)

    # Troca code por access_token, conforme OAuth docs
    # https://developers.tiktok.com/doc/oauth-user-access-token-management
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    payload = {
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": TIKTOK_REDIRECT_URI,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(token_url, json=payload)

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Error fetching access token: {resp.text}",
        )

    data = resp.json()
    # TikTok retorna access_token, open_id etc.
    LATEST_ACCESS_TOKEN = data.get("access_token")
    LATEST_OPEN_ID = data.get("open_id")

    return {
        "message": "Authorization successful.",
        "open_id": LATEST_OPEN_ID,
        "scopes": data.get("scopes"),
        "expires_in": data.get("expires_in"),
    }


@app.post("/upload-test")
async def upload_test():
    if not LATEST_ACCESS_TOKEN or not LATEST_OPEN_ID:
        raise HTTPException(
            status_code=400,
            detail="No access token in memory. Run /auth flow first.",
        )

    # Endpoint e payload baseados na Content Posting API guide
    # https://developers.tiktok.com/doc/content-posting-api-get-started
    # e upload reference
    # https://developers.tiktok.com/doc/content-posting-api-reference-upload-video

    init_url = (
        "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
    )

    # Por simplicidade, usamos PULL_FROM_URL;
    # depois você pode ajustar para FILE_UPLOAD se preferir.
    test_video_url = os.getenv(
        "TIKTOK_TEST_VIDEO_URL",
        "https://xavier-guilherme.github.io/xgpostiz-legal/sample-video.mp4",
    )

    headers = {"Authorization": f"Bearer {LATEST_ACCESS_TOKEN}"}

    payload = {
        "post_mode": "PUBLISH_INBOX",  # ou PUBLISH_NOW, dependendo da config
        "media_type": "VIDEO",
        "source": "PULL_FROM_URL",
        "video_url": test_video_url,
        "post_info": {
            "title": "XGPostiz API demo",
            "disable_duet": False,
            "disable_stitch": False,
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(init_url, json=payload, headers=headers)

    return {
        "status_code": resp.status_code,
        "response": resp.json() if resp.content else {},
    }
