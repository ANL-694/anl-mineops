from .main import app
from .mcp_server import create_mcp_server

if __name__ == "__main__":
    create_mcp_server(app.state.service).run()
