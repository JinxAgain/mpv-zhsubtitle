"""Archive extraction, charset fixing, and subtitle file management."""

import gzip
import io
import os
import re
import shutil
import tempfile
import zipfile
from typing import List, Optional, Tuple

from .models import DownloadResult

SUBTITLE_EXTS = (".srt", ".ass", ".ssa", ".vtt", ".sub")
SIDECAR_EXTS = (".idx",)
ARCHIVE_EXTS = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz")


def fix_archive_filename(filename: str) -> str:
    """Fix mojibake in zip filenames caused by CP437 vs GBK/GB18030 mismatch."""
    try:
        # Zipfile decodes as CP437 if UTF-8 bit is missing. Recover raw bytes and decode as GBK/GB18030
        raw_bytes = filename.encode("cp437")
        return raw_bytes.decode("gb18030")
    except Exception:
        return filename


def sanitize_filename(name: str) -> str:
    """Remove illegal characters from filename."""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")


def pick_best_subtitle_file(
    filenames: List[str],
    episode: Optional[int] = None,
    prefer_format: Optional[List[str]] = None,
    prefer_language: Optional[List[str]] = None
) -> Optional[str]:
    """
    Select the most suitable subtitle file from a list of extracted files.
    Ranks by episode match, format preference (.ass > .srt), and language preference.
    """
    if not filenames:
        return None

    prefer_format = [f.lower() for f in (prefer_format or ["ass", "srt", "ssa", "vtt"])]
    prefer_language = [l.lower() for l in (prefer_language or ["chs", "cht", "eng"])]

    def score_file(name: str) -> Tuple[int, int, int]:
        lower = name.lower()
        ep_score = 0
        if episode is not None:
            ep_patterns = [
                rf"\b[eE][pP]?0*{episode}\b",
                rf"s\d{{1,2}}e0*{episode}\b",
                rf"第\s*0*{episode}\s*[集话話]",
                rf"\[0*{episode}\]"
            ]
            for pat in ep_patterns:
                if re.search(pat, lower):
                    ep_score = 100
                    break

        # Format score
        fmt_score = 0
        ext = os.path.splitext(lower)[1].lstrip(".")
        if ext in prefer_format:
            fmt_score = len(prefer_format) - prefer_format.index(ext)

        # Language score
        lang_score = 0
        if "chs" in lower or "sc" in lower or "gb" in lower or "简体" in lower or "简中" in lower:
            lang_score = 10
        elif "cht" in lower or "tc" in lower or "big5" in lower or "繁体" in lower or "繁中" in lower:
            lang_score = 8
        elif "eng" in lower or "en" in lower or "英文" in lower or "英语" in lower:
            lang_score = 5

        return (ep_score, lang_score, fmt_score)

    sorted_files = sorted(filenames, key=score_file, reverse=True)
    return sorted_files[0]


def extract_and_save_subtitle(
    content_bytes: bytes,
    original_filename: str,
    target_dir: str,
    video_path: Optional[str] = None,
    episode: Optional[int] = None,
    rename_to_video: bool = True,
    prefer_format: Optional[List[str]] = None,
    prefer_language: Optional[List[str]] = None
) -> DownloadResult:
    """
    Save downloaded bytes, unpack archives (.zip, .gz, etc.), extract subtitle files,
    and save the selected subtitle file directly to target_dir.
    """
    os.makedirs(target_dir, exist_ok=True)
    lower_name = original_filename.lower()

    # Case 1: GZIP compressed file
    if content_bytes[:2] == b"\x1f\x8b" or lower_name.endswith(".gz"):
        try:
            decompressed = gzip.decompress(content_bytes)
            clean_base = re.sub(r"\.gz$", "", original_filename, flags=re.IGNORECASE)
            return extract_and_save_subtitle(
                decompressed,
                clean_base,
                target_dir,
                video_path=video_path,
                episode=episode,
                rename_to_video=rename_to_video,
                prefer_format=prefer_format,
                prefer_language=prefer_language
            )
        except Exception as e:
            return DownloadResult(success=False, error_msg=f"Gzip decompression error: {e}")

    # Case 2: ZIP archive
    if content_bytes[:2] == b"PK" or lower_name.endswith(".zip"):
        return _extract_from_zip(
            content_bytes,
            target_dir,
            video_path=video_path,
            episode=episode,
            rename_to_video=rename_to_video,
            prefer_format=prefer_format,
            prefer_language=prefer_language
        )

    # Case 3: Direct subtitle file (.srt, .ass, etc.)
    ext = os.path.splitext(original_filename)[1].lower()
    if ext in SUBTITLE_EXTS:
        final_name = _determine_final_name(original_filename, video_path, rename_to_video)
        final_path = os.path.join(target_dir, final_name)
        try:
            with open(final_path, "wb") as f:
                f.write(content_bytes)
            return DownloadResult(
                success=True,
                saved_path=final_path,
                extracted_files=[final_path]
            )
        except Exception as e:
            return DownloadResult(success=False, error_msg=f"Failed to write subtitle file: {e}")

    # Case 4: Other archive formats (.rar, .7z, etc.) fallback via temp folder
    return _extract_generic_archive(
        content_bytes,
        original_filename,
        target_dir,
        video_path=video_path,
        episode=episode,
        rename_to_video=rename_to_video,
        prefer_format=prefer_format,
        prefer_language=prefer_language
    )


