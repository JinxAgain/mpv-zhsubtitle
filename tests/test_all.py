"""Unit tests for mpv-zhsubtitle modules."""

import io
import os
import shutil
import tempfile
import unittest
import zipfile

from zhsubtitle.config import Config, load_config
from zhsubtitle.extractor import (
    extract_and_save_subtitle,
    fix_archive_filename,
    pick_best_subtitle_file,
)
from zhsubtitle.guess import parse_video
from zhsubtitle.models import VideoMeta
from zhsubtitle.service import SubtitleService


class TestGuessItParser(unittest.TestCase):
    """Test video filename parsing and search query generation."""

    def test_movie_parsing(self):
        meta = parse_video("Oppenheimer.2023.IMAX.1080p.BluRay.x264.DTS-WiKi.mkv")
        self.assertEqual(meta.title, "Oppenheimer")
        self.assertEqual(meta.year, 2023)
        self.assertFalse(meta.is_tv)
        queries = meta.build_search_queries()
        self.assertIn("Oppenheimer 2023", queries)

    def test_tv_show_parsing(self):
        meta = parse_video("Severance.S01E01.Good.News.About.Hell.1080p.ATVP.WEB-DL.DDP5.1.Atmos.H.264-FLUX.mkv")
        self.assertEqual(meta.title, "Severance")
        self.assertEqual(meta.season, 1)
        self.assertEqual(meta.episode, 1)
        self.assertTrue(meta.is_tv)
        queries = meta.build_search_queries()
        self.assertTrue(any("Severance 第一季" in q or "Severance" in q for q in queries))
        chips = meta.get_search_chips()
        self.assertTrue(any("Severance S01" in val for _, val in chips))

    def test_bilingual_title(self):
        meta = parse_video("老友记.Friends.S01E01.1080p.BluRay.x264-FLUX.mp4")
        self.assertTrue(meta.alternative_title == "老友记" or meta.title == "Friends" or "老友记" in meta.title)
        self.assertEqual(meta.season, 1)
        self.assertEqual(meta.episode, 1)

    def test_anime_brackets(self):
        meta = parse_video("[VCB-Studio] Sousou no Frieren [01][Ma10p_1080p][x265_flac].mkv")
        self.assertTrue("Sousou no Frieren" in meta.title or "Frieren" in meta.title)
        self.assertEqual(meta.episode, 1)


class TestSubtitleExtractor(unittest.TestCase):
    """Test archive extraction, GBK decoding, and subtitle saving."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="zhsub_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_pick_best_subtitle(self):
        files = [
            "Movie.2023.eng.srt",
            "Movie.2023.chs.ass",
            "Movie.2023.cht.srt"
        ]
        best = pick_best_subtitle_file(files, prefer_format=["ass", "srt"], prefer_language=["chs", "cht", "eng"])
        self.assertEqual(best, "Movie.2023.chs.ass")

    def test_pick_best_subtitle_episode(self):
        files = [
            "Show.S01E01.chs.ass",
            "Show.S01E02.chs.ass",
            "Show.S01E03.chs.ass"
        ]
        best = pick_best_subtitle_file(files, episode=2)
        self.assertEqual(best, "Show.S01E02.chs.ass")

    def test_extract_zip_in_memory(self):
        # Create a sample ZIP archive in memory
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("Sample.Movie.chs.ass", "[Script Info]\nTitle: Sample Subtitle\n")
            zf.writestr("Sample.Movie.eng.srt", "1\n00:00:01,000 --> 00:00:03,000\nHello\n")
            zf.writestr("readme.txt", "Download from SubHD")

        zip_bytes = zip_buf.getvalue()
        video_path = os.path.join(self.test_dir, "Sample.Movie.2023.1080p.mkv")

        res = extract_and_save_subtitle(
            content_bytes=zip_bytes,
            original_filename="sample_sub.zip",
            target_dir=self.test_dir,
            video_path=video_path,
            rename_to_video=True
        )

        self.assertTrue(res.success)
        self.assertTrue(os.path.isfile(res.saved_path))
        self.assertTrue(res.saved_path.endswith(".zh-CN.ass") or res.saved_path.endswith(".ass"))
        # Verify content
        with open(res.saved_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Sample Subtitle", content)

    def test_custom_extract_dir(self):
        custom_dir = os.path.join(self.test_dir, "custom_subtitles_vault")
        cfg = Config({"extract_dir": custom_dir})
        resolved = cfg.resolve_extract_dir("C:/Videos/Movie.mkv")
        self.assertEqual(resolved, os.path.abspath(custom_dir))
        self.assertTrue(os.path.isdir(resolved))


class TestConfigManager(unittest.TestCase):
    """Test config resolution."""

    def test_default_config(self):
        cfg = Config()
        self.assertEqual(cfg.prefer_format[0], "srt")
        self.assertTrue(cfg.rename_to_video)
        self.assertTrue(cfg.is_provider_enabled("subhd"))
        self.assertTrue(cfg.is_provider_enabled("zimuku"))


if __name__ == "__main__":
    unittest.main()
