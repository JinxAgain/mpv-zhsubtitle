"""Data models for video metadata, subtitle items, and download results."""

from dataclasses import dataclass, field
import re
from typing import List, Optional, Tuple


CN_NUM_MAP = {
    1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
    6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
    11: "十一", 12: "十二", 13: "十三", 14: "十四", 15: "十五"
}


def to_cn_season(season: Optional[int]) -> str:
    """Convert integer season number to Chinese season text (e.g. 3 -> '第三季')."""
    if season is None:
        return ""
    cn_num = CN_NUM_MAP.get(season, str(season))
    return f"第{cn_num}季"


@dataclass
class VideoMeta:
    """Parsed video metadata extracted via guessit and online resolution."""
    raw_name: str = ""
    file_path: str = ""
    title: str = ""
    alternative_title: str = ""
    cn_title: str = ""
    work_title: str = ""
    douban_id: str = ""
    imdb_id: str = ""
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    is_tv: bool = False
    part: Optional[int] = None
    release_group: str = ""
    source: str = ""
    screen_size: str = ""
    video_codec: str = ""

    def get_search_chips(self) -> List[Tuple[str, str]]:
        """
        Generate labeled quick search options for GUI buttons:
        Returns list of (label, query_string).
        """
        chips: List[Tuple[str, str]] = []

        # 1. Douban ID
        if self.douban_id:
            chips.append((f"Douban ID: {self.douban_id}", self.douban_id))

        # 2. Chinese Title + Season / Year
        best_cn = self.cn_title or self.alternative_title or self.title
        if self.is_tv and self.season:
            cn_season = to_cn_season(self.season)
            if cn_season and (cn_season in best_cn or f"第{self.season}季" in best_cn):
                cn_query = best_cn
            else:
                cn_query = f"{best_cn} {cn_season}".strip()
            chips.append((f"CN Title + Season: {cn_query}", cn_query))
        elif self.year:
            if str(self.year) in best_cn:
                cn_query = best_cn
            else:
                cn_query = f"{best_cn} {self.year}".strip()
            chips.append((f"CN Title + Year: {cn_query}", cn_query))
        elif best_cn:
            chips.append((f"CN Title: {best_cn}", best_cn))

        # 3. IMDb ID
        if self.imdb_id:
            chips.append((f"IMDb: {self.imdb_id}", self.imdb_id))

        # 4. English Title + Season / Year
        if self.title:
            if self.is_tv and self.season:
                chips.append((f"EN Title + Season: {self.title} S{self.season:02d}", f"{self.title} S{self.season:02d}"))
            elif self.year:
                chips.append((f"EN Title + Year: {self.title} {self.year}", f"{self.title} {self.year}"))
            else:
                chips.append((f"EN Title: {self.title}", self.title))

        return chips

    def build_search_queries(self) -> List[str]:
        """Generate prioritized search queries for subtitle engines."""
        queries = []

        # Douban ID first if known
        if self.douban_id:
            queries.append(self.douban_id)

        # Chinese title permutations
        best_cn = self.cn_title or self.alternative_title
        if best_cn:
            if self.is_tv and self.season:
                cn_season = to_cn_season(self.season)
                if cn_season not in best_cn and f"第{self.season}季" not in best_cn:
                    queries.append(f"{best_cn} {cn_season}")
                queries.append(best_cn)
            elif self.year:
                if str(self.year) not in best_cn:
                    queries.append(f"{best_cn} {self.year}")
                queries.append(best_cn)
            else:
                queries.append(best_cn)

        # English title permutations
        if self.title:
            if self.is_tv and self.season:
                queries.append(f"{self.title} {to_cn_season(self.season)}")
                queries.append(f"{self.title} 第{self.season}季")
                queries.append(f"{self.title} Season {self.season}")
                queries.append(self.title)
            elif self.year:
                queries.append(f"{self.title} {self.year}")
                queries.append(self.title)
            else:
                queries.append(self.title)

        if self.imdb_id:
            queries.append(self.imdb_id)

        # Deduplicate while preserving order
        seen = set()
        unique_queries = []
        for q in queries:
            q_clean = " ".join(q.split()).strip()
            if q_clean and q_clean not in seen:
                seen.add(q_clean)
                unique_queries.append(q_clean)
        return unique_queries


@dataclass
class SubtitleTags:
    """Metadata tags for a subtitle entry."""
    lang: List[str] = field(default_factory=list)   # 'chs', 'cht', 'eng', etc.
    fmt: List[str] = field(default_factory=list)    # 'ass', 'srt', 'ssa', 'vtt', 'sub'
    source: List[str] = field(default_factory=list) # 'official', 'ai', 'original', 'reprint', 'other', 'machine'
    bilingual: bool = False
    collection: bool = False
    fansub: str = ""
    uploader: str = ""
    provider: str = ""

    def display_uploader_or_group(self) -> str:
        """Return uploader username if available, else fansub group, filtering placeholder values."""
        if self.uploader:
            return self.uploader
        if self.fansub and self.fansub not in ("见字幕文件", "见片头", "见压缩包", "-"):
            return self.fansub
        return "-"

    def display_lang(self) -> str:
        """Format language string for GUI display with bilingual clarity."""
        if self.bilingual:
            if "cht" in self.lang and "chs" in self.lang:
                return "简繁/双语"
            elif "cht" in self.lang:
                return "繁英双语"
            else:
                return "中英双语"

        if "chs" in self.lang and "cht" in self.lang:
            return "简/繁"
        elif "cht" in self.lang:
            return "繁体"
        elif "chs" in self.lang:
            return "简体"
        elif "eng" in self.lang:
            return "英文"
        elif self.lang:
            return "/".join(l.upper() for l in self.lang)
        return "简体"

    def display_type(self) -> str:
        """Format subtitle type/source for GUI display preserving original text."""
        if not self.source:
            return "-"
        return "/".join(self.source)

    def summary_label(self) -> str:
        """Construct a formatted tag string for display in GUI or CLI."""
        parts = []
        lang_str = "/".join(self.lang).upper() if self.lang else "CHS"
        if self.bilingual and "DUAL" not in lang_str:
            lang_str += " (Dual)"
        parts.append(f"[{lang_str}]")

        if self.fmt:
            parts.append(f"[{'/'.join(f.upper() for f in self.fmt)}]")

        type_str = self.display_type()
        if type_str and type_str != "-":
            parts.append(f"[{type_str}]")

        uploader_group = self.display_uploader_or_group()
        if uploader_group and uploader_group != "-":
            parts.append(f"[{uploader_group}]")

        if self.collection:
            parts.append("[Pack]")

        return " ".join(parts)


@dataclass
class SubtitleItem:
    """A subtitle search result."""
    id: str
    title: str
    page_url: str
    provider: str
    tags: SubtitleTags = field(default_factory=SubtitleTags)
    download_url: Optional[str] = None
    rate: float = 0.0
    rate_stars: str = ""
    downloads_count: int = 0
    score: float = 0.0

    @property
    def display_title(self) -> str:
        tag_str = self.tags.summary_label()
        return f"{tag_str} {self.title}".strip()

    @property
    def display_rating(self) -> str:
        if self.rate_stars:
            return self.rate_stars
        if self.rate > 0:
            return f"{self.rate:.1f}★"
        return "-"


@dataclass
class DownloadResult:
    """Result of subtitle download and extraction."""
    success: bool = False
    saved_path: str = ""
    all_saved_paths: List[str] = field(default_factory=list)
    extracted_files: List[str] = field(default_factory=list)
    error_msg: str = ""
