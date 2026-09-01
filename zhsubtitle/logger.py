"""Logging utility for zhsubtitle to console and dynamically resolved log file."""

import logging
import os
import sys
from typing import Optional


def resolve_log_path() -> str:
    """
    Dynamically resolve log path:
    If installed in .../scripts/mpv-zhsubtitle, go up 2 levels to mpv/mpv.net root.
    Otherwise fallback to the package directory or current working directory.
    """
    try:
        # zhsubtitle package root
        pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        parent_dir = os.path.dirname(pkg_root)
        parent_name = os.path.basename(parent_dir).lower()

        # If inside .../scripts/mpv-zhsubtitle, go up to mpv / mpv.net root
        if parent_name == "scripts":
            mpv_root = os.path.dirname(parent_dir)
            return os.path.join(mpv_root, "zhsubtitle.log")

        # Check if parent is mpv/mpv.net directly
        if parent_name in ("mpv", "mpv.net"):
            return os.path.join(parent_dir, "zhsubtitle.log")

        # Fallback to package root
        return os.path.join(pkg_root, "zhsubtitle.log")
    except Exception:
        return "zhsubtitle.log"


def setup_logger(log_file: Optional[str] = None, debug: bool = True) -> logging.Logger:
    """Configure and return the application logger."""
    logger = logging.getLogger("zhsubtitle")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # Console handler (stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.addHandler(console_handler)

    # File handler with dynamically resolved path
    target_log_file = log_file or resolve_log_path()

    try:
        os.makedirs(os.path.dirname(os.path.abspath(target_log_file)), exist_ok=True)
        file_handler = logging.FileHandler(target_log_file, mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except Exception as e:
        sys.stderr.write(f"[zhsubtitle] Failed to initialize log file at {target_log_file}: {e}\n")

    return logger


logger = setup_logger()
