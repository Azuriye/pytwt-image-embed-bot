import logging

# 1) Grab the specific downloader logger
http_logger = logging.getLogger("gallery_dl.downloader.http")

# 2) Define a handler that raises on WARNING or above
class RaiseOnWarningHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            raise RuntimeError(record.getMessage())

# 3) Replace existing handlers with ours
http_logger.handlers.clear()
http_logger.addHandler(RaiseOnWarningHandler())

import asyncio
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

    def run(self):
        status = super().run()
        if status != 0:
            # bit 0x4 indicates HTTP/download failure
            raise RuntimeError(f"gallery-dl extraction failed (status=0x{status:x})")
        return status

# Try up to 4 times to build and run CombinedJob; return the job on success or None on permanent failure
async def extract_with_retry(tweet_url: str, delay: float = 1.0):
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            j = CombinedJob(tweet_url)
            j.run()
            return j
        except RuntimeError as e:
            if attempt < max_attempts:
                logging.info(
                    f"[Attempt {attempt}] Extraction failed for {tweet_url!r}: {e}. "
                    "Retrying in %.1fs…" % delay)
                await asyncio.sleep(delay)
            else:
                logging.error(f"[{attempt}/{max_attempts}] Permanent failure extracting {tweet_url!r}: {e}.")
                return None