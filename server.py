from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
import uuid
from datetime import datetime, timezone


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

# Include the router in the main app
app.include_router(api_router)

# --- Debug endpoints for QA of the TikTok bot service layer ---
debug_router = APIRouter(prefix="/api/debug")
import tiktok_service as tk
import formatting as F
from urllib.parse import urlparse


def _akey(url):
    if not url:
        return ""
    seg = urlparse(url).path.rstrip("/").split("/")[-1]
    return seg.split("~")[0].split(".")[0] or seg


@debug_router.get("/profile/{username}")
async def dbg_profile(username: str):
    import time
    t0 = time.time()
    p = await tk.fetch_profile(username)
    took = round(time.time() - t0, 2)
    if not p:
        return {"ok": False, "took_sec": took}
    return {
        "ok": True,
        "took_sec": took,
        "uniqueId": p["uniqueId"],
        "nickname": p["nickname"],
        "followerCount": p["followerCount"],
        "videoCount": p["videoCount"],
        "avatar_key": _akey(p.get("avatar")),
        "storyStatus": p.get("storyStatus"),
        "card_len": len(F.profile_card(p)),
    }


@debug_router.get("/avatar-stable/{username}")
async def dbg_avatar_stable(username: str):
    """Fetch twice and confirm avatar_key is identical (false-change bug fix)."""
    p1 = await tk.fetch_profile(username)
    p2 = await tk.fetch_profile(username)
    if not p1 or not p2:
        return {"ok": False}
    k1, k2 = _akey(p1.get("avatar")), _akey(p2.get("avatar"))
    return {"ok": True, "stable": k1 == k2, "key1": k1, "key2": k2}


@debug_router.get("/posts/{username}")
async def dbg_posts(username: str):
    """Runs the posts fetch in a clean subprocess (avoids uvicorn's uvloop
    incompatibility with Playwright). This mirrors what the bot process does."""
    import asyncio as _a
    import json as _j
    import re
    if not re.match(r"^[\w.\-]{1,30}$", username):
        return {"ok": False, "error": "bad username"}
    try:
        import sys as _sys
        proc = await _a.create_subprocess_exec(
            _sys.executable, "posts_cli.py", username,
            cwd=str(ROOT_DIR), stdout=_a.subprocess.PIPE, stderr=_a.subprocess.PIPE,
        )
        out, _ = await _a.wait_for(proc.communicate(), timeout=90)
        line = out.decode().strip().splitlines()[-1] if out else "{}"
        return _j.loads(line)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@debug_router.get("/stories/{username}")
async def dbg_stories(username: str):
    s = await tk.fetch_stories(username)
    return {"ok": True, "count": len(s), "has_story": bool(s)}


app.include_router(debug_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()