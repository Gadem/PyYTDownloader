# YouTube Downloader

Proyecto en Python para descargar videos de YouTube en calidad maxima de 720p, guardarlos con el titulo del video, bajar su miniatura principal en la mayor calidad disponible y generar un `.txt` con sus metadatos.

## Licencia

Este proyecto se distribuye bajo la licencia GNU GPLv3. Consulta [LICENSE](/Users/gadem/Developer/python/youtube_downloader/LICENSE).

## Requisitos

- Python 3.10 o superior
- `ffmpeg` opcional, pero recomendado para combinar mejor video y audio
- Se recomienda instalar `yt-dlp` con extras por defecto para incluir componentes EJS necesarios en YouTube

## Instalacion

```bash
cd /Users/gadem/Developer/python/youtube_downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso con `videos.csv`

```bash
python3 download_youtube.py
```

El script lee por defecto el archivo `videos.csv`. Usa una URL por fila:

```csv
url
https://www.youtube.com/watch?v=VIDEO_ID
https://www.youtube.com/watch?v=OTRO_VIDEO_ID
```

## Uso con una URL directa

```bash
python3 download_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Para elegir otra carpeta de salida o un CSV distinto:

```bash
python3 download_youtube.py --csv-file videos.csv --output-dir mis_videos
```

Para descargar solo los primeros 60 segundos de un video:

```bash
python3 download_youtube.py --duration 60 "https://www.youtube.com/watch?v=VIDEO_ID"
```

Para omitir archivos que ya existan y ajustar los reintentos:

```bash
python3 download_youtube.py --skip-existing --retry-delay 90 --max-retries 5
```

Para descargar solo el audio:

```bash
python3 download_youtube.py --audio-only "https://www.youtube.com/watch?v=VIDEO_ID"
```

Para descargar solo la miniatura y metadatos:

```bash
python3 download_youtube.py --thumbnail-only "https://www.youtube.com/watch?v=VIDEO_ID"
```

Para guardar cada video en su propia carpeta:

```bash
python3 download_youtube.py --per-video-dir "https://www.youtube.com/watch?v=VIDEO_ID"
```

Si YouTube pide verificacion de bot, puedes usar cookies del navegador:

```bash
python3 download_youtube.py --cookies-from-browser chrome
```

Tambien puedes usar un archivo `cookies.txt` exportado manualmente:

```bash
python3 download_youtube.py --cookies ~/Downloads/cookies.txt
```

Si tienes `node` o `deno` instalado, puedes indicarlo como runtime JavaScript:

```bash
python3 download_youtube.py --cookies-from-browser chrome --js-runtime node
```

## Notas

- El nombre del archivo se genera con el titulo y el ID del video para evitar colisiones.
- La miniatura principal tambien se descarga y se guarda junto al video en la mejor calidad que YouTube exponga.
- Por cada video descargado se crea un archivo `.txt` con titulo, canal, URL, ID, duracion, fecha, vistas y descripcion.
- Cada ejecucion genera `downloads/results.csv` con el estado de cada URL procesada.
- Cada ejecucion genera `downloads/logs/last_run.log` con detalles tecnicos y errores.
- `--skip-existing` omite videos ya descargados cuando detecta un archivo con el mismo ID.
- `--retry-delay` y `--max-retries` permiten ajustar la estrategia de reintentos antibot.
- `--audio-only` descarga solo el audio del video.
- `--thumbnail-only` descarga solo la miniatura y el archivo de metadatos.
- `--per-video-dir` guarda cada descarga en una carpeta separada nombrada con titulo e ID.
- Si `ffmpeg` esta instalado, `yt-dlp` puede descargar mejor combinacion de video y audio manteniendo el objetivo de 720p.
- Si no existe una version exacta a 720p, se descargara la mejor disponible que no supere esa altura.
- Algunos videos de YouTube pueden requerir cookies de sesion para pasar la verificacion antibot.
- Instalar `node` o `deno` ayuda a `yt-dlp` a extraer mejor la informacion de YouTube.
- Si aparece `n challenge solving failed` u `Only images are available for download`, actualiza dependencias con `pip install -U -r requirements.txt`.
- `--duration` solo acepta enteros mayores que 0.
