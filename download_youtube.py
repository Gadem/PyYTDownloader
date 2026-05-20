#!/usr/bin/env python3
"""Descarga videos de YouTube en 720p, miniaturas y metadatos."""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
import time
from pathlib import Path

import yt_dlp
from yt_dlp.utils import download_range_func

BOT_ERROR_SNIPPETS = (
    "sign in to confirm you’re not a bot",
    "sign in to confirm you're not a bot",
)
BOT_RETRY_DELAY_SECONDS = 60
BOT_MAX_RETRIES = 3
VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("El valor debe ser un entero mayor que 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descarga videos de YouTube en calidad 720p usando su titulo."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="URL del video de YouTube. Si no se indica, se usa videos.csv",
    )
    parser.add_argument(
        "-c",
        "--csv-file",
        default="videos.csv",
        help="Archivo CSV con una columna llamada 'url' o URLs en la primera columna",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="downloads",
        help="Carpeta de salida donde se guardaran los videos",
    )
    parser.add_argument(
        "--cookies",
        help="Ruta a un archivo cookies.txt exportado para autenticar descargas",
    )
    parser.add_argument(
        "--cookies-from-browser",
        dest="cookies_from_browser",
        default="chrome",
        help=(
            "Importa cookies directamente desde el navegador "
            "(por ejemplo: chrome, safari, firefox, edge). "
            "Por defecto: chrome"
        ),
    )
    parser.add_argument(
        "--js-runtime",
        dest="js_runtime",
        default="node",
        help=(
            "Runtime JavaScript para yt-dlp al extraer informacion de YouTube "
            "(por ejemplo: node, deno). Por defecto: node"
        ),
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=positive_int,
        help="Descarga solo los primeros N segundos del video. Requiere ffmpeg.",
    )
    return parser


def build_format_selector(ffmpeg_available: bool) -> str:
    if ffmpeg_available:
        return "bestvideo[height<=720]+bestaudio/best[height<=720]/best"

    # Sin ffmpeg, evitamos forzar video+audio separados para maximizar compatibilidad.
    return "best[height<=720][ext=mp4]/best[height<=720]/best"


def sanitize_name(value: str, fallback: str = "video") -> str:
    cleaned = "".join(
        character for character in value if character not in '<>:"/\\|?*'
    ).strip()
    return cleaned or fallback


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "Desconocida"

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def write_metadata_file(video_path: Path, info: dict) -> Path:
    metadata_path = video_path.with_suffix(".txt")
    lines = [
        f"Titulo: {info.get('title', 'Sin titulo')}",
        f"Canal: {info.get('channel') or info.get('uploader') or 'Desconocido'}",
        f"URL: {info.get('webpage_url') or info.get('original_url') or 'N/A'}",
        f"ID: {info.get('id', 'N/A')}",
        f"Duracion: {format_duration(info.get('duration'))}",
        f"Fecha de subida: {info.get('upload_date', 'N/A')}",
        f"Visualizaciones: {info.get('view_count', 'N/A')}",
        f"Descripcion: {info.get('description') or 'Sin descripcion'}",
    ]
    metadata_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return metadata_path


def resolve_thumbnail_path(video_path: Path, info: dict) -> Path | None:
    thumbnails = info.get("thumbnails") or []
    possible_extensions = []

    for thumbnail in reversed(thumbnails):
        ext = thumbnail.get("ext")
        if ext and ext not in possible_extensions:
            possible_extensions.append(ext)

    possible_extensions.extend(["webp", "jpg", "jpeg", "png"])

    seen_extensions: set[str] = set()
    for extension in possible_extensions:
        if extension in seen_extensions:
            continue
        seen_extensions.add(extension)

        candidate = video_path.with_suffix(f".{extension}")
        if candidate.exists():
            return candidate

    return None


def resolve_downloaded_path(output_dir: Path, info: dict, ydl: yt_dlp.YoutubeDL) -> Path:
    requested_downloads = info.get("requested_downloads") or []
    if requested_downloads:
        for download in requested_downloads:
            filepath = download.get("filepath")
            if filepath:
                candidate = Path(filepath)
                if candidate.exists():
                    return candidate

    prepared_path = Path(ydl.prepare_filename(info))
    if prepared_path.exists():
        return prepared_path

    mp4_candidate = prepared_path.with_suffix(".mp4")
    if mp4_candidate.exists():
        return mp4_candidate

    title = sanitize_name(info.get("title", "video"))
    video_id = sanitize_name(info.get("id", "video"))
    matches = sorted(output_dir.glob(f"{title} [{video_id}].*"))
    for match in matches:
        if match.suffix.lower() in VIDEO_EXTENSIONS:
            return match

    return mp4_candidate


