#!/usr/bin/env python3
"""Descarga videos de YouTube en 720p, miniaturas y metadatos."""

from __future__ import annotations

import argparse
import csv
import logging
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
RESULTS_FILENAME = "results.csv"
LOGS_DIRNAME = "logs"
LOG_FILENAME = "last_run.log"


@dataclass
class DownloadResult:
    url: str
    status: str
    output_dir: str
    output_file: str
    metadata_file: str
    thumbnail_file: str
    error_type: str
    error_message: str
    attempts: int


LOGGER = logging.getLogger("youtube_downloader")


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
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Omite URLs cuyo archivo de salida ya exista en la carpeta destino.",
    )
    parser.add_argument(
        "--retry-delay",
        type=positive_int,
        default=BOT_RETRY_DELAY_SECONDS,
        help=(
            "Segundos de espera antes de reintentar errores de verificacion antibot. "
            f"Por defecto: {BOT_RETRY_DELAY_SECONDS}"
        ),
    )
    parser.add_argument(
        "--max-retries",
        type=positive_int,
        default=BOT_MAX_RETRIES,
        help=(
            "Numero maximo de reintentos para errores de verificacion antibot. "
            f"Por defecto: {BOT_MAX_RETRIES}"
        ),
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Descarga solo el audio del video.",
    )
    parser.add_argument(
        "--thumbnail-only",
        action="store_true",
        help="Descarga solo la miniatura y los metadatos, sin bajar el video.",
    )
    parser.add_argument(
        "--per-video-dir",
        action="store_true",
        help="Guarda cada descarga en una carpeta separada con video, miniatura y metadatos.",
    )
    return parser


def build_format_selector(
    ffmpeg_available: bool, audio_only: bool = False, thumbnail_only: bool = False
) -> str:
    if thumbnail_only:
        return "bestaudio/best"
    if audio_only:
        return "bestaudio/best"
    if ffmpeg_available:
        return "bestvideo[height<=720]+bestaudio/best[height<=720]/best"

    # Sin ffmpeg, evitamos forzar video+audio separados para maximizar compatibilidad.
    return "best[height<=720][ext=mp4]/best[height<=720]/best"


def sanitize_name(value: str, fallback: str = "video") -> str:
    cleaned = "".join(
        character for character in value if character not in '<>:"/\\|?*'
    ).strip()
    return cleaned or fallback


def build_video_stem(info: dict) -> str:
    title = sanitize_name(info.get("title", "video"))
    video_id = sanitize_name(info.get("id", "video"))
    return f"{title} [{video_id}]"


def build_target_directory(output_dir: Path, info: dict, per_video_dir: bool) -> Path:
    if not per_video_dir:
        return output_dir
    return output_dir / build_video_stem(info)


def build_output_template(base_output_dir: Path, per_video_dir: bool) -> str:
    if per_video_dir:
        return str(base_output_dir / "%(title)s [%(id)s]" / "%(title)s [%(id)s].%(ext)s")
    return str(base_output_dir / "%(title)s [%(id)s].%(ext)s")


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


def resolve_downloaded_path(target_dir: Path, info: dict, ydl: yt_dlp.YoutubeDL) -> Path:
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

    stem = build_video_stem(info)
    matches = sorted(target_dir.glob(f"{stem}.*"))
    for match in matches:
        if match.suffix.lower() in VIDEO_EXTENSIONS:
            return match

    return mp4_candidate


def extract_video_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc.endswith("youtu.be"):
        video_id = parsed.path.strip("/")
        return video_id or None

    if "youtube.com" in parsed.netloc:
        query_video_id = parse_qs(parsed.query).get("v", [])
        if query_video_id:
            return query_video_id[0]
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live"}:
            return path_parts[1]

    return None


def has_existing_output(
    url: str,
    output_dir: Path,
    thumbnail_only: bool = False,
    per_video_dir: bool = False,
) -> bool:
    video_id = extract_video_id_from_url(url)
    if not video_id:
        return False

    marker = f" [{video_id}]"
    if per_video_dir:
        for candidate_dir in output_dir.iterdir():
            if not candidate_dir.is_dir() or marker not in candidate_dir.name:
                continue
            for candidate in candidate_dir.iterdir():
                if not candidate.is_file():
                    continue
                suffix = candidate.suffix.lower()
                if thumbnail_only and suffix in {".webp", ".jpg", ".jpeg", ".png"}:
                    return True
                if not thumbnail_only and suffix in VIDEO_EXTENSIONS:
                    return True
    else:
        for candidate in output_dir.iterdir():
            if not candidate.is_file() or marker not in candidate.stem:
                continue
            suffix = candidate.suffix.lower()
            if thumbnail_only and suffix in {".webp", ".jpg", ".jpeg", ".png"}:
                return True
            if not thumbnail_only and suffix in VIDEO_EXTENSIONS:
                return True
    return False


