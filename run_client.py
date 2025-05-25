# run_client.py
from client_app.client import Client
from common.protocol import HOST, PORT

if __name__ == "__main__":
    client = Client(HOST, PORT)
    client.run_ui()