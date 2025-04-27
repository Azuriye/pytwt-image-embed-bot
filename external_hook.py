import logging

# 1) Grab the specific downloader logger
http_logger = logging.getLogger("gallery_dl.downloader.http")

# 2) Define a handler that raises on WARNING or above
class RaiseOnWarningHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            raise RuntimeError(record.getMessage())

# 3) Replace existing handlers with ours
http_logger.handlers.clear()
http_logger.addHandler(RaiseOnWarningHandler())

import os
import asyncio
import tempfile
import subprocess as sp
from datetime import timezone
from gallery_dl import job
from io import BytesIO

class CombinedJob(job.UrlJob):
    def __init__(self, url, parent=None):
        super().__init__(url, parent)
        self.urls = []
        self.kwdicts = []
        self.keyword_job = job.KeywordJob(url, parent)

    def handle_url(self, url, kwdict):
        self.urls.append(url)
        self.kwdicts.append(kwdict.copy())

    def run(self):
        status = super().run()
        if status != 0:
            # bit 0x4 indicates HTTP/download failure
            raise RuntimeError(f"gallery-dl extraction failed (status=0x{status:x})")
        return status

# Try up to 4 times to build and run CombinedJob; return the job on success or None on permanent failure
async def extract_with_retry(tweet_url: str, delay: float = 1.0):
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            j = CombinedJob(tweet_url)
            j.run()
            return j
        except RuntimeError as e:
            if attempt < max_attempts:
                logging.info(
                    f"[Attempt {attempt}] Extraction failed for {tweet_url!r}: {e}. "
                    "Retrying in %.1fs…" % delay)
                await asyncio.sleep(delay)
            else:
                logging.error(f"[{attempt}/{max_attempts}] Permanent failure extracting {tweet_url!r}: {e}.")
                return None

async def async_convert_video_to_gif(video_bytes, scale):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, convert_video_to_gif, video_bytes, scale)

# https://stackoverflow.com/a/45846841
def human_format(num: int) -> str:
    num = float('{:.3g}'.format(num))
    magnitude = 0
    while abs(num) >= 1000:
        magnitude += 1
        num /= 1000.0
    return '{}{}'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'K', 'M', 'B', 'T'][magnitude])

# https://stackoverflow.com/a/13287083
def utc_to_local(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)

# https://stackoverflow.com/a/67878795
# https://superuser.com/a/556031
# https://wunkolo.github.io/post/2020/02/buttery-smooth-10fps
# http://blog.pkh.me/p/21-high-quality-gif-with-ffmpeg.html
def convert_video_to_gif(video_bytes: bytes, scale: str, fps: int = 50, dither: str = 'sierra2_4a') -> BytesIO:
    """
    Convert video bytes to a high-quality GIF using a two-pass FFmpeg process.

    This function first generates a palette based on the video content (using stats_mode=diff),
    then uses that palette to produce the final GIF with improved color mapping and dithering.
    
    Parameters:
      video_bytes (bytes): Input video content.
      fps (int): Frame rate to use for the GIF (default 50 FPS).
      dither (str): Dithering algorithm to use (default 'sierra2_4a').
    
    Returns:
      BytesIO: A BytesIO object containing the resulting GIF.
    """
    # Create a temporary file for the generated palette.
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        palette_path = tmp.name

    # Define filter chain using Lanczos scaling for best quality.
    filters = f"fps={fps},scale={scale}:flags=lanczos"

    # First pass: Generate a global palette that focuses on moving pixels (stats_mode=diff)
    # Remove the 'split' filter, as it is not needed for a single output.
    cmd_palette = [
        'ffmpeg',
        '-hide_banner',
        '-i', 'pipe:',
        '-vf', f"{filters},palettegen=stats_mode=diff:max_colors=256",
        '-y', palette_path
    ]
    result_palette = sp.run(cmd_palette, input=video_bytes, stdout=sp.PIPE, stderr=sp.PIPE)
    if result_palette.returncode != 0:
        os.remove(palette_path)
        raise RuntimeError("Palette generation failed: " + result_palette.stderr.decode())

    # Second pass: Generate the GIF using the previously generated palette.
    cmd_gif = [
        'ffmpeg',
        '-hide_banner',
        '-i', 'pipe:',
        '-i', palette_path,
        '-lavfi', f"{filters} [s]; [s][1:v] paletteuse=dither={dither}",
        '-loop', '0',
        '-f', 'gif',
        '-loglevel', 'error',
        'pipe:'
    ]
    result_gif = sp.run(cmd_gif, input=video_bytes, stdout=sp.PIPE, stderr=sp.PIPE)

    # Clean up the temporary palette file.
    os.remove(palette_path)

    if result_gif.returncode != 0:
        raise RuntimeError("GIF conversion failed: " + result_gif.stderr.decode())

    return BytesIO(result_gif.stdout)
