import gettext
import http.client
import json

from osdlyrics.lyricsource import BaseLyricSourcePlugin, SearchResult
from osdlyrics.utils import get_proxy_settings, http_download

_ = gettext.gettext

NETEASE_HOST = 'music.163.com'
NETEASE_SEARCH_URL = '/api/search/get'
NETEASE_LYRIC_URL = '/api/song/lyric'

gettext.bindtextdomain('osdlyrics')
gettext.textdomain('osdlyrics')

import logging

class NeteaseTranslatedSource(BaseLyricSourcePlugin):
    """ Lyric source from music.163.com
    """

    def __init__(self, attempt_use_translation=True):
        if not attempt_use_translation:
            super().__init__(id='netease', name=_('Netease'))
        else:
            super().__init__(id='netease_tr', name=_('Netease (TR)'))
        self.attempt_use_translation = attempt_use_translation

    def do_search(self, metadata):
        # type: (osdlyrics.metadata.Metadata) -> List[SearchResult]
        keys = []
        if metadata.title:
            keys.append(metadata.title)
        if metadata.artist:
            keys.append(metadata.artist)
        url = NETEASE_HOST + NETEASE_SEARCH_URL
        urlkey = '+'.join(keys).replace(' ', '+')
        params = 's=%s&type=1' % urlkey

        status, content = http_download(url=url,
                                        method='POST',
                                        params=params.encode('utf-8'),
                                        proxy=get_proxy_settings(self.config_proxy))

        if status < 200 or status >= 400:
            raise http.client.HTTPException(status, '')

        def map_func(song):
            if song['artists']:
                artist_name = song['artists'][0]['name']
            else:
                artist_name = ''
            url = NETEASE_HOST + NETEASE_LYRIC_URL + '?id=' + str(song['id']) + '&lv=-1&kv=-1&tv=-1'
            return SearchResult(title=song['name'],
                                artist=artist_name,
                                album=song['album']['name'],
                                sourceid=self.id,
                                downloadinfo=url)

        parsed = json.loads(content.decode('utf-8'))
        result = list(map(map_func, parsed['result']['songs']))

        # If there are more than 10 songs we do a second request.
        song_count = parsed['result']['songCount']
        if song_count > 10:
            params = params + '&offset=10'
            status, content = http_download(url=url,
                                            method='POST',
                                            params=params.encode('utf-8'),
                                            proxy=get_proxy_settings(self.config_proxy))
        if status < 200 or status >= 400:
            raise http.client.HTTPException(status, '')
        parsed = json.loads(content.decode('utf-8'))
        result = result + list(map(map_func, parsed['result']['songs']))


        try:
            title_lower = (metadata.title or '').strip().lower()
            exact_matches = [r for r in result if (r._title or '').strip().lower() == title_lower]
            others = [r for r in result if (r._title or '').strip().lower() != title_lower]
            result = exact_matches + others
        except Exception as e:
            logging.warning("CAP Sorting search result failed: %s", str(e))

        
        return result

    def do_download(self, downloadinfo):
        # type: (Any) -> bytes
        status, content = http_download(url=downloadinfo,
                                        proxy=get_proxy_settings(self.config_proxy))
        if status < 200 or status >= 400:
            raise http.client.HTTPException(status)

        parsed = json.loads(content.decode('utf-8'))
        # Avoid processing results with no lyrics.
        if 'nolyric' in parsed or 'uncollected' in parsed:
            raise ValueError('This item has no lyrics.')

        if self.attempt_use_translation:
            lyric = parsed['tlyric']['lyric']
            if not lyric:
                lyric = parsed['lrc']['lyric']
        else:
            lyric = parsed['lrc']['lyric']

        return lyric.encode('utf-8')


if __name__ == '__main__':
    netease = NeteaseTranslatedSource()
    netease._app.run()
