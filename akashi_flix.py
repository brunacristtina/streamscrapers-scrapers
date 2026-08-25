# -*- coding: utf-8 -*-
"""
AkashiFlix - MegaSource
================================

Protocol
--------
Seguindo o protocolo do MegaSource, este arquivo define:

    TITLE, VERSION, DESCRIPTION
    get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id   : "tt0111161" (filme) | "603" (filme por TMDB ID)
             "tt0944947:1:1" (serie: temporada: episodio) | "1396:1:1" (serie por TMDB ID)

O AkashiFlix (https://akashi-flix.up.railway.app) e um frontend TMDB:
a API /api/catalog devolve apenas IDs TMDB e o player embute os
provedores de video. A construcao das URLs de embed abaixo espelha a
funcao tn() do bundle JS do site:

    Dublado  : https://mgeb.top/embed/{tmdb_id}[/{s}/{e}]?player=vidstack
    Legendado: https://nhdapi.com/embed/movie|tv/{tmdb_id}... (requer API key)

O provedor principal (mgeb.top) expoe as fontes de video como JSON
direto na pagina (`var sources = [...]`), com MP4 e HLS validos.

Retorna streams com behaviorHints.proxyHeaders
"""
import requests
import json
import re
import logging

# Configuração de logging apenas para ERROS
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

TITLE = "AkashiFlix"
VERSION = "1.0.0"
DESCRIPTION = "Filmes e Series do AkashiFlix"

# Configurações
BASE_URL = "https://akashi-flix.up.railway.app"
MGEB_EMBED = "https://mgeb.top/embed"          # provedor dublado padrao do site
TMDB_API_KEY = "\x31\x38\x36\x35\x66\x34\x33\x61\x30\x35\x34\x39\x63\x61\x35\x30\x64\x33\x34\x31\x64\x64\x39\x61\x62\x38\x62\x32\x39\x66\x34\x39"
TMDB_BASE_URL = "https://api.themoviedb.org/3"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Headers padrão
DEFAULT_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Cache-Control': 'max-age=0',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

