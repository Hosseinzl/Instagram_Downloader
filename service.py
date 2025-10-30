import asyncio
import logging
import requests
import json
import re
import time
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from TorPool import get_tor_pool

# create a reusable Stealth instance
stealth = Stealth()

# module logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

# Tor pool singleton used by this module
tor_pool = get_tor_pool()

def decode_unicode(s):
    # In Python, JSON parsing can handle unicode escapes
    return json.loads(f'"{s}"')

def sleep(ms):
    time.sleep(ms / 1000)

async def alter1reels(url=""):
    async with async_playwright() as p:

        # linux
        browser = await p.chromium.launch(
            headless=True,
            executable_path="/snap/bin/chromium",  # Adjust if needed
            args=["--no-sandbox", "--proxy-server=socks://127.0.0.1:9050"]
        )

        # windows
        # pick a socks port from the tor pool for this browser instance
        try:
            proxies, idx = await tor_pool.get_next_proxies()
            # proxies are like 'socks5h://127.0.0.1:9050'
            socks_url = proxies.get("http", "socks5h://127.0.0.1:9050")
            socks_port = socks_url.split(":")[-1]
        except Exception:
            socks_port = "9050"

        # browser = await p.chromium.launch(
        #     headless=True,
        #     args=["--no-sandbox", f"--proxy-server=socks://127.0.0.1:{socks_port}"]
        # )

        page = await browser.new_page()
        # apply Playwright stealth evasions to the created page
        await stealth.apply_stealth_async(page)

        result = {"resolved": None}

        async def handle_response(response):
            url_r = response.url
            if "/api/convert" in url_r:
                try:
                    data = await response.json()
                    urls = data.get("url", [])
                    meta = data.get("meta", {})
                    comment_count = meta.get("comment_count", 0)
                    like_count = meta.get("like_count", 0)
                    title = meta.get("title", "")
                    shortcode = meta.get("shortcode", "")
                    video = urls[0]["url"] if urls else ""
                    result["resolved"] = {
                        "code": shortcode,
                        "images": [],
                        "video": video,
                        "carousel": [],
                        "caption": title,
                        "likes": like_count,
                        "comments": comment_count,
                        "type": "video"
                    }
                except Exception as err:
                    pass

        page.on("response", handle_response)

        try:
            await page.goto("https://sssinstagram.com/reels-downloader", wait_until="networkidle")
            await sleep(1000)
            # Handle consent button
            await page.evaluate("""
                () => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const consentBtn = buttons.find(btn => btn.textContent.includes('Consent'));
                    if (consentBtn) {
                        consentBtn.click();
                    }
                }
            """)
            await page.type("#input", url)
            await page.click(".form__submit")
            await sleep(3000)

            # Wait up to 15 seconds for resolution
            start_time = time.time()
            while time.time() - start_time < 15 and not result["resolved"]:
                await asyncio.sleep(0.1)

            await page.close()
            await browser.close()
            return result["resolved"]
        except Exception as err:
            print(f"instagram (alter1reels): {err}")
            await page.close()
            await browser.close()
            return None

def default_headers():
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip",
        "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

def _log_request_start(url, idx=None):
    try:
        logger.info("Request start: url=%s tor_index=%s", url, str(idx))
    except Exception:
        pass

def parse_carousel(carousel_media=None):
    if carousel_media is None:
        carousel_media = []
    items = []
    for m in carousel_media:
        original_height = m.get("original_height")
        original_width = m.get("original_width")
        image_versions2 = m.get("image_versions2", {}).get("candidates", [])  # Adjusted for structure
        video_versions = m.get("video_versions", [])
        media_type = m.get("media_type")
        if media_type != 2:
            for img in image_versions2:
                url = img.get("url")
                height = img.get("height")
                width = img.get("width")
                if height == original_height and width == original_width:
                    items.append(url)
        else:
            if video_versions:
                items.append(video_versions[0].get("url"))
    return items

