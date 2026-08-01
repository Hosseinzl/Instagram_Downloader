import asyncio
import logging
from TorPool import get_tor_pool
import instaloader
from instaloader import Post
from urllib.parse import urlparse

USE_PROXY = True

logging.basicConfig(level=logging.INFO)

L = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    save_metadata=False,
    download_comments=False,
)

def _fetch_post_sync(shortcode: str) -> Post:
    """Synchronous helper to fetch the post via Instaloader"""
    return Post.from_shortcode(L.context, shortcode)

async def extract_instagram_data(url: str):
    """Extracts Instagram data asynchronously and returns (data, status_code, tor_index)."""
    parsed_url = urlparse(url)
    path_parts = [p for p in parsed_url.path.split('/') if p]
    
    shortcode = None
    for i, part in enumerate(path_parts):
        if part in ("p", "reel", "tv", "reels"):
            if i + 1 < len(path_parts):
                shortcode = path_parts[i + 1]
            break
    
    if not shortcode:
        shortcode = path_parts[-1] if path_parts else ""

    tor_pool = get_tor_pool()
    post = None
    idx = None
    
    for attempt in range(2):
        local_L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            save_metadata=False,
            download_comments=False,
        )
        
        if USE_PROXY:
            proxies, idx = await tor_pool.get_next_proxies()
            local_L.context._session.proxies.update(proxies)
            logging.info(f"Attempt {attempt + 1}: Using proxy {proxies} (Tor index: {idx}) for {shortcode}")

        try:
            # ارسال local_L.context به تابع
            post = await asyncio.to_thread(Post.from_shortcode, local_L.context, shortcode)
            break
            
        except Exception as e:
            logging.error(f"Error fetching {shortcode} on attempt {attempt + 1}: {e}")
            if USE_PROXY:
                await tor_pool.renew(idx)
            
            if attempt == 1:
                if isinstance(e, instaloader.exceptions.PostNotFoundException):
                    return None, 404, idx
                return None, 500, idx

    if not post:
        return None, 500, idx

    # Data extraction logic
    data = {
        "images": [],
        "video": None,
        "carousel": [],
        "caption": post.caption if post.caption else "",
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

    return data, 200, idx
