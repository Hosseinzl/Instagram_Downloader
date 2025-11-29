# api_server.py
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, HttpUrl
import asyncio
import uvicorn
from typing import Optional
from service import download
from sqlite_db import init_db, async_log_request

app = FastAPI(title="Local Tor Downloader API", version="0.1")

# initialize sqlite DB for request logging
init_db()

class DownloadRequest(BaseModel):
    url: HttpUrl
    # optional max retries override
    tries: Optional[int] = None

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/download")
async def post_download(req: DownloadRequest):
    url = str(req.url)
    try:
        # call the existing async download function which now returns (result, status_code, tor_index)
        result, status, tor_index = await download(url, trys=1)
        # log the request outcome to sqlite (do not fail the request if logging fails)
        try:
            await async_log_request(url, tor_index, status)
        except Exception:
            pass

        if result is None:
            raise HTTPException(status_code=502, detail={"error": "no data", "status_code": status})
        return {"ok": True, "result": result, "status_code": status, "tor_index": tor_index}
    except Exception as e:
        await async_log_request(url, None, 500)
        raise HTTPException(status_code=500, detail={"error": str(e)})

# optional simple GET wrapper (for quick manual testing)
@app.get("/download")
async def get_download(url: str):
    try:
        result, status, tor_index = await download(url, trys=1)
        try:
            await async_log_request(url, tor_index, status)
        except Exception:
            pass
        if result is None:
            raise HTTPException(status_code=502, detail={"error": "no data", "status_code": status})
        return {"ok": True, "result": result, "status_code": status, "tor_index": tor_index}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})

if __name__ == "__main__":
    uvicorn.run("api_server:app", host="127.0.0.1", port=3000, log_level="info")