def parse_post(source=""):
    soup = BeautifulSoup(source, "html.parser")
    obj = None
    final_items = []
    for s in soup.find("body").find_all("script"):
        if s.get("type") == "application/json":
            ms = s.string.strip()
            if "xdt_api__v1__media__shortcode__web_info" in ms:
                obj = json.loads(ms)
                # Navigate the nested structure carefully
                try:
                    items_path = obj["require"][0][3][0]["__bbox"]["require"][0][3][1]["__bbox"]["result"]["data"]["xdt_api__v1__media__shortcode__web_info"]["items"]
                    for it in items_path:
                        code = it.get("code")
                        pk = it.get("pk")
                        id_ = it.get("id")
                        video_versions = it.get("video_versions", [])
                        image_versions2 = it.get("image_versions2", {}).get("candidates", [])
                        caption = it.get("caption")
                        like_count = it.get("like_count", 0)
                        comment_count = it.get("comment_count", 0)
                        media_type = it.get("media_type")
                        original_height = it.get("original_height")
                        original_width = it.get("original_width")
                        carousel_media = it.get("carousel_media", [])

                        images = []
                        for img in image_versions2:
                            url = img.get("url")
                            height = img.get("height")
                            width = img.get("width")
                            if height == original_height and width == original_width:
                                images.append(url)

                        video = video_versions[0].get("url") if video_versions else None

                        carousel = parse_carousel(carousel_media)
                        final_items.append({
                            "code": code,
                            "pk": pk,
                            "id": id_,
                            "images": images,
                            "video": video,
                            "carousel": carousel,
                            "caption": caption.get("text", "") if caption else "",
                            "likes": like_count,
                            "comments": comment_count,
                            "type": "carousel" if media_type == 8 else "video" if media_type == 2 else "photo",
                            "media_type": media_type
                        })
                except KeyError:
                    pass
    return final_items[0] if final_items else None

def download2(short_code=""):
    try:
        # use a Tor proxy from the pool for this request
        # If called from async context, callers should be awaiting the async pool getter.
        # Here we attempt to use the pool synchronously by grabbing its current index and port.
        # Prefer the async interface when calling from async code.
        try:
            # attempt to synchronously obtain an index/port via the pool (best-effort)
            proxies, idx = asyncio.get_event_loop().run_until_complete(tor_pool.get_next_proxies())
        except Exception:
            # fallback to default socks port
            proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}
            idx = None

        _log_request_start(f"https://www.instagram.com/p/{short_code}/?direct=true", idx)
        response = requests.get(f"https://www.instagram.com/p/{short_code}/?direct=true", headers=default_headers(), proxies=proxies, timeout=30)
        response.raise_for_status()
        return parse_post(response.text)
    except Exception as err:
        logger.exception("download2 failed for shortcode=%s (tor_index=%s): %s", short_code, locals().get('idx'), err)
        return None

