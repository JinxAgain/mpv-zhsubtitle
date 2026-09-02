"""Lightweight local cache for subtitle search results."""

from dataclasses import asdict
import hashlib
import json
import logging
import os
import tempfile
import time
from typing import List, Optional, Tuple

from .models import SubtitleItem, SubtitleTags, VideoMeta

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(tempfile.gettempdir(), "zhsubtitle_cache")
DEFAULT_CACHE_TTL = 86400  # 24 hours
MAX_CACHE_ENTRIES = 100    # Maximum number of video search caches to preserve


def _safe_instantiate(cls, data_dict: dict):
    """Safely instantiate dataclass ignoring unexpected keys."""
    valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data_dict.items() if k in valid_keys}
    return cls(**filtered)


def _get_cache_key(video_path: str) -> str:
    """Generate MD5 hash key from video path or filename."""
    clean = video_path.strip().lower()
    return hashlib.md5(clean.encode("utf-8", errors="ignore")).hexdigest()


def _get_cache_path(video_path: str) -> str:
    """Return the absolute path to the cache file for the given video."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _get_cache_key(video_path)
    return os.path.join(CACHE_DIR, f"{key}.json")


def _prune_cache(max_age: int = DEFAULT_CACHE_TTL, max_entries: int = MAX_CACHE_ENTRIES) -> None:
    """
    Automatically clean up expired cache files and prune old entries if exceeding limit.
    Ensures cache directory never grows indefinitely and stays well under 1-2 MB.
    """
    if not os.path.isdir(CACHE_DIR):
        return

    try:
        now = time.time()
        entries = []
        for fname in os.listdir(CACHE_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(CACHE_DIR, fname)
            try:
                mtime = os.path.getmtime(fpath)
                if now - mtime > max_age:
                    os.remove(fpath)
                else:
                    entries.append((mtime, fpath))
            except Exception:
                pass

        if len(entries) > max_entries:
            entries.sort(key=lambda x: x[0])  # Sort oldest first
            overflow = len(entries) - max_entries
            for _, fpath in entries[:overflow]:
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"[Cache] Auto-pruning error: {e}")


def get_cached_search(
    video_path: Optional[str],
    max_age: int = DEFAULT_CACHE_TTL
) -> Optional[Tuple[List[SubtitleItem], VideoMeta]]:
    """
    Retrieve cached search results and metadata for a video.
    Returns None if cache does not exist, is expired, or is corrupted.
    """
    if not video_path:
        return None

    cache_file = _get_cache_path(video_path)
    if not os.path.isfile(cache_file):
        return None

    try:
        mtime = os.path.getmtime(cache_file)
        if time.time() - mtime > max_age:
            logger.debug(f"[Cache] Expired cache file removed: {cache_file}")
            try:
                os.remove(cache_file)
            except Exception:
                pass
            return None

        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        meta_dict = data.get("meta", {})
        results_list = data.get("results", [])

        meta = _safe_instantiate(VideoMeta, meta_dict)
        items: List[SubtitleItem] = []
        for it in results_list:
            tags_dict = it.pop("tags", {})
            tags = _safe_instantiate(SubtitleTags, tags_dict)
            it["tags"] = tags
            item = _safe_instantiate(SubtitleItem, it)
            items.append(item)

        logger.info(f"[Cache] Successfully loaded {len(items)} cached results for {os.path.basename(video_path)}")
        return items, meta

    except Exception as e:
        logger.debug(f"[Cache] Failed to load cache file {cache_file}: {e}")
        return None


def save_cached_search(
    video_path: Optional[str],
    results: List[SubtitleItem],
    meta: VideoMeta
) -> None:
    """Save search results and metadata to cache file."""
    if not video_path or not results:
        return

    cache_file = _get_cache_path(video_path)
    try:
        payload = {
            "version": 1,
            "timestamp": time.time(),
            "video_path": video_path,
            "meta": asdict(meta),
            "results": [asdict(r) for r in results]
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        logger.info(f"[Cache] Saved {len(results)} results to cache for {os.path.basename(video_path)}")
        _prune_cache()
    except Exception as e:
        logger.debug(f"[Cache] Failed to write cache file {cache_file}: {e}")


def clear_cached_search(video_path: Optional[str] = None) -> None:
    """Clear cache for a specific video or all cached results."""
    try:
        if video_path:
            cache_file = _get_cache_path(video_path)
            if os.path.isfile(cache_file):
                os.remove(cache_file)
        elif os.path.isdir(CACHE_DIR):
            import shutil
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
    except Exception as e:
        logger.debug(f"[Cache] Clear cache error: {e}")
