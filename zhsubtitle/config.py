"""Configuration manager for loading and resolving settings from .conf or .json."""

import json
import os
import sys
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "extract_dir": "",
    "rename_to_video": False,
    "prefer_format": ["srt", "ass", "ssa", "vtt"],
    "prefer_language": ["chs", "cht", "eng"],
    "providers": {
        "subhd": {
            "enabled": True,
            "base_url": "https://subhd.tv",
            "fallback_urls": ["https://subhd.me", "https://subhd.one"],
            "timeout": 5
        },
        "zimuku": {
            "enabled": True,
            "base_url": "https://srtku.com",
            "fallback_urls": ["https://zmk.pw", "https://zimuku.org"],
            "timeout": 5
        }
    },
    "timeout": 10
}


class Config:
    """Application configuration handler supporting both JSON and MPV .conf formats."""

    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        self._data = dict(DEFAULT_CONFIG)
        if config_dict:
            self._update_deep(self._data, config_dict)

    def _update_deep(self, base: dict, override: dict) -> None:
        for k, v in override.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                self._update_deep(base[k], v)
            else:
                base[k] = v

    @property
    def extract_dir(self) -> str:
        return self._data.get("extract_dir", "")

    @property
    def rename_to_video(self) -> bool:
        return bool(self._data.get("rename_to_video", False))

    @property
    def prefer_format(self) -> List[str]:
        return self._data.get("prefer_format", ["srt", "ass", "ssa", "vtt"])

    @property
    def prefer_language(self) -> List[str]:
        return self._data.get("prefer_language", ["chs", "cht", "eng"])

    @property
    def timeout(self) -> int:
        return int(self._data.get("timeout", 10))

    def is_provider_enabled(self, name: str) -> bool:
        providers = self._data.get("providers", {})
        prov_cfg = providers.get(name, {})
        return bool(prov_cfg.get("enabled", True))

    def get_provider_config(self, name: str) -> Dict[str, Any]:
        providers = self._data.get("providers", {})
        return providers.get(name, {})

    def resolve_extract_dir(self, video_path: Optional[str] = None) -> str:
        """
        Resolve the target directory where subtitle files should be extracted.
        If extract_dir is empty or 'same_as_video', uses the directory of video_path.
        """
        raw_dir = self.extract_dir.strip() if self.extract_dir else ""

        if not raw_dir or raw_dir.lower() in ("same_as_video", "video_dir"):
            if video_path and os.path.exists(video_path):
                return os.path.dirname(os.path.abspath(video_path))
            elif video_path:
                dirname = os.path.dirname(video_path)
                return dirname if dirname else os.getcwd()
            return os.getcwd()

        # Expand user path (~) and env variables
        expanded = os.path.expandvars(os.path.expanduser(raw_dir))
        if video_path:
            video_dir = os.path.dirname(os.path.abspath(video_path)) if os.path.exists(video_path) else os.getcwd()
            expanded = expanded.replace("{video_dir}", video_dir)

        os.makedirs(expanded, exist_ok=True)
        return os.path.abspath(expanded)


def _parse_conf_file(file_path: str) -> Dict[str, Any]:
    """Parse MPV style key=value script-opts conf file."""
    config_dict: Dict[str, Any] = {
        "providers": {
            "subhd": {},
            "zimuku": {}
        }
    }
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip().lower()
                val = val.strip()

                if key == "extract_dir":
                    config_dict["extract_dir"] = val
                elif key == "rename_to_video":
                    config_dict["rename_to_video"] = val.lower() in ("yes", "true", "1", "on")
                elif key == "prefer_format":
                    config_dict["prefer_format"] = [fmt.strip().lower() for fmt in val.split(",") if fmt.strip()]
                elif key == "prefer_language":
                    config_dict["prefer_language"] = [lang.strip().lower() for lang in val.split(",") if lang.strip()]
                elif key == "timeout":
                    try:
                        config_dict["timeout"] = int(val)
                    except ValueError:
                        pass
                # SubHD options
                elif key == "subhd_enabled":
                    config_dict["providers"]["subhd"]["enabled"] = val.lower() in ("yes", "true", "1", "on")
                elif key == "subhd_base_url":
                    config_dict["providers"]["subhd"]["base_url"] = val
                elif key == "subhd_fallback_urls":
                    config_dict["providers"]["subhd"]["fallback_urls"] = [u.strip() for u in val.split(",") if u.strip()]
                elif key == "subhd_timeout":
                    try:
                        config_dict["providers"]["subhd"]["timeout"] = int(val)
                    except ValueError:
                        pass
                # Zimuku options
                elif key == "zimuku_enabled":
                    config_dict["providers"]["zimuku"]["enabled"] = val.lower() in ("yes", "true", "1", "on")
                elif key == "zimuku_base_url":
                    config_dict["providers"]["zimuku"]["base_url"] = val
                elif key == "zimuku_fallback_urls":
                    config_dict["providers"]["zimuku"]["fallback_urls"] = [u.strip() for u in val.split(",") if u.strip()]
                elif key == "zimuku_timeout":
                    try:
                        config_dict["providers"]["zimuku"]["timeout"] = int(val)
                    except ValueError:
                        pass
    except Exception as e:
        sys.stderr.write(f"[zhsubtitle] Warning: Error reading conf file {file_path}: {e}\n")

    return config_dict


def find_config_file() -> Optional[str]:
    """Look for zhsubtitle.conf or config.json in MPV / mpv.net and package dirs."""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cur_dir = os.getcwd()

    candidates = [
        os.path.join(cur_dir, "zhsubtitle.conf"),
        os.path.join(cur_dir, "config.json"),
    ]

    # If inside .../scripts/mpv-zhsubtitle, check .../script-opts/zhsubtitle.conf
    parent_dir = os.path.dirname(script_dir)
    if os.path.basename(parent_dir).lower() == "scripts":
        mpv_root = os.path.dirname(parent_dir)
        candidates.append(os.path.join(mpv_root, "script-opts", "zhsubtitle.conf"))
        candidates.append(os.path.join(mpv_root, "script-opts", "zhsubtitle.json"))
        candidates.append(os.path.join(mpv_root, "config.json"))

    # Standard Windows APPDATA paths
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidates.append(os.path.join(appdata, "mpv.net", "script-opts", "zhsubtitle.conf"))
            candidates.append(os.path.join(appdata, "mpv.net", "script-opts", "zhsubtitle.json"))
            candidates.append(os.path.join(appdata, "mpv", "script-opts", "zhsubtitle.conf"))
            candidates.append(os.path.join(appdata, "mpv", "script-opts", "zhsubtitle.json"))
            candidates.append(os.path.join(appdata, "mpv", "config.json"))
    else:
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, ".config", "mpv", "script-opts", "zhsubtitle.conf"))
        candidates.append(os.path.join(home, ".config", "mpv", "script-opts", "zhsubtitle.json"))
        candidates.append(os.path.join(home, ".config", "mpv", "zhsubtitle.json"))

    # Local package dir
    candidates.append(os.path.join(script_dir, "zhsubtitle.conf"))
    candidates.append(os.path.join(script_dir, "config.json"))

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def load_config(custom_path: Optional[str] = None) -> Config:
    """Load configuration from .conf or .json file, falling back to defaults."""
    config_path = custom_path or find_config_file()
    if config_path and os.path.isfile(config_path):
        try:
            if config_path.endswith(".conf"):
                data = _parse_conf_file(config_path)
                return Config(data)
            else:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return Config(data)
        except Exception as e:
            sys.stderr.write(f"[zhsubtitle] Warning: Failed to parse config file at {config_path}: {e}\n")
    return Config()
