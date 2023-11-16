from gallery_dl import job

Job = job.UrlJob

class UrlJob(Job):

    def __init__(self, url, parent=None):
        Job.__init__(self, url, parent)
        self.urls = []

    def handle_url(self, url, _):
        self.urls.append(url)