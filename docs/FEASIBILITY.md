# Feasibility: real Needle3 and Laya runtimes (Brief 2, Stage 0)

Stage 0 report, written before any build work. It records what was checked, how, and what
was found. Nothing in the apps or in `requirements.txt` was changed: this branch carries findings
and recommendations only. The first pass (2026-10-21) stopped at a failed network gate; the
second pass (2026-10-22), after the Hugging Face and PyTorch hosts were allowed, downloaded both
models, loaded them offline and measured them. Stage 0 is complete.

> **Update, 2026-10-22: Stages 1 to 4 were then built on this branch.** The five wiring defects
> below are fixed in the apps, the recommended corrections were applied (pins in
> `requirements.txt`, bound and API-checked probes, `predict()` instead of `route()`, real artifact
> names, REAL only when an artifact loads), and the measured results are in
> [`EVALUATION.md`](EVALUATION.md); how to build the models dir and rerun everything is in
> [`../eval/README.md`](../eval/README.md). This file is kept as the Stage 0 record; where it says
> "not applied" it describes the state before those stages.

## Date and environment

| Item | Value |
|---|---|
| Dates | 2026-10-21 (UTC): first pass, network gate failed, code read only. 2026-10-22 (UTC): second pass, gate passed, every weight-dependent number below measured |
| Machine | Intel(R) Xeon(R) Processor @ 2.80GHz, 4 vCPU (4 cores, 1 thread per core, 1 socket), AVX2, FMA, AVX-512F and AVX-512 VNNI present (`lscpu`, same on both dates) |
| Memory | 15 GiB RAM, no swap (`free -h`) |
| OS | Ubuntu 24.04.5 LTS, kernel 6.18.44-fc-v139, x86_64 |
| Disk | 28 GB free on `/` on 2026-10-21; 26 GB free on 2026-10-22 after the venv and model downloads |
| Toolchain | python3 3.13.16 (default); python3.12 3.12.3 (used by the venvs), g++ 13.3.0, clang, cmake, cargo and rustc 1.97.0 |
| Measurement venv (2026-10-22) | `/home/user/venv_models` (Python 3.12.3, pip 26.2.2): `torch==2.14.1+cpu`, `cactus-needle==3.2.8`, `laya==0.4.13`, `hnswlib==0.8.0`, `transformers==5.20.2`, `huggingface_hub==2.2.0`, `hf-xet==1.7.0`, `tokenizers==0.23.3`, `safetensors==0.8.0`, `numpy==2.5.4` (`pip freeze`) |
| Models dir (2026-10-22) | `/home/user/models/laya` (Laya English root checkpoint); Needle3 in its package cache `~/.cache/cactus-needle/v3/3.3.3/`. Both outside the repository |
| Network | Claude Code cloud session; all HTTPS goes through the session's agent proxy (policy-enforcing egress) |
| GPU | none; every statement below is about CPU-only use |

"Measured on this machine, 2026-10-22" below means the 4 vCPU Xeon above, with the venv above,
offline (`HF_HUB_OFFLINE=1`), with `NEEDLE_TELEMETRY=0` and `DO_NOT_TRACK=1` set for every
command. Model files had just been downloaded, so "cold load" means a fresh Python process with
the files likely in the OS page cache, not a cold disk.

## Verdict

**The Stage 0 network gate initially FAILED on 2026-10-21 and PASSED on 2026-10-22 after the
hosts were allowed.** On 2026-10-21 the proxy answered `CONNECT tunnel failed, response 403` for
`huggingface.co`, `hf.co`, every LFS and Xet storage host probed, and `download.pytorch.org`. On
2026-10-22 `huggingface.co`, `hf.co`, the Xet storage hosts actually used (`cas-server.xethub.hf.co`
and `us.aws.cdn.hf.co`), `download.pytorch.org` and its wheel host `download-r2.pytorch.org` all
opened (see "Hosts").

With the gate open, both runtimes work on this machine from Python, CPU only, fully offline once
staged:

- **Needle3** (`cactus-needle` 3.2.8, engine 3.3.3): 36.0 MB downloaded; weights Apache-2.0 per
  the model card; **embedding dimension 3072** (not 384 as the decks say, not 128 as the training
  code's default suggests), L2 norm 1.0000002; `embed("Patient denies headache.")` median 23.3 ms,
  p90 27.2 ms; cold load 0.40 s; peak RSS 112 MiB.
- **Laya** (`laya` 0.4.13, English root checkpoint): 846.2 MB downloaded; weights Apache-2.0 per
  the model card; one `predict()` with 1 question median 268.9 ms (p90 310.8 ms), with 4 questions
  median 531.4 ms (p90 604.1 ms) at 4 torch threads; cold load 8.4 s; peak RSS 2,866 MiB.
- An `hnswlib` inner-product index over the 12 demo dictionary names embedded by Needle3 returns
  sensible top-1 matches (sanity check only).

The gate passing does not remove the wiring defects found by reading the app code: they still
stop the real path (see "Defects found in the apps' real-path wiring"; defect 2 was re-verified
against the real loaded Laya). One measured example also shows the negation risk is real (Laya
gave P(headache reported) = 0.655 for "Patient denies headache."; one example, not an evaluation).

## Hosts

### What the allowlist must cover (in place since 2026-10-22)

Where it is set: the cloud environment's settings (environment menu in the session's title bar,
then Edit), **Network access**, **Custom** (labeled **Limited** in newer app versions), **Allowed
domains**, one per line, with **Also include default list of common package managers** kept
checked so PyPI and crates.io stay reachable. Reference:
https://code.claude.com/docs/en/cloud-environments#network-access ("A leading `*.` matches every
subdomain"). A running session may need restarting to see a changed policy.

Required for the models:

```
huggingface.co
*.huggingface.co
hf.co
*.hf.co
```

Recommended (smaller CPU-only torch; the real path works without it, using the default torch
from PyPI):

```
download.pytorch.org
download-r2.pytorch.org
```

`download-r2.pytorch.org` is needed in addition to `download.pytorch.org`: observed on
2026-10-22, every one of the 1,219 file links in `https://download.pytorch.org/whl/cpu/torch/`
points at `https://download-r2.pytorch.org/whl/cpu/...`, and that is where pip downloaded the torch
wheel from. (The same wheel path is also served directly by `download.pytorch.org`: HEAD 200 with
the same `content-length: 196253677`.)

Explicit hostnames instead of wildcards are possible but brittle; the storage hosts below arrive
in redirect headers and Hugging Face can change them. The ones observed in use on 2026-10-22 are
`huggingface.co`, `hf.co` (redirects to `huggingface.co`), `cas-server.xethub.hf.co` and
`us.aws.cdn.hf.co`.

Optional: `docs.rs` (crate documentation only; nothing at runtime needs it).

