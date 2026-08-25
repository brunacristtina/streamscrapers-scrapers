# -*- coding: utf-8 -*-
"""
SuperFlixAPI - MegaSource
================================

Protocolo
---------
Seguindo o protocolo do MegaSource, este arquivo define:

    TITLE, VERSION, DESCRIPTION
    get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]
    search(query: str, limit: int = 20) -> list[dict]   (helper opcional)

media_type : "movie" | "series"
media_id   : "tt0111161" (filme por IMDb) | "603" (filme por TMDB ID)
             "tt0944947:1:1" (serie: temporada: episodio) | "1396:1:1" (serie por TMDB ID)

Fonte: SuperFlixAPI (https://superflixapi.sbs), frontend TMDB que serve
embeds de filmes, series, animes e doramas (parceiro de video: visioncine.lat).

Padroes de URL do player (validados em browser):
    Filme : https://superflixapi.sbs/filme/{imdb_id_ou_tmdb_id}
    Serie : https://superflixapi.sbs/serie/{imdb_id_ou_tmdb_id}/{temporada}/{episodio}

O player aceita tanto o ID do IMDb (tt...) quanto o ID numerico do TMDB,
sem necessidade de conversao externa. Exemplos testados:
    /filme/tt0111161            -> "Player | Um Sonho de Liberdade"
    /filme/238                  -> "Player | O Poderoso Chefao"
    /serie/1396/1/1             -> "Player | Breaking Bad" (TMDB)
    /serie/tt0903747/1/1        -> "Player | Breaking Bad" (IMDb)

NOTA sobre o Turnstile (Cloudflare):
------------------------------------
O player exige a verificacao do Cloudflare Turnstile em "managed mode"
(1 clique no checkbox), que vale ~45 minutos (cookie __sf_turnstile_pass,
header x-cloudflare-captcha-ttl-minutes: 45). Requisicoes HTTP diretas
(curl/requests) SEM o cookie recebem a pagina "Verificacao" (HTTP 200),
por isso este scraper NAO tenta resolver o video no servidor: ele devolve
a URL do player como stream do tipo web/embed, que o MegaSource abre em
webview. Dentro do webview o usuario final passa o Turnstile com 1 clique
(a cada ~45 min) e o player carrega normalmente.

Dica: quando o player e carregado dentro de um iframe (como o webview do
MegaSource faz), ele carrega direto o player real, sem a pagina "gate"
(que so aparece em navegacao top-level apos o captcha).

Busca: o endpoint publico /pesquisar?q=... e servido SEM captcha e devolve
o HTML com os cards de resultados (titulo, ano, tipo, TMDB/IMDb ID e link
do player), parseado pela funcao search() abaixo.

Retorna streams com behaviorHints.proxyHeaders (mesmo padrao do original)
"""
import requests
import json
import re
import logging
from urllib.parse import quote

# Configuração de logging apenas para ERROS
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

TITLE = "SuperFlixAPI"
VERSION = "1.0.0"
DESCRIPTION = "Filmes e Séries do SuperFlixAPI"

# Configurações
BASE_URL = "https://superflixapi.sbs"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Headers padrão
DEFAULT_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Cache-Control': 'max-age=0',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# Mapeia o tipo devolvido pelo MegaSource para a categoria do site
TYPE_MAP = {
    'movie': 'filme',
    'series': 'serie',
    'tv': 'serie',
}


