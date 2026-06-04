# reality2u — Coolify deployment

## Možnost A: Static site (nejjednodušší)

V Coolify zvolte **Static / Static deployment**:
1. Upload obsahu složky [`site/`](site/) (nebo `reality2u-site.zip` rozbalený)
2. Coolify naservíruje přes vlastní reverse proxy

## Možnost B: Docker image (doporučeno, dává cache + gzip + clean URLs)

V Coolify zvolte **Dockerfile**:
1. Source: Git nebo upload této složky `deploy/`
2. Build context: `.` (Dockerfile staví z `site/`)
3. Port: `80`

Lokální test:
```bash
cd deploy
docker build -t reality2u .
docker run -p 8080:80 reality2u
# otevřít http://localhost:8080
```

## Domény

Po nasazení v Coolify nastavit:
- **reality2u.djai.cz** (až přepnete DNS) — server IP vašeho Coolify
- Coolify zařídí HTTPS přes Let's Encrypt automaticky

DNS změna na Cloudflare: změnit existující CNAME/A záznam `reality2u.djai.cz` aby ukazoval na IP serveru Coolify.

## Co je obsaženo

```
deploy/
├── Dockerfile          ← nginx:alpine + statické soubory
├── nginx.conf          ← gzip, cache, security headers, clean URLs
├── site/               ← všechny HTML, CSS, JPG fotky týmu, atd.
└── README.md
```
