"""Zimuku (srtku.com / zmk.pw / zimuku.org) subtitle provider implementation."""

import base64
import re
import struct
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
import requests

from .base import BaseProvider
from ..logger import logger
from ..models import SubtitleItem, SubtitleTags, VideoMeta, to_cn_season

FILE_MIN_SIZE = 100


class ZimukuBmpSolver:
    """Recognizes 5 digits of Zimuku's 100x27 BMP verification image using template matching."""

    IMG_WIDTH, IMG_HEIGHT = 100, 27
    CHAR_WIDTH, NUM_CHARS = 20, 5
    PIXEL_DATA_OFFSET = 54

    SAMPLE_POINTS = [
        (10, 7), (7, 8), (12, 8), (10, 13),
        (7, 19), (12, 19), (10, 20), (6, 13), (14, 13)
    ]

    TEMPLATES = {
        '0': [1, 1, 1, 1, 1, 1, 1, 1, 0],
        '1': [0, 1, 0, 0, 0, 0, 1, 0, 0],
        '2': [1, 0, 1, 0, 1, 0, 1, 0, 0],
        '3': [1, 0, 1, 1, 0, 1, 1, 0, 0],
        '4': [0, 0, 1, 0, 0, 1, 0, 0, 0],
        '5': [1, 1, 0, 0, 0, 1, 1, 0, 0],
        '6': [1, 0, 1, 1, 1, 1, 1, 1, 0],
        '7': [1, 0, 1, 0, 0, 0, 0, 0, 0],
        '8': [1, 1, 1, 1, 1, 1, 1, 0, 0],
        '9': [1, 1, 1, 0, 1, 0, 1, 0, 0],
    }

    def __init__(self, b64_string: str):
        self._data = base64.b64decode(b64_string)
        if len(self._data) < self.PIXEL_DATA_OFFSET or self._data[:2] != b'BM':
            raise ValueError("Invalid BMP data")
        self._stride = (self.IMG_WIDTH * 3 + 3) & ~3

    def recognize(self) -> str:
        result = []
        one_offset = 0
        for i in range(self.NUM_CHARS):
            char_x = i * self.CHAR_WIDTH
            features = [
                1 if self._is_foreground(char_x + px - one_offset, py) else 0
                for px, py in self.SAMPLE_POINTS
            ]
            digit = self._match_digit(features)
            if digit == '1':
                one_offset += 1
            elif digit == '4':
                one_offset -= 1
            result.append(digit)
        return "".join(result)

    def _is_foreground(self, x: int, y: int, threshold: int = 70) -> bool:
        bmp_y = self.IMG_HEIGHT - 1 - y
        offset = self.PIXEL_DATA_OFFSET + bmp_y * self._stride + x * 3
        if offset + 2 >= len(self._data):
            return False
        b, g, r = self._data[offset], self._data[offset + 1], self._data[offset + 2]
        return (r + g + b) / 3 < threshold

    def _match_digit(self, features: List[int]) -> str:
        best, min_diff = '?', float('inf')
        for digit, template in self.TEMPLATES.items():
            diff = sum(f != t for f, t in zip(features, template))
            if diff < min_diff:
                min_diff, best = diff, digit
            if min_diff == 0:
                break
        return best