Do **not** add: the Needle telemetry endpoint `vlqqczxwyaodtcdmdmlw.supabase.co` (from
`needle/_telemetry.py`, line 19). Keep it blocked and set `NEEDLE_TELEMETRY=0` and
`DO_NOT_TRACK=1` (see the Needle3 section).

### What the download client actually contacts (observed 2026-10-22)

`huggingface_hub` 2.2.0 hard-codes only Hub hosts (`hf.co`, `huggingface.co`, the staging host
`hub-ci.huggingface.co`, the datasets server `datasets-server.huggingface.co`, and the configured
endpoint: `huggingface_hub/constants.py` lines 67 to 92); storage hosts arrive at run time in
redirect `Location` headers and Xet headers (line 334: `HUGGINGFACE_HEADER_X_XET_ENDPOINT =
"X-Xet-Cas-Url"`). On 2026-10-22 the actual redirect chain was observed with `curl -sS -I`:

| Request | Response | Next host |
|---|---|---|
| `https://hf.co/convaiinnovations/laya/resolve/main/rl_agent_config.json` | 307 | `https://huggingface.co/...` (same path) |
| `https://huggingface.co/convaiinnovations/laya/resolve/main/rl_agent_config.json` (small file) | 307 to a relative `/api/resolve-cache/models/convaiinnovations/laya/7b928d8.../rl_agent_config.json` | stays on `huggingface.co` |
| `https://huggingface.co/Cactus-Compute/needle3/resolve/main/needle3.cact` | 302, `x-linked-size: 35335380`, `x-repo-commit: d6c7d6a2e9655505e0f8e23339356dd1705900eb` | `https://us.aws.cdn.hf.co/xet-bridge-us/...` (signed URL) |
| `.../Cactus-Compute/needle3/resolve/main/python/cactus_needle-3.3.3-py3-none-manylinux2014_x86_64.whl` | 302, `x-linked-size: 689201` | `us.aws.cdn.hf.co` |
| `.../convaiinnovations/laya/resolve/main/model.safetensors` | 302, `x-linked-size: 842609210`, `x-repo-commit: 7b928d828b7b0e022f929d9bd2e44165aa270148` | `us.aws.cdn.hf.co` |
| Same `needle3.cact` URL with `Accept: application/vnd.xet-fileinfo+json` (what `hf_xet` sends) | `link:` headers name `https://huggingface.co/api/models/Cactus-Compute/needle3/xet-read-token/...` and `https://cas-server.xethub.hf.co/v1/reconstructions/<hash>` | `cas-server.xethub.hf.co` |
| `https://huggingface.co/api/models/Cactus-Compute/needle3/xet-read-token/main` | JSON `casUrl: "https://cas-server.xethub.hf.co"` | `cas-server.xethub.hf.co` |
| `https://cas-server.xethub.hf.co/v1/reconstructions/<needle3.cact hash>` (with that token) | JSON; every chunk URL in it is on `https://us.aws.cdn.hf.co` | `us.aws.cdn.hf.co` |

So the hosts actually used are `huggingface.co` (plus `hf.co` if a URL uses the short domain),
`cas-server.xethub.hf.co` and `us.aws.cdn.hf.co`. All are covered by `huggingface.co`, `hf.co` and
`*.hf.co`. None of the legacy `cdn-lfs*` hosts was used.

### Probe results, both dates (one probe per host, through the existing proxy)

Command shape: `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 20 <url>`, TLS
verification on, proxy untouched. A bare HTTP code means the proxy opened the tunnel and the
origin answered; "CONNECT 403/502" means the proxy refused the tunnel. A 403 or 404 from an origin
at `/` is normal for a storage host that serves only signed paths.

