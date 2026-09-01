--[[
MPV Chinese Subtitle Downloader (SubHD & Zimuku)
Features:
- Ctrl+Shift+s: Main shortcut (Opens GUI by default, or Auto-download if configured in default_mode)
- Dedicated bindings: zhsubtitle_gui, zhsubtitle_auto
--]]

local mp = require 'mp'
local utils = require 'mp.utils'
local opt = require 'mp.options'

-- Default script options (customizable in script-opts/zhsubtitle.conf)
local options = {
    python_path = "python",
    shortcut_key = "Ctrl+Shift+s",
    default_mode = "gui", -- 'gui' (Visual Picker) or 'auto' (Direct Download)
    gui_key = "",
    auto_key = "",
    notify_duration = 3
}

opt.read_options(options, "zhsubtitle")

-- Find the directory where this script and main.py reside
local function get_script_dir()
    local src = debug.getinfo(1).source
    if src:sub(1, 1) == "@" then
        src = src:sub(2)
        local dir = utils.split_path(src)
        return dir
    end
    return mp.get_script_directory() or ""
end

local function find_main_py()
    local script_dir = get_script_dir()
    local candidates = {
        utils.join_path(script_dir, "main.py"),
        utils.join_path(script_dir, "../main.py"),
        utils.join_path(mp.find_config_file("scripts") or "", "mpv-zhsubtitle/main.py"),
        utils.join_path(mp.find_config_file("scripts") or "", "zhsubtitle/main.py")
    }

    for _, path in ipairs(candidates) do
        local norm = utils.join_path("", path)
        local info = utils.file_info(norm)
        if info and info.is_file then
            return norm
        end
    end
    return utils.join_path(script_dir, "../main.py")
end

-- Resolve python executable
local function get_python_binary()
    if options.python_path and options.python_path ~= "python" and options.python_path ~= "python3" then
        return options.python_path
    end

    local test_py = mp.command_native({
        name = "subprocess",
        playback_only = false,
        capture_stdout = true,
        args = { "python", "--version" }
    })
    if test_py and test_py.status == 0 then
        return "python"
    end

    return "python3"
end

local is_auto_running = false
local is_gui_running = false
local watchdog_timer = nil

local function run_sub_downloader(mode)
    if mode == "auto" and is_auto_running then
        mp.osd_message("[zhsubtitle] Auto search is already in progress...", 2)
        return
    end

    local video_path = mp.get_property("path")
    if not video_path or video_path == "" then
        mp.osd_message("[zhsubtitle] No media currently playing", 2)
        return
    end

    if video_path:find("^http://") or video_path:find("^https://") then
        local media_title = mp.get_property("media-title") or "stream"
        video_path = media_title
    end

    local python_bin = get_python_binary()
    local main_py = find_main_py()

    local args = { python_bin, main_py, mode, video_path }

    if mode == "auto" then
        is_auto_running = true
        mp.osd_message("[zhsubtitle] Searching best Chinese subtitles...", options.notify_duration)
    else
        is_gui_running = true
        mp.osd_message("[zhsubtitle] Opening subtitle picker GUI...", 2)
    end

    -- Safety watchdog to prevent lockup
    if watchdog_timer then
        watchdog_timer:kill()
    end
    watchdog_timer = mp.add_timeout(30, function()
        is_auto_running = false
        is_gui_running = false
    end)

    mp.command_native_async({
        name = "subprocess",
        playback_only = false,
        capture_stdout = true,
        capture_stderr = true,
        args = args
    }, function(success, res, err)
        if mode == "auto" then
            is_auto_running = false
        else
            is_gui_running = false
        end

        if not success or (res and res.status ~= 0) then
            local err_output = (res and res.stderr) or err or "unknown error"
            mp.msg.warn("zhsubtitle error: " .. tostring(err_output))
            if mode == "auto" then
                mp.osd_message("[zhsubtitle] No subtitles found or download failed", 3)
            end
            return
        end

        local stdout = res.stdout or ""
        local loaded_path = stdout:match("%[SUBTITLE_LOADED%]([^\r\n]+)")

        -- Add any additional extracted subtitles as selectable tracks
        for extracted_path in stdout:gmatch("%[SUBTITLE_EXTRACTED%]([^\r\n]+)") do
            if extracted_path ~= loaded_path then
                mp.commandv("sub-add", extracted_path, "auto")
                mp.msg.info("Added secondary subtitle track: " .. extracted_path)
            end
        end

        if loaded_path and loaded_path ~= "" then
            mp.commandv("sub-add", loaded_path, "select")
            local _, sub_name = utils.split_path(loaded_path)
            mp.osd_message("[zhsubtitle] Subtitle Loaded: " .. (sub_name or loaded_path), 4)
            mp.msg.info("Loaded primary subtitle: " .. loaded_path)
        elseif mode == "auto" then
            mp.osd_message("[zhsubtitle] No subtitles found", 3)
        end
    end)
end

local function trigger_shortcut()
    local mode = (options.default_mode and options.default_mode:lower() == "auto") and "auto" or "gui"
    run_sub_downloader(mode)
end

local function trigger_auto()
    run_sub_downloader("auto")
end

local function trigger_gui()
    run_sub_downloader("gui")
end

-- Register main shortcut (default: Ctrl+Shift+s -> opens GUI or Auto)
if options.shortcut_key and options.shortcut_key ~= "" then
    mp.add_key_binding(options.shortcut_key, "zhsubtitle_shortcut", trigger_shortcut)
end

if options.gui_key and options.gui_key ~= "" then
    mp.add_key_binding(options.gui_key, "zhsubtitle_gui", trigger_gui)
end

if options.auto_key and options.auto_key ~= "" then
    mp.add_key_binding(options.auto_key, "zhsubtitle_auto", trigger_auto)
end

mp.register_script_message("zhsubtitle-shortcut", trigger_shortcut)
mp.register_script_message("zhsubtitle-auto", trigger_auto)
mp.register_script_message("zhsubtitle-gui", trigger_gui)