def _extract_from_zip(
    content_bytes: bytes,
    target_dir: str,
    video_path: Optional[str],
    episode: Optional[int],
    rename_to_video: bool,
    prefer_format: Optional[List[str]],
    prefer_language: Optional[List[str]]
) -> DownloadResult:
    """Extract subtitles from ZIP bytes in-memory."""
    try:
        with zipfile.ZipFile(io.BytesIO(content_bytes)) as zf:
            extracted_map = {}
            for info in zf.infolist():
                if info.is_dir():
                    continue

                # Recover GBK charset if UTF-8 flag bit is not set
                filename = info.filename if (info.flag_bits & 0x800) else fix_archive_filename(info.filename)
                base_name = os.path.basename(filename)
                if not base_name:
                    continue

                if base_name.lower().endswith(SUBTITLE_EXTS + SIDECAR_EXTS):
                    extracted_map[base_name] = zf.read(info)

            sub_names = [name for name in extracted_map if name.lower().endswith(SUBTITLE_EXTS)]
            if not sub_names:
                return DownloadResult(success=False, error_msg="No subtitle files (.srt, .ass, etc.) found in archive")

            best_sub = pick_best_subtitle_file(
                sub_names,
                episode=episode,
                prefer_format=prefer_format,
                prefer_language=prefer_language
            )

            if not best_sub:
                best_sub = sub_names[0]

            # Save the chosen subtitle
            final_name = _determine_final_name(best_sub, video_path, rename_to_video)
            final_path = os.path.join(target_dir, final_name)
            with open(final_path, "wb") as f:
                f.write(extracted_map[best_sub])

            # If it's a .sub file and a matching .idx exists, extract .idx too
            if best_sub.lower().endswith(".sub"):
                idx_base = os.path.splitext(best_sub)[0] + ".idx"
                for k in extracted_map:
                    if k.lower() == idx_base.lower():
                        idx_final = os.path.splitext(final_path)[0] + ".idx"
                        with open(idx_final, "wb") as f:
                            f.write(extracted_map[k])
                        break

            return DownloadResult(
                success=True,
                saved_path=final_path,
                extracted_files=[final_path]
            )

    except Exception as e:
        return DownloadResult(success=False, error_msg=f"Failed to extract ZIP archive: {e}")


def _extract_generic_archive(
    content_bytes: bytes,
    original_filename: str,
    target_dir: str,
    video_path: Optional[str],
    episode: Optional[int],
    rename_to_video: bool,
    prefer_format: Optional[List[str]],
    prefer_language: Optional[List[str]]
) -> DownloadResult:
    """Handle other archive formats (.tar, etc.) using a temporary directory."""
    temp_dir = tempfile.mkdtemp(prefix="zhsub_")
    try:
        temp_archive = os.path.join(temp_dir, original_filename)
        with open(temp_archive, "wb") as f:
            f.write(content_bytes)

        # Try unpacking via shutil.unpack_archive
        try:
            shutil.unpack_archive(temp_archive, temp_dir)
        except Exception:
            pass

        # Scan for extracted subtitles
        found_subs = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.lower().endswith(SUBTITLE_EXTS):
                    found_subs.append(os.path.join(root, file))

        if not found_subs:
            return DownloadResult(success=False, error_msg=f"Unsupported archive or no subtitles found in {original_filename}")

        # Pick best subtitle
        sub_basenames = [os.path.basename(p) for p in found_subs]
        best_base = pick_best_subtitle_file(
            sub_basenames,
            episode=episode,
            prefer_format=prefer_format,
            prefer_language=prefer_language
        ) or sub_basenames[0]

        best_src_path = next(p for p in found_subs if os.path.basename(p) == best_base)
        final_name = _determine_final_name(best_base, video_path, rename_to_video)
        final_path = os.path.join(target_dir, final_name)

        shutil.copyfile(best_src_path, final_path)
        return DownloadResult(
            success=True,
            saved_path=final_path,
            extracted_files=[final_path]
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _determine_final_name(subtitle_filename: str, video_path: Optional[str], rename_to_video: bool) -> str:
    """Determine the final saved filename for the subtitle."""
    ext = os.path.splitext(subtitle_filename)[1].lower()

    if rename_to_video and video_path:
        video_base = os.path.splitext(os.path.basename(video_path))[0]
        # Detect if subtitle has language indicators
        lower_sub = subtitle_filename.lower()
        lang_suffix = ""
        if "chs" in lower_sub or "简" in lower_sub:
            lang_suffix = ".zh-CN"
        elif "cht" in lower_sub or "繁" in lower_sub:
            lang_suffix = ".zh-TW"
        elif "eng" in lower_sub or "en" in lower_sub:
            lang_suffix = ".en"
        elif "双语" in lower_sub or "dual" in lower_sub:
            lang_suffix = ".zh-CN&en"

        return f"{video_base}{lang_suffix}{ext}"

    return sanitize_filename(subtitle_filename)
