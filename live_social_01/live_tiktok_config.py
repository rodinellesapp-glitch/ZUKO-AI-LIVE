"""Public broadcaster configuration only; no credentials or session files."""
import os
import re
from urllib.parse import urlsplit

DEFAULT_TIKTOK_UNIQUE_ID = ''


def tiktok_config(unique_id=None, allow_broadcaster=False):
    ident=(unique_id if unique_id is not None else os.environ.get('TIKTOK_UNIQUE_ID',DEFAULT_TIKTOK_UNIQUE_ID)).strip().removeprefix('@')
    if not re.fullmatch(r'[A-Za-z0-9_.]{1,64}',ident):
        raise ValueError('TIKTOK_UNIQUE_ID_INVALID: use somente o identificador público')
    ignore=os.environ.get('TIKTOK_IGNORE_BROADCASTER_COMMENTS','true').lower()!='false'
    return ident, ignore and not allow_broadcaster


def tiktok_room_id(unique_id=None):
    """Optional room ID declared from the broadcaster's canonical live page.

    TikTokLive accepts a room_id override, but does not verify where a manually
    supplied value came from. Require both the value and its source URL and
    validate that URL's HTTPS origin and broadcaster path.
    """
    raw=os.environ.get('TIKTOK_ROOM_ID','').strip()
    source=os.environ.get('TIKTOK_ROOM_ID_SOURCE_URL','').strip()
    if not raw and not source:return None
    if not raw or not source:
        raise ValueError('TIKTOK_ROOM_ID_CONFIG_INCOMPLETE')
    if not re.fullmatch(r'[1-9][0-9]{0,18}',raw):
        raise ValueError('TIKTOK_ROOM_ID_INVALID')
    ident=(unique_id or tiktok_config()[0]).removeprefix('@').casefold()
    try:
        parsed=urlsplit(source)
        valid=(parsed.scheme=='https' and parsed.hostname=='www.tiktok.com'
            and parsed.username is None and parsed.password is None and parsed.port is None
            and not parsed.query and not parsed.fragment
            and parsed.path.casefold()==f'/@{ident}/live')
    except ValueError:
        valid=False
    if not valid:
        raise ValueError('TIKTOK_ROOM_ID_SOURCE_INVALID')
    return int(raw)

