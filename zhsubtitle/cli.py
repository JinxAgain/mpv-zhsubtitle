"""Command line interface runner for zhsubtitle."""

import argparse
import os
import sys
from typing import List, Optional

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from .config import load_config
from .extractor import extract_and_save_subtitle
from .guess import parse_video
from .gui import launch_gui
from .models import VideoMeta
from .service import SubtitleService



def auto_download(video_path: str, custom_query: Optional[str] = None) -> int:
    """
    Automatic one-key search and download.
    Parses video name with guessit, queries providers, tries best-ranked subtitles,
    extracts to target directory, and prints [SUBTITLE_LOADED]<path>.
    """
    config = load_config()
    service = SubtitleService(config)

    meta: VideoMeta = parse_video(video_path)
    queries = [custom_query] if custom_query else meta.build_search_queries()
    if not queries:
        queries = [os.path.basename(video_path)]

    print(f"[zhsubtitle] Auto search queries: {queries}", file=sys.stderr)

    results = []
    for q in queries:
        print(f"[zhsubtitle] Searching query: '{q}'...", file=sys.stderr)
        results = service.search(q, meta=meta)
        if results:
            break

    if not results:
        print(f"[zhsubtitle] No subtitles found for {video_path}", file=sys.stderr)
        return 1

    # Try downloading from top-ranked candidates until one succeeds
    for rank, item in enumerate(results[:15], 1):
        print(f"[zhsubtitle] Trying candidate #{rank}: [{item.provider.upper()}] {item.title} (Score: {int(item.score)})", file=sys.stderr)
        res = service.download_and_extract(item, video_path=video_path, meta=meta)
        if res.success and res.saved_path:
            for extra_path in res.all_saved_paths:
                if extra_path != res.saved_path:
                    print(f"[SUBTITLE_EXTRACTED]{extra_path}")
            print(f"[SUBTITLE_LOADED]{res.saved_path}")
            sys.stdout.flush()
            return 0
        else:
            print(f"[zhsubtitle] Candidate #{rank} failed ({res.error_msg}), trying next...", file=sys.stderr)

    print(f"[zhsubtitle] All top subtitle candidates failed to download", file=sys.stderr)
    return 1



def search_cli(query: str, video_path: Optional[str] = None) -> int:
    """Search and list results in terminal."""
    config = load_config()
    service = SubtitleService(config)
    meta = parse_video(video_path) if video_path else None

    results = service.search(query, meta=meta)
    print(f"\nSearch results for '{query}' ({len(results)} found):")
    print("-" * 75)
    for idx, item in enumerate(results, 1):
        tags_str = item.tags.summary_label()
        print(f"{idx:2d}. [{item.provider.upper()}] {item.title}")
        print(f"    Tags: {tags_str} | Score: {int(item.score)} | ID: {item.id}")
    print("-" * 75)
    return 0


def main(args: Optional[List[str]] = None) -> int:
    """Entry point parsing CLI arguments."""
    parser = argparse.ArgumentParser(description="MPV Chinese Subtitle Downloader (SubHD & Zimuku)")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # auto sub-command
    auto_parser = subparsers.add_parser("auto", help="Auto-search and download the best subtitle")
    auto_parser.add_argument("video", nargs="?", help="Path to video file")
    auto_parser.add_argument("--video", dest="video_opt", help="Path to video file")
    auto_parser.add_argument("--query", "-q", help="Override search query")

    # gui sub-command
    gui_parser = subparsers.add_parser("gui", help="Open interactive visual search GUI")
    gui_parser.add_argument("video", nargs="?", help="Path to video file")
    gui_parser.add_argument("--video", dest="video_opt", help="Path to video file")
    gui_parser.add_argument("--query", "-q", help="Initial search query")

    # search sub-command
    search_parser = subparsers.add_parser("search", help="Search subtitles in terminal")
    search_parser.add_argument("query", help="Search query string")
    search_parser.add_argument("--video", help="Optional video file for score ranking")

    parsed = parser.parse_args(args)

    if parsed.command == "auto":
        v_path = parsed.video or parsed.video_opt
        if not v_path:
            print("Error: video path is required for auto mode", file=sys.stderr)
            return 1
        return auto_download(v_path, custom_query=parsed.query)

    elif parsed.command == "gui" or parsed.command is None:
        v_path = getattr(parsed, "video", None) or getattr(parsed, "video_opt", None)
        query = getattr(parsed, "query", None)
        sub_path = launch_gui(video_path=v_path, initial_query=query)
        return 0 if sub_path else 1

    elif parsed.command == "search":
        return search_cli(parsed.query, video_path=parsed.video)

    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
