import os
import asyncio
import tempfile
from io import BytesIO
import subprocess as sp

async def scale_mp4(video_bytes: bytes, scale: str) -> BytesIO:
    """
    Asynchronously downscale video bytes.
    
    Parameters:
      video_bytes (bytes): Input video content.
      scale (str): Resolution scale (e.g., '320:-1').
    
    Returns:
      BytesIO: A BytesIO object containing the resulting video.
    """
    process = await asyncio.create_subprocess_exec(
        'ffmpeg',
        '-hide_banner',
        '-i', 'pipe:',
        '-vf', f"scale={scale}",
        '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
        '-f', 'mp4',
        '-loglevel', 'error',
        'pipe:',
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate(input=video_bytes)

    if process.returncode != 0:
        raise RuntimeError(f"Video downscale failed: {stderr.decode()}")
    
    
    return BytesIO(stdout)

# https://stackoverflow.com/a/67878795
# https://superuser.com/a/556031
# https://wunkolo.github.io/post/2020/02/buttery-smooth-10fps
# http://blog.pkh.me/p/21-high-quality-gif-with-ffmpeg.html
async def convert_video_to_gif(video_bytes: bytes, scale: str, fps: int = 50, dither: str = 'sierra2_4a') -> BytesIO:
    """
    Asynchronously convert video bytes to a high-quality GIF using a two-pass FFmpeg process.
    
    Parameters:
      video_bytes (bytes): Input video content.
      scale (str): Resolution scale (e.g., '320:-1').
      fps (int): Frame rate for the GIF (default 50).
      dither (str): Dithering algorithm to use (default 'sierra2_4a').
    
    Returns:
      BytesIO: A BytesIO object containing the resulting GIF.
    """
    loop = asyncio.get_event_loop()

    def sync_convert():
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            palette_path = tmp.name

        filters = f"fps={fps},scale={scale}:flags=lanczos"

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
        os.remove(palette_path)

        if result_gif.returncode != 0:
            raise RuntimeError("GIF conversion failed: " + result_gif.stderr.decode())

        return BytesIO(result_gif.stdout)

    return await loop.run_in_executor(None, sync_convert)