| Host (URL probed) | 2026-10-21 | 2026-10-22 | Needed for |
|---|---|---|---|
| `huggingface.co` (`/`, `/api/models/Cactus-Compute/needle3`, `/api/models/convaiinnovations/laya`) | CONNECT 403 | 200, 200, 200 | Hub, API, small files |
| `hf.co` (`/`) | CONNECT 403 | 307 to `https://huggingface.co/` | Hub short domain |
| `us.aws.cdn.hf.co` (`/`) | not probed | 200 | Xet chunk and bridge downloads (observed in use) |
| `cas-server.xethub.hf.co` (`/`) | CONNECT 403 | 404 at `/`; `/v1/reconstructions/<hash>` 200 with a token | Xet reconstruction info (observed in use) |
| `cas.xethub.hf.co` (`/`) | CONNECT 403 | 404 | named in `hf_xet`; not observed in use |
| `cas-bridge.xethub.hf.co`, `transfer.xethub.hf.co` (`/`) | CONNECT 403 | 403 from origin (tunnel opened) | not observed in use |
| `cdn-lfs.hf.co`, `cdn-lfs-us-1.hf.co` (`/`) | CONNECT 403 | 403 from origin (tunnel opened) | legacy LFS; not observed in use |
| `cdn-lfs.huggingface.co`, `cdn-lfs-us-1.huggingface.co` (`/`) | CONNECT 403 | CONNECT 502; proxy status logs `connect_rejected`, "gateway answered 502 to CONNECT (policy denial or upstream failure)" | legacy LFS; not observed in use, so this does not block anything |
| `download.pytorch.org` (`/whl/cpu/torch/`) | CONNECT 403 | 200 | CPU-only torch index |
| `download-r2.pytorch.org` (`/`; real wheel `/whl/cpu/torch-2.14.1%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl`) | CONNECT 403 | 404 at `/`; wheel HEAD 200, `content-length: 196253677` | CPU-only torch wheel files (observed in use) |
| `docs.rs` (`/`) | CONNECT 403 (`/crate/laya/latest`) | 200 | documentation only |
| `pypi.org`, `files.pythonhosted.org` | 200 | used by pip without errors | package index and files (in the session's `NO_PROXY` list) |
| `crates.io`, `static.crates.io`, `index.crates.io` | 200 | not re-probed | crate metadata (Laya Rust port only) |
| `raw.githubusercontent.com` | 200 | not re-probed | Laya ONNX export script |
| `github.com`, `api.github.com` | tunnel opens; GitHub gateway 403 "GitHub access to this repository is not enabled for this session" | not re-probed | not needed for Stage 1 |

On 2026-10-22, `curl -sS "$HTTPS_PROXY/__agentproxy/status"` listed only the two
`cdn-lfs*.huggingface.co` 502s under `recentRelayFailures`, and no failure during the model
downloads.

## Needle3 (PyPI `cactus-needle`)

Evidence: on 2026-10-21, the PyPI wheel and sdist of `cactus-needle` 3.2.8 (wheel SHA-256
`1a0f58430041574de6e823f5db47a3b9b72286da265af11817fe6e97ee9930ed`, matched PyPI) were unpacked
and read as data. On 2026-10-22 the package was installed into `/home/user/venv_models`, the engine
and weights were downloaded with the package's own CLI, and the model was loaded and run offline.
Scripts ran with `python -I` from an empty working directory.

| Question | Finding | Status |
|---|---|---|
| Python path | Official PyPI package `cactus-needle` 3.2.8 (uploaded 2026-10-19). Pure-Python wrapper that loads a **prebuilt native engine** (`libneedle3.so` inside the engine wheel, saved as `libneedle.so` on fetch) with `ctypes` and feeds it a `.cact` weights archive. No torch, no JAX at inference. | verified from code; run 2026-10-22 |
| Import name | `needle` (`top_level.txt`: `needle`; console script `needle = needle.cli:main`). | verified, imported |
| API | `agent = needle.Needle(tools=None, system=None, weights=None, ...)`; `agent.embed(text) -> list[float]`; `agent.complete(text)` / `agent.run(query)` for tool calls; `needle.extract(text, schema)` for structured extraction. | verified from code; `Needle()` and `embed()` run |
| Text embedding exposed? | Yes. `embed()` is not listed in the package's `llms.txt` "Core API", but it works: measured below. | **measured on this machine, 2026-10-22** |
| Embedding dimension | **3072**, L2 norm **1.0000002164664556** for `Needle().embed("Patient denies headache.")` (first five values 0.00533, -0.00299, -0.00582, 0.00277, -0.00603); two calls on the same string returned identical vectors; all 12 demo dictionary names also gave norms between 0.99999988 and 1.00000036. For comparison: the decks say "384-dim (SapBERT)", and the training code's default is 128 (`needle/model/architecture.py` line 51 `embedding_dim: int = 128`), which does not describe the released 20-layer model. | **measured on this machine, 2026-10-22** |
| Span extraction | `extract()` returns the schema's field values (a dict or a Pydantic instance), not character offsets. The engine also rewrites values: `llms.txt` line 113, "Arguments arrive after the engine's deterministic repair step ... a truncated phone number is completed". | verified from code and docs; not run |
| Decision or probability | Every response carries a `confidence` from a learned head (`None` for local LoRA fine-tunes, `__init__.py` lines 204 to 209). Not a per-class probability. | verified from code |
| Hugging Face files it downloads | Repo `Cactus-Compute/needle3`, commit `d6c7d6a2e9655505e0f8e23339356dd1705900eb` (Hub API, last modified 2026-10-19). `needle fetch`: engine wheel `python/cactus_needle-3.3.3-py3-none-manylinux2014_x86_64.whl` (689,201 bytes), member `needle/libneedle3.so` extracted and written as `libneedle.so`. `needle download needle3`: `needle3.cact`. Each also force-downloads `config.json` (1,273 bytes) through `_register_download`. Not needed at inference: `checkpoints/needle3.safetensors` (242,047,978 bytes, fine-tuning only). The Hub file list (131 files) has no `.onnx` file. | **verified on the Hub, 2026-10-22** |
| Files on disk after download | `~/.cache/cactus-needle/v3/3.3.3/libneedle.so` 1,590,584 bytes, SHA-256 `87476ff70e80334d7c766dbf236b72f42876072df22014c6ec8a9b087b82b260`; `~/.cache/cactus-needle/v3/3.3.3/needle3.cact` 35,335,380 bytes, SHA-256 `c9d915eca282ed42d1a09b143b592adb4cc6744ffe2d294adf5cfc5548170c38`. `fetch.py` copies rather than links, so the Hugging Face cache `~/.cache/huggingface/` holds a second copy of the weights plus the engine wheel and `config.json` (36,100,561 bytes, `du -sb`). | **measured on this machine, 2026-10-22** |
| Download size | **36.0 MB fetched** (35,335,380 + 689,201 + 1,273 bytes = 36,025,854 bytes); about 73 MB on disk because of the two caches. `needle fetch` took 1.7 s, `needle download needle3 --out ~/.cache/cactus-needle/v3/3.3.3` 3.2 s. Author statements, for comparison: wheel METADATA "A 14MB foundation tool-calling model"; README and model card "a single 8-29 MB binary"/"file"; `llms.txt` "the 35 MB `needle3.cact` weights" (this one matches). | **measured on this machine, 2026-10-22**; author-stated figures for comparison |
| CPU speed, short string | `embed("Patient denies headache.")`, 3 warm-up calls then 20 timed calls: **median 23.3 ms, p90 27.2 ms** (min 19.3, max 37.8). A second process gave median 29.4 ms, p90 34.4 ms (min 20.1, max 46.3). No author-stated CPU latency exists for Needle text inference. | **measured on this machine, 2026-10-22** |
| Cold load | Fresh process, offline: `import needle` 0.05 s, `Needle()` 0.32 s (reads the 35 MB archive, `needle_load`, `needle_init`), first `embed()` 25 ms; 0.40 s in all (second process: 0.47 s). Peak RSS 112 MiB (`resource.getrusage`). | **measured on this machine, 2026-10-22** |
| Offline load | Works. With `HF_HUB_OFFLINE=1`, `Needle()` found the engine and weights in `~/.cache/cactus-needle/v3/3.3.3/` (`needle._library_path(3)` and `needle._loaded_base` printed those paths), and the forced `config.json` download failed silently as expected. | **measured on this machine, 2026-10-22** |
| ONNX | None. No ONNX export or runtime in the package, and no `.onnx` file in the Hub repo. The deployable artifact is `needle3.cact` plus the native engine. | verified |
| CPU-only | Yes: the engine is a native CPU library (`ldd`: only `libm`, `libc`, `libpthread`, `libdl`; it imports `pthread_create` and `sched_getaffinity`, so it is multithreaded). Engine builds are published for `manylinux2014_x86_64`, `manylinux2014_aarch64`, musl, macOS and Windows. | verified from code and the binary |
| License | Package: Apache-2.0 (`dist-info/licenses/LICENSE`; METADATA `License: Apache-2.0`). **Weights and engine: Apache-2.0**: the `Cactus-Compute/needle3` model card front matter says `license: apache-2.0`, the Hub API reports `cardData.license: apache-2.0` and `gated: false`, and the repo ships a `LICENSE` file (11,358 bytes, the Apache License 2.0 text, SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`). The engine wheels live in the same repo under the same card. | **verified on the Hub, 2026-10-22** |

The embedding API, quoted from `needle/__init__.py` lines 314 to 328:

```python
    def embed(self, text: str = "") -> list[float]:
        if self._generation < 3:
            raise ValueError("embeddings require a Needle 3 model")
        self._bind()
        if self._worker is not None:
            return self._worker.embed(text)
        lib = _lib(self._generation)
        dim = lib.needle_embed(text.encode("utf-8"), None, 0, None, 0)
        if dim <= 0:
            raise RuntimeError(f"needle_embed failed (code {dim})")
        output = (ctypes.c_float * dim)()
        rc = lib.needle_embed(text.encode("utf-8"), None, 0, output, dim)
        if rc != dim:
            raise RuntimeError(f"needle_embed failed (code {rc})")
        return list(output)
```

On 2026-10-21, with the Hub denied, `needle.Needle()` raised `LocalEntryNotFoundError` from
`huggingface_hub` while trying to fetch the engine wheel. That failure is gone once the files are
staged (above).

### Offline and air-gapped path (Needle3)

Confirmed on 2026-10-22 for the default cache layout:

1. On a connected machine: `needle fetch` (engine) and `needle download needle3 --out
   ~/.cache/cactus-needle/v3/3.3.3` (weights; without `--out` the CLI writes `needle3.cact` to the
   current directory). `llms.txt` line 265: "For air-gapped devices, also see `NEEDLE3_LIB_PATH`
   ... and `HF_HUB_OFFLINE`".
2. On the target: set `NEEDLE3_LIB_PATH=<models>/libneedle.so` (read by `_library_path`,
   `__init__.py` lines 81 to 91), or leave the engine at
   `~/.cache/cactus-needle/v3/3.3.3/libneedle.so`; place `needle3.cact` at
   `~/.cache/cactus-needle/v3/3.3.3/needle3.cact` (`_base_weights_path`, lines 112 to 119).
   Passing `weights=<path>.cact` also works, but the package then treats it as a tuned model: it
   runs in a worker subprocess and reports `confidence=None` unless the archive carries a
   confidence head (lines 196 to 230). The `NEEDLE3_LIB_PATH` variant was not run.
3. Always set `HF_HUB_OFFLINE=1`: every base load calls `_register_download`, which
   force-downloads `config.json` from the Hub even with a warm cache (`fetch.py` lines 204 to 211
   and 257 to 262). Offline mode makes that call fail fast; the package swallows the error
   (observed: no warning, load succeeded).
4. Always set `NEEDLE_TELEMETRY=0` and `DO_NOT_TRACK=1`. `needle/_telemetry.py` posts usage
   events to `https://vlqqczxwyaodtcdmdmlw.supabase.co/functions/v1/telemetry` unless one of
   them (or `CI`) is set (lines 17 to 37). The README's Deploy section says "By default,
   telemetry is turned on in the binary" for the per-platform `needle` executables. Checked on
   2026-10-22 for the ctypes-loaded engine `libneedle.so` 3.3.3: `strings` finds no URL, no
   `supabase` and no `telemetry` string, and `nm -D --undefined-only` shows no `socket`,
   `connect`, `getaddrinfo`, `send`, `recv`, curl or SSL symbol, so telemetry in this setup comes
   only from the Python side, which the two variables switch off.

### Needle3 risks

- The engine is an unsigned prebuilt native library downloaded at run time and loaded with
  `ctypes`; `fetch.py` checks no hash. The SHA-256s measured on 2026-10-22 are recorded above;
  check them when staging and load only the staged file.
- Telemetry is on by default in the Python package (verified from code); the engine library has
  no network code (above).
- **Dimension: 3072, measured.** The decks and the `meddra_app.py` header describe "a 384-dim UNIT
  vector (SapBERT)". Needle3 is not SapBERT, the package makes no biomedical claim, and the
  vector has 3072 float32 values (12,288 bytes per term before index overhead). The app's real
  branch sizes the index from `V.shape[1]`, so the dimension will not crash it, but the header and
  decks are wrong. The vector is unit-norm, so `hnswlib` `space="ip"` equals cosine similarity.
- **Scores are compressed.** In the smoke test below, unrelated terms score 0.93 to 0.94 against a
  query whose correct match scores 0.96. Ranking was right on both queries, but any fixed
  similarity threshold from the decks will not transfer; thresholds must be fitted on Needle3
  scores in Stage 1.
- PHI spans: `extract()` returns values, not offsets, and may repair them, so `phi_app.py`'s
  planned "SAME 4-tuple shape" needs an offset-recovery step that accepts only values found
  verbatim in the field and rejects repaired ones.
- Fast release cadence: 37 PyPI releases since 2026-08-10. Pin the package version (3.2.8) and
  the engine version (3.3.3) together.
- Name collision: an unrelated PyPI project named `needle` (0.5.0, "Automated testing for your
  CSS.") installs the same import name `needle`, so the apps' probe `_have("needle")` would
  return True for it.

## Laya (PyPI `laya`)

Evidence: on 2026-10-21, `laya-0.4.13-py3-none-any.whl` and the sdist from PyPI (wheel SHA-256
`0ce3a444821b62ae9a452f922156e08d99b6c6d625e3fa590e84177eb3e980a8`, matched PyPI) were unpacked
and read as data; the PyPI README is the wheel's `laya-0.4.13.dist-info/METADATA` (line numbers
below refer to it). On 2026-10-22 the package was installed with CPU torch, the English root
checkpoint was downloaded, and it was loaded and run offline.

| Question | Finding | Status |
|---|---|---|
| Python path | Official PyPI package `laya` 0.4.13 by Convai Innovations (uploaded 2026-10-21; 51 releases since 2026-09-18). PyTorch plus `transformers` runtime; requires `torch>=2.0.0`, `transformers>=4.48.0`, `safetensors>=0.4.0`, `huggingface_hub>=0.20.0`, `numpy>=1.20.0`. With `torch==2.14.1+cpu` installed first, pip kept the CPU torch and resolved `transformers` 5.20.2. | verified; run 2026-10-22 |
| Import name | `laya` (`top_level.txt`: `laya`). | verified, imported |
| API | `agent = laya.load(model_dir, device="cpu")`, then `agent.predict(state, questions)` (alias of `system_one`, `agent.py` line 1982); or `laya.Router(models={"english": model_dir}).predict(state, questions, model="english")`. Questions are a dict of `{qid: {"type": "noul" or "choice" or "score", "instructions": ..., "criteria": ...}}` (METADATA lines 588 to 612). `Router.route()` only picks a checkpoint and returns a `RouteDecision`. | verified from code; `load`, `predict`, `Router.predict` and `route` run 2026-10-22 |
| Returned structure | Measured: `agent.predict("Patient denies headache.", {"headache": {"type": "noul", "instructions": "Does the patient report a headache?"}})` returned `{"model": "laya-rl-agent", "answers": {"headache": {"type": "noul", "noul": 0.6553, "confidence": 0.6553, "answer_confidence": 0.6553, "action": {"act_probability": 1.0}}}, "usage": {"input_tokens": 37, "output_tokens": 0, "state_tokens": 4, "state_tokens_dropped": 0, "truncated": false, "truncated_questions": []}}`. A `choice` answer adds `choice` and `probabilities` per label; a `score` answer adds `score` (expected level), `legend` and `probabilities` per level. | **measured on this machine, 2026-10-22** |
| Embedding or spans | Not an embedder and not a span extractor; it answers typed questions over a whole state. | verified from code |
| Hugging Face repos and files | `router.py` lines 50 to 63: `BUNDLE_REPO = "convaiinnovations/laya"`, English at the repo root, `multilingual/` and `typed-decisions/` as subfolders. Files per checkpoint (`agent.py` lines 595 to 597, the `allow_patterns` Laya itself uses): `rl_agent_config.json`, `model.safetensors`, `tokenizer/*`, `encoder/*`. Hub main is commit `7b928d828b7b0e022f929d9bd2e44165aa270148` (last modified 2026-10-03); the reviewed pin in `laya/revisions.py` is `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`. The four root files have identical `x-linked-etag` values at both commits, so the download used the reviewed pin. The repo has no `.onnx` file and no `LICENSE` file. | **verified on the Hub, 2026-10-22** |
| Files on disk after download | `/home/user/models/laya/`, from `snapshot_download("convaiinnovations/laya", revision="55cf4c4...", local_dir=..., allow_patterns=["rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*"])` (subfolders not downloaded): `model.safetensors` 842,609,210 bytes (SHA-256 `891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c`, equal to the Hub's `x-linked-etag`), `tokenizer/tokenizer.json` 3,583,228, `encoder/config.json` 2,083, `rl_agent_config.json` 745, `tokenizer/tokenizer_config.json` 308 bytes (unchanged by loading). | **measured on this machine, 2026-10-22** |
| Download size | **846.2 MB** (846,195,574 bytes in five files; 846,202,382 bytes with the `local_dir` metadata, `du -sb`), fetched in 9.5 s. Author-stated, for comparison: third-party crate README "~847 MB" for the root checkpoint; Laya README "~2.3 GB" for all three checkpoints (not downloaded). | **measured on this machine, 2026-10-22**; author-stated figures for comparison |
| CPU speed, short string | State "Patient denies headache.", `torch.get_num_threads()` = 4 (interop 4), 3 warm-ups then 20 timed `predict()` calls: **1 question median 268.9 ms, p90 310.8 ms** (min 231.8, max 329.0); **4 questions** (2 `noul`, 1 four-way `choice`, 1 four-level `score`) **median 531.4 ms, p90 604.1 ms** (min 472.4, max 627.2), about 133 ms per question. Authors' table, for comparison (README lines 410 to 416, 4 questions on a short email, 28 threads on a 56-core Intel Mac Pro): `laya` 453 ms. | **measured on this machine, 2026-10-22**; author-stated for comparison |
| Cold load and memory | Fresh process, offline: `import torch, laya` 1.47 s, `laya.load(dir, device="cpu")` 6.68 s, first `predict()` 0.27 s; 8.43 s in all. Peak RSS 2,866 MiB (`resource.getrusage`, unchanged after the 4-question runs). Load warns: "laya: this checkpoint ships invalid temperatures or values outside [0.5, 5]; using choice:11+=0.10058280825614929 -> 0.5. Treat confidence from the affected entries as uncalibrated." | **measured on this machine, 2026-10-22** |
| Offline and air-gap | Works. With `HF_HUB_OFFLINE=1`, `laya.load("/home/user/models/laya", device="cpu")` and `laya.Router(models={"english": "/home/user/models/laya"})` loaded and answered without network (`agent.py` calls `snapshot_download` only when the path does not exist). No telemetry found in the package. | **measured on this machine, 2026-10-22** |
| ONNX | Runtime yes: `laya.load(dir, backend="onnx", onnx_path=...)`, extra `laya[onnx]`. Export no: the exporter is `scripts/export_onnx.py` in the GitHub repo, not in the PyPI package, and the Hub repo has no `.onnx` file. The ONNX path still needs the checkpoint directory and still imports torch. Not run. | verified from code and the Hub file list |
| CPU-only | Yes. README line 362: "Device selection is automatic, in this order: CUDA, MPS, XPU, CPU"; "CPU and MPS run fp32"; `device="cpu"` forces it. Run on CPU above. | measured |
| License | Package: Apache-2.0 (`dist-info/licenses/LICENSE`). **Weights: Apache-2.0**: the `convaiinnovations/laya` model card front matter says `license: apache-2.0` (its tags include `commercial-use`), and the Hub API reports `cardData.license: apache-2.0` and `gated: false`. The repo has no separate `LICENSE` file, so the card is the only license statement for the weights. | **verified on the Hub, 2026-10-22** |

### crates.io `laya` is a different project

`https://crates.io/api/v1/crates/laya`: "Rust inference for the Laya non-autoregressive
typed-decision model (ModernBERT-large + RL decision head)", repository
`https://github.com/aovestdipaperino/laya-rust`, Apache-2.0, owner `aovestdipaperino`, versions
0.1.1 (2026-09-20, current) and 0.1.0 (yanked). It is an independent third-party
[candle](https://github.com/huggingface/candle) port that reads the same checkpoint files, has no
Python binding, and downloads no weights itself. Its README says "Weights are f16 on disk and are
upcast when loaded, so peak memory is around 2.4 GB"; the Python package measured 2,866 MiB peak
RSS above. The `.crate` (0.1.1, 178,498 bytes) matched the index checksum; it was not built.

### Laya risks

- **Over-confident as shipped.** README line 1638: "Both checkpoints are over-confident as
  shipped." Refitting one temperature per (question type, option count) bucket moves mean ECE
  0.466 to 0.081 (`laya`) and 0.314 to 0.106 (`laya-multilingual`) on the authors' data. The
  English checkpoint also warns at load that one shipped temperature is invalid (above).
- **Near chance zero-shot.** README line 1652: "The base checkpoints are near chance on
  typed-decisions zero-shot", 0.362 and 0.352 accuracy against "a 0.318 random baseline and a
  0.461 majority-class baseline". The 0.766 figure is from a checkpoint fine-tuned on that
  benchmark's own training split. The authors' summary is that Laya is a fast base to specialize
  by fine-tuning, not a zero-shot decision engine.
- **Negation, now seen on this machine.** README lines 1660 to 1664 report the English checkpoint
  picking the cancel option for all four negated cancellation requests. Measured on 2026-10-22,
  one example: "Does the patient report a headache?" on "Patient denies headache." gave
  `noul` 0.6553, that is, more likely yes than no for a denied symptom (in the same call, "Is a
  symptom explicitly denied or negated?" gave 0.7989). One example is not an evaluation, but
  `meddra_app.py` Tier 3 exists to separate "X" from "patient denies X", so Stage 2 must test
  negation on a labeled set before any Laya output drives a decision.
- **Routing.** Re-measured on 2026-10-22 with the real router and the local checkpoint:
  `Router(models={"english": dir}).route("Patient denies headache.", ...)` returns
  `RouteDecision(model='multilingual', reason='Latin script, language not identified and no
  non-English letters; using default (multilingual)')`, the checkpoint with no fitted
  temperatures. Pin `model="english"` or load one local checkpoint with `laya.load`.
- **`Router(preload=True)`**, as the apps call it, loads all three checkpoints. One checkpoint
  measured 2,866 MiB peak RSS here; three (about 2.3 GB of files by the authors' figure) would use
  a large share of a 15 GiB machine with no swap.
- **Speed.** 269 ms for one question and 531 ms for four on this 4 vCPU machine. That is fine for
  an interactive single-record demo but adds up over a batch: about 9 minutes for 1,000 records
  at 4 questions each, at the measured median.
- **INT8 ONNX is not accuracy-safe.** The exporter's own docstring says INT8 "trades real accuracy
  ... do not use it where the calibrated probability or confidence matters".
- Release cadence: 51 releases in five weeks. Pin the package (0.4.13) and the checkpoint
  revision (`55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`, identical root files to main today).

**Consequence:** until per-bucket temperatures are refit on held-out labeled data that looks
like the apps' inputs, and the model is fine-tuned or at least evaluated on the apps' questions
(negation included), no Laya probability in these apps should carry an `[RM]` tag as if it meant
something. Until then it is an uncalibrated score.

## hnswlib smoke test with the real Needle3 dimension (sanity check only)

This is only a check that the pieces connect (Needle3 embeddings into an `hnswlib` index); it is
not an evaluation of retrieval quality. Measured on this machine, 2026-10-22, offline: the 12
`llt_name` values in `sample_data/meddra_demo.csv` embedded with `Needle().embed()` (shape
12 x 3072, float32, norms 0.99999988 to 1.00000036), `hnswlib.Index(space="ip", dim=3072)`,
`init_index(max_elements=12, M=32, ef_construction=200)`, `set_ef(64)`, `knn_query(k=3)`. Scores
are inner products (`1 - distance`). For both queries the index's top 3 equalled an exact
brute-force inner-product ranking.

| Query | Top 3 (score) |
|---|---|
| "headache" | Headache (0.9593), Nausea (0.9292), Lightheadedness (0.9286) |
| "severe throbbing pain in back of head" | Pain in back of head (0.9601), Throbbing pain in head (0.9418), Watery diarrhoea (0.9365) |

The top-1 match is right for both queries; the narrow score range (an unrelated term at 0.9365) is
the compression noted under "Needle3 risks".

## requirements.txt pip names

Checked against the PyPI JSON API (`https://pypi.org/pypi/<name>/json`) and by installing (2026-10-21
in throwaway venvs; 2026-10-22 into `/home/user/venv_models`).

| pip name in requirements.txt | Exists on PyPI? | Correct project? | Import name | Correct in the apps? | Fix needed? |
|---|---|---|---|---|---|
| `cactus-needle` | Yes, 3.2.8 (wheel 130,098 bytes, Apache-2.0, requires only `huggingface_hub`) | Yes: Cactus Compute's Needle (repo `Cactus-Compute/needle3`). Not `cactus-compute` 2.2.2 (proprietary), `cactus` (a static site generator) or `needle` (CSS testing) | `needle` | `meddra_app.py`, `phi_app.py`: `"needle"` (right name, but cannot tell it from the unrelated `needle` package). `anomaly_app.py`: `"cactus-needle"`, which can never import | Pip name: no. Pin `==3.2.8`. Probes: yes (see below) |
| `laya` | Yes, 0.4.13 (wheel 439,568 bytes, Apache-2.0) | Yes: Convai Innovations' Laya (Hugging Face `convaiinnovations/laya`). The crates.io crate of the same name is a different project | `laya` | Probe name yes (`"laya"` in all three apps); the call sites are broken, see "Defects" | Pip name: no. Pin `==0.4.13`; it also pulls torch and transformers (see CPU torch below) |
| `hnswlib` | Yes, 0.8.0, sdist only (36,206 bytes) | Yes (`github.com/yurymalkov/hnsw`) | `hnswlib` | Yes | No. Needs a C++ compiler (built from sdist with g++ 13.3.0: 1 min 16 s alone on 2026-10-21). Works with the real 3072-dim Needle3 vectors (smoke test above) |
| `xgboost` | Yes, 3.4.1 (Apache-2.0, `requires_python >=3.12`, requires `numpy` and `scipy`; Linux x86_64 wheel 57,615,456 bytes, plus `nvidia-nccl-cu13` on Linux, unpinned, today a 305.1 MB wheel) | Yes | `xgboost` | `meddra_app.py`, `phi_app.py`, `risk_app.py`: yes. `anomaly_app.py`: missing from `HAVE`, although its `_guard_artifacts` reads `HAVE.get("xgboost")`, so an `anomaly_model.json` in the models dir always hard-stops the app | Pip name: no. Optional: on CPU-only Linux use `xgboost-cpu` 3.4.1 (same import name, 5,796,137-byte wheel, no NCCL; no macOS wheel, so macOS needs plain `xgboost`). Never install both. Not part of Stage 0's model checks and not re-run on 2026-10-22 |

Not in the table but checked in passing: `POT` imports as `ot`, `scikit-learn` as `sklearn`,
`pyreadstat` as `pyreadstat`; the apps probe those names correctly.

## Defects found in the apps' real-path wiring

Found while reading the probes on 2026-10-21; defects 1 to 4 were reproduced with Streamlit's
`AppTest` and stub modules on `sys.path`, and defect 5 with the real `laya` 0.4.13 package and no
torch. On 2026-10-22 defect 2 was re-verified against the real loaded Laya checkpoint, and the
Hub file lists behind defect 4 were checked. No app file was changed at Stage 0. All five are
fixed in Stages 1 to 4, and each fix is pinned by an always-run `RW` check in `tests/qc_test.py`
(stub packages, no models needed): defect 1 by RW2, 2 by RW4, 3 by RW1 and RW11, 4 by the guard and
loader using the real artifact names (RW8, RW9), 5 by RW8.

1. **The module names are never bound.** `_have()` calls `__import__(m)` and discards the result;
   no app has an `import needle`, `import laya`, `import hnswlib` or `import xgboost`. With
   importable stubs, `meddra_app.py` stops with `NameError: name 'needle' is not defined` (at
   `_agent = needle.Needle() if REAL_T2 else None`) and `phi_app.py` with
   `NameError: name 'laya' is not defined` (at `_router = laya.Router(preload=True)`).
2. **Wrong Laya call (re-verified 2026-10-22 with the real model).** `meddra_app.py` `t3_coding`
   and `phi_app.py` `t3_phi` call `_router.route(s, SCHEMA)` and read `r.unambiguous` /
   `r.direct_pii` / `r.reident_risk`. With laya 0.4.13 and the real English checkpoint loaded
   offline, `Router(models={"english": "/home/user/models/laya"}).route("Patient denies
   headache.", CODING_SCHEMA)` (the app's own `CODING_SCHEMA`) returns
   `RouteDecision(model='multilingual', reason='...')`; `hasattr(r, "unambiguous")` is False and
   `r.unambiguous` raises `AttributeError: 'RouteDecision' object has no attribute
   'unambiguous'`. The working call,
   `router.predict(s, CODING_SCHEMA, model="english")["answers"]["unambiguous"]["noul"]`,
   returned 0.2358 with routing `{"model": "english", "reason": "explicit model='english'"}`.
3. **Banners claim REAL with no real code path.** `REAL_T4` (`meddra_app.py`, `phi_app.py`) is set
   when `xgboost` is importable, but no code loads `meddra_coder.json` or
   `phi_token_classifier.json` or calls xgboost. With an empty stub module named `xgboost`, both
   banners read "Tier 4: REAL xgboost". Likewise `phi_app.py` `REAL_T2` only changes the label:
   `t2_phi` always runs the regex stand-in. `anomaly_app.py` has no Needle or Laya call at all, so
   its broken `"cactus-needle"` probe is, by accident, what keeps its text-tier label honest.
4. **Artifact names that cannot exist.** `_guard_artifacts` in `meddra_app.py` and `phi_app.py`
   guards `needle3.onnx` and `laya.onnx`. Verified on 2026-10-22: neither Hub repo
   (`Cactus-Compute/needle3`, 131 files; `convaiinnovations/laya`, 39 files) contains any `.onnx`
   file. Needle3's artifacts are `needle3.cact` plus the engine (`libneedle.so`,
   `libneedle.dylib` or `libneedle.dll`); Laya's is a checkpoint directory, with `laya.onnx` only
   if exported by the user.
5. **The Laya probe reports REAL with torch absent.** `import laya` is torch-free (the
   torch-backed names, `load` among them, are lazy: `laya/__init__.py` `_LAZY_ATTRS`, and
   `agent.py` line 14 is `import torch`), and `transformers` is imported only inside functions.
   So `_have("laya")` returns True, and `REAL_T3` is on, with neither torch nor transformers
   installed. Measured with laya 0.4.13 and no torch: `hasattr(laya, "load")` and
   `laya.Router(preload=True)` raise `ModuleNotFoundError: No module named 'torch'`
   (`hasattr()` catches only `AttributeError`). Once the module is bound, the same probe would
   crash both apps at `laya.Router(preload=True)` instead of falling back to the stand-in.

## Recommended corrections (not applied; for the build stages)

Nothing below was applied at Stage 0. All of it was applied in Stages 1 to 4 (see the update at
the top of this file).

`requirements.txt`, real-path comment block (versions as installed and measured on 2026-10-22):

```
# Real path (CPU). Pin exact versions: both model packages release several times a week.
#   pip install "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu   # CPU-only torch first
#   pip install "cactus-needle==3.2.8" "laya==0.4.13" "hnswlib==0.8.0" "transformers==5.20.2"
#   pip install "xgboost-cpu==3.4.1; platform_system == 'Linux'" "xgboost==3.4.1; platform_system != 'Linux'"
# (xgboost-cpu and xgboost both import as "xgboost": install one, not both; 3.4.1 needs Python >= 3.12.
#  hnswlib ships no wheels and needs a C++ compiler. Never "pip install needle": that is an
#  unrelated CSS-testing package that installs the same import name as cactus-needle.)
# Weights are NOT on PyPI: stage them into the models dir (see docs/FEASIBILITY.md) and run with
#   HF_HUB_OFFLINE=1 NEEDLE_TELEMETRY=0 DO_NOT_TRACK=1 NEEDLE3_LIB_PATH=<models>/libneedle.so
# (needle fetch writes libneedle.so; libneedle.dylib on macOS, libneedle.dll on Windows)
```

Probes and real paths, per app (each file keeps its own copy, as the headers require):

- Bind the module and check its API, so the unrelated `needle` package and empty stubs fail the
  probe. Every API check must sit inside the same `try/except Exception` as the import (an
  attribute can be lazy and import more code, defect 5; `hasattr()` catches only
  `AttributeError`). For example: `_mod(m, *attrs)` does
  `try: mod = importlib.import_module(m); return mod if all(hasattr(mod, a) for a in attrs) else None`
  with `except Exception: return None`, then `needle = _mod("needle", "Needle")`. `laya` must
  expose `load` and `Router` and also needs `_have("torch")` and `_have("transformers")`.
  `hnswlib` must expose `Index`, `xgboost` must expose `Booster`.
- `anomaly_app.py`: change the probe from `"cactus-needle"` to `"needle"` and add `"xgboost"`, but
  only in the same change that wires a real text tier.
- A tier may show REAL only when its model artifact is present and loaded, not when a library is
  importable: tie `REAL_T4` to a loaded booster, `REAL_T2` (PHI) to a working `needle.extract`
  path, `REAL_T3` to a loaded and calibrated Laya checkpoint.
- Laya: replace `.route(...)` plus attribute access with
  `.predict(text, SCHEMA, model="english")["answers"][qid]["noul"]`, or `laya.load(<models>/laya,
  device="cpu", calibration=<models>/laya_calibration.json)`; drop `preload=True`.
- `_guard_artifacts`: guard `needle3.cact` (and the engine if bundled, under its per-OS name) for
  `needle`, and the checkpoint directory `laya/` (containing `rl_agent_config.json` and
  `model.safetensors`) plus the optional `laya.onnx` for `laya`, instead of `needle3.onnx` and
  `laya.onnx`. Record and check the SHA-256s listed in the Needle3 and Laya tables.
- Correct the `meddra_app.py` header and the decks: Needle3 is not SapBERT and its vectors are
  3072-dim (measured), not 384-dim.

## Laya substitute

Not needed: Laya has a workable, official Python path, now measured (CPU, offline from a local
directory). If Stage 2 shows that Laya cannot be made useful on the apps' questions even after
temperature refitting and a fine-tune (the negation example above is the first warning sign), the
closest honest substitute is a small ModernBERT-base sequence classifier with one head per
question, fine-tuned on synthetic labeled eCRF strings and calibrated with per-bucket temperature
scaling, labeled in every banner and audit row as "ModernBERT classifier (not Laya)". It would
keep the same output columns (one probability per question) and share Laya's base encoder
family. Its weights would also come from Hugging Face, which is now reachable.

## Recommendation and next steps

1. **Stage 0 is complete.** The gate passed on 2026-10-22; both models download, load offline
   and run on CPU on this machine, and every Stage 0 question (Python path, license, download size,
   CPU speed on a short string) has a measured or Hub-verified answer above. Staged files:
   `~/.cache/cactus-needle/v3/3.3.3/{libneedle.so,needle3.cact}` and `/home/user/models/laya/`;
   venv `/home/user/venv_models` (1.2 GiB). These live outside the repository and a new session
   will not have them unless the environment's setup script stages them.
2. **Stage 1 first: fix the wiring before using the models.** Apply the corrections above (bound
   modules, API-checked probes, `predict(..., model="english")` instead of `route()`, real
   artifact names with SHA-256 checks, REAL only when a model is loaded), each app separately,
   with stub-module tests added to `tests/qc_test.py` so the QC baseline grows and keeps passing
   with no model installed (baseline on this branch: 95 of 95 with the optional extras, 92 of 92
   with `requirements.txt` only, as of 2026-10-21). Fix the "384-dim (SapBERT)" header at the same
   time.
3. **Then Stage 1 proper (real Tier 2 for coding).** Needle3 embeddings (3072-dim) of the
   99-prefixed placeholder dictionary plus a generated synthetic dictionary in the thousands of
   terms, a real `hnswlib` inner-product index with `M=32`, `efConstruction=200`, `efSearch=64`,
   top-K per verbatim; measure embed and search latency per verbatim and resident index size, and
   fit any similarity threshold on Needle3's own score distribution (scores are compressed).
4. **Stage 2 (real Tier 3).** Laya `P(direct PHI)`, `P(quasi-ID)` and the coding ambiguity
   scalar via `predict(..., model="english")`, with per-bucket temperatures fitted on a synthetic
   labeled split and ECE reported before and after, and a labeled negation set (the single
   measured example above went the wrong way). Budget for about 0.5 s per record at 4 questions on
   4 vCPU. Use the labeled ModernBERT substitute only if Laya cannot be made useful.
5. **Stage 3 (Tier 4 and evaluation).** A synthetic evaluation set with known answers, the
   XGBoost re-ranker fitted on a training split and reported on a held-out split only, fixed
   seeds, results in `docs/EVALUATION.md`. Only numbers produced there may carry an `[RM]` tag.
6. **Stage 4 (decks).** Replace each illustrative `[RM]` value in Deck B with its measured value,
   in both `.md` and `.html` (and the `docs/` HTML copies if the hosted-mode change has merged).

**Time and disk for the install (measured on this machine, 2026-10-22, unless labeled).**

- CPU-only torch: `torch-2.14.1+cpu-cp312-cp312-manylinux_2_28_x86_64.whl`, **196,253,677 bytes**
  (HEAD `content-length` of the wheel pip resolved from `https://download.pytorch.org/whl/cpu`,
  served from `download-r2.pytorch.org`). `pip install --no-cache-dir torch==2.14.1 --index-url
  https://download.pytorch.org/whl/cpu` (download plus install, with its 9 dependencies) took
  **40.2 s**; installed `torch/` is 769 MiB.
- `pip install --no-cache-dir cactus-needle==3.2.8 laya==0.4.13 hnswlib==0.8.0 transformers`
  (from PyPI, including the hnswlib source build) took **100 s**; pip kept the CPU torch.
- Whole venv: **1.2 GiB** (1,129,424,926 bytes, `du -sb`).
- For comparison (from PyPI's declared sizes on 2026-10-21, not downloaded): the default Linux
  torch from PyPI pulls at least 1.80 GB of CUDA-flavored wheels (torch 554.6 MB, `nvidia-cudnn-cu13`
  553.1 MB, `triton` 248.0 MB, `nvidia-nccl-cu13` 216.0 MB, and more), useless on this machine.
- Model downloads: Needle3 36.0 MB in about 5 s; Laya English checkpoint 846.2 MB in 9.5 s
  (about 89 MB/s through the proxy).
- Disk for Stage 1: venv 1.2 GiB plus models about 0.9 GB fits a 5 GB allowance; 26 GB is free.
  A setup script that creates the venv and stages the models should take about 2.6 minutes at
  the throughput above (40 s + 100 s + about 15 s of model downloads; an estimate from the
  measured steps, not timed end to end).

## Evidence index

2026-10-21 downloads (each into its own empty scratch directory; nothing executed from them):
`cactus_needle-3.2.8` wheel and sdist, `laya-0.4.13` wheel and sdist, `hnswlib-0.8.0.tar.gz`
(hashes checked against PyPI), `laya-0.1.1.crate` (checksum
`a4664d1e957fa64cd4c52b3509787413ed237bd5b82fa55abd379ae1f07803a0`, matched the crates.io index),
and Laya's `scripts/export_onnx.py` from raw.githubusercontent.com.

2026-10-22 downloads: the CPU torch wheel and the PyPI packages listed under "Date and
environment" (installed with `--no-cache-dir`); `needle fetch` and `needle download needle3`
(Needle3 engine and weights, SHA-256s above); `snapshot_download` of the Laya English root
checkpoint at `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851` (SHA-256 above); the model cards
`Cactus-Compute/needle3/README.md` (8,103 bytes) and `convaiinnovations/laya/README.md`
(23,187 bytes), `Cactus-Compute/needle3/LICENSE`, and both repos' Hub API metadata
(`/api/models/<repo>?blobs=true`).

Files read (package-relative): `needle/__init__.py`, `needle/agent/fetch.py`, `needle/cli.py`,
`needle/_telemetry.py`, `needle/_worker.py`, `needle/model/architecture.py`,
`cactus_needle-3.2.8/README.md`, `cactus_needle-3.2.8/llms.txt`; `laya/__init__.py`,
`laya/router.py`, `laya/agent.py`, `laya/common.py`, `laya/onnx_agent.py`, `laya/revisions.py`,
`laya-0.4.13.dist-info/METADATA`; crate `Cargo.toml` and `README.md`; installed
`huggingface_hub/constants.py`, `huggingface_hub/file_download.py`.

2026-10-22 runs (all with `NEEDLE_TELEMETRY=0 DO_NOT_TRACK=1`; the model runs also with
`HF_HUB_OFFLINE=1`, via `/home/user/venv_models/bin/python -I <script>` from an empty directory):
host probes and redirect inspection with `curl`; Needle3 cold load, dimension, norm and 20-run
`embed()` timing (two processes); Laya cold load, 1-question and 4-question 20-run `predict()`
timing, peak RSS; defect 2 re-check with `Router.route` and `Router.predict`; `strings`, `nm` and
`ldd` on `libneedle.so`; the hnswlib smoke test. The pip cache created for this run was deleted;
the venv and the staged models were kept for later stages.
