"""Archive extraction, charset fixing, and subtitle file management."""

import gzip
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from typing import List, Optional, Tuple

from .models import DownloadResult

logger = logging.getLogger(__name__)

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
    """Remove illegal characters from filename while preserving valid spaces and symbols."""
    clean = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return clean or "subtitle"


def pick_best_subtitle_file(
    filenames: List[str],
    episode: Optional[int] = None,
    prefer_format: Optional[List[str]] = None,
    prefer_language: Optional[List[str]] = None
) -> Optional[str]:
    """
    Select the most suitable subtitle file from a list of extracted files.
    Ranks by:
    1. Target episode match (+1000)
    2. Language priority: Bilingual (+500) > Simplified Chinese (+300) > Traditional Chinese (+280) > English (+50)
    3. User format preference (.srt, .ass, etc.)
    """
    if not filenames:
        return None

    prefer_format = [f.lower() for f in (prefer_format or ["srt", "ass", "ssa", "vtt"])]

    # Bilingual patterns (e.g. zh-en, chs.eng, 简英, 繁英, 双语, chs&eng)
    bilingual_pat = re.compile(
        r'双语|简英|繁英|中英|chs[&+._ -]?eng|cht[&+._ -]?eng|zh[&+._ -]?en|chi[&+._ -]?eng|zho[&+._ -]?eng|en[&+._ -]?zh',
        re.IGNORECASE
    )

    # Simplified Chinese patterns
    chs_pat = re.compile(
        r'chs|gb|sc|简|简体|简中|zh-cn|zh-hans|zh-sg|chi|zho|\bzh\b|\bcn\b',
        re.IGNORECASE
    )

    # Traditional Chinese patterns
    cht_pat = re.compile(
        r'cht|tc|big5|繁|繁体|繁體|繁中|zh-tw|zh-hk|zh-hant|hk|tw',
        re.IGNORECASE
    )

    # English-only patterns
    eng_pat = re.compile(r'eng|en|英文|英语', re.IGNORECASE)

    def score_file(name: str) -> Tuple[int, int, int]:
        lower = name.lower()

        # 1. Episode score
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
                    ep_score = 1000
                    break

        # 2. Language score (Bilingual > CHS > CHT > ENG)
        lang_score = 0
        if bilingual_pat.search(lower):
            lang_score = 500
        elif chs_pat.search(lower):
            lang_score = 300
        elif cht_pat.search(lower):
            lang_score = 280
        elif eng_pat.search(lower):
            lang_score = 50

        # 3. Format score
        fmt_score = 0
        ext = os.path.splitext(lower)[1].lstrip(".")
        if ext in prefer_format:
            fmt_score = (len(prefer_format) - prefer_format.index(ext)) * 10

        return (ep_score, lang_score, fmt_score)

    sorted_files = sorted(filenames, key=score_file, reverse=True)
    return sorted_files[0]


def extract_and_save_subtitle(
    content_bytes: bytes,
    original_filename: str,
    target_dir: str,
    video_path: Optional[str] = None,
    episode: Optional[int] = None,
    rename_to_video: bool = False,
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
    """Extract all subtitles from ZIP bytes in-memory and return primary and secondary files."""
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
            ) or sub_names[0]

            # Save ALL subtitle files to target_dir
            used_names = set()
            saved_paths_map = {}
            for sub_name in sub_names:
                out_name = _determine_final_name(sub_name, video_path, rename_to_video, used_names)
                used_names.add(out_name)
                out_path = os.path.join(target_dir, out_name)
                with open(out_path, "wb") as f:
                    f.write(extracted_map[sub_name])
                saved_paths_map[sub_name] = out_path

                # If it's a .sub file and a matching .idx exists, extract .idx too
                if sub_name.lower().endswith(".sub"):
                    idx_base = os.path.splitext(sub_name)[0] + ".idx"
                    for k in extracted_map:
                        if k.lower() == idx_base.lower():
                            idx_final = os.path.splitext(out_path)[0] + ".idx"
                            with open(idx_final, "wb") as f:
                                f.write(extracted_map[k])
                            break

            primary_path = saved_paths_map.get(best_sub, list(saved_paths_map.values())[0])
            all_paths = list(saved_paths_map.values())

            return DownloadResult(
                success=True,
                saved_path=primary_path,
                all_saved_paths=all_paths,
                extracted_files=all_paths
            )

    except Exception as e:
        return DownloadResult(success=False, error_msg=f"Failed to extract ZIP archive: {e}")


