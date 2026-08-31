"""Optional local-web adapter.

Keep package import dependency-free so standard-library judge discovery never
requires FastAPI. The runnable entrypoint imports :mod:`demo.api.app` directly.
"""
