import json, re, sys, aiohttp, logging
from io import BytesIO
from gallery_dl import config
from traceback import print_exc
from discord.ext import commands
from discord import Intents, File, Embed, Colour
from external_hook import CombinedJob, human_format, convert_video_to_gif, utc_to_local

# Load configuration
with open(sys.path[0]+'/config.json', 'r') as file:
    config_data = json.load(file)

twitter_token = config_data.get('TwitterToken')
discord_token = config_data.get('DiscordToken')
discord_channels = config_data.get('DiscordChannels')

if not all([twitter_token, discord_token, discord_channels, discord_channels != ['']]):
    print("Please fill in all the values in config.json")
    exit(1)

# Set up Discord bot with necessary intents
intents = Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Set up initial configuration for gallery-dl
config.clear()
config.set(("extractor", "twitter"), "unique", "false")
config.set(("extractor", "twitter"), "replies", "false")
config.set(("extractor", "twitter", "cookies"), "auth_token", twitter_token)

# Twitter URL regex (matches both twitter.com and x.com)
TWITTER_URL_REGEX = r'(https?://(?:\w+\.)?(twitter\.com|[^\s]*?/status/\d{19}|x\.com/[^\s]*?/status/\d{19}))'


@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')


@bot.event
async def on_message(message):
    try:
        if message.author == bot.user:
            return

        if str(message.channel.id) in discord_channels:
            content = message.content

            if 'twitter.com' in content or 'x.com' in content:
                urls = re.findall(TWITTER_URL_REGEX, content)

                if not urls:
                    return

                if message.attachments:
                    return

                for url, *_ in urls:
                    # Normalize the URL to always use twitter.com domain.
                    url = re.sub(r'https?://(?:\w*\.?)?(twitter\.com|\w*?x\.com)', r'https://twitter.com', url)
                    attachments = []
                    j = CombinedJob(url)
                    j.run()

                    async with message.channel.typing():
                        async with aiohttp.ClientSession() as session:
                            for content_url, kwdict in zip(j.urls, j.kwdicts):
                                async with session.get(content_url) as resp:
                                    tweet_date = kwdict['date']
                                    tweet_id = str(kwdict['tweet_id'])
                                    extension = "."+kwdict['extension']
                                    image_num = "_"+str(+kwdict['num'])
                                    filename = tweet_date.strftime('%d.%m.%Y')+"."+tweet_id+image_num+extension

                                    bitrate = kwdict.get('bitrate')
                                    # Process as static image if no bitrate key exists or if bitrate is non-zero.
                                    if 'bitrate' not in kwdict or (bitrate and bitrate != 0):
                                        attachment = File(BytesIO(await resp.read()), filename=filename)
                                        attachments.append(attachment)
                                    else:
                                        # Process as video: convert video to GIF and attach both MP4 and GIF versions.
                                        video_bytes = await resp.read()
                                        gif_bytes = convert_video_to_gif(video_bytes)
                                        attachment_mp4 = File(BytesIO(video_bytes), filename=filename)
                                        attachment_gif = File(gif_bytes, filename=filename[:-4] + ".gif")
                                        attachments.extend([attachment_mp4, attachment_gif])
                    
                            if attachments:
                                # Use the first kwdict for tweet metadata (assuming all media share the same tweet).
                                tweet_author = kwdict['author']['name']
                                tweet_nick = kwdict['author']['nick']
                                tweet_content = kwdict['content']
                                tweet_link = f'https://twitter.com/{tweet_author}/status/{tweet_id}'

                                tweet_replies = human_format(kwdict['reply_count'])
                                tweet_retweets = human_format(kwdict['retweet_count'])
                                tweet_likes = human_format(kwdict['favorite_count'])

                                embed = Embed(title=f'{tweet_nick} (@{tweet_author})',  description=f'{tweet_content}', url=tweet_link, timestamp=utc_to_local(tweet_date), colour=Colour.blue())
                                embed.set_author(name=f'💬 {tweet_replies}   🔁 {tweet_retweets}   💖 {tweet_likes}', url=tweet_link)
                                embed.set_footer(text='Twitter')
                                await message.channel.send(files=attachments, embed=embed)
                await message.delete()
                                                  
    except Exception as e:
        logging.error("Error in on_message: %s", e)
        print_exc()


@bot.event
async def on_error(event, *args, **kwargs):
    logging.error("Error in event %s", event)
    print_exc()

bot.run(discord_token, log_level=logging.WARN)