def _find_extractor_tool(cmd: str, extra_locations: List[str]) -> Optional[str]:
    """Locate an archive extractor executable in system PATH or standard install paths."""
    found = shutil.which(cmd)
    if found:
        return found
    for path in extra_locations:
        if os.path.isfile(path):
            return path
    return None


def _unpack_archive_with_external_tools(archive_path: str, extract_dir: str) -> bool:
    """
    Unpack archives (.rar, .7z, .tar, .xz, .zip) using available system tools:
    1. 7-Zip (7z.exe / 7za.exe)
    2. Windows System32 tar.exe or POSIX bsdtar/tar (libarchive-based)
    3. WinRAR (UnRAR.exe / WinRAR.exe)
    4. Optional Python modules (py7zr, rarfile)
    5. Python shutil.unpack_archive
    """
    lower = archive_path.lower()

    # 1. Try 7-Zip (handles .7z, .rar, .zip, .tar, etc.)
    exe_7z = _find_extractor_tool("7z", [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe"
    ]) or _find_extractor_tool("7za", [])
    if exe_7z:
        try:
            res = subprocess.run([exe_7z, "x", "-y", f"-o{extract_dir}", archive_path], capture_output=True, text=True)
            if res.returncode == 0:
                logger.debug(f"[Extractor] Unpacked via 7-Zip: {archive_path}")
                return True
        except Exception:
            pass

    # 2. Try Windows 10/11 / POSIX tar (bsdtar with libarchive extracts .tar, .tar.gz, .7z, .rar, .zip)
    tar_exe = _find_extractor_tool("tar", [r"C:\Windows\System32\tar.exe"])
    if tar_exe:
        try:
            res = subprocess.run([tar_exe, "-xf", archive_path, "-C", extract_dir], capture_output=True, text=True)
            if res.returncode == 0:
                logger.debug(f"[Extractor] Unpacked via tar: {archive_path}")
                return True
        except Exception:
            pass

    # 3. Try UnRAR / WinRAR for .rar files
    if lower.endswith(".rar"):
        unrar_exe = _find_extractor_tool("unrar", [
            r"C:\Program Files\WinRAR\UnRAR.exe",
            r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
            r"C:\Program Files\WinRAR\WinRAR.exe",
            r"C:\Program Files (x86)\WinRAR\WinRAR.exe"
        ])
        if unrar_exe:
            try:
                args = [unrar_exe, "x", "-ibck", "-y", archive_path, extract_dir + "\\"]
                res = subprocess.run(args, capture_output=True, text=True)
                if res.returncode == 0:
                    logger.debug(f"[Extractor] Unpacked via WinRAR/UnRAR: {archive_path}")
                    return True
            except Exception:
                pass

    # 4. Try Python packages if installed
    if lower.endswith(".7z"):
        try:
            import py7zr
            with py7zr.SevenZipFile(archive_path, mode="r") as z:
                z.extractall(extract_dir)
            logger.debug(f"[Extractor] Unpacked via py7zr: {archive_path}")
            return True
        except Exception:
            pass

    if lower.endswith(".rar"):
        try:
            import rarfile
            with rarfile.RarFile(archive_path) as rf:
                rf.extractall(extract_dir)
            logger.debug(f"[Extractor] Unpacked via rarfile: {archive_path}")
            return True
        except Exception:
            pass

    # 5. Fallback to standard library shutil.unpack_archive
    try:
        shutil.unpack_archive(archive_path, extract_dir)
        logger.debug(f"[Extractor] Unpacked via shutil: {archive_path}")
        return True
    except Exception:
        pass

    return False


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
    """Handle other archive formats (.rar, .7z, .tar, etc.) using a temporary directory."""
    temp_dir = tempfile.mkdtemp(prefix="zhsub_")
    try:
        # Determine accurate archive extension even if original filename has spacing/encoding anomalies
        ext = os.path.splitext(original_filename.strip())[1].lower()
        if not ext:
            if content_bytes[:4] == b"Rar!":
                ext = ".rar"
            elif content_bytes[:6] == b"7z\xbc\xaf\x27\x1c":
                ext = ".7z"
            elif content_bytes[:2] == b"PK":
                ext = ".zip"

        temp_archive = os.path.join(temp_dir, f"archive{ext}")
        with open(temp_archive, "wb") as f:
            f.write(content_bytes)

        # Try unpacking via external tools and libraries
        unpacked = _unpack_archive_with_external_tools(temp_archive, temp_dir)
        if not unpacked:
            logger.warning(f"[Extractor] External unpack tools failed for {original_filename}")

        # Scan for extracted subtitles
        found_subs = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.lower().endswith(SUBTITLE_EXTS):
                    found_subs.append(os.path.join(root, file))

        if not found_subs:
            return DownloadResult(success=False, error_msg="No subtitle files found inside extracted archive")

        # Pick best subtitle
        sub_basenames = [os.path.basename(p) for p in found_subs]
        best_base = pick_best_subtitle_file(
            sub_basenames,
            episode=episode,
            prefer_format=prefer_format,
            prefer_language=prefer_language
        ) or sub_basenames[0]

        used_names = set()
        saved_paths_map = {}
        for src_path in found_subs:
            bname = os.path.basename(src_path)
            out_name = _determine_final_name(bname, video_path, rename_to_video, used_names)
            used_names.add(out_name)
            out_path = os.path.join(target_dir, out_name)
            shutil.copyfile(src_path, out_path)
            saved_paths_map[bname] = out_path

        primary_path = saved_paths_map.get(best_base, list(saved_paths_map.values())[0])
        all_paths = list(saved_paths_map.values())

        return DownloadResult(
            success=True,
            saved_path=primary_path,
            all_saved_paths=all_paths,
            extracted_files=all_paths
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _determine_final_name(
    subtitle_filename: str,
    video_path: Optional[str],
    rename_to_video: bool,
    used_names: Optional[set] = None
) -> str:
    """Determine the final saved filename for the subtitle with language differentiation."""
    ext = os.path.splitext(subtitle_filename)[1].lower()
    used = used_names or set()

    if rename_to_video and video_path:
        video_base = os.path.splitext(os.path.basename(video_path))[0]
        lower_sub = subtitle_filename.lower()

        # Check bilingual first
        bilingual_match = re.search(r'双语|简英|繁英|中英|zh[-_.]?en|chs[&+._ -]?eng|cht[&+._ -]?eng', lower_sub)
        if bilingual_match:
            lang_suffix = ".zh-en"
        elif any(k in lower_sub for k in ("chs", "简", "sc", "gb", "zh-cn", "zh-hans")):
            lang_suffix = ".zh-cn"
        elif any(k in lower_sub for k in ("cht", "繁", "tc", "big5", "zh-tw", "zh-hk")):
            lang_suffix = ".zh-tw"
        elif any(k in lower_sub for k in ("eng", "en", "英文")):
            lang_suffix = ".en"
        elif "zh" in lower_sub or "cn" in lower_sub:
            lang_suffix = ".zh"
        else:
            lang_suffix = ""

        candidate = f"{video_base}{lang_suffix}{ext}" if lang_suffix else f"{video_base}{ext}"
        if candidate not in used:
            return candidate

        # Disambiguate collision (e.g. two .zh-en.srt files)
        counter = 2
        while f"{video_base}{lang_suffix}.{counter}{ext}" in used:
            counter += 1
        return f"{video_base}{lang_suffix}.{counter}{ext}"

    # Preserve original subtitle name without modifying it to video name
    candidate = sanitize_filename(os.path.basename(subtitle_filename))
    if candidate not in used:
        return candidate

    name_root, name_ext = os.path.splitext(candidate)
    counter = 2
    while f"{name_root}.{counter}{name_ext}" in used:
        counter += 1
    return f"{name_root}.{counter}{name_ext}"