class SuperFlixAPIResolver:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        # suprime o aviso de SSL (o site usa proxy/CDN com certificado valido,
        # mas verify=False evita quebra em redes que interceptam TLS)
        try:
            requests.packages.urllib3.disable_warnings(
                requests.packages.urllib3.exceptions.InsecureRequestWarning
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Construção da URL do player
    # ------------------------------------------------------------------
    def _build_player_url(self, media_id, media_type, season=None, episode=None):
        """Monta a URL do player no padrao do SuperFlixAPI.

        O player aceita IMDb ID (tt...) ou TMDB ID numerico, entao o
        media_id e usado como veio do Stremio:
            filme : {BASE}/filme/{id}
            serie : {BASE}/serie/{id}/{s}/{e}
        """
        if media_type == 'serie':
            s = max(1, int(season or 1))
            e = max(1, int(episode or 1))
            return f"{BASE_URL}/serie/{media_id}/{s}/{e}"
        return f"{BASE_URL}/filme/{media_id}"

    # ------------------------------------------------------------------
    # Formatação do título exibido no MegaSource
    # ------------------------------------------------------------------
    def _format_title(self, title, media_type, season, episode, server_name):
        """Formata o título com quebra de linha no padrao do original"""
        if title and title.strip().lower() != 'superflixapi':
            label = f"🎬 {title}"
        else:
            label = f"🎬 {server_name}"

        if media_type == 'serie' and season and episode:
            label += f"\n📺 S{str(season).zfill(2)}E{str(episode).zfill(2)}"

        label += f"\n📊 HD"

        if title and title.strip().lower() != server_name.lower():
            label += f"\n📥 {server_name}"

        return label

    # ------------------------------------------------------------------
    # Resolução de streams
    # ------------------------------------------------------------------
    def resolve(self, media_id, media_type='movie', season=None, episode=None):
        """Resolve o stream para filme ou serie via SuperFlixAPI.

        Retorna uma lista com 1 stream (a URL do player). Nao faz nenhuma
        requisicao ao site: a URL e montada direto, e o player (com o
        Turnstile managed de 1 clique) roda no webview do MegaSource.
        """
        try:
            media_type = TYPE_MAP.get(media_type, media_type)
            if media_type not in ('filme', 'serie'):
                return []

            if media_type == 'serie' and not (season and episode):
                return []

            player_url = self._build_player_url(media_id, media_type, season, episode)

            # Titulo generico — o nome real e resolvido pelo proprio player.
            # Para series exibimos a temporada/episodio, que e o que importa
            # na hora de escolher o stream.
            display_title = self._format_title(
                "", media_type, season, episode, "SuperFlixAPI"
            )

            return [{
                'title': display_title,
                'stream': player_url,
                'quality': 720,
                'quality_label': 'HD',
                'size': '',
                'User-Agent': USER_AGENT,
                'Referer': f"{BASE_URL}/",
                'Origin': BASE_URL,
            }]
        except Exception as e:
            logging.error(f"Erro ao resolver: {e}")
            return []

    # ------------------------------------------------------------------
    # Busca pública (sem captcha)
    # ------------------------------------------------------------------
    def search(self, query, limit=20):
        """Busca conteudos no SuperFlixAPI via /pesquisar?q=... (publico).

        Retorna lista de dicts:
            {title, year, type ('movie'|'series'), tmdb_id, imdb_id, player_url}
        """
        try:
            url = f"{BASE_URL}/pesquisar?q={quote(query)}"
            response = self.session.get(url, headers=DEFAULT_HEADERS, timeout=15)
            if response.status_code != 200:
                logging.error(f"Busca retornou HTTP {response.status_code}")
                return []

            html = response.text

            # Cada card de resultado comeca com este container
            cards = html.split('class="group/card relative w-full"')[1:]
            results = []

            for card in cards:
                if len(results) >= limit:
                    break

                # Tipo pelo link do player: /filme/ ou /serie/
                link_match = re.search(
                    r'href="https://superflixapi\.sbs/(filme|serie)/[^"]+"', card
                )
                if not link_match:
                    continue
                content_type = 'movie' if link_match.group(1) == 'filme' else 'series'

                # Titulo pelo alt da imagem do card
                title_match = re.search(r'alt="([^"]+)"', card)
                if not title_match:
                    continue
                title = title_match.group(1).strip()

                # Ano
                year_match = re.search(r'<span>(\d{4})</span>', card)
                year = year_match.group(1) if year_match else ''

                # TMDB ID (data-copy="12345" data-msg="TMDB ID copiado!")
                tmdb_match = re.search(r'data-copy="(\d+)" data-msg="TMDB ID copiado!"', card)
                tmdb_id = tmdb_match.group(1) if tmdb_match else ''

                # IMDb ID
                imdb_match = re.search(r'data-copy="(tt\d+)"', card)
                imdb_id = imdb_match.group(1) if imdb_match else ''

                # Link do player com ID numerico (mais estavel que o slug)
                player_url = ""
                copy_link = re.search(
                    r'data-copy="https://superflixapi\.sbs/(filme|serie)/[^"]*"', card
                )
                if copy_link:
                    player_url = copy_link.group(0)[len('data-copy="'):-1]

                if not player_url and link_match:
                    player_url = f"{BASE_URL}/{link_match.group(1)}/{title.lower().replace(' ', '-')}"

                results.append({
                    'title': title,
                    'year': year,
                    'type': content_type,
                    'tmdb_id': tmdb_id,
                    'imdb_id': imdb_id,
                    'player_url': player_url,
                })

            return results
        except Exception as e:
            logging.error(f"Erro na busca: {e}")
            return []


def get_streams(media_type, media_id, config=None):
    """
    Função principal do scraper - chamada pelo MegaSource
    """
    # Parse do media_id
    content_id = media_id
    season = episode = None

    if ":" in media_id:
        parts = media_id.split(":", 2)
        content_id = parts[0]
        if len(parts) > 1:
            season = int(parts[1])
        if len(parts) > 2:
            episode = int(parts[2])

    resolver = SuperFlixAPIResolver()

    # Busca streams conforme o tipo
    if media_type == "movie":
        streams_data = resolver.resolve(content_id, 'movie', None, None)
    elif media_type == "series" and season and episode:
        streams_data = resolver.resolve(content_id, 'series', season, episode)
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
                        "Origin": stream.get('Origin', BASE_URL),
                        "Referer": stream.get('Referer', f"{BASE_URL}/"),
                    }
                },
            },
        })

    return result


