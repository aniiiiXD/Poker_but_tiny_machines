# Model bot starter

`agent.py` and `weights.json` show how to load an inference artifact from the submitted project. This tiny example is a hand-set linear scoring model; replace it with your own code and weights. `Agent.act(observation)` must return a legal poker action.

The current local model track supports Python 3.12, the standard library, NumPy 2.1.3 and files in the project. Network, GPUs and other third-party ML libraries are unavailable. The project has a 16 MiB compressed and uncompressed limit, 100-file cap, 512 MB sandbox memory and a 50 ms practice decision budget. Training happens outside the arena. Do not load files from an untrusted project on your own computer.

To use GitHub, put these files at the repository root, connect the repository and branch with track `model`, and push a commit. Alternatively, ZIP the files at the archive root and submit the archive to `POST /api/models/submissions?name=MyModel` using an authenticated, verified account with a team. Poll the returned job ID at `/api/jobs/{id}`. See `plans/GITHUB_MODEL_BACKEND.md` for API setup.
