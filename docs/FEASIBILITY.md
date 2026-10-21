# Feasibility: real Needle3 and Laya runtimes (Brief 2, Stage 0)

Stage 0 report, written before any build work. It records what was checked, how, and what
was found. Nothing in the apps or in `requirements.txt` was changed: the network gate failed,
so this branch carries findings and recommendations only.

## Date and environment

| Item | Value |
|---|---|
| Date | 2026-10-21 (UTC) |
| Machine | Intel(R) Xeon(R) Processor @ 2.80GHz, 4 vCPU (4 cores, 1 thread per core, 1 socket), AVX2, FMA, AVX-512F and AVX-512 VNNI present (`lscpu`) |
| Memory | 15 GiB RAM, no swap (`free -h`) |
| OS | Ubuntu 24.04.5 LTS, kernel 6.18.44-fc-v139, x86_64 |
| Disk | 28 GB free on `/` |
| Toolchain | python3 3.13.16 (default); python3.12 3.12.3 (used by the venvs), g++ 13.3.0, clang, cmake, cargo and rustc 1.97.0 |
| Network | Claude Code cloud session; all HTTPS goes through the session's agent proxy (policy-enforcing egress) |
| GPU | none; every statement below is about CPU-only use |

## Verdict

**The Stage 0 network gate FAILED.** Every Hugging Face host the real path needs is denied by
the environment's network policy: the proxy answers `CONNECT tunnel failed, response 403` for
`huggingface.co`, `hf.co` and all of the LFS and Xet storage hosts, and its status endpoint logs
each one as `connect_rejected` with the detail "gateway answered 403 to CONNECT (policy denial
or upstream failure)". Policy denial is an inference, not something the proxy states: the same
403 comes back for every Hugging Face and PyTorch host, while PyPI, crates.io and
raw.githubusercontent.com open through the same proxy. Both model packages install from PyPI (which
is reachable), but neither can run without files that live only on Hugging Face: Needle3 needs
its native engine library and its `needle3.cact` weights from `Cactus-Compute/needle3`, and Laya
needs its checkpoint (`model.safetensors`, tokenizer, encoder config) from
`convaiinnovations/laya`. This blocks every measurement that needs the weights (download size,
CPU speed on a short string, embedding dimension, any accuracy or calibration number) and all of
Stages 1 to 4. `download.pytorch.org` is also denied; that blocks only the smaller CPU-only
torch wheel, not the real path, because PyPI serves a default torch that installs and runs on
CPU (see "Time and disk for the torch install"). Separately from the network, reading the app code turned up
wiring defects that would stop the real path even after the hosts are allowed (see
"Defects found in the apps' real-path wiring").

## Hosts to add under Allowed domains

Where to change it: open the cloud environment's settings (environment menu in the session's
title bar, then Edit), go to **Network access**, choose **Custom** (labeled **Limited** in newer
app versions), and add the hosts below under **Allowed domains**, one per line. Keep **Also
include default list of common package managers** checked so PyPI and crates.io stay reachable.
Reference: https://code.claude.com/docs/en/cloud-environments#network-access (that page states
"A leading `*.` matches every subdomain"). If a running session still sees the old policy, start
a new session in the same environment.

