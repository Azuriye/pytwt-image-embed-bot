"""Re-embed tweets + direct video.twimg.com links with mp4/webp files."""
import asyncio
import json
import logging
import re
from io import BytesIO
from pathlib import Path
from traceback import print_exc
from urllib.parse import urlparse, unquote
import aiohttp
from discord import Colour, Embed, File, Intents, HTTPException
from discord.ext import commands
from gallery_dl import config

from gallery_hook import CombinedJob
from media_converter import make_webp_preview, shrink_mp4_to_fit
from utils import human_format, utc_to_local

# --- config ---------------------------------------------------------------

def load_config() -> tuple[str, str, set[str]]:
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "config.json", here / "config.json"):
        if cand.exists():
            with open(cand) as f:
                data = json.load(f)
            break
    else:
        raise SystemExit("config.json not found next to bot or project root")

    twitter_token = data.get("TwitterToken")
    discord_token = data.get("DiscordToken")
    channels = set(map(str, data.get("DiscordChannels") or []))
    if not (twitter_token and discord_token and channels and channels != {""}):
        raise SystemExit("Please fill in all the values in config.json")
    return twitter_token, discord_token, channels


twitter_token, discord_token, DISCORD_CHANNELS = load_config()

config.clear()
config.set(("extractor", "twitter"), "unique", "false")
config.set(("extractor", "twitter"), "replies", "false")
config.set(("extractor", "twitter"), "retweets", "false")
config.set(("extractor", "twitter", "cookies"), "auth_token", twitter_token)

intents = Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- patterns / limits -----------------------------------------------------

BASE_PATTERN = r"(?:https?://)?(?:www\.|mobile\.)?(?:(?:[fv]x)?twitter|(?:fix(?:up|v))?x)\.com"
TWEET_RE = re.compile(BASE_PATTERN + r"/([^/?#]+|i/web)/status/(\d+)/?(?=\s|$|\?|#|photo/|video/)")
TWIMG_RE = re.compile(r"https?://video\.twimg\.com/[^\s<>\")\]]+")

MAX_FILES_PER_MSG = 10  # Discord limit


def find_tweet_refs(content: str) -> list[tuple[str, str]]:
    return TWEET_RE.findall(content)


def find_twimg_urls(content: str) -> list[str]:
    seen, out = set(), []
    for raw in TWIMG_RE.findall(content):
        url = raw.rstrip(".,;:!?)'\"")
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def get_max_size_mb(guild) -> float:
    # Bot uploads are capped by the *server's* boost, not your Nitro.
    limit = getattr(guild, "filesize_limit", None)  # bytes, tier + perks aware
    if limit:
        return limit / (1024 * 1024) - 0.5  # 0.5MB safety for embed JSON overhead
    if guild is None:  # DM, no tier
        return 20 - 0.5
    tier = getattr(guild, "premium_tier", 0) or 0
    return {3: 100, 2: 50, 1: 20, 0: 20}.get(tier, 20) - 0.5


def tweet_filename(tweet_date, tweet_id: str, num, ext: str) -> str:
    return f"{tweet_date:%d.%m.%Y}.{tweet_id}_{num}.{ext.lstrip('.')}"


def twimg_filename(url: str) -> str:
    name = unquote(urlparse(url).path.rstrip("/").split("/")[-1] or "video.mp4")
    return name if name.lower().endswith(".mp4") else name + ".mp4"


# --- fetching --------------------------------------------------------------

async def fetch_bytes(session: aiohttp.ClientSession, url: str) -> bytes | None:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logging.warning("fetch %s -> %s", url, resp.status)
                return None
            return await resp.read()
    except Exception:
        print_exc()
        return None


def fetch_tweet_media(tweet_url: str) -> tuple[list[str], list[dict]]:
    """Blocking gallery-dl call - run via asyncio.to_thread."""
    j = CombinedJob(tweet_url)
    j.run()
    return j.urls, j.kwdicts


