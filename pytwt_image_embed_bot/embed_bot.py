import re
import os
import sys
import json
import aiohttp
import logging
from io import BytesIO
from gallery_dl import config
from traceback import print_exc
from discord.ext import commands
from discord import Intents, File, Embed, Colour
from gallery_hook import extract_with_retry
from gif_converter import async_convert_video_to_gif
from utils import human_format, utc_to_local

# Load configuration
with open(os.path.join(os.path.dirname(sys.path[0]), 'config.json'), 'r') as file:
    config_data = json.load(file)

twitter_token = config_data.get('TwitterToken')
discord_token = config_data.get('DiscordToken')
discord_channels = config_data.get('DiscordChannels')

if not all([twitter_token, discord_token, discord_channels, discord_channels != ['']]):
    logging.error("Please fill in all the values in config.json")
    exit(1)

# Set up Discord bot with necessary intents
intents = Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Set up initial configuration for gallery-dl
config.clear()
config.set(("extractor", "twitter"), "unique", "false")
config.set(("extractor", "twitter"), "replies", "false")
config.set(("extractor", "twitter"), "retweets", "false")
config.set(("extractor", "twitter", "cookies"), "auth_token", twitter_token)

# Twitter URL pattern
BASE_PATTERN = (r"(?:https?://)?(?:www\.|mobile\.)?"
                r"(?:(?:[fv]x)?twitter|(?:fix(?:up|v))?x)\.com")

# Helper function to check the server's boost level
async def get_server_boost_level(guild):
    # Returns the Nitro boost level: None (no boost), 1 (Tier 1), 2 (Tier 2), 3 (Tier 3)
    return guild.premium_tier

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')


@bot.event
async def on_message(message):
    try:
        if message.author == bot.user: return

        if str(message.channel.id) in discord_channels:
            content = message.content

            # TwitterTweetExtractor
            pattern = (BASE_PATTERN + r"/([^/?#]+|i/web)/status/(\d+)"
               r"/?(?=\s|$|\?|#|photo/|video/)")
            
            urls = re.findall(pattern, content)

            if not urls: return

            if message.attachments: return

            # Get the boost level of the server
            guild = message.guild
            boost_level = await get_server_boost_level(guild)

            # Mapping of boost level to max gif size
            boost_to_size = {3: 250, 2: 100, 1: 50, 0: 8}

            # Get the max gif size based on the boost level
            max_gif_size_mb = boost_to_size.get(boost_level, 8)

            for author, tweet_id in urls:
                    attachments = []
                    url = f'https://x.com/{author}/status/{tweet_id}'

                    j = await extract_with_retry(url)
                    if j is None: continue

                    async with message.channel.typing():
                        async with aiohttp.ClientSession() as session:
                            for content_url, kwdict in zip(j.urls, j.kwdicts):
                                async with session.get(content_url) as resp:
                                    tweet_date = kwdict['date']
                                    extension = "."+kwdict['extension']
                                    image_num = "_"+str(+kwdict['num'])
                                    filename = tweet_date.strftime('%d.%m.%Y')+"."+tweet_id+image_num+extension

                                    # Process as image or video if bitrate is non-zero.
                                    if kwdict.get('bitrate') != 0:
                                        attachment = File(BytesIO(await resp.read()), filename=filename)
                                        attachments.append(attachment)
                                    else:
                                        # Process as video: convert video to GIF and attach both MP4 and GIF versions.
                                        video_bytes = await resp.read()
                                        width = int(kwdict['width'])

                                        # Convert and check size
                                        gif_bytes = await async_convert_video_to_gif(video_bytes, str(f'{width}:-1'))
                                        gif_data = gif_bytes.read()
                                        gif_size_mb = len(gif_data) / (1024 * 1024)
                                        gif_bytes.seek(0)

                                        while gif_size_mb > max_gif_size_mb:
                                            width = int(width * 0.75)
                                            logging.info(f"GIF too large ({gif_size_mb:.2f} MB), retrying with width={width}")

                                            gif_bytes = await async_convert_video_to_gif(video_bytes, str(f'{width}:-1'))
                                            gif_data = gif_bytes.read()
                                            gif_size_mb = len(gif_data) / (1024 * 1024)
                                            gif_bytes.seek(0)

                                        mp4_attachment = File(BytesIO(video_bytes), filename=filename)
                                        gif_attachment = File(gif_bytes, filename=filename[:-4] + ".gif")
                                        attachments.extend([mp4_attachment, gif_attachment])

                            if attachments:
                                # Use the first kwdict for tweet metadata (assuming all media share the same tweet).
                                tweet_nick = kwdict['author']['nick']
                                tweet_content = kwdict['content']

                                tweet_replies = human_format(kwdict['reply_count'])
                                tweet_retweets = human_format(kwdict['retweet_count'])
                                tweet_likes = human_format(kwdict['favorite_count'])

                                embed = Embed(title=f'{tweet_nick} (@{author})', description=f'{tweet_content}', url=url, timestamp=utc_to_local(tweet_date), colour=Colour.blue())
                                embed.set_author(name=f'💬 {tweet_replies}   🔁 {tweet_retweets}   💖 {tweet_likes}', url=url)
                                embed.set_footer(text='EmbedBot', icon_url="https://files.catbox.moe/3u1fe7.jpg")
                                await message.channel.send(files=attachments, embed=embed)
            await message.delete()

    except Exception:
        print_exc()


@bot.event
async def on_error(event, *args, **kwargs):
    logging.error("Error in event %s", event)
    print_exc()

bot.run(discord_token, log_level=logging.WARN)
