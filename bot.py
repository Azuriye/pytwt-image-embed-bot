import json, re, sys, aiohttp
from io import BytesIO
from gallery_dl import config
from discord.ext import commands
from discord import Intents, File

from urljob_hook import UrlJob

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
                url = ""
                try:
                    url = re.search('(https?://[^\s]*)', content).group(1)
                except AttributeError:
                    return False

                if message.attachments:
                    return


                j = UrlJob(url)
                j.run()
                async with aiohttp.ClientSession() as session:
                    async with session.get(j.urls[0]) as resp:
                        image_bytes = BytesIO(await resp.read())
                        url_number = re.search(r'/status/(\d+)', url)
                        filename = f'{url_number.group(1)}.png'
                        attachment = File(image_bytes, filename=filename)

                        if attachment:
                            await message.channel.send(content=url, file=attachment)
                    
                
    except Exception as e:
        print("Error: ", e)


@bot.event
async def on_error(event, *args, **kwargs):
    print(f'Error in event {event}: {args[0]}')

bot.run(discord_token)
