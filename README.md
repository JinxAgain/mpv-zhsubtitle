# mpv-zhsubtitle

An intelligent, high-precision Chinese subtitle search and download plugin for **MPV** and **mpv.net**. It seamlessly integrates **SubHD** and **Zimuku (字幕库)** with GuessIt-based video metadata parsing, automated WAF/captcha bypassing, two-stage Douban & IMDb bridge resolution, multi-subtitle archive unpacking with bilingual auto-selection, and an interactive dark-themed GUI with quick search chips.

---

## ✨ Features

- ⚡ **Two-Stage Precision Resolution**: Automatically resolves video work-level metadata on Zimuku, extracts **Douban ID** / **IMDb ID** / localized Chinese titles, and bridges to SubHD to fetch 100% of matching season/movie subtitles without keyword mismatches.
- 🎯 **GuessIt Metadata Parsing**: Automatically parses video filenames into clean titles, seasons, episodes, years, audio/video codecs, and release groups.
- 🖼️ **Modern Dark-Themed GUI**:
  - Instant pre-loading of all matched subtitles on launch.
  - Pre-filled Douban ID in search box for maximum accuracy.
  - **Quick Search Chips**: One-click query switching (`Douban ID`, `CN Title + Season`, `IMDb ID`, `EN Title + Season`).
  - **Interactive Column Sorting**: Click any table header (`Source`, `Lang`, `Format`, `Type`, `Uploader / Group`, `Rating`, `Match`) to sort ascending (`▲`) or descending (`▼`).
  - **Floating Hover Tooltip**: Instant, zero-latency popup displaying full unclipped release names, languages, formats, uploader, fansub group, and download statistics.
  - **On-Demand Details Dialog**: Right-click ➔ `View Details` asynchronously fetches full webpage release notes/remarks and archive file listings without freezing the UI.
  - **Open in Browser**: Direct one-click navigation to the source subtitle page.
- 📦 **Multi-Subtitle Archive Unpacking & Dual Track Loading**:
  - Unpacks **ALL subtitle files** inside `.zip`, `.rar`, `.7z`, and `.tar.gz` archives into your designated subtitle folder with structured language suffixes (`.zh-en.srt`, `.zh-cn.srt`, `.zh-tw.srt`, `.en.srt`).
  - **Bilingual Priority**: Intelligently ranks and activates the best bilingual SRT/ASS subtitle by default (`sub-add select`), while loading all other extracted language tracks into MPV (`sub-add auto`) for instant switching via shortcut (`j` / `Alt+s`).
- 💯 **Normalized 100-Point Match Scoring**:
  - Smart scoring system capped strictly between `0` and `100`.
  - Enforces cross-season mismatch penalties (`-50` points) to prevent previous seasons from ranking above current season episodes.
- 🏷️ **Authentic Tag & Uploader Extraction**:
  - Preserves exact source badge text (`AI校对`, `其他来源`, `官方字幕`, `个人原创翻译`, `转载精修`, etc.).
  - Extracts genuine uploaders and studio fansub groups while automatically filtering generic placeholders.
- 🛡️ **Yunsuo WAF & Anti-Bot Auto-Solver**: Built-in 5-digit BMP template-matching solver that bypasses Zimuku WAF challenges on the fly.
- 🌐 **Multi-Domain & Failover Support**: Built-in fallback mirrors for SubHD (`subhd.tv`, `subhd.me`, `subhd.one`) and Zimuku (`srtku.com`, `zmk.pw`, `zimuku.org`).
- 🔤 **Smart Encoding Detection**: Automatically converts legacy GBK / GB2312 / Big5 subtitles into standard UTF-8.
- ⚙️ **Native MPV Configuration**: Full support for standard MPV `script-opts/zhsubtitle.conf`.

---

## 📥 Installation

### 1. Requirements

- **Python 3.8+** (Must be added to system `PATH` or configured in `zhsubtitle.conf`)
- Install Python dependencies:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Install to MPV / mpv.net

#### For `mpv.net`:
1. Copy the `mpv-zhsubtitle` repository folder into your `mpv.net` scripts directory:
   ```text
   %APPDATA%\mpv.net\scripts\mpv-zhsubtitle\
   ```
2. Ensure the folder contains `main.lua` and `main.py`.

#### For standard `mpv`:
1. Copy the `mpv-zhsubtitle` repository folder into your `mpv` scripts directory:
   ```text
   %APPDATA%\mpv\scripts\mpv-zhsubtitle\
   ```
   *(On Linux/macOS: `~/.config/mpv/scripts/mpv-zhsubtitle/`)*

---

## ⌨️ Keybindings

Default shortcuts configured in the script:

| Shortcut | Description |
| :--- | :--- |
| `Ctrl+Shift+s` | **Main Shortcut**: Opens interactive Subtitle Picker GUI (or auto-downloads if configured) |
| `Ctrl+Shift+a` | **Dedicated GUI Shortcut**: Always opens the graphical subtitle picker window |
| `Ctrl+Shift+d` | **Dedicated Auto Shortcut**: Directly downloads and loads the highest-matching subtitle |

### Customizing Keybindings in `input.conf`

You can customize bindings in your `input.conf`:

```conf
# Trigger default action (GUI or Auto based on zhsubtitle.conf)
Ctrl+Shift+s script-binding zhsubtitle_shortcut

# Dedicated bindings
Ctrl+Shift+a script-binding zhsubtitle_gui
Ctrl+Shift+d script-binding zhsubtitle_auto

# Or custom single-key bindings:
b script-binding zhsubtitle_auto
B script-binding zhsubtitle_gui
```

---

## ⚙️ Configuration (`zhsubtitle.conf`)

Configuration is managed via the standard MPV option file **`script-opts/zhsubtitle.conf`**.

Copy `zhsubtitle.example.conf` to your MPV `script-opts` folder:
- **mpv.net path**: `%APPDATA%\mpv.net\script-opts\zhsubtitle.conf`
- **mpv path**: `%APPDATA%\mpv\script-opts\zhsubtitle.conf`

### Configuration Options Reference

```conf
# ------------------------------------------------------------------------------
# 1. Keybindings & Interaction Mode
# ------------------------------------------------------------------------------
# Main shortcut key (default: Ctrl+Shift+s)
shortcut_key=Ctrl+Shift+s

# Action for main shortcut (gui or auto)
#   gui  = Opens visual window to choose and download subtitle (Recommended)
#   auto = Directly searches and loads the best-matching subtitle automatically
default_mode=gui

# Direct dedicated shortcuts (optional)
# gui_key=Ctrl+Shift+a
# auto_key=Ctrl+Shift+d

# Duration (in seconds) for OSD notifications
notify_duration=3

# Python executable path (default: python)
python_path=python

# ------------------------------------------------------------------------------
# 2. Subtitle Download & Extraction Settings
# ------------------------------------------------------------------------------
# Directory where downloaded subtitles are extracted.
# Leave empty to extract into the same directory as the playing video file.
# Examples:
#   extract_dir=C:/Users/Username/Subtitles
#   extract_dir={video_dir}/subs
extract_dir=

# Automatically rename extracted subtitle to match video name (yes/no)
rename_to_video=yes

# Preferred subtitle formats in priority order (comma-separated, srt first)
prefer_format=srt,ass,ssa,vtt

# Preferred subtitle languages (comma-separated)
prefer_language=chs,cht,eng

# ------------------------------------------------------------------------------
# 3. SubHD Provider Settings
# ------------------------------------------------------------------------------
subhd_enabled=yes
subhd_base_url=https://subhd.tv
subhd_fallback_urls=https://subhd.me,https://subhd.one
subhd_timeout=5

# ------------------------------------------------------------------------------
# 4. Zimuku Provider Settings
# ------------------------------------------------------------------------------
zimuku_enabled=yes
zimuku_base_url=https://srtku.com
zimuku_fallback_urls=https://zmk.pw,https://zimuku.org
zimuku_timeout=5

# ------------------------------------------------------------------------------
# 5. Global Timeout (seconds)
# ------------------------------------------------------------------------------
timeout=10
```

---

## 🖥️ Standalone CLI Usage

The script can also be executed directly from terminal / command line:

```bash
# Auto-download best matching subtitle for a video:
python main.py auto "C:/Videos/Silo.S03E08.mkv"

# Open visual GUI search picker for a video:
python main.py gui "C:/Videos/Oppenheimer.2023.mkv"

# Search subtitles in terminal:
python main.py search "Oppenheimer"
```

---

## 🧪 Testing

Run the automated test suite with:

```bash
python -m unittest discover tests
```

---

## 🙏 Acknowledgements

We would like to express our deepest gratitude to:
- **[service.subtitles.chinesesubtitles](https://github.com/qzydustin/service.subtitles.chinesesubtitles)** (by `qzydustin`) and **[subtitle-finder](https://github.com/moonlin1213/subtitle-finder)** (by `moonlin1213`) for providing foundational research, architecture patterns, and provider API insights.
- **All subtitle creators, translators, fansub groups, and community archivers** whose continuous dedication and passion make high-quality subtitles accessible to movie and TV enthusiasts worldwide.

---

## 🤖 AI Disclosure

This project was developed, designed, and pair-programmed with the assistance of **Google Gemini 3.7 Flash** (via Google Antigravity).

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