def search(query, limit=20):
    """
    Helper opcional: busca publica no SuperFlixAPI (sem captcha).
    Retorna metadados (titulo, ano, tipo, TMDB/IMDb ID, player_url).
    """
    resolver = SuperFlixAPIResolver()
    return resolver.search(query, limit=limit)


if __name__ == "__main__":
    import sys

    print(f"=== {TITLE} v{VERSION} ===\n")

    # Exemplo: filme por IMDb
    movie_imdb = get_streams("movie", "tt0111161")
    print("Filme (IMDb tt0111161):")
    print(json.dumps(movie_imdb, ensure_ascii=False, indent=2))

    # Exemplo: filme por TMDB
    movie_tmdb = get_streams("movie", "603")
    print("\nFilme (TMDB 603):")
    print(json.dumps(movie_tmdb, ensure_ascii=False, indent=2))

    # Exemplo: serie por TMDB
    series_tmdb = get_streams("series", "1396:1:1")
    print("\nSerie (TMDB 1396:1:1):")
    print(json.dumps(series_tmdb, ensure_ascii=False, indent=2))

    # Exemplo: serie por IMDb
    series_imdb = get_streams("series", "tt0903747:1:1")
    print("\nSerie (IMDb tt0903747:1:1):")
    print(json.dumps(series_imdb, ensure_ascii=False, indent=2))

    # Busca publica (opcional)
    if len(sys.argv) > 1:
        print(f"\nBusca por \"{sys.argv[1]}\":")
        found = search(sys.argv[1])
        for item in found[:5]:
            print(f"  - [{item['type']}] {item['title']} ({item['year']}) "
                  f"tmdb={item['tmdb_id']} imdb={item['imdb_id']}")
