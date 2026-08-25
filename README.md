# StreamScrapers Scrapers

Scrapers Python seguindo o protocolo [MegaSource](https://github.com/zoreu/megasource_stremio), prontos para usar com o addon **StreamScrapers** no Stremio.

## Scrapers

| Arquivo | Fonte | Protocolo |
|---|---|---|
| [`akashi_flix.py`](akashi_flix.py) | AkashiFlix (TMDB) | `TITLE`/`VERSION`/`DESCRIPTION` + `get_streams()` |
| [`superflix.py`](superflix.py) | SuperFlixAPI (TMDB) | `TITLE`/`VERSION`/`DESCRIPTION` + `get_streams()` |
| [`watchplayer.py`](watchplayer.py) | WatchPlayer | `get_streams()` (stdlib pura) |

Todos recebem `media_type` (`movie` | `series`) e `media_id` no formato MegaSource:

- Filme: `tt0111161` (IMDb) ou `603` (TMDB)
- Série: `tt0944947:1:1` ou `1396:1:1` (`{id}:{temporada}:{episodio}`)

## Como usar no StreamScrapers

No addon StreamScrapers, adicione cada scraper com a URL raw:

```
https://raw.githubusercontent.com/brunacristtina/streamscrapers-scrapers/main/akashi_flix.py
https://raw.githubusercontent.com/brunacristtina/streamscrapers-scrapers/main/superflix.py
https://raw.githubusercontent.com/brunacristtina/streamscrapers-scrapers/main/watchplayer.py
```

Ou use as URLs curtas do GitHub (o addon resolve `blob/` automaticamente):

```
https://github.com/brunacristtina/streamscrapers-scrapers/blob/main/akashi_flix.py
```

### Config via URL do manifest

```
https://streamscrapers.wasmer.app/{manifest|stream}/...?config=<base64url do JSON>
```

Onde o JSON segue o formato:

```json
{
  "scrapers": [
    {"name": "AkashiFlix", "url": "https://raw.githubusercontent.com/brunacristtina/streamscrapers-scrapers/main/akashi_flix.py"},
    {"name": "SuperFlixAPI", "url": "https://raw.githubusercontent.com/brunacristtina/streamscrapers-scrapers/main/superflix.py"},
    {"name": "WatchPlayer", "url": "https://raw.githubusercontent.com/brunacristtina/streamscrapers-scrapers/main/watchplayer.py"}
  ]
}
```

## Disclaimer

Os scrapers apenas consultam fontes públicas. Use por sua conta e risco; respeite os termos de uso de cada site.
