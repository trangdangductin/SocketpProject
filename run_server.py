# run_server.py
from server_app.server import Server
from common.protocol import HOST, PORT

if __name__ == "__main__":
    server = Server(HOST, PORT)
    server.start()