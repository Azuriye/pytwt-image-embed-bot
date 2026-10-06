"""Collect gallery-dl results instead of downloading.

UrlJob normally downloads each URL. Overriding handle_url lets us
grab (url, kwdict) pairs so the bot can fetch/convert them itself.
"""
from gallery_dl import job


class CombinedJob(job.UrlJob):
    def __init__(self, url, parent=None):
        super().__init__(url, parent)
        self.urls: list[str] = []
        self.kwdicts: list[dict] = []
        
    def handle_url(self, url, kwdict):
        self.urls.append(url)
        self.kwdicts.append(kwdict.copy())