class ZimukuProvider(BaseProvider):
    """Zimuku subtitle provider with mirror fallbacks, WAF bypass, and metadata extraction."""

    name: str = "zimuku"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.base_url = self.config.get("base_url", "https://srtku.com").rstrip("/")
        self.fallback_urls = self.config.get("fallback_urls", ["https://zmk.pw", "https://zimuku.org"])
        self.timeout = min(int(self.config.get("timeout", 6)), 8)

    def _fetch_page(self, url: str, referer: Optional[str] = None) -> Optional[requests.Response]:
        """Perform GET request with automatic Yunsuo WAF bypass and JS redirect handling."""
        headers = {"Referer": referer} if referer else {}
        for _ in range(3):
            try:
                resp = self.session.get(url, headers=headers, timeout=self.timeout)
            except Exception as e:
                logger.debug(f"[Zimuku] GET {url} failed: {e}")
                return None

            # Check if Yunsuo WAF captcha verification page is returned (status 404 or 200)
            if b"security_verify_img" in resp.content or b"YunsuoAutoJump" in resp.content:
                logger.info(f"[Zimuku] WAF verification challenge detected for {url}")
                solved = self._solve_waf_captcha(url, resp.content)
                if solved:
                    logger.info("[Zimuku] WAF challenge solved, retrying request...")
                    continue
                else:
                    logger.warning("[Zimuku] Failed to solve WAF challenge")
                    return None

            # Handle JS location.replace redirect
            if resp.status_code == 200:
                m = re.search(r"window\.location\.replace\(['\"]([^'\"]+)['\"]\)", resp.text)
                if m:
                    redirect_url = m.group(1)
                    logger.debug(f"[Zimuku] Following JS redirect -> {redirect_url[:60]}")
                    try:
                        resp = self.session.get(redirect_url, headers={"Referer": url}, timeout=self.timeout)
                    except Exception:
                        pass
                return resp

            if resp.status_code == 200:
                return resp
            break

        return None

    def _solve_waf_captcha(self, url: str, content: bytes) -> bool:
        """Answer the Yunsuo BMP captcha and submit security_verify_img verification."""
        try:
            soup = BeautifulSoup(content.decode("utf-8", "ignore"), "html.parser")
            img = soup.find("img")
            if not img:
                return False
            src = img.get("src", "")
            if "data:image/bmp;base64," not in src:
                return False

            b64_data = src.split("data:image/bmp;base64,", 1)[1]
            code = ZimukuBmpSolver(b64_data).recognize()
            logger.info(f"[Zimuku] Recognized BMP captcha code: {code}")

            parsed = urllib.parse.urlparse(url)
            srcurl_hex = "".join(f"{ord(c):x}" for c in url)
            self.session.cookies.set("srcurl", srcurl_hex, domain=parsed.netloc, path="/")

            code_hex = "".join(f"{ord(c):x}" for c in code)
            verify_url = f"{parsed.scheme}://{parsed.netloc}/?security_verify_img={code_hex}"
            self.session.get(verify_url, headers={"Referer": url}, timeout=self.timeout)
            return True
        except Exception as e:
            logger.error(f"[Zimuku] Captcha bypass error: {e}")
            return False

    def search(self, query: str, meta: Optional[VideoMeta] = None) -> List[SubtitleItem]:
        """Search Zimuku for works and parse their subtitle lists."""
        if not query.strip():
            return []

        # Prepare candidate queries
        candidate_queries = [query]

        # If query contains SxxExx or episode numbers, clean it to Show Name + Season or Show Name
        ep_match = re.search(r"([sS]\d{1,2})[.\s]*[eE]\d{1,3}", query)
        if ep_match:
            season_num = int(ep_match.group(1)[1:])
            base_show = query[:ep_match.start()].strip()
            if base_show:
                candidate_queries.append(f"{base_show} {to_cn_season(season_num)}")
                candidate_queries.append(f"{base_show} S{season_num:02d}")
                candidate_queries.append(base_show)

        if meta and meta.is_tv and meta.title:
            if meta.season:
                candidate_queries.append(f"{meta.title} {to_cn_season(meta.season)}")
                candidate_queries.append(f"{meta.title} S{meta.season:02d}")
            candidate_queries.append(meta.title)
            if meta.alternative_title:
                if meta.season:
                    candidate_queries.append(f"{meta.alternative_title} {to_cn_season(meta.season)}")
                candidate_queries.append(meta.alternative_title)

        # Deduplicate candidates
        seen_cand = set()
        clean_candidates = []
        for cq in candidate_queries:
            cq_clean = " ".join(cq.split()).strip()
            if cq_clean and cq_clean not in seen_cand:
                seen_cand.add(cq_clean)
                clean_candidates.append(cq_clean)

        domains = [self.base_url] + [fb.rstrip("/") for fb in self.fallback_urls if fb.rstrip("/") != self.base_url]

        items: List[SubtitleItem] = []
        for target_query in clean_candidates:
            for domain in domains:
                url = f"{domain}/search?q={urllib.parse.quote(target_query)}"
                logger.info(f"[Zimuku] Searching {url}...")
                resp = self._fetch_page(url)
                if not resp or resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.content.decode("utf-8", "ignore"), "html.parser")
                work_items = soup.select("div.item")
                if not work_items:
                    logger.debug(f"[Zimuku] No works for '{target_query}' on {domain}")
                    continue

                logger.info(f"[Zimuku] Found {len(work_items)} works for '{target_query}' on {domain}")
                for work in work_items[:3]:
                    title_a = work.select_one("div.title p.tt a")
                    if not title_a or not title_a.get("href"):
                        continue

                    raw_work_title = title_a.get_text(strip=True)
                    work_page_url = urllib.parse.urljoin(domain, title_a["href"])
                    work_subs = self._parse_work_page(work_page_url, domain, meta, raw_work_title)
                    items.extend(work_subs)

                if items:
                    break

            if items:
                break

        return items

    def _parse_work_page(
        self,
        work_url: str,
        domain_base: str,
        meta: Optional[VideoMeta] = None,
        raw_work_title: str = ""
    ) -> List[SubtitleItem]:
        """Parse subtitle table and extract Douban ID / IMDb ID from a Zimuku work page."""
        resp = self._fetch_page(work_url)
        if not resp or resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.content.decode("utf-8", "ignore"), "html.parser")

        # Extract Douban ID & IMDb ID to enrich metadata
        if meta:
            douban_a = soup.find("a", href=re.compile(r"douban\.com/(?:subject|movie)/(\d+)"))
            if douban_a:
                m_douban = re.search(r"/(\d+)", douban_a["href"])
                if m_douban and not meta.douban_id:
                    meta.douban_id = m_douban.group(1)
                    logger.info(f"[Zimuku] Extracted Douban ID: {meta.douban_id}")

            imdb_a = soup.find("a", href=re.compile(r"imdb\.com/title/(tt\d+)"))
            if imdb_a:
                m_imdb = re.search(r"(tt\d+)", imdb_a["href"])
                if m_imdb and not meta.imdb_id:
                    meta.imdb_id = m_imdb.group(1)
                    logger.info(f"[Zimuku] Extracted IMDb ID: {meta.imdb_id}")

            if raw_work_title:
                meta.work_title = raw_work_title
                # Extract clean Chinese title (e.g. '末日地堡 第三季' from '末日地堡 第三季 Silo Season 3 (2025)')
                m_cn = re.match(r"^([\u4e00-\u9fa5\s\d第季]+)", raw_work_title)
                if m_cn:
                    cn_name = m_cn.group(1).strip()
                    if cn_name and not meta.cn_title:
                        meta.cn_title = cn_name
                        logger.info(f"[Zimuku] Extracted Chinese title: {meta.cn_title}")

        subs_box = soup.select_one("div.subs.box.clearfix")
        if not subs_box or not subs_box.tbody:
            return []

        items = []
        for row in subs_box.tbody.find_all("tr"):
            link = row.find("a")
            if not link or not link.get("href"):
                continue

            title = link.get_text(strip=True)
            detail_url = urllib.parse.urljoin(domain_base, link["href"])
            m = re.search(r"/detail/(\d+)", link["href"])
            sub_id = m.group(1) if m else link["href"]

            tags = SubtitleTags(provider=self.name)

            # Languages
            lang_td = row.find("td", class_="tac lang")
            if lang_td:
                for img in lang_td.find_all("img"):
                    img_title = img.get("title", "")
                    if "简体" in img_title and "chs" not in tags.lang:
                        tags.lang.append("chs")
                    if "繁体" in img_title and "cht" not in tags.lang:
                        tags.lang.append("cht")
                    if "English" in img_title and "eng" not in tags.lang:
                        tags.lang.append("eng")
                    if "双语" in img_title:
                        tags.bilingual = True

            # Formats
            fmt_span = row.find("span", class_="label-info")
            if fmt_span:
                for fmt in fmt_span.get_text(strip=True).lower().split("/"):
                    f = fmt.strip()
                    if f and f not in tags.fmt:
                        tags.fmt.append(f)

            # Fansub
            fansub_a = row.select_one('a[href^="/t/"]')
            if fansub_a:
                tags.fansub = fansub_a.get_text(strip=True)

            item = SubtitleItem(
                id=sub_id,
                title=title,
                page_url=detail_url,
                provider=self.name,
                tags=tags
            )
            items.append(item)

        return items

    def download(self, item: SubtitleItem) -> Tuple[Optional[bytes], str]:
        """Download subtitle file by resolving Zimuku detail -> download page -> mirror file links."""
        logger.info(f"[Zimuku] Fetching detail page: {item.page_url}")
        resp = self._fetch_page(item.page_url)
        if not resp or resp.status_code != 200:
            return None, ""

        domain_base = f"{urllib.parse.urlparse(item.page_url).scheme}://{urllib.parse.urlparse(item.page_url).netloc}"
        soup = BeautifulSoup(resp.content.decode("utf-8", "ignore"), "html.parser")
        dl_sub = soup.find("li", class_="dlsub")
        if not dl_sub or not dl_sub.a:
            logger.warning(f"[Zimuku] No dlsub download link found on {item.page_url}")
            return None, ""

        dl_url = urllib.parse.urljoin(domain_base, dl_sub.a["href"])
        logger.info(f"[Zimuku] Fetching download page: {dl_url}")
        dl_page_resp = self._fetch_page(dl_url, referer=item.page_url)
        if not dl_page_resp or dl_page_resp.status_code != 200:
            return None, ""

        dl_soup = BeautifulSoup(dl_page_resp.content.decode("utf-8", "ignore"), "html.parser")
        links_box = dl_soup.find("div", class_="clearfix")
        if not links_box:
            return None, ""

        links = links_box.find_all("a", href=True)
        for a in links:
            file_url = urllib.parse.urljoin(domain_base, a["href"])
            logger.info(f"[Zimuku] Trying mirror download from: {file_url}")
            try:
                file_resp = self.session.get(file_url, headers={"Referer": dl_url}, timeout=self.timeout)
                if file_resp.status_code == 200 and len(file_resp.content) >= FILE_MIN_SIZE:
                    filename = self.extract_filename_from_response(file_resp, default=f"zimuku_{item.id}.zip")
                    logger.info(f"[Zimuku] Successfully downloaded {filename} ({len(file_resp.content)} bytes)")
                    return file_resp.content, filename
            except Exception as e:
                logger.debug(f"[Zimuku] Mirror error: {e}")
                continue

        return None, ""
