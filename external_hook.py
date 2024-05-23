from datetime import timezone
from gallery_dl import job
from io import BytesIO
import subprocess as sp

class CombinedJob(job.UrlJob):
    def __init__(self, url, parent=None):
        super().__init__(url, parent)
        self.urls = []
        self.kwdicts = []
        self.keyword_job = job.KeywordJob(url, parent)

    def handle_url(self, url, kwdict):
        self.urls.append(url)
        self.kwdicts.append(kwdict.copy())

# https://stackoverflow.com/a/45846841
def human_format(num: int) -> str:
    num = float('{:.3g}'.format(num))
    magnitude = 0
    while abs(num) >= 1000:
        magnitude += 1
        num /= 1000.0
    return '{}{}'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'K', 'M', 'B', 'T'][magnitude])

# https://stackoverflow.com/a/67878795
# https://superuser.com/a/556031
# https://wunkolo.github.io/post/2020/02/buttery-smooth-10fps/
def convert_video_to_gif(video_bytes: bytes) -> BytesIO:
    gif_bytes = BytesIO()

    ffmpeg = 'ffmpeg'
    cmd = [ffmpeg,
           '-i', 'pipe:',
           '-vf', 'fps=50,scale=320:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse',
           '-loop', '0',
           '-f', 'gif',
           '-loglevel', 'error',
           'pipe:']

    proc = sp.Popen(cmd, stdout=sp.PIPE, stdin=sp.PIPE)
    out, _ = proc.communicate(input=video_bytes)
    proc.wait()

    gif_bytes.write(out)
    gif_bytes.seek(0)

    return gif_bytes

# https://stackoverflow.com/a/13287083
def utc_to_local(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
