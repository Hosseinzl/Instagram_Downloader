import asyncio
import json
import logging
import re
import sys
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from TorPool import get_tor_pool

# Stealth instance and logging
stealth = Stealth()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

tor_pool = get_tor_pool()

INSTAGRAM_APP_ID = "936619743392459"


def default_headers() -> Dict[str, str]:
    return {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Encoding": "gzip",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "X-IG-App-ID": INSTAGRAM_APP_ID,
    }


def extract_shortcode(url: str) -> Optional[str]:
    """Safely extracts Instagram shortcode from /p/, /reel/, /reels/, or /tv/ paths."""
    match = re.search(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def clean_caption(raw_text: str) -> str:
    """
    Safely handles Persian/Arabic/UTF-8 captions and automatically
    repairs any Latin-1 / Windows-1252 Mojibake corruption.
    """
    if not raw_text:
        return ""

    text = str(raw_text).strip()

    # If the text was accidentally read as Latin-1/ISO-8859-1 (Mojibake), repair it:
    try:
        fixed = text.encode("latin-1").decode("utf-8")
        return fixed.strip()
    except (UnicodeEncodeError, UnicodeDecodeError):
        # Already valid UTF-8 (Persian characters cannot be encoded in latin-1)
        pass

    return text

def extract_context_json(html_text: str) -> Optional[Dict[str, Any]]:
    """Extracts contextJSON whether encoded as a JSON string or raw nested object."""
    # Match escaped JSON string: "contextJSON":"{...}"
    m_str = re.search(r'"contextJSON"\s*:\s*("(?:(?:\\.)|[^"\\])*")', html_text)
    if m_str:
        try:
            return json.loads(json.loads(m_str.group(1)))
        except Exception:
            pass

    # Match raw JSON object: "contextJSON":{...}
    m_obj = re.search(r'"contextJSON"\s*:\s*(\{.+?\})\s*,\s*"\w+"', html_text)
    if m_obj:
        try:
            return json.loads(m_obj.group(1))
        except Exception:
            pass

    return None


def parse_carousel(carousel_media: Optional[list] = None) -> list:
    if not carousel_media:
        return []
    items = []
    for m in carousel_media:
        orig_h = m.get("original_height")
        orig_w = m.get("original_width")
        image_versions = m.get("image_versions2", {}).get("candidates", [])
        video_versions = m.get("video_versions", [])
        media_type = m.get("media_type")

        if media_type != 2:
            matched = False
            for img in image_versions:
                if img.get("height") == orig_h and img.get("width") == orig_w:
                    items.append(img.get("url"))
                    matched = True
                    break
            if not matched and image_versions:
                items.append(image_versions[0].get("url"))
        else:
            if video_versions:
                items.append(video_versions[0].get("url"))
    return items


def parse_shortcode_media(media: Dict[str, Any]) -> Dict[str, Any]:
    """Builds standard normalized dictionary from GraphQL shortcode_media."""
    id_ = media.get("id")
    shortcode = media.get("shortcode")
    typename = media.get("__typename", "")

    # Extract caption
    caption = ""
    cap_edges = media.get("edge_media_to_caption", {}).get("edges", [])
    if cap_edges:
        caption = clean_caption(cap_edges[0].get("node", {}).get("text", ""))

    # Extract carousel items
    carousel = []
    sidecar_edges = media.get("edge_sidecar_to_children", {}).get("edges", [])
    if sidecar_edges:
        for edge in sidecar_edges:
            node = edge.get("node", {})
            if node.get("is_video"):
                v_url = node.get("video_url")
                if v_url:
                    carousel.append(v_url)
            else:
                resources = node.get("display_resources", [])
                img_src = resources[-1]["src"] if resources else node.get("display_url")
                if img_src:
                    carousel.append(img_src)
    elif media.get("display_url") and not media.get("video_url"):
        carousel.append(media.get("display_url"))

    # Extract single display images
    images = []
    if media.get("display_url"):
        images.append(media.get("display_url"))
    elif media.get("display_resources"):
        images.append(media["display_resources"][-1]["src"])

    owner = media.get("owner", {}).copy()
    for field in ["edge_owner_to_timeline_media", "edge_owner_to_timeline_video_media"]:
        owner.pop(field, None)

    is_video = typename == "GraphVideo" or media.get("is_video", False)
    post_type = "carousel" if typename == "GraphSidecar" else ("video" if is_video else "photo")

    return {
        "code": shortcode,
        "pk": id_,
        "id": id_,
        "images": images,
        "video": media.get("video_url"),
        "carousel": carousel,
        "caption": caption,
        "likes": media.get("edge_liked_by", {}).get("count", 0),
        "comments": media.get("edge_media_to_comment", {}).get("count", 0),
        "type": post_type,
        "owner": owner,
    }


def parse_post(source: str) -> Optional[Dict[str, Any]]:
    """Parses Instagram web responses including embedded JSON states or OpenGraph fallbacks."""
    # 1. Parse JSON response directly
    try:
        data = json.loads(source)
        items = (
            data.get("items")
            or data.get("graphql", {}).get("shortcode_media")
            or []
        )
        if isinstance(items, list) and items:
            it = items[0]
            carousel = parse_carousel(it.get("carousel_media", []))
            images = [
                img["url"] for img in it.get("image_versions2", {}).get("candidates", [])
                if img.get("height") == it.get("original_height") and img.get("width") == it.get("original_width")
            ]
            if not images and it.get("image_versions2", {}).get("candidates"):
                images.append(it["image_versions2"]["candidates"][0]["url"])

            video = it.get("video_versions", [{}])[0].get("url") if it.get("video_versions") else None
            cap_dict = it.get("caption") or {}
            media_type = it.get("media_type")

            return {
                "code": it.get("code"),
                "pk": it.get("pk"),
                "id": it.get("id"),
                "images": images,
                "video": video,
                "carousel": carousel,
                "caption": cap_dict.get("text", "") if isinstance(cap_dict, dict) else "",
                "likes": it.get("like_count", 0),
                "comments": it.get("comment_count", 0),
                "type": "carousel" if media_type == 8 else ("video" if media_type == 2 else "photo"),
                "media_type": media_type,
            }
        elif isinstance(items, dict):
            return parse_shortcode_media(items)
    except Exception:
        pass

    # 2. Parse script tags inside HTML
    soup = BeautifulSoup(source, "html.parser")
    for s in soup.find_all("script", type="application/json"):
        ms = s.string or ""
        if "xdt_api__v1__media__shortcode__web_info" in ms:
            try:
                obj = json.loads(ms.strip())
                items_path = obj["require"][0][3][0]["__bbox"]["require"][0][3][1]["__bbox"]["result"]["data"]["xdt_api__v1__media__shortcode__web_info"]["items"]
                for it in items_path:
                    images = [
                        img["url"] for img in it.get("image_versions2", {}).get("candidates", [])
                        if img.get("height") == it.get("original_height") and img.get("width") == it.get("original_width")
                    ]
                    video = it.get("video_versions", [{}])[0].get("url") if it.get("video_versions") else None
                    caption = it.get("caption") or {}
                    media_type = it.get("media_type")

                    return {
                        "code": it.get("code"),
                        "pk": it.get("pk"),
                        "id": it.get("id"),
                        "images": images,
                        "video": video,
                        "carousel": parse_carousel(it.get("carousel_media", [])),
                        "caption": caption.get("text", "") if isinstance(caption, dict) else "",
                        "likes": it.get("like_count", 0),
                        "comments": it.get("comment_count", 0),
                        "type": "carousel" if media_type == 8 else ("video" if media_type == 2 else "photo"),
                        "media_type": media_type,
                    }
            except (KeyError, IndexError, json.JSONDecodeError):
                continue

    # 3. OpenGraph fallback
    og_img = soup.select_one('meta[property="og:image"]')
    og_vid = soup.select_one('meta[property="og:video"]')
    og_desc = soup.select_one('meta[property="og:description"]')
    if og_img or og_vid:
        img_url = og_img.get("content") if og_img else None
        vid_url = og_vid.get("content") if og_vid else None
        return {
            "code": None,
            "pk": None,
            "id": None,
            "images": [img_url] if img_url else [],
            "video": vid_url,
            "carousel": [],
            "caption": og_desc.get("content", "") if og_desc else "",
            "likes": 0,
            "comments": 0,
            "type": "video" if vid_url else "photo",
        }

    return None


async def alter1reels(url: str = "") -> Tuple[Optional[Dict[str, Any]], Optional[int], Optional[int]]:
    """Playwright stealth scraper fallback."""
    idx = None
    try:
        proxies, idx = await tor_pool.get_next_proxies()
        socks_url = proxies.get("http", proxies.get("https", "socks5h://127.0.0.1:9050"))
        socks_port = socks_url.split(":")[-1]
    except Exception:
        socks_port = "9050"

    logger.info("alter1reels: using tor index=%s socks_port=%s", idx, socks_port)
    browser_args = ["--no-sandbox", f"--proxy-server=socks5://127.0.0.1:{socks_port}"]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=browser_args)
        page = await browser.new_page()
        await stealth.apply_stealth_async(page)

        result: Dict[str, Any] = {"resolved": None}

        async def handle_response(response):
            if "/api/convert" in response.url:
                try:
                    data = await response.json()
                    urls = data.get("url", [])
                    meta = data.get("meta", {})
                    video = urls[0]["url"] if urls else ""
                    result["resolved"] = {
                        "code": meta.get("shortcode", ""),
                        "images": [],
                        "video": video,
                        "carousel": [],
                        "caption": meta.get("title", ""),
                        "likes": meta.get("like_count", 0),
                        "comments": meta.get("comment_count", 0),
                        "type": "video",
                    }
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            await page.goto("https://sssinstagram.com/reels-downloader", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(1)

            await page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const consentBtn = buttons.find(btn => btn.textContent.includes('Consent'));
                    if (consentBtn) consentBtn.click();
                }
            """)
            await page.fill("#input", url)
            await page.click(".form__submit")
            await asyncio.sleep(3)

            start_time = time.time()
            while time.time() - start_time < 15 and not result["resolved"]:
                await asyncio.sleep(0.2)

            return result["resolved"], 200, idx
        except Exception as err:
            logger.error("alter1reels failed: %s", err)
            return None, None, idx
        finally:
            await page.close()
            await browser.close()


async def download2(
    short_code: str = "",
    proxies: Optional[Dict[str, str]] = None,
    idx: Optional[int] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[int], Optional[int]]:
    """Async wrapper around Instagram web info endpoint."""
    if not proxies:
        try:
            proxies, idx = await tor_pool.get_next_proxies()
        except Exception:
            proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}

    # Query with API parameters for JSON payload
    req_url = f"https://www.instagram.com/p/{short_code}/?__a=1&__d=dis"
    logger.info("Request download2: url=%s tor_index=%s", req_url, idx)

    try:
        response = await asyncio.to_thread(
            requests.get,
            req_url,
            headers=default_headers(),
            proxies=proxies,
            timeout=25,
        )
        parsed = parse_post(response.text)
        if parsed and (parsed.get("images") or parsed.get("video") or parsed.get("carousel")):
            return parsed, response.status_code, idx
    except Exception as err:
        logger.warning("download2 failed for shortcode=%s: %s", short_code, err)

    return None, None, idx


async def download(url: str = "", trys: int = 1) -> Tuple[Optional[Dict[str, Any]], Optional[int], Optional[int]]:
    """Primary fetch method utilizing embed extraction and automatic multi-stage fallbacks."""
    shortcode = extract_shortcode(url)
    if not shortcode:
        logger.error("Could not extract shortcode from url: %s", url)
        return None, None, None

    furl = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    idx = None
    try:
        proxies, idx = await tor_pool.get_next_proxies()
    except Exception:
        proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}

    try:
        logger.info("GET embed attempt %d: url=%s tor_index=%s", trys, furl, idx)
        response = await asyncio.to_thread(
            requests.get,
            furl,
            headers=default_headers(),
            proxies=proxies,
            timeout=25,
        )
        status_code = response.status_code
        data = response.text

        # 1. Guard against broken or deleted post embeds
        soup = BeautifulSoup(data, "html.parser")
        if soup.select_one(".EmbedBrokenMedia"):
            logger.warning("Embed returned EmbedBrokenMedia for shortcode=%s", shortcode)
            # Escalate to direct download2 instead of failing or returning empty data
            res_d2, sc_d2, idx_d2 = await download2(shortcode, proxies=proxies, idx=idx)
            if res_d2:
                return res_d2, sc_d2, idx_d2
            raise ValueError("Post is removed, private, or blocked by Instagram.")

        # 2. Extract and parse contextJSON
        parsed_context = extract_context_json(data)
        if parsed_context:
            media = parsed_context.get("gql_data", {}).get("shortcode_media", {})
            if media:
                data_dict = parse_shortcode_media(media)
                if data_dict.get("images") or data_dict.get("video") or data_dict.get("carousel"):
                    return data_dict, status_code, idx

        # 3. Check OpenGraph tags within embed HTML
        og_fallback = parse_post(data)
        if og_fallback and (og_fallback.get("images") or og_fallback.get("video")):
            return og_fallback, status_code, idx

        raise ValueError("Failed to extract media attributes from embed response.")

    except Exception as err:
        logger.warning("Instagram embed attempt %d failed: %s", trys, err)

    # 4. Multi-stage Fallback and Retry Pipeline
    if trys == 1:
        logger.info("Escalating to download2 fallback for %s...", shortcode)
        result2, sc2, idx2 = await download2(shortcode, proxies=proxies, idx=idx)
        if result2:
            return result2, sc2, idx2

    if trys == 2:
        logger.info("Escalating to alter1reels Playwright fallback for %s...", url)
        result_alt, sc_alt, idx_alt = await alter1reels(url)
        if result_alt:
            return result_alt, sc_alt, idx_alt

    if trys < 3:
        try:
            logger.info("Renewing TOR identity on index %s...", idx)
            await tor_pool.renew(idx)
        except Exception:
            pass
        await asyncio.sleep(1)
        return await download(url, trys + 1)

    logger.error("All extraction stages exhausted for URL: %s", url)
    return None, None, idx