Required (paste as is):

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
```

The wheel file host behind the PyTorch index could not be observed, because the index itself is
denied. `download-r2.pytorch.org` was probed and is also denied (403), but whether the index
links there is unknown. After allowing `download.pytorch.org`, re-probe a real CPU wheel URL from
`/whl/cpu/torch/` and add whatever host it redirects to.

If you prefer explicit hostnames to wildcards, these are the ones the wildcards above must
cover (all probed, all denied today): `cdn-lfs.huggingface.co`, `cdn-lfs-us-1.huggingface.co`,
`cdn-lfs.hf.co`, `cdn-lfs-us-1.hf.co`, `cas-bridge.xethub.hf.co`, `cas-server.xethub.hf.co`,
`cas.xethub.hf.co`, `transfer.xethub.hf.co`. Explicit names are brittle: Hugging Face picks the
storage host at download time (see below), so the wildcards are the safer choice.

Optional: `docs.rs` (crate documentation only; nothing at runtime needs it).

Do **not** add: the Needle telemetry endpoint `vlqqczxwyaodtcdmdmlw.supabase.co` (from
`needle/_telemetry.py`, line 19). Keep it blocked and set `NEEDLE_TELEMETRY=0` and
`DO_NOT_TRACK=1` (see the Needle3 section).

### Why these hosts: what the download client actually contacts

`huggingface_hub` 2.2.0 (installed into a throwaway venv and read) hard-codes only Hub hosts
(`hf.co`, `huggingface.co`, the staging host `hub-ci.huggingface.co`, the datasets server
`datasets-server.huggingface.co`, and the configured endpoint); the storage hosts arrive at run
time in redirect `Location` headers and Xet headers:

- `huggingface_hub/constants.py` line 67: `_HF_DEFAULT_ENDPOINT = "https://huggingface.co"`;
  line 68: `_HF_DEFAULT_STAGING_ENDPOINT = "https://hub-ci.huggingface.co"`;
  line 70: `HUGGINGFACE_CO_URL_TEMPLATE = ENDPOINT + "/{repo_id}/resolve/{revision}/{filename}"`.
- Lines 76 to 90: `HF_URL_HOSTS` is `hf.co`, `huggingface.co`, the staging host
  `hub-ci.huggingface.co` and the configured endpoint's host, described as the hosts used "to
  decide which redirects to follow when resolving files". Line 92:
  `DATASETS_SERVER_ENDPOINT = "https://datasets-server.huggingface.co"`. All of these are covered
  by `hf.co`, `huggingface.co` and `*.huggingface.co`, so the list above does not change.
- Line 334: `HUGGINGFACE_HEADER_X_XET_ENDPOINT = "X-Xet-Cas-Url"`: the Xet storage server is
  named by the Hub in a response header, not in the client.
- The `hf_xet` 1.7.0 native extension (`hf_xet/hf_xet.abi3.so`) embeds the string
  `cas.xethub.hf.co`.

So the Hub (`huggingface.co`) plus whatever `*.hf.co` / `*.huggingface.co` storage host it
redirects to must all be reachable. The exact redirect targets could not be observed because
the first hop is already denied.

### Probe results (2026-10-21, one probe per host, through the existing proxy)

Command shape: `curl -sS -o /dev/null -w '%{http_code}' --max-time 20 <url>`, with a
User-Agent for crates.io. TLS verification on, proxy untouched. `pypi.org`,
`files.pythonhosted.org` and `index.crates.io` are in the session's `NO_PROXY` list, so tools
reach them without the proxy; forced through the proxy (`-x "$HTTPS_PROXY" --noproxy ''`) they
also open (`pypi.org` 200, `files.pythonhosted.org` tunnel opened).

| Host (URL probed) | Result | Needed for |
|---|---|---|
| `huggingface.co` (`/`, `/api/models/Cactus-Compute/needle3`, `/api/models/convaiinnovations/laya`) | DENIED: `CONNECT tunnel failed, response 403` | Needle3 engine and weights; Laya checkpoints |
| `hf.co` | DENIED (403) | Hub short domain, redirects |
| `cdn-lfs.huggingface.co`, `cdn-lfs-us-1.huggingface.co` | DENIED (403) | LFS file storage |
| `cdn-lfs.hf.co`, `cdn-lfs-us-1.hf.co` | DENIED (403) | LFS file storage |
| `cas-bridge.xethub.hf.co`, `cas-server.xethub.hf.co`, `cas.xethub.hf.co`, `transfer.xethub.hf.co` | DENIED (403) | Xet file storage |
| `download.pytorch.org` (`/whl/cpu/torch/`) | DENIED (403) | CPU-only torch wheels (recommended, not required) |
| `download-r2.pytorch.org` (`/`, probed during the fact-check) | DENIED (403) | possibly the PyTorch wheel file host (unverified) |
| `docs.rs` (`/crate/laya/latest`) | DENIED (403) | documentation only |
| `pypi.org` (`/simple/cactus-needle/`) | 200 | package index |
| `files.pythonhosted.org` (real `cactus_needle-3.2.8` wheel URL) | 200, 130,098 bytes | package files |
| `crates.io` (`/api/v1/crates/laya`) | 200 | crate metadata |
| `static.crates.io` (`/crates/laya/laya-0.1.0.crate`, `laya-0.1.1.crate`) | 200 | crate download |
| `index.crates.io` (`/config.json`, `/la/ya/laya`) | 200 | sparse index |
| `raw.githubusercontent.com` (Laya `scripts/export_onnx.py`) | 200 | Laya ONNX export script (not in the PyPI package) |
| `github.com`, `api.github.com` (`/repos/NandhaKishorM/laya`, `/repos/cactus-compute/needle`) | tunnel opens; GitHub gateway answers 403 "GitHub access to this repository is not enabled for this session" | not needed for Stage 1; GitHub uses its own session proxy, not the allowlist |

`curl -sS "$HTTPS_PROXY/__agentproxy/status"` lists `connect_rejected` ("gateway answered 403 to
CONNECT (policy denial or upstream failure)") for exactly the denied hosts above:
`huggingface.co`, `hf.co`, `cdn-lfs.huggingface.co`, `cdn-lfs-us-1.huggingface.co`,
`cdn-lfs.hf.co`, `cdn-lfs-us-1.hf.co`, `cas-bridge.xethub.hf.co`, `cas-server.xethub.hf.co`,
`cas.xethub.hf.co`, `transfer.xethub.hf.co`, `docs.rs`, `download.pytorch.org` (and
`download-r2.pytorch.org` after the fact-check probe). None of the
Hugging Face or PyTorch hosts are in the environment's default Trusted list (checked against the
"Default allowed domains" section of the page cited above).

## Needle3 (PyPI `cactus-needle`)

Evidence: `cactus_needle-3.2.8-py3-none-any.whl` and `cactus_needle-3.2.8.tar.gz`, fetched from
PyPI into an empty directory (SHA-256 matched the PyPI JSON: wheel
`1a0f58430041574de6e823f5db47a3b9b72286da265af11817fe6e97ee9930ed`), unpacked and read as data.
The wheel's `needle/` tree is identical to the sdist's. Imports were run only with `python -I`
from another directory, with `HF_HUB_OFFLINE=1`, `NEEDLE_TELEMETRY=0`, `DO_NOT_TRACK=1`.

| Question | Finding | Status |
|---|---|---|
| Python path | Official PyPI package `cactus-needle` 3.2.8 (uploaded 2026-10-19; 3.0.0 was uploaded 2026-09-17). Pure-Python wrapper that loads a **prebuilt native engine** (`libneedle3.so` inside the engine wheel, saved as `libneedle.so` on fetch) with `ctypes` and feeds it a `.cact` weights archive. No torch, no JAX at inference. | verified from code |
| Import name | `needle` (`top_level.txt`: `needle`; console script `needle = needle.cli:main`). | verified, imported |
| API | `agent = needle.Needle(tools=None, system=None, weights=None, ...)`; `agent.embed(text) -> list[float]`; `agent.complete(text)` / `agent.run(query)` for tool calls; `needle.extract(text, schema)` for structured extraction. | verified from code |
| Text embedding exposed? | Yes, in code (see quote below). It is not listed in the package's own API reference (`llms.txt` "Core API"), only claimed in the README ("the same model returns a vector for a sentence"). | verified from code, not run |
| Embedding dimension | Not stated anywhere in the package. The engine reports it at run time (`needle_embed(text, None, 0, None, 0)` returns the size). The training code's default is **128**, not 384: `needle/model/architecture.py` line 51 `embedding_dim: int = 128`. The embedding head L2-normalizes its output (`EmbeddingHead.__call__`, `return p / denom...`). | not measured |
| Span extraction | `extract()` returns the schema's field values (a dict or a Pydantic instance), not character offsets. The engine also rewrites values: `llms.txt` line 113, "Arguments arrive after the engine's deterministic repair step ... a truncated phone number is completed". | verified from code and docs |
| Decision or probability | Every response carries a `confidence` from a learned head (`None` for local LoRA fine-tunes, `__init__.py` lines 204 to 209). Not a per-class probability. | verified from code |
| Hugging Face files it downloads | Repo `Cactus-Compute/needle3` (`needle/agent/fetch.py` lines 9 to 24): weights `needle3.cact`; engine wheel `python/cactus_needle-3.3.3-py3-none-manylinux2014_x86_64.whl` (engine version 3.3.3), from which the member `needle/libneedle3.so` is extracted and written as `libneedle.so` (`fetch.py` line 321: `out = os.path.join(dest_dir, lib)`, with `lib = lib_name(generation, tag)` at line 315, which returns `libneedle.so`, `libneedle.dylib` on macOS and `libneedle.dll` on Windows; the name `libneedle3.so` is looked for only next to `needle/__init__.py`, lines 95 to 102); `config.json`, re-downloaded with `force_download=True` on every base-model load (`_register_download`, lines 204 to 211); training checkpoint `checkpoints/needle3.safetensors` only for fine-tuning. Cache: `~/.cache/cactus-needle/v3/3.3.3/`. | verified from code |
| ONNX | None. No ONNX export or runtime anywhere in the package (`grep -i onnx` finds nothing). The deployable artifact is `needle3.cact` plus the native engine. | verified |
| CPU-only | Yes: the engine is a native CPU library; engine builds are published for `manylinux2014_x86_64`, `manylinux2014_aarch64`, musl, macOS and Windows (`fetch.py` lines 34 to 37). The `[gpu]` and `[metal]` extras are JAX training only. | verified from code |
| License | Package: Apache-2.0 (`dist-info/licenses/LICENSE`, the full Apache 2.0 text; METADATA `License: Apache-2.0`). Weights and native engine: the README points to Hugging Face for both; their license could not be read because `huggingface.co` is denied. | package verified; weights not verified |
| Download size | Author statements disagree. Wheel METADATA line 4: "A 14MB foundation tool-calling model for tiny devices". `cactus_needle-3.2.8/README.md` line 3: "The whole model is a single 8-29 MB binary". `llms.txt` line 3: "A sub-1 MB engine and the 35 MB `needle3.cact` weights are fetched once from Hugging Face and cached". Parameters, `llms.txt` line 3: "a 29-121M parameter on-device model". | author-stated (conflicting); not measured |
| CPU speed, short string | No author-stated CPU latency for Needle text inference in the package (the only timing claims are for the Whistle speech model on an Apple M4 Pro). | not measured: weights and engine unreachable |

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

What happens today with no network (measured): `needle.Needle()` raises
`LocalEntryNotFoundError` from `huggingface_hub` while trying to fetch the engine wheel, so the
package cannot run at all until the Hub is reachable or the files are staged locally.

### Offline and air-gapped path (Needle3)

The package supports it, but by convention rather than one switch:

1. On a connected machine: `needle fetch` (engine) and `needle download needle3` (weights), per
   `llms.txt` line 265: "For air-gapped devices, also see `NEEDLE3_LIB_PATH` ... and
   `HF_HUB_OFFLINE`".
2. On the target: set `NEEDLE3_LIB_PATH=<models>/libneedle.so` (read by `_library_path`,
   `__init__.py` lines 81 to 91). `needle fetch` writes the engine as `libneedle.so`
   (`libneedle.dylib` on macOS, `libneedle.dll` on Windows), not `libneedle3.so`; the variable
   takes any path, so point it at that file, or rename the file and use the new name
   everywhere (guard list, audit, SHA-256 record). Then place `needle3.cact` at
   `~/.cache/cactus-needle/v3/3.3.3/needle3.cact` (`_base_weights_path`, lines 112 to 119).
   Passing `weights=<path>.cact` also works, but the package then treats it as a tuned model: it
   runs in a worker subprocess and reports `confidence=None` unless the archive carries a
   confidence head (lines 196 to 230).
3. Always set `HF_HUB_OFFLINE=1`: even with a warm cache, every base load calls
   `_register_download`, which force-downloads `config.json` from the Hub (`fetch.py` docstring,
   lines 260 to 262: "The download is registered before the cache is consulted, so a warm cache
   still counts as a use of the model"). Offline mode makes that call fail fast; the package
   swallows the error.
4. Always set `NEEDLE_TELEMETRY=0` and `DO_NOT_TRACK=1`. `needle/_telemetry.py` posts usage
   events to `https://vlqqczxwyaodtcdmdmlw.supabase.co/functions/v1/telemetry` unless one of
   them (or `CI`) is set (lines 17 to 37). Separately, `cactus_needle-3.2.8/README.md` line 168,
   in the Deploy section about the per-platform `needle` binaries built with
   `needle build --platform`, says "By default, telemetry is turned on in the binary". That is
   author-stated for the native binary and unverified for the ctypes-loaded engine library,
   which could not be downloaded to check. Set both variables either way.

