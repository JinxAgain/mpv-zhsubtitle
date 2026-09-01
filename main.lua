--[[
MPV Chinese Subtitle Downloader - Package Entry
Allows mpv to load the repository directly when placed in the scripts/ folder.
--]]

local utils = require 'mp.utils'
local script_dir = utils.split_path(debug.getinfo(1).source:sub(2))
local lua_script = utils.join_path(script_dir, "scripts/zhsubtitle.lua")

local f = io.open(lua_script, "r")
if f then
    f:close()
    dofile(lua_script)
else
    -- Fallback if scripts folder is flattened
    require 'mp'.msg.error("[zhsubtitle] Could not find scripts/zhsubtitle.lua")
end