async def files_for_tweet_item(session, content_url: str, meta: dict,
                               tweet_id: str, max_size_mb: float) -> list[File]:
    """One gallery-dl item -> 1 image, or 1 video (+ webp if gif-like)."""
    data = await fetch_bytes(session, content_url)
    if not data:
        return []
    ext = meta["extension"].lstrip(".")
    name = tweet_filename(meta["date"], tweet_id, meta["num"], ext)

    if "bitrate" not in meta:  # photo
        return [File(BytesIO(data), filename=name)]

    files = [File(BytesIO(await shrink_mp4_to_fit(data, max_size_mb)), filename=name)]
    if meta.get("bitrate") == 0:  # tweet gif -> also send looping webp
        webp = await make_webp_preview(data, max_size_mb)
        files.append(File(webp, filename=Path(name).stem + ".webp"))
    return files


async def handle_tweet(session, channel, author: str, tweet_id: str, max_size_mb: float) -> bool:
    tweet_url = f"https://x.com/{author}/status/{tweet_id}"
    try:
        urls, metas = await asyncio.to_thread(fetch_tweet_media, tweet_url)
    except Exception:
        print_exc()
        return False
    if not urls:
        return False

    files: list[File] = []
    for content_url, meta in zip(urls, metas):
        try:
            files.extend(await files_for_tweet_item(session, content_url, meta, tweet_id, max_size_mb))
        except Exception:
            print_exc()

    if not files:
        return False

    meta = metas[0]
    embed = Embed(
        title=f"{meta['author']['nick']} (@{author})",
        description=meta.get("content") or "",
        url=tweet_url, timestamp=utc_to_local(meta["date"]),
        colour=Colour.blue()
    )
    embed.set_author(name=f"💬 {human_format(meta['reply_count'])}   "
                          f"🔁 {human_format(meta['retweet_count'])}   "
                          f"💖 {human_format(meta['favorite_count'])}",
                     url=tweet_url)
    embed.set_footer(text="EmbedBot", icon_url="https://files.catbox.moe/3u1fe7.jpg")
    try:
        await channel.send(files=files, embed=embed)
    except HTTPException as e:
         logging.warning("send failed %s %s: %s", author, tweet_id, e)
         return False
    return True


async def handle_twimg_links(session, channel, urls: list[str], max_size_mb: float) -> bool:
    files: list[File] = []
    for url in urls:
        if not urlparse(url).path.lower().endswith(".mp4"):
            continue
        data = await fetch_bytes(session, url)
        if not data:
            continue
        try:
            name = twimg_filename(url)
            files.append(File(BytesIO(await shrink_mp4_to_fit(data, max_size_mb)), filename=name))
            if "/tweet_video/" in url.lower():
                webp = await make_webp_preview(data, max_size_mb)
                files.append(File(webp, filename=Path(name).stem + ".webp"))
        except Exception:
            print_exc()
    if not files:
        return False
    for i in range(0, len(files), MAX_FILES_PER_MSG):
        await channel.send(files=files[i:i + MAX_FILES_PER_MSG])
    return True

# --- events ----------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")


@bot.event
async def on_message(message):
    try:
        if message.author == bot.user:
            return
        if str(message.channel.id) not in DISCORD_CHANNELS:
            return
        if message.attachments:
            return

        tweets = find_tweet_refs(message.content)
        twimgs = find_twimg_urls(message.content)
        if not tweets and not twimgs:
            return

        max_size_mb = get_max_size_mb(message.guild)

        sent = False
        async with message.channel.typing():
            async with aiohttp.ClientSession() as session:
                for author, tweet_id in tweets:
                    if await handle_tweet(session, message.channel, author, tweet_id, max_size_mb):
                        sent = True
                if twimgs and await handle_twimg_links(session, message.channel, twimgs, max_size_mb):
                    sent = True

        if sent:
            try:
                await message.delete()
            except Exception:
                pass
    except Exception:
        print_exc()


@bot.event
async def on_error(event, *args, **kwargs):
    logging.error("Error in event %s", event)
    print_exc()


bot.run(discord_token, log_level=logging.WARN, root_logger=True)
