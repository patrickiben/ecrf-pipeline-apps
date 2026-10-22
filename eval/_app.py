"""Load an app's tier functions straight from its file, so the evaluation measures the SHIPPED code.

Each app is a Streamlit script whose functions (tiers, loaders, guards) all sit above the line
'# ============================ UI ============================'. Executing the file up to that
marker in a fresh namespace gives exactly the functions the app runs, with no copy that could
drift from it and no UI. The apps share no module on purpose; neither does this loader import
one app into another.
"""
import os, warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_MARKER = "# ============================ UI ============================"

def load_app(name, models_dir=None):
    """Return the namespace of <name>_app.py above its UI marker. With models_dir, the app's own
    load_real() runs on it and its tiers are activated exactly as the UI would do it; a load error
    or a feature-contract error raises instead of quietly running a stand-in."""
    path = os.path.join(ROOT, f"{name}_app.py")
    src = open(path, encoding="utf-8").read()
    cut = src.index(UI_MARKER)
    ns = {"__name__": f"ecrf_eval_{name}", "__file__": path}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")          # Streamlit's "no ScriptRunContext" outside a run
        exec(compile(src[:cut], path, "exec"), ns)
    if models_dir:
        R = ns["load_real"](models_dir)
        if R["errors"]: raise RuntimeError("; ".join(R["errors"]))
        ns["_activate"](R)
        err = ns["_contract_error"](R)
        if err: raise RuntimeError(err)
        ns["_R"] = R
    return ns
