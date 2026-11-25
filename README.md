# Dexter desk dashboard

Static research dashboard: daily brief archive, desk status, watchlist snapshots.
No frameworks, no build step — plain HTML/CSS/JSON served by nginx.

## Local (Docker, private LAN)

    docker run -d --name dexter-dashboard --restart unless-stopped \
      -p 8080:80 \
      -v "$PWD":/usr/share/nginx/html:ro \
      nginx:alpine

Then open http://<host-ip>:8080

## Publishing a daily brief

1. Add `briefs/NNN-name.html` (template: copy any existing brief).
2. Prepend a new entry to `briefs/index.json` (newest first).
3. Refresh the page — bind mount means nothing to rebuild.

## GitHub Pages (public mirror, optional)

    gh auth login          # once, interactive
    git remote add origin git@github.com:<user>/dexter-desk.git
    git push -u origin main
    # then: repo Settings -> Pages -> Deploy from branch -> main / root

## Hard rule

This repo publishes to the public internet. It must contain ONLY the
dashboard and published briefs — never holdings, journals, transactions,
or any file under `investment-research/` outside `dashboard/`.