class AkashiFlixResolver:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update(DEFAULT_HEADERS)

    def _imdb_to_tmdb(self, imdb_id):
        """Converte IMDb ID para TMDB ID"""
        try:
            url = f"{TMDB_BASE_URL}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                return None, None

            data = response.json()

            results = data.get('movie_results', [])
            if results:
                return results[0].get('id'), 'movie'

            results = data.get('tv_results', [])
            if results:
                return results[0].get('id'), 'tv'

            return None, None
        except Exception as e:
            logging.error(f"Erro ao converter IMDb para TMDB: {e}")
            return None, None

    def _fetch_tmdb_details(self, tmdb_id, media_type):
        """Busca detalhes do TMDB"""
        try:
            url = f"{TMDB_BASE_URL}/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}&append_to_response=external_ids"

            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                return None

            data = response.json()

            return {
                'title': data.get('title' if media_type == 'movie' else 'name') or data.get('original_title' if media_type == 'movie' else 'original_name'),
                'year': (data.get('release_date' if media_type == 'movie' else 'first_air_date') or '')[:4],
                'imdb_id': data.get('external_ids', {}).get('imdb_id')
            }
        except Exception as e:
            logging.error(f"Erro ao buscar detalhes do TMDB: {e}")
            return None

    def _resolve_tmdb_id(self, media_id, media_type):
        """Resolve o media_id para TMDB ID.

        Aceita tanto IMDb (tt...) quanto ID numerico do TMDB.
        """
        media_id = str(media_id).strip()

        # ID numerico do TMDB (o AkashiFlix usa TMDB IDs direto)
        if re.fullmatch(r'\d+', media_id):
            return int(media_id), ('tv' if media_type in ('series', 'tv') else 'movie')

        # IMDb ID -> TMDB
        if media_id.lower().startswith('tt'):
            return self._imdb_to_tmdb(media_id)

        return None, None

    def _get_index_quality(self, text):
        """Extrai qualidade do texto"""
        if not text:
            return 'Unknown'

        match = re.search(r'(\d{3,4})[pP]', text)
        if match:
            return f"{match.group(1)}p"

        if '4K' in text.upper() or 'UHD' in text.upper():
            return '2160p'

        return 'Unknown'

    def _parse_quality(self, quality_label):
        """Converte label de qualidade para numero"""
        quality_map = {
            '4K': 2160,
            '2160p': 2160,
            '1440p': 1440,
            '1080p': 1080,
            '720p': 720,
            '480p': 480,
            '360p': 360,
        }

        if isinstance(quality_label, str):
            match = re.search(r'(\d{3,4})', quality_label)
            if match:
                return int(match.group(1))

        return quality_map.get(quality_label, 720)

    def _build_embed_url(self, tmdb_id, media_type, season=None, episode=None):
        """Monta a URL do embed no padrao do AkashiFlix (provedor mgeb.top).

        Espelha a funcao tn() do bundle do site:
            filme : https://mgeb.top/embed/{id}?player=vidstack
            serie : https://mgeb.top/embed/{id}/{s}/{e}?player=vidstack
        """
        if media_type == 'tv':
            s = max(1, int(season or 1))
            e = max(1, int(episode or 1))
            return f"{MGEB_EMBED}/{tmdb_id}/{s}/{e}?player=vidstack"
        return f"{MGEB_EMBED}/{tmdb_id}?player=vidstack"

    def _fetch_mgeb_sources(self, embed_url):
        """Busca a pagina do embed e extrai o JSON `var sources = [...]`.

        Retorna lista de dicts: {'file', 'type', 'label'}
        """
        try:
            response = self.session.get(embed_url, headers=DEFAULT_HEADERS, timeout=15)
            if response.status_code != 200:
                logging.error(f"Embed mgeb retornou HTTP {response.status_code}")
                return []

            html = response.text

            # O mgeb embute as fontes como JSON em `var sources = [...]`
            match = re.search(r'var\s+sources\s*=\s*(\[.*?\])\s*;', html, re.S)
            if not match:
                logging.error("JSON de sources nao encontrado no embed")
                return []

            data = json.loads(match.group(1))
            if not isinstance(data, list):
                return []

            return [s for s in data if isinstance(s, dict) and s.get('file')]
        except Exception as e:
            logging.error(f"Erro ao buscar sources do mgeb: {e}")
            return []

    def _format_title(self, details, media_type, season, episode, server_name, quality_label):
        """Formata o título com quebra de linha incluindo a qualidade"""
        title = f"🎬 {details['title']}"

        if media_type == 'tv' and season and episode:
            title += f"\n📺 S{str(season).zfill(2)}E{str(episode).zfill(2)}"

        if quality_label and quality_label != 'Unknown':
            title += f"\n📊 {quality_label}"
        else:
            title += f"\n📊 HD"

        title += f"\n📥 {server_name}"

        return title

    def resolve(self, media_id, media_type='movie', season=None, episode=None):
        """Resolve streams para filme ou série via AkashiFlix"""
        try:
            # Resolve o media_id (IMDb ou TMDB numerico) para TMDB ID
            tmdb_id, resolved_type = self._resolve_tmdb_id(media_id, media_type)
            if not tmdb_id:
                logging.error(f"TMDB ID não encontrado para {media_id}")
                return []

            media_type = resolved_type or media_type

            # Busca detalhes do TMDB
            details = self._fetch_tmdb_details(tmdb_id, media_type)
            if not details:
                logging.error("Detalhes do TMDB não encontrados")
                return []

            # Monta o embed no padrao do AkashiFlix
            embed_url = self._build_embed_url(tmdb_id, media_type, season, episode)

            # Extrai as fontes de video do embed
            sources = self._fetch_mgeb_sources(embed_url)
            if not sources:
                logging.error("Nenhuma fonte encontrada no embed")
                return []

            final_results = []

            for i, source in enumerate(sources, start=1):
                stream_url = source.get('file', '')
                stream_type = source.get('type', '')
                label = source.get('label', '')

                if not stream_url:
                    continue

                # Inferencia de qualidade a partir da URL
                quality = self._get_index_quality(stream_url)
                if quality == 'Unknown':
                    quality = 'HD' if stream_type == 'hls' else '720p'

                server_name = f"AkashiFlix Fonte {i}"
                title = self._format_title(
                    details, media_type, season, episode,
                    server_name, quality
                )

                final_results.append({
                    'title': title,
                    'stream': stream_url,
                    'quality': self._parse_quality(quality),
                    'quality_label': quality,
                    'size': '',
                    'User-Agent': USER_AGENT,
                    'Referer': embed_url,
                    'Origin': MGEB_EMBED.rsplit('/embed', 1)[0],
                })

            # Remove duplicatas
            seen_urls = set()
            unique_streams = []
            for stream in final_results:
                url = stream.get('stream', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_streams.append(stream)

            # Ordena por qualidade (HLS adaptativo primeiro)
            quality_order = {'HD': 7, '4K': 6, '2160p': 5, '1440p': 4, '1080p': 3, '720p': 2, '480p': 1, '360p': 0}
            unique_streams.sort(key=lambda x: quality_order.get(x.get('quality_label', '720p'), 0), reverse=True)

            return unique_streams

        except Exception as e:
            logging.error(f"Erro ao resolver: {e}")
            return []


def get_streams(media_type, media_id, config=None):
    """
    Função principal do scraper - chamada pelo MegaSource
    """
    # Parse do media_id
    imdb_id = media_id
    season = episode = None

    if ":" in media_id:
        parts = media_id.split(":", 2)
        imdb_id = parts[0]
        if len(parts) > 1:
            season = int(parts[1])
        if len(parts) > 2:
            episode = int(parts[2])

    resolver = AkashiFlixResolver()

    # Busca streams conforme o tipo
    if media_type == "movie":
        streams_data = resolver.resolve(imdb_id, 'movie', None, None)
    elif media_type == "series" and season and episode:
        streams_data = resolver.resolve(imdb_id, 'tv', season, episode)
    else:
        return []

    if not streams_data:
        return []

    # Formata para o padrão do MegaSource
    result = []
    for stream in streams_data:
        url = stream.get('stream', '')
        if not url:
            continue

        title = stream.get('title', TITLE)

        result.append({
            "name": TITLE,
            "title": title,
            "url": url,
            "behaviorHints": {
                "notMyMetadata": True,
                "proxyHeaders": {
                    "request": {
                        "User-Agent": stream.get('User-Agent', USER_AGENT),
                        "Origin": stream.get('Origin', "https://mgeb.top"),
                        "Referer": stream.get('Referer', "https://mgeb.top/"),
                    }
                },
            },
        })

    return result
