"""ffmpeg helpers: mp4 downscale + mp4 -> animated webp."""
import asyncio
import os
import tempfile
from io import BytesIO

_MIB = 1024 * 1024
FFMPEG_SEM = asyncio.Semaphore(2)  # 2 encodes at once max


async def _ffmpeg_bytes(args: list[str], video_bytes: bytes, what: str) -> BytesIO:
    async with FFMPEG_SEM:
        """Run ffmpeg with bytes in -> bytes out. Shared plumbing."""
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:", *args, "pipe:",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=video_bytes)
        if proc.returncode != 0:
            raise RuntimeError(f"{what} failed: {stderr.decode()}")
        return BytesIO(stdout)


async def scale_mp4(video_bytes: bytes, scale: str = "iw*3/4:-2") -> BytesIO:
    """Downscale mp4. Scale is an ffmpeg expression, e.g. '640:-2'."""
    return await _ffmpeg_bytes(
        ["-vf", f"scale={scale}:flags=lanczos",
         "-movflags", "frag_keyframe+empty_moov+default_base_moof",
         "-f", "mp4"],
        video_bytes, "Video downscale",
    )


async def convert_video_to_webp(video_bytes: bytes, scale: str = "iw:-2", fps: int = 20, quality: int = 90, lossless: bool = False, compression_level: int = 4, method: int = 4, preset: str = "picture") -> BytesIO:
    pix = "rgb24" if lossless else "yuv420p"
    filters = f"fps={fps},scale={scale}:flags=lanczos,format={pix}"

    with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as tmp:
        out_path = tmp.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:",
            "-vf", filters,
            "-c:v", "libwebp",
            "-lossless", "1" if lossless else "0",
            "-quality", str(quality),
            "-compression_level", str(compression_level),
            "-method", str(method),
            "-preset", preset,
            "-loop", "0",
            "-an",
            "-y", out_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(input=video_bytes), timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"WebP conversion failed: {stderr.decode()}")

        with open(out_path, "rb") as f:
            return BytesIO(f.read())
    finally:
        try: os.remove(out_path)
        except FileNotFoundError: pass


async def shrink_mp4_to_fit(video_bytes: bytes, max_size_mb: float, max_attempts: int = 6) -> bytes:
    """Repeatedly 0.75x the video until it fits. Returns raw bytes."""
    for _ in range(max_attempts):
        if len(video_bytes) / _MIB <= max_size_mb:
            break
        shrunk = (await scale_mp4(video_bytes, "iw*3/4:-2")).getvalue()
        if not shrunk or len(shrunk) >= len(video_bytes):
            break
        video_bytes = shrunk
    return video_bytes


async def make_webp_preview(video_bytes: bytes, max_size_mb: float,
                            fps: int = 20, quality: int = 90) -> BytesIO:
    """Near-native first, shrink only if it doesn't fit."""
    # tweet_video gifs are 2-5s 480p: lossless often still <10MB
    if len(video_bytes) < 8 * 1024 * 1024:
        try:
            out = await convert_video_to_webp(
                video_bytes, "iw:-2", fps=fps,
                lossless=True, preset="picture")
            if len(out.getvalue()) / _MIB <= max_size_mb:
                return out
        except Exception:
            pass

    # lossy fallback: q90 -> 80 -> 65, keep res first
    q, factor, scale = quality, 1.0, "iw:-2"
    out = await convert_video_to_webp(video_bytes, scale, fps=fps, quality=q)
    for _ in range(8):
        if len(out.getvalue()) / _MIB <= max_size_mb:
            break
        if q > 65:
            q -= 10
        else:
            factor *= 0.75
            scale = f"iw*{factor}:-2"
            if factor < 0.2:
                break
        out = await convert_video_to_webp(
            video_bytes, scale,
            fps=fps if factor > 0.5 else 15,
            quality=q)
    return out
