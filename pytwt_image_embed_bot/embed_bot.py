import logging
logging.basicConfig(level=logging.INFO)

import re
import os
import sys
import json
import aiohttp
from io import BytesIO
from gallery_dl import config
from traceback import print_exc
from discord.ext import commands
from discord import Intents, File, Embed, Colour
from gallery_hook import CombinedJob
from media_converter import scale_mp4, convert_video_to_gif
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
            boost_to_size = {3: 250, 2: 100, 1: 50, 0: 10}

            # Get the max size based on the boost level
            max_size_mb = boost_to_size.get(boost_level, 10)

            for author, tweet_id in urls:
                    attachments = []
                    tweet_url = f'https://x.com/{author}/status/{tweet_id}'

                    j = CombinedJob(tweet_url)
                    j.run()

                    async with message.channel.typing():
                        async with aiohttp.ClientSession() as session:
                            for content_url, kwdict in zip(j.urls, j.kwdicts):
                                async with session.get(content_url) as resp:
                                    tweet_date = kwdict['date']
                                    extension = "."+kwdict['extension']
                                    image_num = "_"+str(+kwdict['num'])
                                    filename = tweet_date.strftime('%d.%m.%Y')+"."+tweet_id+image_num+extension

                                    # Process as an image if bitrate keyword does not exist.
                                    if 'bitrate' not in kwdict:
                                        image_attachment = File(BytesIO(await resp.read()), filename=filename)
                                        attachments.append(image_attachment)

                                    # Process both GIF images and videos.
                                    elif kwdict.get('bitrate') >= 0:
                                        video_bytes = await resp.read()
                                        width = int(kwdict['width'])
                                        video_size_mb = len(video_bytes) / (1024 * 1024)

                                        # GIF image logic.
                                        if kwdict.get('bitrate') == 0:
                                            gif_bytes = await convert_video_to_gif(video_bytes, str(f'{width}:-1'))
                                            gif_data = gif_bytes.read()
                                            gif_size_mb = len(gif_data) / (1024 * 1024)
                                            gif_bytes.seek(0)

                                            while gif_size_mb > max_size_mb:
                                                width = int(width * 0.75)
                                                logging.info(f"GIF too large ({gif_size_mb:.2f} MB), retrying with width={width}")

                                                gif_bytes = await convert_video_to_gif(video_bytes, str(f'{width}:-1'))
                                                gif_data = gif_bytes.read()
                                                gif_size_mb = len(gif_data) / (1024 * 1024)
                                                gif_bytes.seek(0)

                                            gif_attachment = File(gif_bytes, filename=filename[:-4] + ".gif")
                                        
                                        while video_size_mb > max_size_mb:
                                            width = int(width * 0.75)
                                            logging.info(f"Video too large ({video_size_mb:.2f} MB), retrying with width={width}")

                                            scaled_video_io = await scale_mp4(video_bytes, f'{width}:-1')
                                            video_bytes = scaled_video_io.getvalue()
                                            video_size_mb = len(video_bytes) / (1024 * 1024)

                                        # Append video first then gif image later.
                                        video_attachment = File(BytesIO(video_bytes), filename=filename)
                                        attachments.append(video_attachment)
                                        if kwdict.get('bitrate') == 0: attachments.append(gif_attachment)

                            if attachments:
                                # Use the first kwdict for tweet metadata (assuming all media share the same tweet).
                                tweet_nick = kwdict['author']['nick']
                                tweet_content = kwdict['content']

                                tweet_replies = human_format(kwdict['reply_count'])
                                tweet_retweets = human_format(kwdict['retweet_count'])
                                tweet_likes = human_format(kwdict['favorite_count'])

                                embed = Embed(title=f'{tweet_nick} (@{author})', description=f'{tweet_content}', url=tweet_url, timestamp=utc_to_local(tweet_date), colour=Colour.blue())
                                embed.set_author(name=f'💬 {tweet_replies}   🔁 {tweet_retweets}   💖 {tweet_likes}', url=tweet_url)
                                embed.set_footer(text='EmbedBot', icon_url="https://files.catbox.moe/3u1fe7.jpg")
                                await message.channel.send(files=attachments, embed=embed)
            await message.delete()

    except Exception:
        print_exc()


@bot.event
async def on_error(event, *args, **kwargs):
    logging.error("Error in event %s", event)
    print_exc()

bot.run(discord_token)