def build_ydl_options(output_dir: Path, args: argparse.Namespace) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_available = shutil.which("ffmpeg") is not None

    ydl_opts = {
        "format": build_format_selector(ffmpeg_available),
        "outtmpl": str(output_dir / "%(title)s [%(id)s].%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "windowsfilenames": True,
        "restrictfilenames": False,
        "writethumbnail": True,
    }

    if args.cookies:
        ydl_opts["cookiefile"] = str(Path(args.cookies).expanduser())

    if args.cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (args.cookies_from_browser,)

    if args.js_runtime:
        ydl_opts["js_runtimes"] = {
            args.js_runtime: {
                "path": shutil.which(args.js_runtime) or args.js_runtime,
            }
        }

    if args.duration:
        if not ffmpeg_available:
            print(
                "Advertencia: Se especifico --duration pero 'ffmpeg' no esta instalado. "
                "Los cortes podrian no ser exactos o fallar.",
                file=sys.stderr,
            )
        ydl_opts["download_ranges"] = download_range_func(None, [(0, args.duration)])
        ydl_opts["force_keyframes_at_cuts"] = True

    if ffmpeg_available:
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }
        ]

    return ydl_opts


def download_video(
    url: str, output_dir: Path, ydl: yt_dlp.YoutubeDL
) -> tuple[Path, Path, Path | None]:
    info = ydl.extract_info(url, download=True)
    final_path = resolve_downloaded_path(output_dir, info, ydl)
    metadata_path = write_metadata_file(final_path, info)
    thumbnail_path = resolve_thumbnail_path(final_path, info)
    return final_path, metadata_path, thumbnail_path


def read_urls_from_csv(csv_path: Path) -> list[str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"No existe el archivo CSV: {csv_path}")

    urls: list[str] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue

            first_cell = row[0].strip()
            if not first_cell:
                continue

            if first_cell.lower() == "url":
                continue

            urls.append(first_cell)

    if not urls:
        raise ValueError(f"El archivo CSV no contiene URLs validas: {csv_path}")

    return urls


def collect_urls(args: argparse.Namespace) -> list[str]:
    if args.url:
        return [args.url]
    return read_urls_from_csv(Path(args.csv_file))


def write_failed_urls(output_dir: Path, failed_urls: list[str]) -> Path:
    failed_path = output_dir / "failed_urls.txt"
    failed_path.write_text("\n".join(failed_urls) + "\n", encoding="utf-8")
    return failed_path


def is_bot_verification_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(snippet in message for snippet in BOT_ERROR_SNIPPETS)


def wait_before_retry(url: str, attempt: int) -> None:
    print(
        f"YouTube pidio verificacion antibot para {url}. "
        f"Esperando {BOT_RETRY_DELAY_SECONDS} segundos antes del reintento {attempt}.",
        file=sys.stderr,
    )
    time.sleep(BOT_RETRY_DELAY_SECONDS)


def download_video_with_retries(
    url: str, output_dir: Path, ydl: yt_dlp.YoutubeDL
) -> tuple[Path, Path, Path | None]:
    attempts = BOT_MAX_RETRIES + 1

    for attempt in range(1, attempts + 1):
        try:
            return download_video(url, output_dir, ydl)
        except yt_dlp.utils.DownloadError as exc:
            if not is_bot_verification_error(exc) or attempt == attempts:
                raise
            wait_before_retry(url, attempt)

    raise RuntimeError(f"No se pudo descargar el video tras {attempts} intentos: {url}")

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        urls = collect_urls(args)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    ydl_opts = build_ydl_options(output_dir, args)
    downloaded_count = 0
    failed_urls: list[str] = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in urls:
            try:
                saved_path, metadata_path, thumbnail_path = download_video_with_retries(
                    url, output_dir, ydl
                )
                downloaded_count += 1
                print(f"Video descargado en: {saved_path.resolve()}")
                print(f"Metadatos guardados en: {metadata_path.resolve()}")
                if thumbnail_path:
                    print(f"Miniatura guardada en: {thumbnail_path.resolve()}")
                else:
                    print("No se encontro la miniatura descargada.", file=sys.stderr)
            except yt_dlp.utils.DownloadError as exc:
                failed_urls.append(url)
                print(f"No se pudo descargar {url}: {exc}", file=sys.stderr)
            except Exception as exc:  # pragma: no cover
                failed_urls.append(url)
                print(f"Ocurrio un error inesperado con {url}: {exc}", file=sys.stderr)

    print(
        f"Resumen: {downloaded_count} descargado(s), "
        f"{len(failed_urls)} fallido(s), {len(urls)} total."
    )

    if failed_urls:
        failed_path = write_failed_urls(output_dir, failed_urls)
        print(f"URLs fallidas guardadas en: {failed_path.resolve()}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