def build_ydl_options(output_dir: Path, args: argparse.Namespace) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_available = shutil.which("ffmpeg") is not None

    ydl_opts = {
        "format": build_format_selector(
            ffmpeg_available,
            audio_only=args.audio_only,
            thumbnail_only=args.thumbnail_only,
        ),
        "outtmpl": build_output_template(output_dir, args.per_video_dir),
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

    if args.thumbnail_only:
        ydl_opts["skip_download"] = True

    if args.audio_only and ffmpeg_available:
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
        ydl_opts["postprocessor_args"] = []
    if ffmpeg_available:
        if not args.audio_only and not args.thumbnail_only:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ]

    return ydl_opts


def download_video(
    url: str,
    output_dir: Path,
    ydl: yt_dlp.YoutubeDL,
    thumbnail_only: bool = False,
    per_video_dir: bool = False,
) -> tuple[Path, Path, Path | None]:
    info = ydl.extract_info(url, download=True)
    target_dir = build_target_directory(output_dir, info, per_video_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if thumbnail_only:
        final_path = Path(ydl.prepare_filename(info))
    else:
        final_path = resolve_downloaded_path(target_dir, info, ydl)

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


def setup_logging(output_dir: Path) -> Path:
    logs_dir = output_dir / LOGS_DIRNAME
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / LOG_FILENAME
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    LOGGER.addHandler(handler)
    LOGGER.propagate = False
    return log_path


def result_from_skip(url: str) -> DownloadResult:
    return DownloadResult(
        url=url,
        status="skipped",
        output_dir="",
        output_file="",
        metadata_file="",
        thumbnail_file="",
        error_type="",
        error_message="Archivo existente detectado; se omitio la descarga.",
        attempts=0,
    )


def classify_error(exc: Exception) -> tuple[str, str]:
    message = str(exc)
    lowered = message.lower()

    if is_bot_verification_error(exc):
        return "bot_verification", (
            "YouTube bloqueo la descarga por verificacion antibot. "
            "Intenta de nuevo mas tarde o revisa tus cookies del navegador."
        )
    if "requested format is not available" in lowered:
        return "format_unavailable", (
            "YouTube no expuso un formato de video descargable para esta URL."
        )
    if "only images are available for download" in lowered:
        return "images_only", (
            "YouTube solo expuso imagenes para esta URL y no formatos de video."
        )
    if "private video" in lowered or "this video is private" in lowered:
        return "private_video", "El video es privado y no se puede descargar."
    if "video unavailable" in lowered:
        return "video_unavailable", "El video no esta disponible."
    if "unsupported url" in lowered:
        return "unsupported_url", "La URL no es compatible con yt-dlp."

    return "download_error", message


def write_results_csv(output_dir: Path, results: list[DownloadResult]) -> Path:
    results_path = output_dir / RESULTS_FILENAME
    fieldnames = list(DownloadResult.__dataclass_fields__.keys())
    with results_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))
    return results_path


def is_bot_verification_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(snippet in message for snippet in BOT_ERROR_SNIPPETS)


def wait_before_retry(url: str, attempt: int, retry_delay: int) -> None:
    print(
        f"YouTube pidio verificacion antibot para {url}. "
        f"Esperando {retry_delay} segundos antes del reintento {attempt}.",
        file=sys.stderr,
    )
    time.sleep(retry_delay)


def download_video_with_retries(
    url: str,
    output_dir: Path,
    ydl: yt_dlp.YoutubeDL,
    *,
    thumbnail_only: bool = False,
    per_video_dir: bool = False,
    max_retries: int = BOT_MAX_RETRIES,
    retry_delay: int = BOT_RETRY_DELAY_SECONDS,
) -> tuple[Path, Path, Path | None, int]:
    attempts = max_retries + 1

    for attempt in range(1, attempts + 1):
        try:
            saved_path, metadata_path, thumbnail_path = download_video(
                url,
                output_dir,
                ydl,
                thumbnail_only=thumbnail_only,
                per_video_dir=per_video_dir,
            )
            return saved_path, metadata_path, thumbnail_path, attempt
        except yt_dlp.utils.DownloadError as exc:
            LOGGER.warning("DownloadError on attempt %s for %s: %s", attempt, url, exc)
            if not is_bot_verification_error(exc) or attempt == attempts:
                raise
            wait_before_retry(url, attempt, retry_delay)

    raise RuntimeError(f"No se pudo descargar el video tras {attempts} intentos: {url}")