### Needle3 risks

- The engine is an unsigned prebuilt native library downloaded at run time and loaded with
  `ctypes`; `fetch.py` checks no hash. Stage it once, record its SHA-256 in the audit, and load
  it only through `NEEDLE3_LIB_PATH`.
- Telemetry is on by default in the Python package (verified from code) and, per the authors, in
  the native binary (unverified for the ctypes library; above).
- The decks and the `meddra_app.py` header describe "a 384-dim UNIT vector (SapBERT)". Needle3
  is not SapBERT, the package makes no biomedical claim, and the only dimension in its code is
  128. The app's real branch already sizes the index from `V.shape[1]`, so a different dimension
  will not crash it, but the deck claim is unverified until the engine reports its size.
- PHI spans: `extract()` returns values, not offsets, and may repair them, so `phi_app.py`'s
  planned "SAME 4-tuple shape" needs an offset-recovery step that accepts only values found
  verbatim in the field and rejects repaired ones.
- Fast release cadence: 37 PyPI releases since 2026-08-10. Pin the package version and the
  engine version (3.3.3) together.
- Name collision: an unrelated PyPI project named `needle` (0.5.0, "Automated testing for your
  CSS.", BSD, depends on `selenium<4` and `nose`) installs the same import name `needle`. Its
  `needle/__init__.py` only sets `__version__` and author fields (wheel read, not installed), so
  the apps' probe `_have("needle")` would return True for it.

## Laya (PyPI `laya`)

Evidence: `laya-0.4.13-py3-none-any.whl` and `laya-0.4.13.tar.gz` from PyPI (wheel SHA-256
`0ce3a444821b62ae9a452f922156e08d99b6c6d625e3fa590e84177eb3e980a8`, matched PyPI), unpacked
and read as data; the PyPI README is the wheel's `laya-0.4.13.dist-info/METADATA` (line numbers
below refer to it). Imported with `python -I` from another directory (torch and transformers
not installed; `import laya` is torch-free by design). That design is also why the apps' bare
import probe reports Laya as available with torch missing; see defect 5 under "Defects found in
the apps' real-path wiring".

