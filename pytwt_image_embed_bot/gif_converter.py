import os
import asyncio
import tempfile
from io import BytesIO
import subprocess as sp

async def async_convert_video_to_gif(video_bytes, scale):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, convert_video_to_gif, video_bytes, scale)

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
