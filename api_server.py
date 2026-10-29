import asyncio
import logging
import random
from typing import Any, Dict, Optional, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

from sqlite_db import async_log_request, init_db

# ---------------------------------------------------------------------------
# Imports from both services
# ---------------------------------------------------------------------------
from direct_http.service import download as direct_http_download
from Instaloader.Instaloader_service import extract_instagram_data as instaloader_download

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("api_server")

app = FastAPI(title="Local Tor Downloader API", version="0.2")

# Initialize sqlite DB for request logging
init_db()


class DownloadRequest(BaseModel):
    url: HttpUrl
    tries: Optional[int] = None


async def execute_download_pipeline(url: str) -> Tuple[Dict[str, Any], int, Optional[int], str]:
    """
    Randomly selects either direct_http or Instaloader.
    If the chosen service fails or returns no data, fails over to the other.
    """
    services = [
        ("direct_http", direct_http_download),
        ("instaloader", instaloader_download),
    ]

    # Randomize order for 50/50 load balancing
    random.shuffle(services)

    last_status = 502
    last_tor_index = None
    last_error_msg = "Unknown error"

    for service_name, service_func in services:
        logger.info(f"Dispatching request for {url} using [{service_name}]")
        try:
            result, status, tor_index = await service_func(url)
            last_status = status or last_status
            last_tor_index = tor_index

            # Check if extraction was successful
            if result and (result.get("images") or result.get("video") or result.get("carousel")):
                logger.info(f"[{service_name}] succeeded for {url}")
                return result, status or 200, tor_index, service_name

            logger.warning(
                f"[{service_name}] returned empty data (status={status}). Escalating to fallback..."
            )
            last_error_msg = f"{service_name} returned empty data"

        except Exception as exc:
            logger.error(f"[{service_name}] encountered exception: {exc}. Escalating to fallback...")
            last_error_msg = str(exc)

    # Both services failed
    raise HTTPException(
        status_code=502,
        detail={
            "error": "All download services failed",
            "last_error": last_error_msg,
            "status_code": last_status,
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/download")
async def post_download(req: DownloadRequest):
    url = str(req.url)
    tor_index = None
    status = 500
    try:
        result, status, tor_index, service_used = await execute_download_pipeline(url)

        try:
            await async_log_request(url, tor_index, status)
        except Exception:
            pass

        return {
            "ok": True,
            "result": result,
            "status_code": status,
            "tor_index": tor_index,
            "service_used": service_used,
        }

    except HTTPException as http_exc:
        try:
            await async_log_request(url, tor_index, http_exc.status_code)
        except Exception:
            pass
        raise http_exc

    except Exception as e:
        try:
            await async_log_request(url, None, 500)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail={"error": str(e)})


@app.get("/download")
async def get_download(url: str):
    tor_index = None
    status = 500
    try:
        result, status, tor_index, service_used = await execute_download_pipeline(url)

        try:
            await async_log_request(url, tor_index, status)
        except Exception:
            pass

        return {
            "ok": True,
            "result": result,
            "status_code": status,
            "tor_index": tor_index,
            "service_used": service_used,
        }

    except HTTPException as http_exc:
        try:
            await async_log_request(url, tor_index, http_exc.status_code)
        except Exception:
            pass
        raise http_exc

    except Exception as e:
        try:
            await async_log_request(url, None, 500)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail={"error": str(e)})


if __name__ == "__main__":
    uvicorn.run("api_server:app", host="127.0.0.1", port=3000, log_level="info")