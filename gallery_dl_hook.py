from gallery_dl import job
from gallery_dl.exception import StopExtraction

class CombinedJob(job.UrlJob):
    def __init__(self, url, parent=None):
        super().__init__(url, parent)
        self.urls = []
        self.keyword_job = job.KeywordJob(url, parent)

    def handle_url(self, url, kwdict):
        self.urls.append(url)
        print(kwdict)
        raise StopExtraction

    def handle_directory(self, _):
        pass
