# Anamorph

Local-first Anamorph portfolio with a Vercel-ready CMS.

## Deploy to Vercel

1. Push this repo to GitHub.
2. Import the repo in Vercel.
3. Add environment variables:
   - `CMS_USER`
   - `CMS_PASSWORD`
   - `BLOB_READ_WRITE_TOKEN` from a Vercel Blob store
4. Deploy.

The static Framer-style home page is served from `index.html`. CMS routes are handled by `api/app.js`:

- `/work`
- `/work/:slug`
- `/login`
- `/admin`
- `/api/projects`

Without `BLOB_READ_WRITE_TOKEN`, the deployed CMS can read the seeded `data/cms.json` but cannot persist uploads or edits.
