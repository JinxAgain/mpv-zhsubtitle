"""Core service layer coordinating providers concurrently, ranking results, and managing downloads."""

import concurrent.futures
import re
from typing import Dict, List, Optional, Tuple

from .config import Config, load_config
from .extractor import extract_and_save_subtitle
from .logger import logger
from .models import DownloadResult, SubtitleItem, VideoMeta, to_cn_season
from .providers import BaseProvider, SubhdProvider, ZimukuProvider


class SubtitleService:
    """Orchestrates subtitle searching, scoring, downloading, and extraction."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or load_config()
        self.providers: Dict[str, BaseProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        """Initialize enabled providers."""
        if self.config.is_provider_enabled("subhd"):
            cfg = self.config.get_provider_config("subhd")
            self.providers["subhd"] = SubhdProvider(cfg)

        if self.config.is_provider_enabled("zimuku"):
            cfg = self.config.get_provider_config("zimuku")
            self.providers["zimuku"] = ZimukuProvider(cfg)

    def auto_resolve(self, meta: VideoMeta) -> Tuple[List[SubtitleItem], VideoMeta]:
        """
        Two-stage high precision resolution:
        1. Resolve Zimuku work to extract Douban ID, IMDb ID, Chinese title, and Zimuku subtitles.
        2. Bridge to SubHD using the extracted Douban ID (or IMDb ID / Chinese Title + Season).
        3. Score, deduplicate, and rank all candidates.
        """
        all_results: List[SubtitleItem] = []
        zimuku = self.providers.get("zimuku")
        subhd = self.providers.get("subhd")

        # Stage 1: Query Zimuku to resolve work & extract Douban / IMDb IDs
        if zimuku:
            try:
                base_query = meta.title or meta.alternative_title or meta.raw_name
                logger.info(f"[Service] Auto-resolving work on Zimuku for '{base_query}'...")
                zimuku_subs = zimuku.search(base_query, meta=meta)
                all_results.extend(zimuku_subs)
                logger.info(f"[Service] Zimuku returned {len(zimuku_subs)} subtitles (Douban ID='{meta.douban_id}', IMDb ID='{meta.imdb_id}')")
            except Exception as e:
                logger.error(f"[Service] Zimuku auto-resolve error: {e}")

        # Stage 2: Bridge to SubHD using Douban ID / IMDb ID / Chinese Title
        if subhd:
            try:
                subhd_queries = []
                if meta.douban_id:
                    subhd_queries.append(meta.douban_id)
                if meta.imdb_id:
                    subhd_queries.append(meta.imdb_id)

                best_cn = meta.cn_title or meta.alternative_title or meta.title
                if meta.is_tv and meta.season:
                    subhd_queries.append(f"{best_cn} {to_cn_season(meta.season)}")
                    subhd_queries.append(f"{best_cn} 第{meta.season}季")
                elif meta.year:
                    subhd_queries.append(f"{best_cn} {meta.year}")
                else:
                    subhd_queries.append(best_cn)

                subhd_subs: List[SubtitleItem] = []
                for sq in subhd_queries:
                    logger.info(f"[Service] Querying SubHD with '{sq}'...")
                    subhd_subs = subhd.search(sq, meta=meta)
                    if subhd_subs:
                        break

                all_results.extend(subhd_subs)
                logger.info(f"[Service] SubHD returned {len(subhd_subs)} subtitles")
            except Exception as e:
                logger.error(f"[Service] SubHD bridge query error: {e}")

        # Deduplicate subtitles by (provider, id)
        seen_keys = set()
        unique_results = []
        for item in all_results:
            key = (item.provider, item.id)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_results.append(item)

        # Calculate ranking score
        for item in unique_results:
            item.score = self._calculate_score(item, meta)

        unique_results.sort(key=lambda s: s.score, reverse=True)
        return unique_results, meta

    def search(
        self,
        query: str,
        meta: Optional[VideoMeta] = None,
        provider_names: Optional[List[str]] = None
    ) -> List[SubtitleItem]:
        """
        Direct search across active providers concurrently in parallel threads.
        """
        all_results: List[SubtitleItem] = []
        target_providers = [p for p in (provider_names or list(self.providers.keys())) if p in self.providers]

        if not target_providers:
            return []

        logger.info(f"[Service] Searching '{query}' across providers concurrently: {target_providers}")

        def _do_search(name: str) -> List[SubtitleItem]:
            prov = self.providers.get(name)
            if not prov:
                return []
            try:
                res = prov.search(query, meta=meta)
                return res
            except Exception as e:
                logger.error(f"[{name}] Search error: {e}")
                return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(target_providers)) as executor:
            future_to_provider = {executor.submit(_do_search, name): name for name in target_providers}
            for future in concurrent.futures.as_completed(future_to_provider):
                prov_name = future_to_provider[future]
                try:
                    res = future.result()
                    all_results.extend(res)
                except Exception as e:
                    logger.error(f"[{prov_name}] Future resolution error: {e}")

        # Deduplicate
        seen_keys = set()
        unique_results = []
        for item in all_results:
            key = (item.provider, item.id)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_results.append(item)

        for item in unique_results:
            item.score = self._calculate_score(item, meta)

        unique_results.sort(key=lambda s: s.score, reverse=True)
        logger.info(f"[Service] Total {len(unique_results)} subtitle results aggregated across {target_providers}")
        return unique_results

    def _calculate_score(self, item: SubtitleItem, meta: Optional[VideoMeta]) -> float:
        """Calculate match score based on format, source, and release group match."""
        score = 20.0
        title_lower = item.title.lower()

        # Format weighting (srt is highest by default)
        prefer_formats = [f.lower() for f in self.config.prefer_format]
        for idx, fmt in enumerate(prefer_formats):
            if fmt in item.tags.fmt or f".{fmt}" in title_lower:
                score += (len(prefer_formats) - idx) * 4.0
                break

        # Source quality weighting
        tags = item.tags
        if "official" in tags.source:
            score += 10.0
        elif "reprint" in tags.source:
            score += 8.0
        elif "original" in tags.source:
            score += 6.0
        elif "ai" in tags.source:
            score += 2.0

        if tags.bilingual:
            score += 5.0

        # Metadata matching (Release group, source, resolution)
        if meta:
            if meta.release_group and meta.release_group.lower() in title_lower:
                score += 20.0
            if meta.source and meta.source.lower() in title_lower:
                score += 10.0
            if meta.screen_size and meta.screen_size.lower() in title_lower:
                score += 5.0
            if meta.year and str(meta.year) in title_lower:
                score += 8.0

            # TV episode match bonus (+35 for exact episode)
            if meta.is_tv and meta.episode is not None:
                ep_tokens = [
                    f"s{meta.season:02d}e{meta.episode:02d}" if meta.season else "",
                    f"e{meta.episode:02d}",
                    f"ep{meta.episode:02d}",
                    f"e{meta.episode}",
                    f"第{meta.episode}集",
                    f"第{meta.episode:02d}集"
                ]
                ep_tokens = [tok for tok in ep_tokens if tok]
                if any(tok in title_lower for tok in ep_tokens):
                    score += 35.0

        return score

    def download_and_extract(
        self,
        item: SubtitleItem,
        video_path: Optional[str] = None,
        meta: Optional[VideoMeta] = None
    ) -> DownloadResult:
        """
        Download the given subtitle item, unpack archives, and save to configured destination.
        """
        prov = self.providers.get(item.provider)
        if not prov:
            return DownloadResult(success=False, error_msg=f"Provider '{item.provider}' is not available")

        logger.info(f"Downloading from {item.provider}: {item.title} ({item.page_url})")
        content_bytes, original_filename = prov.download(item)
        if not content_bytes:
            return DownloadResult(success=False, error_msg=f"Download failed from {item.provider}")

        target_dir = self.config.resolve_extract_dir(video_path)
        logger.info(f"Target extraction directory resolved: {target_dir}")

        episode = meta.episode if meta else None
        return extract_and_save_subtitle(
            content_bytes=content_bytes,
            original_filename=original_filename,
            target_dir=target_dir,
            video_path=video_path,
            episode=episode,
            rename_to_video=self.config.rename_to_video,
            prefer_format=self.config.prefer_format,
            prefer_language=self.config.prefer_language
        )
