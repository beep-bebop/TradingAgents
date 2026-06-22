import contextlib
import os
import warnings


def _normalize_ssl_cert_file() -> None:
    """Repair a broken ``SSL_CERT_FILE`` before any HTTP client is created.

    Conda's ``openssl_activate.sh`` (Git Bash on Windows) sets
    ``${CONDA_PREFIX}/ssl/cacert.pem``, but the bundle is at
    ``${CONDA_PREFIX}/Library/ssl/cacert.pem``. When the path is missing,
    try the Library location; otherwise unset so httpx falls back to certifi.
    """
    cert = os.environ.get("SSL_CERT_FILE")
    if not cert or os.path.isfile(cert):
        return
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        candidate = os.path.join(prefix, "Library", "ssl", "cacert.pem")
        if os.path.isfile(candidate):
            os.environ["SSL_CERT_FILE"] = candidate
            return
    os.environ.pop("SSL_CERT_FILE", None)


_normalize_ssl_cert_file()

# Load .env files at package import so DEFAULT_CONFIG's env-var overlay
# (and every llm_clients consumer) sees the user's keys regardless of
# which entry point started the process. find_dotenv(usecwd=True) walks
# from the CWD, so the installed `tradingagents` console script picks up
# the project's .env instead of stepping up from site-packages.
# load_dotenv defaults to override=False, so it never clobbers values
# the caller has already exported.
try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    load_dotenv(find_dotenv(".env.enterprise", usecwd=True), override=False)
except ImportError:
    pass

# langchain-core 1.3.3 calls surface_langchain_deprecation_warnings() in
# its own __init__, which prepends default-action filters for its
# subclassed warning categories. To suppress a specific warning we must
# install our filter AFTER langchain-core has installed its own, so import
# it first. The package is a guaranteed transitive dep via langgraph.
with contextlib.suppress(ImportError):
    import langchain_core  # noqa: F401

# langgraph-checkpoint 4.0.3 calls Reviver() at module load without an
# explicit allowed_objects, which triggers a noisy pending-deprecation
# warning from langchain-core 1.3.3 on every interpreter start. The fix
# is already merged upstream (langchain-ai/langgraph#7743, 2026-05-08)
# and will arrive in the next langgraph-checkpoint release. Remove this
# block (and the langchain_core preload above) when we bump past it.
warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects`.*",
    category=PendingDeprecationWarning,
)
