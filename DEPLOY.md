# Deploying

The app deploys as three free-tier pieces:

| Piece | Host | Built from |
|---|---|---|
| PostgreSQL database | Neon | `schema.sql`, loaded by `scripts/setup_db.py` from your machine |
| API (FastAPI) | Render, as a Docker web service | `Dockerfile` and `render.yaml` |
| Web app (React) | Vercel, as a static site | `web/` and `web/vercel.json` |

Do the steps in this order. Each one needs a URL from the one before, and the last step sends the web app's URL back to the API.

## Environment variables

| Variable | Set it in | Value |
|---|---|---|
| `DATABASE_URL` | Render, and your shell when loading data (step 1) | Neon connection string |
| `ALLOWED_ORIGINS` | Render | The web app's origin(s), comma-separated, with no trailing slash, e.g. `https://nutrition-engine.vercel.app` |
| `VITE_API_URL` | Vercel | The API's URL, with no trailing slash, e.g. `https://nutrition-engine-api.onrender.com` |
| `PORT` | Nothing to do | Render sets it, and the image listens on it |

Nothing secret is committed: `render.yaml` declares `DATABASE_URL` and `ALLOWED_ORIGINS` without values, and Render asks for them. `GEMINI_API_KEY` and `USDA_API_KEY` are only for the data scripts and aren't needed in deployment.

## 1. Neon (database)

1. Sign up at https://neon.tech and create a project. Pick the region closest to where you'll run the API. For Render's Ohio region, that's AWS US East 2 (Ohio).
2. In the project dashboard, click **Connect** and copy the connection string. It looks like `postgresql://USER:PASSWORD@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require`.
   - Use the **direct** connection string (without `-pooler` in the host) for loading data in this step.
   - For Render (step 2), either string works. The pooled one (`-pooler` in the host) copes better with many short-lived connections.
3. Load the schema and food data from your machine, in the repo root with the virtualenv active:

   ```bash
   DATABASE_URL='postgresql://USER:PASSWORD@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require' \
     python scripts/setup_db.py --with-all
   ```

   It should end with `Upserted 73 products. Table now has 73 rows.` (the count grows as foods are added). `--with-all` loads `food_data.csv`, the seed staples and the Trader Joe's items, then applies the USDA overrides.
   - A `DATABASE_URL` in your shell takes precedence over `.env`, so your local settings don't interfere.
   - If you leave `sslmode` out of the URL, `db.py` adds `sslmode=require` for any non-local host, which Neon needs.
4. Neon's free tier suspends the database after a few minutes idle. The first query afterwards wakes it, which takes about a second.

To update the data later (new foods, a new USDA override), rerun step 3. It's safe to rerun at any time.

## 2. Render (API)

1. Push the repo to GitHub, if it isn't there yet.
2. In the Render dashboard, choose **New → Blueprint** and connect the repository. Render reads `render.yaml` and proposes one service, `nutrition-engine-api`: a free Docker web service with health check path `/api/health`.
3. Render asks for the two variables:
   - **`DATABASE_URL`**: the Neon connection string from step 1.
   - **`ALLOWED_ORIGINS`**: you don't have the web app's URL yet, so enter `http://localhost:5173` for now. You'll replace it in step 4.
4. Click **Apply**. The first build takes a few minutes. The build fails early if HiGHS or CBC can't solve a test problem in the image.
5. When it's live, open `https://<your-service>.onrender.com/api/health`. You should see `{"status":"ok","db":true}`. If `db` is `false`, check `DATABASE_URL`. The interactive API docs are at `/docs`.

The free tier sleeps after about 15 minutes without traffic, and the next request wakes it, which can take up to a minute. While that first health check is slow, the web app shows "Waking up the server, this can take up to a minute on the free tier."

## 3. Vercel (web app)

1. In the Vercel dashboard, choose **Add New → Project** and import the same repository.
2. Set **Root Directory** to `web`. The framework is Vite; `web/vercel.json` already sets the build command (`npm run build`), the output directory (`dist`), and the fallback to `index.html`.
3. Under **Environment Variables**, add `VITE_API_URL` = `https://<your-service>.onrender.com`, with no trailing slash, for the Production environment (and Preview, if you'll use preview deployments). It's the only setting the web app needs.
4. Click **Deploy**. Note the production URL, e.g. `https://<your-project>.vercel.app`.

`VITE_API_URL` is built into the app, so if you change it later, redeploy on Vercel for it to take effect.

## 4. Connect the web app to the API

1. In Render, open the service, then **Environment**, and set `ALLOWED_ORIGINS` to the Vercel production URL from step 3, e.g. `https://<your-project>.vercel.app`. Use a comma-separated list to allow more, e.g. a custom domain. Vercel preview URLs change with each deployment, so add one only when you need it.
2. Save. Render redeploys with the new value.
3. Open the Vercel URL and check the whole loop:
   - **Plan my day:** plan a day, then **Save plan**.
   - **Saved plans:** the plan you saved should be listed.
   - **Eat out:** build an order, then find your best order.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| The browser console shows a CORS error | `ALLOWED_ORIGINS` doesn't exactly match the page's origin: scheme and host, no trailing slash, no path. |
| "The planner can't reach the server." | `VITE_API_URL` is wrong (redeploy Vercel after fixing it), or the Render service failed to start (check its logs). |
| `/api/health` says `"db": false` | `DATABASE_URL` is wrong, or SSL is off: keep `sslmode=require` for Neon. |
| The "Waking up the server…" line shows | Expected after the free tier sleeps. It clears once the API answers. |

## Testing the image locally

This is how the image was checked before deployment. It runs the image as x86-64 Linux, like Render, against the local Docker database:

```bash
docker build --platform linux/amd64 -t nutrition-engine-api .
docker run --rm -p 8080:10000 -e PORT=10000 \
  -e DATABASE_URL='postgresql://USER:PASSWORD@host.docker.internal:5433/nutrition_db?sslmode=disable' \
  -e ALLOWED_ORIGINS='http://localhost:5173' \
  nutrition-engine-api
curl localhost:8080/api/health   # {"status":"ok","db":true}
```

`host.docker.internal` is a non-local host from inside the container, so `?sslmode=disable` is needed for a database without SSL. Hosted databases keep `sslmode=require`.
