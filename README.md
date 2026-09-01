# mpv-zhsubtitle

A powerful, modern MPV subtitle search and download tool with support for **SubHD** and **Zimuku** (`srtku.com` / `zmk.pw` / `zimuku.org`), powered by **GuessIt** for smart video filename parsing.

Referencing and integrating core techniques from [qzydustin/service.subtitles.chinesesubtitles](https://github.com/qzydustin/service.subtitles.chinesesubtitles) and [moonlin1213/subtitle-finder](https://github.com/moonlin1213/subtitle-finder).

---

## ✨ Features

- 🔍 **Dual Provider Integration with Concurrent Speed**:
  - **SubHD**: Token-based download flow without login (`prepare-download` -> `/down/{sid}` -> `/api/sub/down`).
  - **Zimuku (`srtku.com` / `zmk.pw` / `zimuku.org`)**: Automated Yunsuo WAF bypass with 5-digit BMP template-matching captcha solver.
  - **Multithreading**: Simultaneous concurrent queries across providers for fast results (2-3 seconds).
- 🧠 **GuessIt Metadata Parsing**:
  - Automatically extracts clean movie titles, Chinese alternative titles, year, season, episode, release groups (`WiKi`, `FLUX`, `REMUX`, etc.), and source format.
  - Generates intelligent search query permutations to maximize Chinese subtitle match rates.
- 📦 **Archive Extraction & Clean Output**:
  - Supports `.zip` (with GBK/CP936 charset recovery), `.gz`, `.tar`, and other archive formats.
  - Automatically extracts **only the clean subtitle file** (`.ass`, `.srt`, `.ssa`, `.vtt`, `.sub`), leaving no leftover archive clutter.
  - Configurable extraction location: save alongside the video or to a dedicated subtitle directory.
  - Optional renaming to match video filename (e.g. `<video_name>.zh-CN.ass`).
- ⚡ **Dual Interaction Modes**:
  - **One-Key Auto Download (`Ctrl+Shift+s`)**: Uses GuessIt to search, select the best-matching subtitle, download, extract, and load it into MPV instantly with on-screen OSD feedback.
  - **Interactive Visual GUI (`Ctrl+Shift+a`)**: Opens a modern dark-themed window with the search query pre-filled, displaying subtitle details (Format, Type, Fansub group, Match score), allowing manual keyword editing and point-and-click downloading.
- 📝 **Detailed Logging**:
  - Automatically writes diagnostics, queries, and download status to `zhsubtitle.log` in your MPV / mpv.net folder for easy troubleshooting.
- 💻 **Standalone CLI**: Can also be executed directly in the terminal outside of MPV.

---

## 📥 Installation

### 1. Install Python Dependencies

Ensure Python 3.8+ is installed on your system, then install the required dependencies:

```bash
pip install -r requirements.txt
```

*(Dependencies: `guessit`, `requests`, `beautifulsoup4`)*

### 2. Install to MPV / mpv.net

Simply place the entire `mpv-zhsubtitle` folder directly into your MPV / mpv.net `scripts` directory:

#### Windows (mpv.net / MPV)
```powershell
# For mpv.net:
Copy-Item -Recurse . -Destination "$env:APPDATA\mpv.net\scripts\mpv-zhsubtitle"

# For standard mpv:
Copy-Item -Recurse . -Destination "$env:APPDATA\mpv\scripts\mpv-zhsubtitle"
```

#### Linux / macOS
```bash
mkdir -p ~/.config/mpv/scripts
cp -r . ~/.config/mpv/scripts/mpv-zhsubtitle
```

*(MPV automatically recognizes `main.lua` in the folder and loads it as a complete package).*

---

## ⌨️ Keybindings

| Shortcut | Action | Script Binding Name |
| :--- | :--- | :--- |
| `Ctrl+Shift+s` | **One-Key Auto Search & Download** | `zhsubtitle_auto` |
| `Ctrl+Shift+a` | **Open Visual GUI Search & Picker** | `zhsubtitle_gui` |

### Customizing Keybindings

You can bind custom shortcuts in your `input.conf` (located in `~/.config/mpv/input.conf` or `%APPDATA%\mpv.net\input.conf` / `%APPDATA%\mpv\input.conf`):

```conf
# Examples in input.conf:
Ctrl+Shift+s script-binding zhsubtitle_auto
Ctrl+Shift+a script-binding zhsubtitle_gui

# Or single-key shortcuts:
b script-binding zhsubtitle_auto
B script-binding zhsubtitle_gui

# Or function keys:
F8 script-binding zhsubtitle_auto
F9 script-binding zhsubtitle_gui
```

---

## ⚙️ Configuration (配置方式)

推荐使用标准 MPV 配置文件 **`script-opts/zhsubtitle.conf`**。

复制 `zhsubtitle.example.conf` 并重命名放置到你的 MPV 配置目录中的 `script-opts` 文件夹：
- **mpv.net 路径**: `%APPDATA%\mpv.net\script-opts\zhsubtitle.conf`
- **mpv 路径**: `%APPDATA%\mpv\script-opts\zhsubtitle.conf`

```conf
# ------------------------------------------------------------------------------
# 快捷键与基础设置
# ------------------------------------------------------------------------------
auto_key=Ctrl+Shift+s
gui_key=Ctrl+Shift+a
python_path=python

# ------------------------------------------------------------------------------
# 字幕下载与解压位置
# ------------------------------------------------------------------------------
# 留空 = 保存到视频所在同级文件夹
# 集中保存示例: extract_dir=C:/Users/Barba/AppData/Roaming/mpv.net/subtitles
# 视频子目录示例: extract_dir={video_dir}/subs
extract_dir=

# 自动重命名为视频同名 (yes/no)
rename_to_video=yes

# 字幕格式优选顺序
prefer_format=ass,srt,ssa,vtt

# ------------------------------------------------------------------------------
# SubHD (主域名 + 备用域名)
# ------------------------------------------------------------------------------
subhd_enabled=yes
subhd_base_url=https://subhd.tv
subhd_fallback_urls=https://subhd.me,https://subhd.one
subhd_timeout=5

# ------------------------------------------------------------------------------
# Zimuku 字幕库 (主域名 + 备用域名)
# ------------------------------------------------------------------------------
zimuku_enabled=yes
zimuku_base_url=https://srtku.com
zimuku_fallback_urls=https://zmk.pw,https://zimuku.org
zimuku_timeout=5

# 全局网络超时 (秒)
timeout=10
```

*(同时也兼容 `config.json` 格式)*。

---

## 🚀 Standalone CLI Usage

也可以在终端直接使用命令行运行 `main.py`：

```bash
# 自动为视频搜索并下载最佳字幕
python main.py auto "Oppenheimer.2023.1080p.BluRay.mkv"

# 打开可视化图形界面
python main.py gui --video "Severance.S01E01.1080p.mkv"

# 在终端列出搜索结果
python main.py search "奥本海默 2023"
```

---

## 📁 Project Structure

```
mpv-zhsubtitle/
├── zhsubtitle.example.conf       # MPV script-opts 配置文件模板
├── config.example.json           # JSON 格式配置模板
├── requirements.txt              # Python 依赖
├── main.py                       # Python CLI 入口
├── main.lua                      # MPV 插件包入口
├── zhsubtitle/
│   ├── __init__.py
│   ├── config.py                 # 支持 .conf 和 .json 的配置解析器
│   ├── guess.py                  # GuessIt 元数据提取
│   ├── extractor.py              # 字幕解压、编码修复与单集提取
│   ├── logger.py                 # 日志记录模块
│   ├── models.py                 # 数据模型 (SubtitleItem, VideoMeta 等)
│   ├── providers/
│   │   ├── base.py               # 抽象基类
│   │   ├── subhd.py              # SubHD 接口 (多域名 + Token 下载)
│   │   └── zimuku.py             # Zimuku 接口 (多域名 + 验证码自动识别)
│   ├── service.py                # 多线程并发搜索与打分引擎
│   ├── gui.py                    # Tkinter 现代化暗黑搜索 GUI 界面
│   └── cli.py                    # 命令行逻辑
├── scripts/
│   └── zhsubtitle.lua            # MPV Lua 脚本 (快捷键与异步进程调度)
├── tests/
│   └── test_all.py               # 单元测试
└── README.md
```

---

## 📜 License

MIT License. Subtitles are for educational and personal research use only.