| Question | Finding | Status |
|---|---|---|
| Python path | Official PyPI package `laya` 0.4.13 by Convai Innovations (uploaded 2026-10-21 13:42 UTC, the day of this report; 51 releases since 2026-09-18). PyTorch plus `transformers` runtime; requires `torch>=2.0.0`, `transformers>=4.48.0`, `safetensors>=0.4.0`, `huggingface_hub>=0.20.0`, `numpy>=1.20.0`. Laya **does** have a workable Python path; it is blocked only by the network. | verified from metadata and code |
| Import name | `laya` (`top_level.txt`: `laya`). | verified, imported |
| API | `agent = laya.load(model_dir, device="cpu")`, then `agent.predict(state, questions)` (alias of `system_one`, `agent.py` line 1982); or `laya.Router(...).predict(state, questions, model="english")`. Answers are typed: `choice`, `score`, `noul` (P(true)). Result shape: `result["answers"][qid]["noul"]`. `Router.route()` only picks a checkpoint and returns a `RouteDecision` (`router.py` lines 1175 to 1188). Temperature refit API: `agent.fit_temperatures(records)`, `agent.save_calibration(path)`, `laya.load(..., calibration=path)`. | verified from code; `route()` run |
| Embedding or spans | Not an embedder and not a span extractor; it answers typed questions over a whole state. (`laya.embed_fn_from_agent` exists only to shortlist labels.) | verified from code |
| Hugging Face repos and files | `router.py` lines 50 to 63: `BUNDLE_REPO = "convaiinnovations/laya"`, with `english` at the repo root and `multilingual` and `typed-decisions` as subfolders; standalone copies `convaiinnovations/laya-multilingual` and `convaiinnovations/laya-typed-decisions`. Files per checkpoint (`agent.py` lines 595 to 597): `rl_agent_config.json`, `model.safetensors`, `tokenizer/*`, `encoder/*`. Reviewed commit pins in `laya/revisions.py` lines 27 to 31 (root: `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`), applied with `LAYA_REVISION=reviewed`; SHA-256 checks with `expected_sha256=` or `LAYA_SHA256_DIGESTS`. | verified from code |
| Offline and air-gap | Supported. A local directory skips the Hub entirely (`agent.py` lines 581 to 587 call `snapshot_download` only when the path does not exist); the tokenizer and encoder config are read from the checkpoint's `tokenizer/` and `encoder/` folders (`agent.py` lines 678 to 684; `common.py` `build_model`: "when `encoder_dir` holds a saved encoder config, nothing is downloaded"). README lines 424 to 432 show `Router(models={"english": "models/laya", ...})` "to keep the router fully offline". Add `HF_HUB_OFFLINE=1`. No telemetry found in the package. | verified from code |
| ONNX | Runtime yes: `laya.load(dir, backend="onnx", onnx_path=...)` or `laya.onnx_agent.ONNXAgent(model_dir, onnx_path="laya.onnx")` (default name `laya.onnx`, `onnx_agent.py` line 90), extra `laya[onnx]`. Export no: the exporter is not in the PyPI package; it is `scripts/export_onnx.py` in the GitHub repo (fetched from raw.githubusercontent.com, default `--output laya.onnx`). The ONNX path still needs the checkpoint directory (tokenizer and config) and still imports torch (`laya/common.py` line 14 `import torch`, imported by `onnx_agent.py`). | verified from code |
| CPU-only | Yes. README line 362: "Device selection is automatic, in this order: CUDA, MPS, XPU, CPU" (arrows replaced by commas); "CPU and MPS run fp32"; `device="cpu"` forces it. | author-stated and in code |
| License | Package: Apache-2.0 (`dist-info/licenses/LICENSE`; classifier "License :: OSI Approved :: Apache Software License"). Weights: the third-party crate README says "The root checkpoint is Apache-2.0 and ungated"; not checked on the model card because `huggingface.co` is denied. | package verified; weights not verified |
| Download size | Third-party crate README (line 24) for the root (English) checkpoint files: "That is ~847 MB." Laya README line 392: "the three checkpoints under `models/` (gitignored, ~2.3 GB)". Parameters (README checkpoint table): `laya` 421M (ModernBERT-large), `laya-multilingual` 322M (mmBERT-base), `laya-typed-decisions` 421M. | author-stated; not measured |
| CPU speed, short string | Authors' table (README lines 413 to 417), one `predict()` with 4 questions on a short email, median of 10, "CPU (28 threads)" on a 56-core Intel Mac Pro: `laya` 453 ms (113 ms per question), `laya-multilingual` 192 ms (48 ms per question). README line 749 gives 193 to 464 ms on CPU with `Router(preload=True)`. GPU figure (README line 189): 33 ms for one question on a T4. This machine has 4 vCPU, so expect slower; nothing was run. | author-stated; not measured: weights unreachable |