# tor_renew function is not defined in the original code, so implementing a stub
# You may need to implement TOR renewal logic if required
def tor_renew(idx=None):
    """Synchronous shim to request a renew on a specific tor index.

    If `idx` is None the pool will decide which index to renew (its previous index).
    This helper schedules the async renew on the running loop when possible or
    runs a temporary loop when not.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # schedule background renew for the specific index
            asyncio.ensure_future(tor_pool.renew(idx))
        else:
            loop.run_until_complete(tor_pool.renew(idx))
    except Exception:
        # Last-resort: try running a new loop
        try:
            asyncio.run(tor_pool.renew(idx))
        except Exception:
            pass


async def download(url="", trys=1):
    furl = url.strip().split("?")[0]
    if not furl.endswith("/"):
        furl += "/"
    furl = f"{furl}embed/captioned/"
    furl = furl.replace("reels", "p").replace("reel", "p")

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/46.0.2490.80",
        "Host": "www.instagram.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip"
    }

    status_code = None  # Initialize status code
    try:
        # obtain proxies for this request from the tor pool
        try:
            proxies, idx = await tor_pool.get_next_proxies()
        except Exception:
            proxies = {"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"}

        response = requests.get(furl, headers=headers, proxies=proxies, timeout=30)
        status_code = response.status_code  # Capture status code
        response.raise_for_status()
        data = response.text

        # Regex to find contextJSON
        regex = r'"contextJSON"\s*:\s*"(\{.*?\})"'
        match = re.search(regex, data)
        if match:
            raw_json = match.group(1)
            raw_json = raw_json.replace('\\"', '"').replace('\\\\"', "").replace('\\/', "/").replace('\\\\/', '/').replace('\\/', '/')
            parsed = json.loads(raw_json)
            media = parsed["context"]["media"]
            id_ = media["id"]
            shortcode = media["shortcode"]
            typename = media["__typename"]
            edge_sidecar_to_children = media.get("edge_sidecar_to_children", {}).get("edges", [])
            video_url = media.get("video_url")
            likes_count = media.get("likes_count", 0)
            comments_count = media.get("comments_count", 0)
            edge_media_to_caption = media.get("edge_media_to_caption")

            caption = ""
            if edge_media_to_caption:
                edges = edge_media_to_caption.get("edges", [])
                if edges:
                    caption = decode_unicode(edges[0]["node"]["text"].strip())

            carousel = []
            for e in edge_sidecar_to_children:
                node = e["node"]
                is_video = node.get("is_video", False)
                video_url_car = node.get("video_url")
                display_url = node.get("display_url")
                display_resources = node.get("display_resources", [])
                if is_video:
                    carousel.append(video_url_car)
                else:
                    if display_resources:
                        reso = display_resources[-1]["src"]
                        carousel.append(reso)

            if typename == "GraphSidecar":
                data_dict = {
                    "code": shortcode,
                    "pk": id_,
                    "id": id_,
                    "images": [],
                    "video": None,
                    "carousel": carousel,
                    "caption": caption,
                    "likes": likes_count,
                    "comments": comments_count,
                    "type": "carousel" if typename == "GraphSidecar" else "video" if typename == "GraphVideo" else "photo"
                }
            else:
                data_dict = {
                    "code": shortcode,
                    "pk": id_,
                    "id": id_,
                    "images": [],
                    "video": video_url,
                    "carousel": carousel,
                    "caption": caption,
                    "likes": likes_count,
                    "comments": comments_count,
                    "type": "carousel" if typename == "GraphSidecar" else "video" if typename == "GraphVideo" else "photo"
                }
            return data_dict, status_code
        else:
            # Fallback HTML parsing
            soup = BeautifulSoup(data, "html.parser")
            image_element = soup.select_one(".EmbeddedMedia img")
            image = image_element["src"] if image_element else None
            caption = ""
            try:
                caption_element = soup.select_one(".Caption")
                if caption_element:
                    caption_element.select_one(".CaptionUsername").decompose()
                    caption = caption_element.get_text(strip=True).replace("&#064;", "#")
            except Exception as err:
                print(err)
            return {
                "images": [image] if image else [],
                "video": None,
                "carousel": [],
                "caption": caption,
                "likes": 0,
                "comments": 0,
                "type": "photo"
            }, status_code
    except Exception as err:
        print(f"instagram (try {trys}): {err}")
        # When an error happens, attempt to renew the Tor circuit used for this request
        try:
            # if we have idx from above, renew that index; otherwise, just trigger a general renew
            await tor_pool.renew(idx if 'idx' in locals() else None)
        except Exception:
            pass

    # Retry logic
    if trys <= 8:
        if trys >= 3:
            print(f"Attempting alter1reels (try {trys})...")
            result = await alter1reels(url)
            if result:
                return result, None  # No status code from alter1reels
        elif trys == 2:
            print(f"Attempting download2 (try {trys})...")
            shortcode = url.split("/")[-2] if "/p/" in url or "/reel/" in url else ""
            result = download2(shortcode)
            if result:
                return result, None  # No status code from download2

        print(f"Retrying with TOR renewal (try {trys + 1})...")
        # Pass the index of the tor instance used for the failing request when available
        tor_renew(idx if 'idx' in locals() else None)
        return await download(url, trys + 1)
        
    print("All retry attempts failed.")
    return None, None