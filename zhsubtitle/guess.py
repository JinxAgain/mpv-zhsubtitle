"""Metadata extraction and filename parsing powered by guessit."""

import os
import re
from typing import Optional, Union

try:
    from guessit import guessit
except ImportError:
    guessit = None

from .models import VideoMeta


def _clean_string(s: Optional[Union[str, list]]) -> str:
    """Normalize string or list of strings."""
    if s is None:
        return ""
    if isinstance(s, list):
        return " ".join(str(x) for x in s if x).strip()
    return str(s).strip()


def parse_video(video_path_or_name: str) -> VideoMeta:
    """
    Parse a video file path or filename using guessit with heuristic fallbacks.
    Returns a VideoMeta object containing structured attributes and prioritized search queries.
    """
    raw_name = os.path.basename(video_path_or_name)
    meta = VideoMeta(
        raw_name=raw_name,
        file_path=video_path_or_name
    )

    # Use guessit for robust title, episode, year, and release parsing
    if guessit:
        try:
            guessed = guessit(raw_name)
            meta.title = _clean_string(guessed.get("title"))
            meta.alternative_title = _clean_string(guessed.get("alternative_title"))

            year = guessed.get("year")
            if year:
                try:
                    meta.year = int(year[0] if isinstance(year, list) else year)
                except (ValueError, TypeError):
                    pass

            season = guessed.get("season")
            if season:
                try:
                    meta.season = int(season[0] if isinstance(season, list) else season)
                except (ValueError, TypeError):
                    pass

            episode = guessed.get("episode")
            if episode:
                try:
                    meta.episode = int(episode[0] if isinstance(episode, list) else episode)
                except (ValueError, TypeError):
                    pass

            part = guessed.get("part")
            if part:
                try:
                    meta.part = int(part[0] if isinstance(part, list) else part)
                except (ValueError, TypeError):
                    pass

            v_type = guessed.get("type")
            meta.is_tv = (v_type == "episode") or (meta.season is not None) or (meta.episode is not None)
            meta.release_group = _clean_string(guessed.get("release_group"))
            meta.source = _clean_string(guessed.get("source"))
            meta.screen_size = _clean_string(guessed.get("screen_size"))
            meta.video_codec = _clean_string(guessed.get("video_codec"))

        except Exception as e:
            # If guessit encounters an error, fallback to regex
            pass

    # Heuristic fallback if title is still empty
    if not meta.title:
        _fallback_parse(raw_name, meta)

    # Handle Part titles (e.g. "Dune Part 2" -> "Dune Part Two" / "Dune Part 2")
    if meta.part and meta.part > 1:
        if not re.search(r"\bpart\b", meta.title, re.IGNORECASE):
            meta.title = f"{meta.title} Part {meta.part}"

    return meta


def _fallback_parse(name: str, meta: VideoMeta) -> None:
    """Fallback regular expression parsing if guessit fails or is unavailable."""
    clean_name = re.sub(r"\.[a-zA-Z0-9]{2,4}$", "", name) # Remove extension

    # Match SxxExx or Season x Episode x
    se_match = re.search(r"[sS](\d{1,2})[.\s]*[eE](\d{1,3})", clean_name)
    if se_match:
        meta.season = int(se_match.group(1))
        meta.episode = int(se_match.group(2))
        meta.is_tv = True
        clean_name = clean_name[:se_match.start()]
    else:
        # Match Chinese Episode/Season
        cn_match = re.search(r"第\s*(\d{1,3})\s*[集话話]", clean_name)
        if cn_match:
            meta.episode = int(cn_match.group(1))
            meta.is_tv = True
            clean_name = clean_name[:cn_match.start()]

    # Match Year (1900-2099)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", clean_name)
    if year_match:
        meta.year = int(year_match.group(1))
        clean_name = clean_name[:year_match.start()]

    # Clean release tokens
    junk = r"\b(1080p|720p|2160p|4k|bluray|bdrip|web-dl|webdl|webrip|h264|x264|h265|x265|hevc|remux)\b"
    clean_name = re.sub(junk, " ", clean_name, flags=re.IGNORECASE)
    clean_name = re.sub(r"[._\-+]+", " ", clean_name).strip()

    meta.title = clean_name or os.path.splitext(name)[0]
