from gallery_dl import job

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
def human_format(num):
    num = float('{:.3g}'.format(num))
    magnitude = 0
    while abs(num) >= 1000:
        magnitude += 1
        num /= 1000.0
    return '{}{}'.format('{:f}'.format(num).rstrip('0').rstrip('.'), ['', 'K', 'M', 'B', 'T'][magnitude])