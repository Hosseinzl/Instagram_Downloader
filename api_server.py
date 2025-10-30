# api_server.py
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, HttpUrl
import asyncio
import uvicorn
from typing import Optional

# فرض بر این است که فایل service.py همان دانلود async را دارد و نام تابع download است
# and torPool singleton already imported/used inside service.download
from service import download

app = FastAPI(title="Local Tor Downloader API", version="0.1")

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
    # اگر بخوای می‌تونی تعداد retries رو به download پاس بدی؛ الان تابع توی service
    # signature: async def download(url="", trys=1)
    try:
        # call the existing async download function
        result, status = await download(url, trys=1)
        if result is None:
            # مشخص کن چه خطایی پیش اومده؛ ممکنه service کد وضعیت رو برنگردونه
            raise HTTPException(status_code=502, detail={"error": "no data", "status_code": status})
        return {"ok": True, "result": result, "status_code": status}
    except Exception as e:
        # لاگ کردن خطا داخل سرور مفیده (اینجا فقط بازگشت به کلاینت)
        raise HTTPException(status_code=500, detail={"error": str(e)})

# optional simple GET wrapper (for quick manual testing)
@app.get("/download")
async def get_download(url: str):
    try:
        result, status = await download(url, trys=1)
        if result is None:
            raise HTTPException(status_code=502, detail={"error": "no data", "status_code": status})
        return {"ok": True, "result": result, "status_code": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e)})

if __name__ == "__main__":
    # Run only on local interface (127.0.0.1) so it's not exposed externally.
    uvicorn.run("api_server:app", host="127.0.0.1", port=3000, log_level="info")