def process_url(
    url: str, output_dir: Path, ydl: yt_dlp.YoutubeDL, args: argparse.Namespace
) -> DownloadResult:
    if args.skip_existing and has_existing_output(
        url,
        output_dir,
        thumbnail_only=args.thumbnail_only,
        per_video_dir=args.per_video_dir,
    ):
        LOGGER.info("Skipped existing output for %s", url)
        return result_from_skip(url)

    saved_path, metadata_path, thumbnail_path, attempts = download_video_with_retries(
        url,
        output_dir,
        ydl,
        thumbnail_only=args.thumbnail_only,
        per_video_dir=args.per_video_dir,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
    )
    result_output_dir = str(saved_path.parent.resolve()) if str(saved_path) else str(metadata_path.parent.resolve())
    return DownloadResult(
        url=url,
        status="success",
        output_dir=result_output_dir,
        output_file=str(saved_path.resolve()) if str(saved_path) else "",
        metadata_file=str(metadata_path.resolve()),
        thumbnail_file=str(thumbnail_path.resolve()) if thumbnail_path else "",
        error_type="",
        error_message="",
        attempts=attempts,
    )

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.audio_only and args.thumbnail_only:
        parser.error("No puedes usar --audio-only y --thumbnail-only al mismo tiempo")

    try:
        urls = collect_urls(args)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    ydl_opts = build_ydl_options(output_dir, args)
    log_path = setup_logging(output_dir)
    downloaded_count = 0
    skipped_count = 0
    failed_urls: list[str] = []
    results: list[DownloadResult] = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in urls:
            try:
                result = process_url(url, output_dir, ydl, args)
                results.append(result)
                if result.status == "skipped":
                    skipped_count += 1
                    print(f"Descarga omitida para {url}: {result.error_message}")
                else:
                    downloaded_count += 1
                    LOGGER.info("Downloaded %s -> %s", url, result.output_file or result.thumbnail_file)
                    if result.output_file:
                        print(f"Archivo descargado en: {result.output_file}")
                    print(f"Metadatos guardados en: {result.metadata_file}")
                    if result.thumbnail_file:
                        print(f"Miniatura guardada en: {result.thumbnail_file}")
                    elif not args.audio_only:
                        print("No se encontro la miniatura descargada.", file=sys.stderr)
            except yt_dlp.utils.DownloadError as exc:
                failed_urls.append(url)
                error_type, user_message = classify_error(exc)
                results.append(
                    DownloadResult(
                        url=url,
                        status="failed",
                        output_dir="",
                        output_file="",
                        metadata_file="",
                        thumbnail_file="",
                        error_type=error_type,
                        error_message=user_message,
                        attempts=args.max_retries + 1 if is_bot_verification_error(exc) else 1,
                    )
                )
                LOGGER.error("Failed %s [%s]: %s", url, error_type, exc)
                print(f"No se pudo descargar {url}: {user_message}", file=sys.stderr)
            except Exception as exc:  # pragma: no cover
                failed_urls.append(url)
                results.append(
                    DownloadResult(
                        url=url,
                        status="failed",
                        output_dir="",
                        output_file="",
                        metadata_file="",
                        thumbnail_file="",
                        error_type="unexpected_error",
                        error_message=str(exc),
                        attempts=1,
                    )
                )
                LOGGER.exception("Unexpected error for %s", url)
                print(f"Ocurrio un error inesperado con {url}: {exc}", file=sys.stderr)

    results_path = write_results_csv(output_dir, results)
    print(
        f"Resumen: {downloaded_count} descargado(s), "
        f"{skipped_count} omitido(s), {len(failed_urls)} fallido(s), {len(urls)} total."
    )
    print(f"Resultados guardados en: {results_path.resolve()}")
    print(f"Log guardado en: {log_path.resolve()}")

    if failed_urls:
        failed_path = write_failed_urls(output_dir, failed_urls)
        print(f"URLs fallidas guardadas en: {failed_path.resolve()}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
