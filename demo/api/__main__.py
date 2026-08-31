from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "demo.api.app:app",
        host="127.0.0.1",
        port=8000,
        workers=1,
        reload=False,
        access_log=False,
        server_header=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
