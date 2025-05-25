# server_app/server.py
import socket
import threading
import os
import math
from common.protocol import (
    HOST, PORT, BUFFER_SIZE, CHUNK_SIZE,
    CMD_LIST_FILES, CMD_DOWNLOAD_FILE, CMD_QUIT,
    RESP_OK, RESP_ERROR, RESP_FILE_NOT_FOUND, RESP_END_OF_LIST,
    RESP_FILE_INFO, RESP_DOWNLOAD_COMPLETE, MSG_SEPARATOR
)

SERVER_FILES_DIR = os.path.join(os.path.dirname(__file__), 'server_files')
if not os.path.exists(SERVER_FILES_DIR):
    os.makedirs(SERVER_FILES_DIR)
    # Create some dummy files for testing
    with open(os.path.join(SERVER_FILES_DIR, "sample1.txt"), "w") as f:
        f.write("This is a sample file.")
    with open(os.path.join(SERVER_FILES_DIR, "sample_large_file.bin"), "wb") as f:
        f.write(os.urandom(2 * CHUNK_SIZE + 50000))  # Approx 2.5MB
    with open(os.path.join(SERVER_FILES_DIR, "image.jpg"), "w") as f:  # Dummy, replace with real image if desired
        f.write("This is a placeholder for an image.")


class ClientHandler(threading.Thread):
    def __init__(self, client_socket, client_address):
        super().__init__()
        self.client_socket = client_socket
        self.client_address = client_address
        print(f"[NEW CONNECTION] {self.client_address} connected.")

    def run(self):
        try:
            while True:
                # Receive command from client
                # We expect a command like "LIST" or "DOWNLOAD<|>filename"
                message = self.client_socket.recv(BUFFER_SIZE).decode().strip()
                if not message:
                    print(f"[DISCONNECTED] {self.client_address} disconnected (empty message).")
                    break

                parts = message.split(MSG_SEPARATOR, 1)
                command = parts[0]
                args = parts[1] if len(parts) > 1 else None

                print(f"[{self.client_address}] Received command: {command} with args: {args}")

                if command == CMD_LIST_FILES:
                    self.handle_list_files()
                elif command == CMD_DOWNLOAD_FILE:
                    if args:
                        self.handle_download_file(args)
                    else:
                        self.client_socket.sendall(f"{RESP_ERROR}{MSG_SEPARATOR}Filename not provided".encode())
                elif command == CMD_QUIT:
                    print(f"[DISCONNECTED] {self.client_address} requested quit.")
                    self.client_socket.sendall(f"{RESP_OK}{MSG_SEPARATOR}Goodbye!".encode())
                    break
                else:
                    self.client_socket.sendall(f"{RESP_ERROR}{MSG_SEPARATOR}Unknown command".encode())
        except ConnectionResetError:
            print(f"[DISCONNECTED] {self.client_address} connection reset.")
        except Exception as e:
            print(f"[ERROR] Error handling client {self.client_address}: {e}")
        finally:
            self.client_socket.close()
            print(f"[CLOSED] Connection with {self.client_address} closed.")

    def handle_list_files(self):
        try:
            files = [f for f in os.listdir(SERVER_FILES_DIR) if os.path.isfile(os.path.join(SERVER_FILES_DIR, f))]
            if not files:
                self.client_socket.sendall(f"{RESP_OK}{MSG_SEPARATOR}No files available.".encode())
                return

            response_header = f"{RESP_OK}{MSG_SEPARATOR}{len(files)}\n".encode()  # Send OK and number of files
            self.client_socket.sendall(response_header)

            for file_name in files:
                self.client_socket.sendall(f"{file_name}\n".encode())
            # self.client_socket.sendall(RESP_END_OF_LIST.encode()) # Old way, now using count
            print(f"Sent file list to {self.client_address}")
        except Exception as e:
            self.client_socket.sendall(f"{RESP_ERROR}{MSG_SEPARATOR}Could not list files: {e}".encode())
            print(f"Error listing files for {self.client_address}: {e}")

    def handle_download_file(self, filename):
        file_path = os.path.join(SERVER_FILES_DIR, filename)
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            self.client_socket.sendall(f"{RESP_FILE_NOT_FOUND}{MSG_SEPARATOR}File '{filename}' not found.".encode())
            print(f"File '{filename}' not found for {self.client_address}.")
            return

        try:
            file_size = os.path.getsize(file_path)
            num_chunks = math.ceil(file_size / CHUNK_SIZE) if file_size > 0 else 1
            if file_size == 0: num_chunks = 1  # Handle zero-byte files

            # Send file info: filename, size, number of chunks
            file_info_msg = f"{RESP_FILE_INFO}{MSG_SEPARATOR}{filename}{MSG_SEPARATOR}{file_size}{MSG_SEPARATOR}{num_chunks}\n"
            self.client_socket.sendall(file_info_msg.encode())
            print(f"Sending file info for {filename} to {self.client_address}: Size={file_size}, Chunks={num_chunks}")

            # Wait for client acknowledgment (optional, but good for sync)
            # ack = self.client_socket.recv(BUFFER_SIZE).decode().strip()
            # if ack != RESP_OK:
            #     print(f"Client did not acknowledge file info for {filename}. Aborting download.")
            #     return

            with open(file_path, 'rb') as f:
                if file_size == 0:  # Handle empty file
                    # Send a single empty chunk if file is empty
                    # The client should expect this based on num_chunks=1 and file_size=0
                    self.client_socket.sendall(b'')  # Sending zero bytes for the chunk
                    print(f"Sent empty file {filename} (1 chunk of 0 bytes) to {self.client_address}")
                else:
                    for i in range(num_chunks):
                        chunk_data = f.read(CHUNK_SIZE)
                        if not chunk_data:
                            break  # Should not happen if num_chunks is correct
                        self.client_socket.sendall(chunk_data)
                        # print(f"Sent chunk {i+1}/{num_chunks} of {filename} ({len(chunk_data)} bytes) to {self.client_address}")

            # Send download complete confirmation
            # self.client_socket.sendall(RESP_DOWNLOAD_COMPLETE.encode()) # Client will know from num_chunks
            print(f"File {filename} sent successfully to {self.client_address}.")

        except Exception as e:
            self.client_socket.sendall(f"{RESP_ERROR}{MSG_SEPARATOR}Error sending file: {e}".encode())
            print(f"Error sending file {filename} to {self.client_address}: {e}")


class Server:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.server_socket = None

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Reuse address
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)  # Max 5 queued connections
            print(f"[LISTENING] Server is listening on {self.host}:{self.port}")
            print(f"Serving files from: {SERVER_FILES_DIR}")

            while True:
                client_socket, client_address = self.server_socket.accept()
                handler = ClientHandler(client_socket, client_address)
                handler.start()
        except OSError as e:
            print(f"[ERROR] Could not start server: {e}")
        except KeyboardInterrupt:
            print("[SHUTTING DOWN] Server is shutting down.")
        finally:
            if self.server_socket:
                self.server_socket.close()
            print("[CLOSED] Server socket closed.")