# -*- coding: utf-8 -*-
"""
WatchPlayer (v1.watchplay.shop) - scraper MegaSource para Stremio.

Fluxo (tudo publico, sem login):
  Filme: GET /movie/{id}  ->  player_select_item[data-id]  ->  API getPlayer  ->  HLS
  Serie: GET /tvshow/{id} (fallback /anime/{id})
         ->  episodeOption[data-contentid]  ->  API getOptions  ->  API getPlayer  ->  HLS

O m3u8 exige header Referer (sem ele: 403), por isso cada stream entrega
proxyHeaders.request com User-Agent + Origin + Referer.

Convencoes MegaSource:
  media_type: "movie" | "series"
  media_id (filme):  "tt1234567" ou numero TMDB
  media_id (serie):  "tt0944947:1:3"  ({id}:{temporada}:{episodio})

Apenas stdlib (urllib.request, json, re) - compatível com o sandbox do MegaSource.
"""

import json
import re
import urllib.parse
import urllib.request

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")

FALLBACK_DOMAIN = "https://v1.watchplay.shop"
API_URL = FALLBACK_DOMAIN + "/api"
TIMEOUT = 15

STREAM_PATTERN = re.compile(r"\.m3u8|\.mp4|/hls/", re.I)


def _request(url, data=None, timeout=TIMEOUT):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Origin"] = FALLBACK_DOMAIN
        headers["Referer"] = FALLBACK_DOMAIN + "/"
    req = urllib.request.Request(
        url, data=data, headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def _api(action, **params):
    body = urllib.parse.urlencode({"action": action}, doseq=True)
    for key, value in params.items():
        body += "&" + urllib.parse.urlencode({key: value})
    raw = _request(API_URL, data=body.encode("utf-8"))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _get_player(video_id):
    """Chama getPlayer e devolve a URL HLS/MP4 ou None."""
    res = _api("getPlayer", video_id=video_id)
    if not res:
        return None
    data = res.get("data") or {}
    url = data.get("video_url") or data.get("url")
    if not url or not STREAM_PATTERN.search(url):
        return None
    return url


def _get_options(contentid):
    res = _api("getOptions", contentid=contentid)
    if not res:
        return []
    return (res.get("data") or {}).get("options") or []


def _label_for_type(typ, index):
    if typ == 1:
        return "Dublado"
    if typ == 2:
        return "Legendado"
    return "Opcao %d" % (index + 1)


def _movie_candidates(html):
    """[(video_id, tipo)] a partir da pagina do filme.

    O site renderiza grupos `players_select_items` (com data-target 1=Dublado,
    2=Legendado quando ha varias opcoes de audio) e um bloco `select_languages`
    com <b> quando ha um unico tipo. Ambos os formatos sao suportados.
    """
    candidates = []
    default_type = None
    m = re.search(r'<div class="select_languages">(.*?)</div>', html, re.S)
    if m:
        text = m.group(1)
        if "Dublado" in text:
            default_type = 1
        elif "Legendado" in text:
            default_type = 2

    segments = re.split(r'<div class="players_select_items', html)
    for seg in segments[1:]:
        gt = seg.find(">")
        attrs = seg[:gt] if gt != -1 else ""
        mt = re.search(r'data-target="(\d+)"', attrs)
        group_type = int(mt.group(1)) if mt else default_type
        body = seg[gt + 1:] if gt != -1 else seg
        for vid in re.finditer(r'player_select_item"\s+data-id="(\d+)"', body):
            candidates.append((int(vid.group(1)), group_type))
    if not candidates:
        for vid in re.finditer(r'player_select_item"\s+data-id="(\d+)"', html):
            candidates.append((int(vid.group(1)), default_type))
    return candidates


def _episode_match(html, season, episode):
    """contentid do episodio pedido; sem temporada/episodio, usa o primeiro."""
    first = None
    for m in re.finditer(
        r'episodeOption[^>]*data-contentid="(\d+)"[^>]*data-season="(\d+)"'
        r'[^>]*data-episode="(\d+)"',
        html,
    ):
        cid, s, e = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if first is None:
            first = (cid, s, e)
        if s == season and e == episode:
            return (cid, s, e)
    if season is None or episode is None:
        return first
    return None


def _build_stream(url, title):
    return {
        "title": title,
        "url": url,
        "behaviorHints": {"notMyMetadata": True},
        "proxyHeaders": {
            "request": {
                "User-Agent": USER_AGENT,
                "Origin": FALLBACK_DOMAIN,
                "Referer": FALLBACK_DOMAIN + "/",
            }
        },
    }


def get_streams(media_type, media_id, config=None):
    config = config or {}
    media_id = urllib.parse.unquote(media_id or "")
    parts = [p.strip() for p in media_id.split(":")]
    if not parts or not parts[0]:
        return []

    item_id = parts[0]
    if item_id.lower().startswith("tmdb:"):
        item_id = item_id[5:]
    if item_id.endswith("."):
        item_id = item_id[:-1]

    try:
        season = int(parts[1]) if len(parts) > 1 else None
        episode = int(parts[2]) if len(parts) > 2 else None
    except ValueError:
        season, episode = None, None
    if config.get("season") is not None:
        season = int(config["season"])
    if config.get("episode") is not None:
        episode = int(config["episode"])

    streams = []
    seen = set()

    if media_type == "movie":
        html = _request("%s/movie/%s" % (FALLBACK_DOMAIN, item_id))
        if not html:
            return []
        for index, (video_id, typ) in enumerate(_movie_candidates(html)):
            url = _get_player(video_id)
            if not url or url in seen:
                continue
            seen.add(url)
            streams.append(_build_stream(
                url, "WatchPlayer • %s" % _label_for_type(typ, index),
            ))
        return streams

    # series e animes usam o mesmo fluxo
    html = None
    for path in ("tvshow", "anime"):
        html = _request("%s/%s/%s" % (FALLBACK_DOMAIN, path, item_id))
        if html and "episodeOption" in html:
            break
    if not html or "episodeOption" not in html:
        return []

    match = _episode_match(html, season, episode)
    if not match:
        return []
    contentid, s, e = match

    for index, option in enumerate(_get_options(contentid)):
        video_id = option.get("ID")
        typ = int(option.get("type") or 0)
        if not video_id:
            continue
        url = _get_player(video_id)
        if not url or url in seen:
            continue
        seen.add(url)
        streams.append(_build_stream(
            url,
            "WatchPlayer • S%de%d • %s" % (s, e, _label_for_type(typ, index)),
        ))
    return streams
