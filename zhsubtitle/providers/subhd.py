"""SubHD (subhd.tv) subtitle provider implementation."""

import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
import requests

from .base import BaseProvider
from ..logger import logger
from ..models import SubtitleItem, SubtitleTags, VideoMeta

SOURCE_MAP = {
    "官方字幕": "official",
    "官方": "official",
    "官译": "official",
    "转载精修": "reprint",
    "精修": "reprint",
    "转载": "reprint",
    "原创翻译": "original",
    "原创": "original",
    "自翻": "original",
    "AI校对": "ai",
    "AI润色": "ai",
    "AI翻润色": "ai",
    "AI翻译": "ai",
    "AI": "ai",
    "机器翻译": "machine",
    "机翻": "machine",
    "其他来源": "other",
    "其他": "other",
    "听译": "hearing"
}


class SubhdProvider(BaseProvider):
    """SubHD provider for searching and downloading subtitles without login."""

    name: str = "subhd"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.base_url = self.config.get("base_url", "https://subhd.tv").rstrip("/")
        self.fallback_urls = self.config.get("fallback_urls", ["https://subhd.me", "https://subhd.one"])
        self.timeout = min(int(self.config.get("timeout", 5)), 6)

    def search(self, query: str, meta: Optional[VideoMeta] = None) -> List[SubtitleItem]:
        """Search SubHD for subtitles matching query with fast mirror fallback."""
        if not query.strip():
            return []

        search_urls = [f"{self.base_url}/search/{urllib.parse.quote(query)}"]
        for fb in self.fallback_urls:
            fb_clean = fb.rstrip("/")
            if fb_clean != self.base_url:
                search_urls.append(f"{fb_clean}/search/{urllib.parse.quote(query)}")

        for url in search_urls:
            logger.info(f"[SubHD] Searching {url}...")
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    html_content = resp.content.decode("utf-8", "ignore")
                    items = self._parse_search_results(html_content, meta)
                    if items:
                        logger.info(f"[SubHD] Found {len(items)} subtitles on {url}")
                        return items
                else:
                    logger.debug(f"[SubHD] {url} returned HTTP {resp.status_code}")
            except Exception as e:
                logger.debug(f"[SubHD] {url} failed: {e}")
                continue

        return []

    def _parse_search_results(self, html: str, meta: Optional[VideoMeta] = None) -> List[SubtitleItem]:
        """Parse subtitle cards from SubHD search HTML."""
        soup = BeautifulSoup(html, "html.parser")
        items: List[SubtitleItem] = []
        seen_sids = set()

        blocks = soup.select("div.bg-white.shadow-sm.rounded-3.mb-4, div.bg-white.shadow-sm.rounded-3.mb-5")
        for block in blocks:
            a_tags = block.find_all("a", href=True)
            sid = None
            for a in a_tags:
                m = re.search(r"^/a/([0-9A-Za-z]+)", a.get("href", ""))
                if m:
                    sid = m.group(1)
                    break

            if not sid or sid in seen_sids:
                continue

            seen_sids.add(sid)

            # Extract both main title and detailed release name from card
            head_a = block.select_one("div.f16 a")
            view_a = block.select_one("div.view-text a") or block.select_one("div.text-secondary a")

            head_text = head_a.get_text(strip=True) if head_a else ""
            view_text = view_a.get_text(strip=True) if view_a else ""

            if view_text and view_text != head_text:
                title = f"{head_text} - {view_text}" if head_text else view_text
            else:
                title = view_text or head_text or f"SubHD Subtitle {sid}"

            tags, dl_count = self._parse_tags_from_element(block)
            page_url = f"{self.base_url}/a/{sid}"

            item = SubtitleItem(
                id=sid,
                title=title,
                page_url=page_url,
                provider=self.name,
                tags=tags,
                downloads_count=dl_count
            )
            items.append(item)

        return items

    def _parse_tags_from_element(self, element) -> Tuple[SubtitleTags, int]:
        """Extract metadata tags from badges and text spans."""
        tags = SubtitleTags(provider=self.name)
        dl_count = 0
        spans = element.find_all("span")

        for span in spans:
            text = span.get_text(strip=True)
            if not text:
                continue

            # Source badges (AI校对, 其他来源, 官方字幕, etc.)
            for cn in SOURCE_MAP.keys():
                if cn in text and cn not in tags.source:
                    tags.source.append(cn)
                    break

            # Language badges
            if ("简体" in text or "简中" in text) and "chs" not in tags.lang:
                tags.lang.append("chs")
            if ("繁体" in text or "繁中" in text) and "cht" not in tags.lang:
                tags.lang.append("cht")
            if ("英语" in text or "英文" in text) and "eng" not in tags.lang:
                tags.lang.append("eng")
            if "双语" in text or "中英" in text:
                tags.bilingual = True

            # Formats
            for fmt in ("ass", "srt", "ssa", "vtt", "sub", "sup"):
                if fmt.upper() in text.upper() and fmt not in tags.fmt:
                    tags.fmt.append(fmt)

            # Download count numbers (e.g. 105, 312, 1357)
            if span.find("i", class_=lambda c: c and ("download" in c or "cloud" in c)):
                try:
                    num_match = re.search(r"(\d+)", text)
                    if num_match:
                        dl_count = int(num_match.group(1))
                except Exception:
                    pass

        # If language is still empty, default to chs
        if not tags.lang:
            tags.lang.append("chs")

        zu_el = element.select_one('a[href^="/zu/"]')
        if zu_el:
            tags.fansub = zu_el.get_text(strip=True)

        u_el = element.select_one('a[href^="/u/"]')
        if u_el:
            tags.uploader = u_el.get_text(strip=True)

        return tags, dl_count

    def download(self, item: SubtitleItem) -> Tuple[Optional[bytes], str]:
        """Download subtitle file from SubHD using the prepare-download -> down API token flow."""
        sid = item.id
        if not sid:
            m = re.search(r"/a/([0-9A-Za-z]+)", item.page_url)
            sid = m.group(1) if m else None

        if not sid:
            return None, ""

        page_url = item.page_url or f"{self.base_url}/a/{sid}"
        logger.info(f"[SubHD] Starting download for sid '{sid}' from {page_url}")

        try:
            # Step 1: Request prepare-download
            prep_resp = self.session.post(
                f"{self.base_url}/api/sub/prepare-download",
                json={"sid": sid},
                headers={
                    "Referer": page_url,
                    "X-Requested-With": "XMLHttpRequest"
                },
                timeout=self.timeout
            )
            if prep_resp.status_code != 200:
                logger.warning(f"[SubHD] prepare-download returned HTTP {prep_resp.status_code}")
                return None, ""

            prep_data = prep_resp.json()
            if not prep_data.get("success"):
                logger.warning(f"[SubHD] prepare-download failed: {prep_data.get('msg')}")
                return None, ""

            down_path = prep_data.get("url") or f"/down/{sid}"
            down_url = down_path if down_path.startswith("http") else f"{self.base_url}{down_path}"

            # Step 2: Visit temp download confirmation page
            logger.info(f"[SubHD] Visiting temp page {down_url}")
            temp_resp = self.session.get(down_url, headers={"Referer": page_url}, timeout=self.timeout)
            if temp_resp.status_code != 200:
                logger.warning(f"[SubHD] Temp page returned HTTP {temp_resp.status_code}")
                return None, ""

            # Step 3: Call /api/sub/down to retrieve download URL
            logger.info(f"[SubHD] Requesting download URL via /api/sub/down")
            api_resp = self.session.post(
                f"{self.base_url}/api/sub/down",
                json={"sid": sid, "cap": ""},
                headers={
                    "Referer": down_url,
                    "X-Requested-With": "XMLHttpRequest"
                },
                timeout=self.timeout
            )
            if api_resp.status_code != 200:
                logger.warning(f"[SubHD] /api/sub/down returned HTTP {api_resp.status_code}")
                return None, ""

            api_data = api_resp.json()
            if not api_data.get("success") or not api_data.get("url"):
                logger.warning(f"[SubHD] /api/sub/down failed: {api_data.get('msg')}")
                return None, ""

            file_url = api_data.get("url")
            if not file_url.startswith("http"):
                file_url = f"{self.base_url}{file_url}"

            # Step 4: Fetch actual file bytes
            logger.info(f"[SubHD] Fetching file content from {file_url}")
            file_resp = self.session.get(file_url, headers={"Referer": down_url}, timeout=self.timeout)
            if file_resp.status_code != 200:
                logger.warning(f"[SubHD] File fetch returned HTTP {file_resp.status_code}")
                return None, ""

            filename = self.extract_filename_from_response(file_resp, default=f"subhd_{sid}.zip")
            logger.info(f"[SubHD] Download complete: {filename} ({len(file_resp.content)} bytes)")
            return file_resp.content, filename

        except Exception as e:
            logger.error(f"[SubHD] Download error: {e}")
            return None, ""
