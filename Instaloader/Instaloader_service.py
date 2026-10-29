import asyncio
import logging
import json
import re
from urllib.parse import urlparse
from typing import Optional, Tuple, Dict, Any

import requests
from bs4 import BeautifulSoup
import instaloader
from instaloader import Post
from TorPool import get_tor_pool

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

USE_PROXY = True
INSTAGRAM_APP_ID = "936619743392459"

BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "X-IG-App-ID": INSTAGRAM_APP_ID,
}


def parse_shortcode(url: str) -> str:
    """Extracts shortcode reliably across various URL formats."""
    match = re.search(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
    if match:
        return match.group(1)
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[-1] if parts else ""


def extract_from_embed_html(html_text: str, shortcode: str) -> Optional[Dict[str, Any]]:
    """Extracts media directly from embed HTML without tripping GraphQL limits."""
    # 1. Check if the post is marked broken/removed
    if "EmbedBrokenMedia" in html_text or "utm_campaign=invalid" in html_text:
        return None

    # 2. Try parsing contextJSON
    match = re.search(r'"contextJSON"\s*:\s*("(?:(?:\\.)|[^"\\])*")', html_text)
    if match:
        try:
            parsed = json.loads(json.loads(match.group(1)))
            media = parsed.get("gql_data", {}).get("shortcode_media")
            if media:
                caption = ""
                cap_edges = media.get("edge_media_to_caption", {}).get("edges", [])
                if cap_edges:
                    caption = cap_edges[0].get("node", {}).get("text", "")

                carousel = []
                for edge in media.get("edge_sidecar_to_children", {}).get("edges", []):
                    node = edge.get("node", {})
                    carousel.append({
                        "type": "video" if node.get("is_video") else "photo",
                        "url": node.get("video_url") if node.get("is_video") else node.get("display_url")
                    })

                is_video = media.get("is_video", False) or media.get("__typename") == "GraphVideo"
                return {
                    "code": shortcode,
                    "images": [media.get("display_url")] if not is_video and media.get("display_url") else [],
                    "video": media.get("video_url") if is_video else None,
                    "carousel": carousel,
                    "caption": caption,
                    "likes": media.get("edge_liked_by", {}).get("count", 0),
                    "comments": media.get("edge_media_to_comment", {}).get("count", 0),
                    "type": "carousel" if carousel else ("video" if is_video else "photo"),
                }
        except Exception:
            pass

    # 3. Fallback to OpenGraph meta tags
    soup = BeautifulSoup(html_text, "html.parser")
    og_img = soup.select_one('meta[property="og:image"]')
    og_vid = soup.select_one('meta[property="og:video"]')
    og_desc = soup.select_one('meta[property="og:description"]')

    if og_img or og_vid:
        return {
            "code": shortcode,
            "images": [og_img["content"]] if og_img else [],
            "video": og_vid["content"] if og_vid else None,
            "carousel": [],
            "caption": og_desc["content"] if og_desc else "",
            "likes": 0,
            "comments": 0,
            "type": "video" if og_vid else "photo",
        }

    return None


async def fetch_embed_stage(shortcode: str, proxies: dict) -> Optional[Dict[str, Any]]:
    """Stage 1: Attempts retrieval via embed page (least restrictive rate limits)."""
    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    try:
        resp = await asyncio.to_thread(
            requests.get,
            embed_url,
            headers=BROWSER_HEADERS,
            proxies=proxies,
            timeout=15
        )
        if resp.status_code == 200:
            return extract_from_embed_html(resp.text, shortcode)
        elif resp.status_code == 429:
            logger.warning("Embed endpoint returned 429 Too Many Requests")
    except Exception as err:
        logger.debug(f"Embed stage failed: {err}")
    return None


async def fetch_instaloader_stage(shortcode: str, proxies: dict) -> Tuple[Optional[Dict[str, Any]], int]:
    """Stage 2: Fallback to Instaloader with tuned session headers."""
    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        save_metadata=False,
        download_comments=False,
    )
    # Apply Tor proxy and standard browser headers
    loader.context._session.proxies.update(proxies)
    loader.context._session.headers.update(BROWSER_HEADERS)

    try:
        post = await asyncio.to_thread(Post.from_shortcode, loader.context, shortcode)
        
        data = {
            "code": shortcode,
            "images": [],
            "video": None,
            "carousel": [],
            "caption": post.caption or "",
            "likes": post.likes,
            "comments": post.comments,
            "type": "photo"
        }

        if post.typename == "GraphSidecar":
            data["type"] = "carousel"
            for node in post.get_sidecar_nodes():
                data["carousel"].append({
                    "type": "video" if node.is_video else "photo",
                    "url": node.video_url if node.is_video else node.display_url
                })
        elif post.is_video:
            data["type"] = "video"
            data["video"] = post.video_url
        else:
            data["type"] = "photo"
            data["images"] = [post.url]

        return data, 200

    except instaloader.exceptions.QueryReturnedBadRequestException:
        logger.warning(f"Instaloader 400 Bad Request / 429 Rate Limited on {shortcode}")
        return None, 429
    except instaloader.exceptions.PostNotFoundException:
        return None, 404
    except Exception as e:
        if "429" in str(e) or "Too Many Requests" in str(e):
            return None, 429
        logger.error(f"Instaloader failed for {shortcode}: {e}")
        return None, 500


async def extract_instagram_data(url: str):
    """
    Extracts post data by attempting the low-friction embed stage first,
    escalating to Instaloader only if necessary, with Tor circuit renewals.
    """
    shortcode = parse_shortcode(url)
    if not shortcode:
        return None, 400, None

    tor_pool = get_tor_pool()
    max_retries = 3

    for attempt in range(max_retries):
        proxies = {}
        idx = None

        if USE_PROXY:
            proxies, idx = await tor_pool.get_next_proxies()
            logger.info(f"[Attempt {attempt + 1}/{max_retries}] Tor Index {idx} for {shortcode}")

        # Stage 1: Fast embed retrieval (rarely triggers 429)
        data = await fetch_embed_stage(shortcode, proxies)
        if data and (data.get("images") or data.get("video") or data.get("carousel")):
            return data, 200, idx

        # Stage 2: Instaloader GraphQL retrieval
        data, status = await fetch_instaloader_stage(shortcode, proxies)
        if data:
            return data, 200, idx

        # Handle rate limiting specifically
        if status == 429:
            logger.warning(f"Tor exit node {idx} is burned by Instagram. Renewing circuit...")
            if USE_PROXY and idx is not None:
                await tor_pool.renew(idx)
            # Tor NEWNYM needs time to establish a new circuit
            await asyncio.sleep(2)
        elif status == 404:
            return None, 404, idx
        else:
            await asyncio.sleep(1)

    return None, 429, idx