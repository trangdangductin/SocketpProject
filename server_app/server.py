# server_app/server.py
import socket
import threading
import os
import math
import time  # Import time
from common.protocol import (
    HOST, PORT, BUFFER_SIZE, CHUNK_SIZE,
    CMD_LIST_FILES, CMD_DOWNLOAD_FILE, CMD_QUIT,
    RESP_OK, RESP_ERROR, RESP_FILE_NOT_FOUND,
    RESP_FILE_INFO, MSG_SEPARATOR
)

SERVER_FILES_DIR = os.path.join(os.path.dirname(__file__), 'server_files')
if not os.path.exists(SERVER_FILES_DIR):
    os.makedirs(SERVER_FILES_DIR)
    with open(os.path.join(SERVER_FILES_DIR, "sample1.txt"), "w", encoding="utf-8") as f:
        f.write("This is sample file 1.")
    with open(os.path.join(SERVER_FILES_DIR, "image.jpg"), "w", encoding="utf-8") as f:
        f.write("This is a dummy image placeholder.")
    with open(os.path.join(SERVER_FILES_DIR, "sample_large_file.bin"), "wb") as f:
        f.write(os.urandom(2 * CHUNK_SIZE + 50000))
    with open(os.path.join(SERVER_FILES_DIR, "empty.txt"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(SERVER_FILES_DIR, "another.txt"), "w", encoding="utf-8") as f:
        f.write("This is another text file for testing purposes.")


class ClientHandler(threading.Thread):
    def __init__(self, client_socket, client_address):
        super().__init__()
        self.client_socket = client_socket
        self.client_address = client_address
        print(f"[NEW CONNECTION] {self.client_address} connected.")

    def run(self):
        try:
            while True:
                message = self.client_socket.recv(BUFFER_SIZE).decode().strip()
                if not message:
                    print(f"[{self.client_address}] Disconnected (empty message received).")
                    break
                parts = message.split(MSG_SEPARATOR, 1)
                command = parts[0]
                args = parts[1] if len(parts) > 1 else None
                print(f"[{self.client_address}] RX: Command='{command}', Args='{args}'")

                if command == CMD_LIST_FILES:
                    self.handle_list_files()
                elif command == CMD_DOWNLOAD_FILE:
                    if args:
                        self.handle_download_single_file(args)
                    else:
                        self.client_socket.sendall(f"{RESP_ERROR}{MSG_SEPARATOR}Filename not provided\n".encode())
                elif command == CMD_QUIT:
                    print(f"[{self.client_address}] Quit requested.")
                    self.client_socket.sendall(f"{RESP_OK}{MSG_SEPARATOR}Goodbye!\n".encode())
                    break
                else:
                    self.client_socket.sendall(f"{RESP_ERROR}{MSG_SEPARATOR}Unknown command\n".encode())
        except ConnectionResetError:
            print(f"[{self.client_address}] Connection reset by peer.")
        except socket.timeout:
            print(f"[{self.client_address}] Socket timeout during client run loop.")
        except Exception as e:
            print(f"[{self.client_address}] ERROR in run loop: {e}")
        finally:
            try:
                if self.client_socket:
                    print(f"[{self.client_address}] Shutting down socket write access (SHUT_WR)...")
                    self.client_socket.shutdown(socket.SHUT_WR)
                    print(f"[{self.client_address}] Socket SHUT_WR successful.")
            except (socket.error, OSError) as e:
                print(f"[{self.client_address}] Note during socket.shutdown(SHUT_WR): {e}")

            if self.client_socket:
                self.client_socket.close()
            print(f"[{self.client_address}] Connection fully closed.")

    def handle_list_files(self):
        try:
            files = [f for f in os.listdir(SERVER_FILES_DIR) if os.path.isfile(os.path.join(SERVER_FILES_DIR, f))]
            if not files:
                self.client_socket.sendall(f"{RESP_OK}{MSG_SEPARATOR}No files available.\n".encode())
                return
            self.client_socket.sendall(f"{RESP_OK}{MSG_SEPARATOR}{len(files)}\n".encode())
            for file_name in files:
                self.client_socket.sendall(f"{file_name}\n".encode())
            print(f"[{self.client_address}] Sent file list.")
        except Exception as e:
            self.client_socket.sendall(f"{RESP_ERROR}{MSG_SEPARATOR}Could not list files: {e}\n".encode())
            print(f"[{self.client_address}] Error listing files: {e}")

    def handle_download_single_file(self, filename):
        file_path = os.path.join(SERVER_FILES_DIR, filename)
        print(f"[{self.client_address}] Prep DL: '{filename}'. Path: {file_path}")
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            self.client_socket.sendall(f"{RESP_FILE_NOT_FOUND}{MSG_SEPARATOR}File '{filename}' not found.\n".encode())
            print(f"[{self.client_address}] File '{filename}' not found.")
            return

        try:
            file_size = os.path.getsize(file_path)
            num_chunks = math.ceil(file_size / CHUNK_SIZE) if file_size > 0 else 1
            print(f"[{self.client_address}] ({filename}) FS:{file_size}, Chunks:{num_chunks}. Sending FILE_INFO...")

            file_info_msg = f"{RESP_FILE_INFO}{MSG_SEPARATOR}{filename}{MSG_SEPARATOR}{file_size}{MSG_SEPARATOR}{num_chunks}\n"
            self.client_socket.sendall(file_info_msg.encode())
            print(f"[{self.client_address}] ({filename}) FILE_INFO sent. Preparing to send data...")

            with open(file_path, 'rb') as f:
                if file_size == 0:
                    print(f"[{self.client_address}] ({filename}) Sending 0 bytes for empty file...")
                    self.client_socket.sendall(b'')
                    print(f"[{self.client_address}] ({filename}) Sent 0 bytes for empty file.")
                else:
                    for i in range(num_chunks):
                        print(f"[{self.client_address}] ({filename}) Reading chunk {i + 1}/{num_chunks}...")
                        chunk_data = f.read(CHUNK_SIZE)
                        if not chunk_data:
                            print(
                                f"[{self.client_address}] ({filename}) Read 0 bytes for chunk {i + 1} unexpectedly. Breaking.")
                            break
                        print(
                            f"[{self.client_address}] ({filename}) Sending chunk {i + 1}/{num_chunks} ({len(chunk_data)} bytes)...")
                        self.client_socket.sendall(chunk_data)
                        print(f"[{self.client_address}] ({filename}) Chunk {i + 1} sent.")
            print(f"[{self.client_address}] File '{filename}' data sending process completed.")

            # ---- DIAGNOSTIC SLEEP ----
            if file_size < CHUNK_SIZE * 2:  # Apply only for relatively small files
                print(f"[{self.client_address}] ({filename}) Small file, adding diagnostic sleep...")
                time.sleep(0.05)  # 50 milliseconds, adjust if needed
                print(f"[{self.client_address}] ({filename}) Diagnostic sleep finished.")
            # ---- END DIAGNOSTIC ----

        except Exception as e:
            print(f"[{self.client_address}] ERROR sending file '{filename}': {e}")


class Server:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.server_socket = None

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            print(f"[LISTENING] Server is listening on {self.host}:{self.port}")
            print(f"Serving files from: {SERVER_FILES_DIR}")

            while True:
                client_socket, client_address = self.server_socket.accept()
                handler = ClientHandler(client_socket, client_address)
                handler.start()
        except OSError as e:
            print(f"[ERROR] Could not start server: {e}")
        except KeyboardInterrupt:
            print("\n[SHUTTING DOWN] Server is shutting down.")
        finally:
            if self.server_socket:
                self.server_socket.close()
            print("[CLOSED] Server socket closed.")


if __name__ == "__main__":
    server = Server(HOST, PORT)
    server.start()