### crates.io `laya` is a different project

`https://crates.io/api/v1/crates/laya` (with a User-Agent): description "Rust inference for the
Laya non-autoregressive typed-decision model (ModernBERT-large + RL decision head)", repository
`https://github.com/aovestdipaperino/laya-rust`, license Apache-2.0, owner `aovestdipaperino`
(author in `Cargo.toml`: Enzo Lombardi), versions 0.1.1 (2026-09-20, current) and 0.1.0
(yanked). The PyPI package is Convai Innovations' project (`github.com/NandhaKishorM/laya`,
Hugging Face `convaiinnovations/laya`). So the crate is an independent third-party
[candle](https://github.com/huggingface/candle) port that reads the same checkpoint files; it is
not the same project as the PyPI package. It has no Python binding (no `pyo3` in its
dependencies; it ships a `laya` CLI, a Rust library and an optional `laya-serve` web console),
so from Python it could only be driven as a subprocess. It downloads no weights itself (its
README tells you to `curl` them from `huggingface.co`), so it is blocked by the same gate. Its
README (line 164) adds: "Weights are f16 on disk and are upcast when loaded, so peak memory is
around 2.4 GB". The `.crate` file (0.1.1, 178,498 bytes) downloaded from `static.crates.io` and
matched the index checksum; it was not built.

### Laya risks

- **Over-confident as shipped.** README line 1638: "Both checkpoints are over-confident as
  shipped." Refitting one temperature per (question type, option count) bucket moves mean ECE
  0.466 to 0.081 (`laya`) and 0.314 to 0.106 (`laya-multilingual`) on the authors' data, and
  "`laya-multilingual` ships with no fitted temperatures at all" (line 1640).
- **Near chance zero-shot.** README line 1652: "The base checkpoints are near chance on
  typed-decisions zero-shot", 0.362 and 0.352 accuracy against "a 0.318 random baseline and a
  0.461 majority-class baseline", that is, below the majority-class baseline. The 0.766 figure
  is from a checkpoint fine-tuned on that benchmark's own training split (lines 144 and 1653 to
  1654). The authors'
  summary (lines 1654 to 1655) is that Laya is a fast base to specialize by fine-tuning, not a
  zero-shot decision engine.
- **Negation.** README lines 1660 to 1664 report that on their cancellation examples the English
  checkpoint picked the cancel option for all four negated requests. `meddra_app.py` Tier 3
  exists precisely to separate "X" from "patient denies X", so this must be tested, not assumed.
