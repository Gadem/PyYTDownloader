import argparse
import tempfile
import unittest
from pathlib import Path

import download_youtube


class DownloadYoutubeTests(unittest.TestCase):
    def test_positive_int_accepts_positive_values(self):
        self.assertEqual(download_youtube.positive_int("7"), 7)

    def test_positive_int_rejects_zero_or_negative_values(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            download_youtube.positive_int("0")
        with self.assertRaises(argparse.ArgumentTypeError):
            download_youtube.positive_int("-2")

    def test_extract_video_id_from_watch_url(self):
        url = "https://www.youtube.com/watch?v=abc123XYZ89"
        self.assertEqual(download_youtube.extract_video_id_from_url(url), "abc123XYZ89")

    def test_extract_video_id_from_short_url(self):
        url = "https://youtu.be/abc123XYZ89?si=token"
        self.assertEqual(download_youtube.extract_video_id_from_url(url), "abc123XYZ89")

    def test_extract_video_id_from_shorts_url(self):
        url = "https://www.youtube.com/shorts/abc123XYZ89"
        self.assertEqual(download_youtube.extract_video_id_from_url(url), "abc123XYZ89")

    def test_has_existing_output_detects_video_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            existing = output_dir / "Titulo [abc123XYZ89].mp4"
            existing.write_text("video", encoding="utf-8")

            self.assertTrue(
                download_youtube.has_existing_output(
                    "https://www.youtube.com/watch?v=abc123XYZ89",
                    output_dir,
                )
            )

    def test_has_existing_output_detects_thumbnail_only_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            existing = output_dir / "Titulo [abc123XYZ89].webp"
            existing.write_text("thumb", encoding="utf-8")

            self.assertTrue(
                download_youtube.has_existing_output(
                    "https://www.youtube.com/watch?v=abc123XYZ89",
                    output_dir,
                    thumbnail_only=True,
                )
            )

    def test_has_existing_output_detects_video_file_in_per_video_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            video_dir = output_dir / "Titulo [abc123XYZ89]"
            video_dir.mkdir()
            existing = video_dir / "Titulo [abc123XYZ89].mp4"
            existing.write_text("video", encoding="utf-8")

            self.assertTrue(
                download_youtube.has_existing_output(
                    "https://www.youtube.com/watch?v=abc123XYZ89",
                    output_dir,
                    per_video_dir=True,
                )
            )

    def test_has_existing_output_ignores_thumbnail_for_video_download(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            existing = output_dir / "Titulo [abc123XYZ89].webp"
            existing.write_text("thumb", encoding="utf-8")

            self.assertFalse(
                download_youtube.has_existing_output(
                    "https://www.youtube.com/watch?v=abc123XYZ89",
                    output_dir,
                )
            )

    def test_build_format_selector_uses_audio_only_mode(self):
        selector = download_youtube.build_format_selector(
            ffmpeg_available=True,
            audio_only=True,
        )
        self.assertEqual(selector, "bestaudio/best")

    def test_build_format_selector_uses_standard_mode(self):
        selector = download_youtube.build_format_selector(ffmpeg_available=False)
        self.assertEqual(selector, "best[height<=720][ext=mp4]/best[height<=720]/best")

    def test_build_output_template_uses_per_video_dir_structure(self):
        template = download_youtube.build_output_template(Path("downloads"), True)
        self.assertEqual(
            template,
            "downloads/%(title)s [%(id)s]/%(title)s [%(id)s].%(ext)s",
        )

    def test_classify_error_maps_format_issue(self):
        error_type, message = download_youtube.classify_error(
            Exception("Requested format is not available")
        )
        self.assertEqual(error_type, "format_unavailable")
        self.assertIn("formato", message.lower())

    def test_result_from_skip_marks_skipped(self):
        result = download_youtube.result_from_skip("https://example.com/video")
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.attempts, 0)


if __name__ == "__main__":
    unittest.main()
