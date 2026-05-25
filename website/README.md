# Mosquito Finder — Official Website

This directory contains the static website for the Mosquito Finder iOS app.

## Pages

| File | URL | Purpose |
|------|-----|---------|
| `index.html` | `/` | Landing page |
| `privacy.html` | `/privacy.html` | Privacy Policy ← **App Store Connect 必须填此 URL** |
| `support.html` | `/support.html` | Support & FAQ ← App Store Connect Support URL |
| `404.html` | auto | Custom 404 page |
| `css/style.css` | — | Shared styles |

## Before Publishing

1. **Replace your email** — search for `your-email@example.com` in all HTML files and replace with your real address.
2. **App Store button** — once the App Store URL is available, update `href` on the `.hero-cta` link in `index.html`.

## Publishing to GitHub Pages (one-time setup)

### Option A — Dedicated repo (recommended)

```bash
# 1. Create a new public GitHub repo named: mosquito-finder-site
# 2. Push this website/ folder as the repo root:

cd /Users/nsaviour/Project/AppleProject/Mosquito-finder/website
git init
git add .
git commit -m "Initial website"
git remote add origin https://github.com/YOUR_USERNAME/mosquito-finder-site.git
git branch -M main
git push -u origin main

# 3. In GitHub repo Settings → Pages:
#    Source: Deploy from branch → main → / (root)
#    Save → site will be live at:
#    https://YOUR_USERNAME.github.io/mosquito-finder-site/
```

Your URLs for App Store Connect:
- **Privacy Policy URL**: `https://YOUR_USERNAME.github.io/mosquito-finder-site/privacy.html`
- **Support URL**: `https://YOUR_USERNAME.github.io/mosquito-finder-site/support.html`

### Option B — Subfolder of existing repo

Push the contents of this `website/` folder into a `docs/` folder of any existing public repo, then in Settings → Pages set Source to `docs/` folder.

## Updating Later

```bash
cd /Users/nsaviour/Project/AppleProject/Mosquito-finder/website
# ... edit files ...
git add . && git commit -m "Update" && git push
```

GitHub Pages redeploys automatically within ~60 seconds.
