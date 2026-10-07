# IPTV English North America

This repository publishes an automatically updated English-language IPTV M3U playlist for IBO Player and other M3U-compatible IPTV players.

The playlist is generated from IPTV-org public data:

- Source playlist: https://iptv-org.github.io/iptv/languages/eng.m3u
- Channel metadata: https://iptv-org.github.io/api/channels.json

Only publicly available legal streams already present in IPTV-org public data are used. The generator does not add pirated, private, unauthorized, hacked, fabricated, or substituted streams. NSFW/adult channels are excluded.

## Playlist URL

Use this exact URL in IBO Player:

```text
https://raw.githubusercontent.com/se7enfigureinc/iptv-english-north-america/main/iptv.m3u
```

## How It Works

`generate_playlist.py` downloads the current IPTV-org English M3U playlist and IPTV-org channel metadata each time it runs. It parses the playlist, preserves IPTV metadata such as `tvg-id`, `tvg-name`, `tvg-logo`, `group-title`, and stream URL, removes duplicate stream URLs, excludes NSFW/adult entries, and writes a fresh `iptv.m3u`.

Channels are organized into useful region and category groups, prioritizing Canada, the United States, the United Kingdom, the Caribbean, North America, Colombia, the Americas, and then other international English-language channels. Channels with incomplete region or category metadata are retained under `International English / Other English` rather than being unnecessarily excluded.

## Automatic Updates

The GitHub Actions workflow in `.github/workflows/build-playlist.yml` runs on a schedule and can also be started manually from the Actions tab. The workflow:

1. Checks out the repository.
2. Sets up Python.
3. Runs `generate_playlist.py`.
4. Validates the generated M3U file.
5. Commits and pushes `iptv.m3u` to `main` only when the generated playlist changes.

If IPTV-org cannot be downloaded or the playlist is invalid, the workflow fails clearly instead of publishing a broken playlist.

## Using It In IBO Player

1. Open IBO Player.
2. Choose the option to add an M3U playlist or playlist URL.
3. Paste:

```text
https://raw.githubusercontent.com/se7enfigureinc/iptv-english-north-america/main/iptv.m3u
```

4. Save or refresh the playlist.

Some streams may be geographically restricted, temporarily offline, removed upstream, or unavailable in your region. If IPTV-org identifies a channel as geo-blocked in the source playlist, the generated playlist keeps that designation in the channel name.

## Legal Notice

This project does not host video streams and does not create or authorize any channel streams. It only republishes a filtered M3U playlist generated from IPTV-org's public English-language data. Stream availability and legality are determined by the upstream public IPTV-org dataset.
