import json
import io
import shutil
import re
import sys
import traceback
from discord.ext import commands
from discord import Intents, File
from gallery_dl import config, job

with open(sys.path[0]+'./config.json', 'r') as file:
    config_data = json.load(file)
    print(config_data)

twitter_token = config_data.get('TwitterToken')
discord_token = config_data.get('DiscordToken')
discord_channels = config_data.get('DiscordChannels')

if not all([twitter_token, discord_token, discord_channels, discord_channels != ['']]):
    print("Please fill in all the values in config.json")
    exit(1)

intents = Intents.default()
intents.messages = True
intents.guilds = True

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
            content = message.clean_content

            if 'twitter.com' in content or 'x.com' in content:
                url = ""
                try:
                    url = re.search('(https?://[^\s]*)', content).group(1)
                except AttributeError:
                    return False

                if message.attachments:
                    return

                stdout_capture = io.StringIO()  # Create a StringIO object to capture stdout
                sys.stdout = stdout_capture  # Redirect stdout to the StringIO object

                job.DownloadJob(url).run()  # Run the job

                file_paths = stdout_capture.getvalue().splitlines()  # Get the captured output
                sys.stdout = sys.__stdout__  # Reset stdout to its original value

                if file_paths:
                    for file_path in file_paths:
                        with open(file_path, 'rb') as file:
                            picture = File(file)
                            await message.channel.send(content=url, file=picture)
                        shutil.rmtree('./gallery-dl')
    except Exception:
        traceback.print_exc()  # Print the full traceback for debugging


@bot.event
async def on_error(event, *args, **kwargs):
    print(f'Error in event {event}: {args[0]}')

bot.run(discord_token)