"""law-openapi-mcp — 법제처 국가법령정보 OPEN API MCP 서버 + CLI."""
from importlib.metadata import PackageNotFoundError, version

try:  # 하드코딩하면 릴리스마다 pyproject 와 어긋난다.
    __version__ = version("law-openapi-mcp")
except PackageNotFoundError:  # 소스 트리에서 직접 임포트한 경우
    __version__ = "0.0.0+local"
