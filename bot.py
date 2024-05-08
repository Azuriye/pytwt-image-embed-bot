import json, re, sys, aiohttp, logging
from io import BytesIO
from gallery_dl import config
from discord.ext import commands
from discord import Intents, File, Embed, Colour

from external_hook import CombinedJob, human_format

with open(sys.path[0]+'/config.json', 'r') as file:
    config_data = json.load(file)

twitter_token = config_data.get('TwitterToken')
discord_token = config_data.get('DiscordToken')
discord_channels = config_data.get('DiscordChannels')

if not all([twitter_token, discord_token, discord_channels, discord_channels != ['']]):
    print("Please fill in all the values in config.json")
    exit(1)

intents = Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Set up initial configuration for gallery-dl
config.clear()
config.set(("extractor", "twitter"), "unique", "false")
config.set(("extractor", "twitter"), "replies", "false")
config.set(("extractor", "twitter", "cookies"), "auth_token", twitter_token)


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
                urls = re.findall(r'(https?://(?:twitter\.com/[^\s]*?/status/(\d{19})|x\.com/[^\s]*?/status/(\d{19})))', content)

                if not urls:
                    return

                if message.attachments:
                    return

                for url, *_ in urls:
                    attachments = []
                    j = CombinedJob(url)
                    j.run()

                    async with aiohttp.ClientSession() as session:
                        for content_url, kwdict in zip(j.urls, j.kwdicts):
                            async with session.get(content_url) as resp:
                                tweet_date = kwdict['date'].strftime('%d.%m.%Y')
                                tweet_id = str(kwdict['tweet_id'])
                                extension = "."+kwdict['extension']
                                image_num = "_"+str(+kwdict['num'])
                                filename = tweet_date+"."+tweet_id+image_num+extension
                                attachment = File(BytesIO(await resp.read()), filename=filename)
                            attachments.append(attachment)
                    
                        if attachments:
                            tweet_author = kwdict['author']['name']
                            tweet_nick = kwdict['author']['nick']
                            tweet_content = kwdict['content']
                            tweet_link = f'https://twitter.com/{tweet_author}/status/{tweet_id}'

                            tweet_replies = human_format(kwdict['reply_count'])
                            tweet_retweets = human_format(kwdict['retweet_count'])
                            tweet_likes = human_format(kwdict['favorite_count'])

                            embed = Embed(title=f'{tweet_nick} (@{tweet_author})',  description=f'{tweet_content}', url=tweet_link, colour=Colour.blue())
                            embed.set_author(name=f'💬 {tweet_replies}   🔁 {tweet_retweets}   💖 {tweet_likes}', url=tweet_link)
                            embed.set_footer(text="Date: "+ '/'.join(tweet_date.split('.')))
                            await message.channel.send(files=attachments, embed=embed)
                await message.delete()
                                                  
    except Exception as e:
        print("Error: ", e)


@bot.event
async def on_error(event, *args, **kwargs):
    print(f'Error in event {event}: {args[0]}')

bot.run(discord_token, log_level=logging.WARN)
