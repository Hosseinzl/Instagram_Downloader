# Instagram Tor Pool Project (minimal)

This folder contains a small project that uses a Tor pool and Playwright to fetch Instagram posts.

Files added:
- `requirements.txt` — Python dependencies
- `.gitignore` — ignores common files and the `tor_instances` folder
- `Dockerfile` — container image using Playwright's Python image
- `docker-compose.yml` — simple compose file to build and run the app

Notes and quick start

1) Local (without Docker)
- Install dependencies into your chosen interpreter:

```powershell
py -3 -m pip install -r requirements.txt
# then install playwright browsers
py -3 -m playwright install --with-deps
```

2) Using Docker (recommended when you want an isolated environment with browsers preinstalled)

Build and run with docker-compose:

```powershell
docker compose build
docker compose up
```

The image is based on the official Playwright Python image which already includes browsers and most browser dependencies. The container will run `main.py` by default.

3) Tor instances

- This repo assumes you will run Tor instances separately (see `launch_tor_instances.py` examples previously provided). The `tor_instances/` directory is mounted into the container by the `docker-compose.yml` so you can store per-instance `DataDirectory` and control cookies there.
- If you want to run Tor inside the container, you'll need to install `tor` in the image and adjust the Dockerfile. Running Tor on the host and mounting the `tor_instances` directory is simpler.

4) Important

- The project uses `stem` for Tor control port signaling. Ensure `tor` is installed and the control ports are accessible from where the code runs.
- If `playwright_stealth` import fails, the PyPI package name is `playwright-stealth`. The code imports `playwright_stealth` (which is the Python module name), so `pip install playwright-stealth` should satisfy it.

If you want, I can:
- Add a `launch_tor_instances.py` file into the repo (I provided a standalone script earlier) and wire it to the compose file.
- Add a small `entrypoint.sh` wrapper to wait for Tor instances before starting the Python app.

Tell me which of the above you'd like next.