- **Routing.** Measured with laya 0.4.13 (`Router.route`, no weights involved): the short
  English string "Patient denies headache." routes to `multilingual` ("Latin script, language
  not identified ... using default (multilingual)"), the checkpoint with no fitted temperatures.
  Pin `model="english"` or load one local checkpoint with `laya.load`.
- **`Router(preload=True)`**, as the apps call it, loads all three checkpoints (about 2.3 GB of
  files by the authors' figure) into a 15 GiB machine with no swap.
- **INT8 ONNX is not accuracy-safe.** The exporter's own docstring (GitHub
  `scripts/export_onnx.py`) says INT8 "trades real accuracy ... do not use it where the
  calibrated probability or confidence matters".
- Release cadence: 51 releases in five weeks, the latest on the day of this report. Pin the
  package and the checkpoint revision.

**Consequence:** until per-bucket temperatures are refit on held-out labeled data that looks
like the apps' inputs, and the model is fine-tuned for the apps' questions, no Laya probability
in these apps should carry an `[RM]` tag as if it meant something. Until then it is an
uncalibrated score.

## requirements.txt pip names

Checked against the PyPI JSON API (`https://pypi.org/pypi/<name>/json`) and by installing into
throwaway venvs (removed afterwards).

| pip name in requirements.txt | Exists on PyPI? | Correct project? | Import name | Correct in the apps? | Fix needed? |
|---|---|---|---|---|---|
| `cactus-needle` | Yes, 3.2.8 (wheel 130,098 bytes, Apache-2.0, requires only `huggingface_hub`) | Yes: Cactus Compute's Needle (repo `Cactus-Compute/needle3`). Not to be confused with `cactus-compute` 2.2.2 ("Cactus Compute License", proprietary classifier) or `cactus` (a static site generator) or `needle` (CSS testing) | `needle` | `meddra_app.py`, `phi_app.py`: `"needle"` (right name, but cannot tell it from the unrelated `needle` package). `anomaly_app.py`: `"cactus-needle"`, which can never import (measured: `_have("cactus-needle")` is False with the package installed) | Pip name: no. Pin `==3.2.8`. Probes: yes (see below) |
| `laya` | Yes, 0.4.13 (wheel 439,568 bytes, Apache-2.0) | Yes: Convai Innovations' Laya (Hugging Face `convaiinnovations/laya`). The crates.io crate of the same name is a different, third-party project | `laya` | Probe name yes (`"laya"` in all three apps); the call sites are broken, see "Defects" | Pip name: no. Pin `==0.4.13`; it also pulls torch and transformers (see CPU torch below) |
| `hnswlib` | Yes, 0.8.0, sdist only (36,206 bytes, uploaded 2023-12-03) | Yes (`github.com/yurymalkov/hnsw`) | `hnswlib` | Yes | No. Needs a C++ compiler: built here from sdist on Python 3.12 with g++ 13.3.0 in 1 min 16 s (measured), and an `ip`-space index with `M=32`, `ef_construction=200`, `set_ef(64)` on 384-dim synthetic unit vectors returned exact self-matches |
| `xgboost` | Yes, 3.4.1 (Apache-2.0, `requires_python >=3.12`, requires `numpy` and `scipy`; Linux x86_64 wheel 57,615,456 bytes, plus `nvidia-nccl-cu13` on Linux, unpinned, so today 2.32.3, a 305.1 MB wheel) | Yes | `xgboost` | `meddra_app.py`, `phi_app.py`, `risk_app.py`: yes. `anomaly_app.py`: missing from `HAVE`, although its `_guard_artifacts` reads `HAVE.get("xgboost")`, so an `anomaly_model.json` in the models dir always hard-stops the app, even with xgboost installed | Pip name: no. Optional: on CPU-only Linux use `xgboost-cpu` 3.4.1 (same import name `xgboost`, 5,796,137-byte wheel, no NCCL; checked on PyPI only; it publishes Linux and Windows wheels but no macOS wheel, so macOS needs plain `xgboost`, whose NCCL dependency is Linux-only). `xgboost` 3.4.1 installed here with `--no-deps` (so without NCCL) imported as 3.4.1 and trained and predicted on CPU through the native `xgboost.train` API. `--no-deps` also skips `scipy`, which xgboost needs at load (`xgboost/core.py` line 40, `import scipy.sparse`); it was already in that venv, and the base `requirements.txt` does not list it. Never install both |

Not in the table but checked in passing: `POT` imports as `ot`, `scikit-learn` as `sklearn`,
`pyreadstat` as `pyreadstat`; the apps probe those names correctly.

## Defects found in the apps' real-path wiring

Found while reading the probes; defects 1 to 4 were reproduced with Streamlit's `AppTest` and
stub modules placed on `sys.path` (no real packages, no repository files touched), and defect 5
with the real `laya` 0.4.13 package and no torch, in plain Python outside the apps:

1. **The module names are never bound.** `_have()` calls `__import__(m)` and discards the result;
   no app has an `import needle`, `import laya`, `import hnswlib` or `import xgboost`. With
   importable stubs, `meddra_app.py` stops with `NameError: name 'needle' is not defined` (at
   `_agent = needle.Needle() if REAL_T2 else None`) and `phi_app.py` with
   `NameError: name 'laya' is not defined` (at `_router = laya.Router(preload=True)`).
2. **Wrong Laya call.** `meddra_app.py` `t3_coding` and `phi_app.py` `t3_phi` call
   `_router.route(s, SCHEMA)` and read `r.unambiguous` / `r.direct_pii` / `r.reident_risk`.
   `route()` returns a `RouteDecision` (fields `model`, `reason`); measured: it has no
   `unambiguous` attribute. The answers come from `predict()`:
   `_router.predict(s, CODING_SCHEMA, model="english")["answers"]["unambiguous"]["noul"]`.
3. **Banners claim REAL with no real code path.** `REAL_T4` (`meddra_app.py`, `phi_app.py`) is set
   when `xgboost` is importable, but no code loads `meddra_coder.json` or
   `phi_token_classifier.json` or calls xgboost. With an empty stub module named `xgboost`, both
   banners read "Tier 4: REAL xgboost". Likewise `phi_app.py` `REAL_T2` only changes the label:
   `t2_phi` always runs the regex stand-in, yet with an empty `needle` stub the banner reads
   "Tier 2: REAL needle". `anomaly_app.py` has no Needle or Laya call at all, so its broken
   `"cactus-needle"` probe is, by accident, what keeps its text-tier label honest.
4. **Artifact names that cannot exist.** `_guard_artifacts` in `meddra_app.py` and `phi_app.py`
   guards `needle3.onnx` and `laya.onnx`. The `cactus-needle` package has no ONNX export or
   runtime and loads only `.cact` weights plus the native engine (written by `needle fetch` as
   `libneedle.so`, `libneedle.dylib` or `libneedle.dll`); the Hub repo's file list is unverified
   (`huggingface.co` denied). Laya's ONNX file is optional, and its primary artifact is a
   checkpoint directory.
5. **The Laya probe reports REAL with torch absent.** `import laya` is torch-free (the
   torch-backed names, `load` among them, are lazy: `laya/__init__.py` `_LAZY_ATTRS`, and
   `agent.py` line 14 is `import torch`), and `transformers` is imported only inside functions
   (`agent.py` line 234, `common.py` line 703). So `_have("laya")` returns True, and `REAL_T3`
   is on in `meddra_app.py` and `phi_app.py`, with neither torch nor transformers installed.
   Measured with laya 0.4.13 and no torch: `import laya`, `hasattr(laya, "Router")` and
   `laya.Router().route(...)` succeed, while `hasattr(laya, "load")` and
   `laya.Router(preload=True)` raise `ModuleNotFoundError: No module named 'torch'`
   (`hasattr()` catches only `AttributeError`). Today defect 1's `NameError` comes first; once
   the module is bound, the same probe would crash both apps at `laya.Router(preload=True)`
   instead of falling back to the stand-in.

## Recommended corrections (not applied; for the build stages)

Per the brief, a failed gate means this change carries findings only. Nothing below has been
applied.

`requirements.txt`, real-path comment block:

```
# Real path (CPU). Pin exact versions: both model packages release several times a week.
#   pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only torch first
#   pip install "cactus-needle==3.2.8" "laya==0.4.13" "hnswlib==0.8.0"
#   pip install "xgboost-cpu==3.4.1; platform_system == 'Linux'" "xgboost==3.4.1; platform_system != 'Linux'"
# (xgboost-cpu and xgboost both import as "xgboost": install one, not both; 3.4.1 needs Python >= 3.12.
#  The markers pick xgboost-cpu on Linux, where plain xgboost pulls a 305 MB NCCL wheel, and plain
#  xgboost elsewhere: xgboost-cpu 3.4.1 publishes no macOS wheel. Both need scipy, which pip pulls in.
#  hnswlib ships no wheels and needs a C++ compiler. Never "pip install needle": that is an
#  unrelated CSS-testing package that installs the same import name as cactus-needle.)
# Weights are NOT on PyPI: stage them into the models dir (see docs/FEASIBILITY.md) and run with
#   HF_HUB_OFFLINE=1 NEEDLE_TELEMETRY=0 DO_NOT_TRACK=1 NEEDLE3_LIB_PATH=<models>/libneedle.so
# (needle fetch writes libneedle.so; libneedle.dylib on macOS, libneedle.dll on Windows)
```

Probes and real paths, per app (each file keeps its own copy, as the headers require):

- Bind the module and check its API, so the unrelated `needle` package and empty stubs fail the
  probe. Every API check must sit inside the same `try/except Exception` as the import: an
  attribute can be lazy and import more code (defect 5), and `hasattr()` catches only
  `AttributeError`, so a check outside the `try` can crash the app, which the headers forbid for
  a missing optional dependency. For example: `_mod(m, *attrs)` does
  `try: mod = importlib.import_module(m); return mod if all(hasattr(mod, a) for a in attrs) else None`
  with `except Exception: return None`, then `needle = _mod("needle", "Needle")`. `laya` must
  expose `load` and `Router` and also needs its runtime: require `_have("torch")` and
  `_have("transformers")` too, because `transformers` is imported only when a checkpoint loads,
  so `hasattr(laya, "load")` alone does not cover it. `hnswlib` must expose `Index`, `xgboost`
  must expose `Booster`.
- `anomaly_app.py`: change the probe from `"cactus-needle"` to `"needle"` and add `"xgboost"`, but
  only in the same change that wires a real text tier; flipping the probe alone would make the
  banner claim REAL Needle3/Laya while the bag-of-words stand-in runs.
- A tier may show REAL only when its model artifact is present and loaded, not when a library is
  importable: tie `REAL_T4` to a loaded booster from `meddra_coder.json` /
  `phi_token_classifier.json`, `REAL_T2` (PHI) to a working `needle.extract` path, `REAL_T3` to a
  loaded and calibrated Laya checkpoint.
- Laya: replace `.route(...)` plus attribute access with
  `.predict(text, SCHEMA, model="english")["answers"][qid]["noul"]`, or `laya.load(<models>/laya,
  device="cpu", calibration=<models>/laya_calibration.json)`; drop `preload=True` (it loads all
  three checkpoints).
- `_guard_artifacts`: guard `needle3.cact` (and the engine if bundled, under its per-OS name:
  `libneedle.so`, `libneedle.dylib`, `libneedle.dll`) for `needle`, and the
  checkpoint directory `laya/` (containing `rl_agent_config.json` and `model.safetensors`) plus the
  optional `laya.onnx` for `laya`, instead of `needle3.onnx` and `laya.onnx`.
- Correct the `meddra_app.py` header and the decks: "384-dim (SapBERT)" is not what Needle3 is;
  record the dimension the engine reports.

## Laya substitute

Not needed: Laya has a workable, official Python path (PyPI `laya`, CPU, offline from a local
directory, optional ONNX Runtime backend). Two caveats. First, any substitute would also need
weights from Hugging Face, so it is blocked by the same gate and is not a workaround for it.
Second, if Stage 3 shows that Laya cannot be made useful on the apps' questions even after
temperature refitting and a fine-tune, the closest honest substitute is a small ModernBERT-base
sequence classifier with one head per question, fine-tuned on synthetic labeled eCRF strings
and calibrated with per-bucket temperature scaling, labeled in every banner and audit row as
"ModernBERT classifier (not Laya)". It would keep the same output columns (one probability per
question) and would share Laya's base encoder family, so the comparison stays fair.

## Recommendation and next steps

1. **Unblock the gate.** Add the four required hosts listed under "Hosts to add under Allowed
   domains" (plus the recommended `download.pytorch.org` for the smaller CPU-only torch), keep
   package managers allowed, and re-run the probes (every Hugging Face URL should return
   200 or a redirect, not a 403).
2. **Finish Stage 0 (an hour).** Pinned installs into a fresh venv; stage `needle3.cact`, the
   engine (`libneedle.so` as `needle fetch` writes it) and the Laya English checkpoint into a
   models dir with SHA-256s recorded; load both fully offline (`HF_HUB_OFFLINE=1`, telemetry
   off); then measure on the session's machine and record as "measured": exact download sizes,
   cold load time, median CPU latency for one short string (for example "Patient denies
   headache.") over 10 runs after warm-up, the Needle embedding dimension and norm, and the
   weights' licenses from the model cards. Update this file with those numbers.
3. **Before Stage 1: fix the wiring.** Apply the corrections above (bound modules, API-checked
   probes, `predict()` instead of `route()`, real artifact names, REAL only when a model is
   loaded), each app separately, with stub-module tests added to `tests/qc_test.py` so the QC
   baseline grows rather than changes and keeps passing with no model installed. Baseline on
   this branch (cut from `main` before the hosted-mode work): 95 of 95 with the optional extras
   (POT, scipy, scikit-learn, pyreadstat) installed, 92 of 92 with `requirements.txt` only.
4. **Stage 1 (real Tier 2 for coding).** Needle3 embeddings of the 99-prefixed placeholder
   dictionary plus a generated synthetic dictionary in the thousands of terms, a real `hnswlib`
   inner-product index with `M=32`, `efConstruction=200`, `efSearch=64`, top-K per verbatim, and
   measured embed and search latency per verbatim and resident index size.
5. **Stage 2 (real Tier 3).** Laya `P(direct PHI)`, `P(quasi-ID)` and the coding ambiguity
   scalar, with per-bucket temperatures fitted on a synthetic labeled split and ECE reported
   before and after, plus the negation cases above. Use the labeled ModernBERT substitute only
   if Laya cannot be made useful.
6. **Stage 3 (Tier 4 and evaluation).** A synthetic evaluation set with known answers, the
   XGBoost re-ranker fitted on a training split and reported on a held-out split only, fixed
   seeds, results in `docs/EVALUATION.md`. Only numbers produced here may carry an `[RM]` tag.
7. **Stage 4 (decks).** Replace each illustrative `[RM]` value in Deck B with its measured value,
   in both `.md` and `.html`. If the hosted-mode change has merged by then, `docs/` holds
   byte-identical copies of the two HTML decks for GitHub Pages, and its QC check D1 fails
   unless the edited `.html` is copied there too.

**Time and disk for the torch install (estimates, labeled as such).**

- CPU-only torch from `download.pytorch.org`: size **unknown** (host denied; no other source
  was checked).
- Default torch from PyPI on Linux (what `pip install laya` resolves if CPU torch is not
  installed first), from PyPI's declared file sizes: `torch-2.14.1-cp312-cp312-manylinux_2_28_x86_64.whl`
  554.6 MB, plus `nvidia-cudnn-cu13` 553.1 MB, `triton` 248.0 MB, `nvidia-nccl-cu13` 2.30.7
  216.0 MB (pinned by torch 2.14.1; xgboost alone, unpinned, pulls 2.32.3 at 305.1 MB),
  `nvidia-cusparselt-cu13` 170.1 MB and `nvidia-nvshmem-cu13` 60.4 MB: at least 1.80 GB
  compressed before the `cuda-toolkit` component wheels (not summed), all of it useless on this
  GPU-less machine. This is why `download.pytorch.org` is on the recommended list.
- Throughput observed here, PyPI only. `files.pythonhosted.org` is in the session's `NO_PROXY`
  list, so these figures bypass the agent proxy and say nothing about `download.pytorch.org` or
  Hugging Face, which go through it. The 9.4 s first reported here for the 57.6 MB xgboost wheel
  was download plus install. Download alone of the same 57,615,456-byte file, re-measured on
  2026-10-21, varied widely: 1.1 s, 5.1 s and 8.6 s with `curl` (about 52, 11 and 7 MB/s);
  15.6 s and 34.0 s with `pip download --no-deps --no-cache-dir`, index lookup included (about
  3.7 and 1.7 MB/s); 3.3 s in the fact-checker's `pip download` run (about 17 MB/s). At 1.7 to
  52 MB/s the 1.80 GB GPU-flavored set takes between about 35 seconds and 18 minutes to
  download. Throughput through the proxy (PyTorch index, Hugging Face) is unknown until those
  hosts are allowed.
- Disk budget for Stage 1: torch CPU, transformers 5.20.2 (12.8 MB wheel), the four packages,
  Needle3 (about 35 MB stated) and one Laya checkpoint (about 847 MB stated) fit comfortably in a
  5 GB allowance; 28 GB is free. If the cloud environment caches setup, keep the install under
  about five minutes. The CPU wheel should make that easier than the CUDA wheels, but its size
  and the proxied throughput are both unknown, so time the first install before relying on it.

## Evidence index

Downloads (each into its own empty scratch directory; nothing executed from them):
`cactus_needle-3.2.8-py3-none-any.whl`, `cactus_needle-3.2.8.tar.gz`,
`laya-0.4.13-py3-none-any.whl`, `laya-0.4.13.tar.gz`, `hnswlib-0.8.0.tar.gz` (hashes checked
against PyPI), `laya-0.1.1.crate` (checksum
`a4664d1e957fa64cd4c52b3509787413ed237bd5b82fa55abd379ae1f07803a0`, matched the crates.io index),
and Laya's `scripts/export_onnx.py` and `laya-ts/scripts/export_onnx.py` from
raw.githubusercontent.com.

Files read (package-relative): `needle/__init__.py`, `needle/agent/fetch.py`,
`needle/_telemetry.py`, `needle/_worker.py`, `needle/model/architecture.py`,
`needle/model/checkpoints.py`, `cactus_needle-3.2.8/README.md`, `cactus_needle-3.2.8/llms.txt`;
`laya/__init__.py`, `laya/router.py`, `laya/agent.py`, `laya/common.py`, `laya/onnx_agent.py`,
`laya/revisions.py`, `laya-0.4.13.dist-info/METADATA`; crate `Cargo.toml`, `README.md`,
`.cargo_vcs_info.json`; installed `huggingface_hub/constants.py`, `huggingface_hub/file_download.py`.

Runs: `python -I` imports of `needle` and `laya` with offline and telemetry-off variables;
`Router.route` on one short string; `needle.Needle()` offline (fails with
`LocalEntryNotFoundError`); hnswlib build and index smoke test; xgboost `--no-deps` install,
import and a 20-round CPU train (scipy already present in that venv); `AppTest` runs of
`meddra_app.py` and `phi_app.py` with stub modules. Added during the fact-check: `import laya`,
`hasattr` checks, `Router().route(...)` and `Router(preload=True)` with no torch installed
(defect 5); timed downloads of the xgboost wheel with `curl` and `pip download`; a
`pip install --dry-run` of the marker-based xgboost line (picks `xgboost-cpu` on Linux); QC
runs on both venvs. Throwaway venvs and the empty `~/.cache/cactus-needle` folder the offline probe created
were deleted afterwards.
