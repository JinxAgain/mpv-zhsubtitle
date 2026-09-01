"""Base class for subtitle providers."""

import abc
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..models import SubtitleItem, VideoMeta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}


class BaseProvider(abc.ABC):
    """Abstract base provider for subtitle searching and downloading."""

    name: str = "base"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.timeout = int(self.config.get("timeout", 15))
        self.session = requests.Session()
        self.session.headers.update(BASE_HEADERS)
        adapter = requests.adapters.HTTPAdapter(max_retries=2)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    @abc.abstractmethod
    def search(self, query: str, meta: Optional[VideoMeta] = None) -> List[SubtitleItem]:
        """Search subtitles for the given query keyword and optional video metadata."""
        pass

    @abc.abstractmethod
    def download(self, item: SubtitleItem) -> Tuple[Optional[bytes], str]:
        """
        Download subtitle file data for the given subtitle item.
        Returns a tuple of (content_bytes, original_filename).
        """
        pass

    def extract_filename_from_response(self, resp: requests.Response, default: str = "subtitle.bin") -> str:
        """Extract filename from Content-Disposition header or URL."""
        cd = resp.headers.get("Content-Disposition", "")
        if cd:
            star_matches = re.findall(r"filename\*\s*=\s*(?:UTF-8''|\")?([^;\"]+)", cd, re.I)
            if star_matches:
                return urllib.parse.unquote(star_matches[0].strip().strip('"').strip("'"))
            plain_matches = re.findall(r"filename\s*=\s*\"?([^;\"]+)", cd, re.I)
            if plain_matches:
                return urllib.parse.unquote(plain_matches[0].strip().strip('"').strip("'"))

        tail = os.path.basename(urllib.parse.urlparse(resp.url).path)
        if tail and "." in tail:
            return urllib.parse.unquote(tail)

        return default
