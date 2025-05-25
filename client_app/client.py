# client_app/client.py
import socket
import os
import math
from common.protocol import (
    HOST, PORT, BUFFER_SIZE, CHUNK_SIZE,
    CMD_LIST_FILES, CMD_DOWNLOAD_FILE, CMD_QUIT,
    RESP_OK, RESP_ERROR, RESP_FILE_NOT_FOUND, RESP_END_OF_LIST,
    RESP_FILE_INFO, MSG_SEPARATOR
)

CLIENT_DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), 'client_downloads')
if not os.path.exists(CLIENT_DOWNLOADS_DIR):
    os.makedirs(CLIENT_DOWNLOADS_DIR)


class Client:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.client_socket = None
        self.receive_buffer = b""  # Buffer for incoming data for line-by-line processing

    def connect(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.host, self.port))
            print(f"Connected to server at {self.host}:{self.port}")
            self.receive_buffer = b""  # Reset buffer on new connection
            return True
        except socket.error as e:
            print(f"Error connecting to server: {e}")
            self.client_socket = None
            return False

    def disconnect(self):
        if self.client_socket:
            try:
                self.client_socket.sendall(CMD_QUIT.encode())
                # For disconnect, a simple recv is okay as we expect a short confirmation
                # or it might fail if server closes immediately.
                response_parts = self.client_socket.recv(BUFFER_SIZE).decode().split(MSG_SEPARATOR, 1)
                if len(response_parts) > 1:
                    print(f"Server: {response_parts[1]}")
                else:
                    print(f"Server: {response_parts[0]}")

            except socket.error as e:
                print(f"Error during disconnect (or server closed connection): {e}")
            finally:
                self.client_socket.close()
                self.client_socket = None
                print("Disconnected from server.")

    def _receive_line(self):
        """
        Receives data from the socket and returns one newline-terminated line.
        Uses self.receive_buffer to handle data that arrives in chunks or multiple lines at once.
        """
        while b'\n' not in self.receive_buffer:
            try:
                part = self.client_socket.recv(BUFFER_SIZE)
            except socket.error as e:
                raise ConnectionError(f"Socket error during receive: {e}")

            if not part:
                # Connection closed by server
                if self.receive_buffer:  # If there's partial data left
                    line = self.receive_buffer
                    self.receive_buffer = b""
                    # Consider this an error as an incomplete line was received before closure
                    raise ConnectionError(
                        f"Connection closed by server. Received partial line: '{line.decode(errors='ignore').strip()}'")
                raise ConnectionError("Connection closed by server unexpectedly.")
            self.receive_buffer += part

        line_end_index = self.receive_buffer.find(b'\n')
        line = self.receive_buffer[:line_end_index]
        self.receive_buffer = self.receive_buffer[line_end_index + 1:]
        return line.decode().strip()

    def request_list_files(self):
        if not self.client_socket:
            print("Not connected to server.")
            return

        try:
            self.client_socket.sendall(CMD_LIST_FILES.encode())

            response_header_str = self._receive_line()  # Use new method
            parts = response_header_str.split(MSG_SEPARATOR, 1)
            status = parts[0]

            if status == RESP_OK:
                message_part = parts[1] if len(parts) > 1 else ""
                if message_part.startswith("No files available"):  # Server sends "OK<|>No files available."
                    print(message_part)
                    return

                try:
                    num_files = int(message_part)  # Server sends "OK<|>3"
                    print(f"\nAvailable files on server ({num_files}):")
                    for _ in range(num_files):  # Iterate num_files times
                        file_name = self._receive_line()  # Read one filename line
                        print(f"- {file_name}")
                    print("-" * 20)
                except ValueError:
                    print(f"Error: Server sent invalid file count: {message_part}")
                except Exception as e:
                    print(f"Error receiving file list details: {e}")

            elif status == RESP_ERROR:
                print(f"Server error listing files: {parts[1] if len(parts) > 1 else 'Unknown error'}")
            else:
                print(f"Unknown response from server for LIST: {response_header_str}")

        except (socket.error, ConnectionError) as e:
            print(f"Communication error listing files: {e}")
            self.disconnect()

    def request_download_file(self, filename):
        if not self.client_socket:
            print("Not connected to server.")
            return

        try:
            self.client_socket.sendall(f"{CMD_DOWNLOAD_FILE}{MSG_SEPARATOR}{filename}".encode())

            response_header_str = self._receive_line()  # Use new method
            parts = response_header_str.split(MSG_SEPARATOR)
            status = parts[0]

            if status == RESP_FILE_NOT_FOUND:
                print(f"Server: {parts[1] if len(parts) > 1 else 'File not found.'}")
                return
            elif status == RESP_ERROR:
                print(f"Server error: {parts[1] if len(parts) > 1 else 'Unknown download error.'}")
                return
            elif status == RESP_FILE_INFO:
                try:
                    _filename_on_server = parts[1]
                    file_size = int(parts[2])
                    num_chunks = int(parts[3])
                    print(f"Downloading '{filename}': Size={file_size} bytes, Chunks={num_chunks}")

                    save_path = os.path.join(CLIENT_DOWNLOADS_DIR, filename)

                    total_bytes_received = 0
                    with open(save_path, 'wb') as f:
                        if file_size == 0 and num_chunks == 1:
                            # Server will send an empty chunk (0 bytes) if the file is empty.
                            # We still need to "receive" it, even if it's nothing.
                            # The server-side sends b'' for an empty file chunk.
                            # A recv(BUFFER_SIZE) on an empty send might block or return b'' immediately.
                            # It's better to expect 0 bytes.
                            # For safety, we can do a non-blocking read or a read with timeout here,
                            # but usually the server will send *something* (even if 0 length payload for the chunk part).
                            # The current server logic for empty files:
                            # self.client_socket.sendall(b'')
                            # The client should be prepared to receive this 0-byte "chunk".
                            # Let's assume a single recv will get this if it's sent.
                            # However, if we rely on the loop below, bytes_to_receive_this_chunk will be 0.
                            # The loop 'while len(chunk_data) < bytes_to_receive_this_chunk' would not run.
                            # This means if server sends an empty chunk, we don't explicitly f.write(b'').
                            # Which is fine for an empty file.
                            print(f"Received empty file '{filename}'. Saved to {save_path}")
                        else:
                            for i in range(num_chunks):
                                bytes_to_receive_this_chunk = min(CHUNK_SIZE, file_size - total_bytes_received)
                                if bytes_to_receive_this_chunk == 0 and total_bytes_received == file_size:
                                    break

                                chunk_data = b''
                                while len(chunk_data) < bytes_to_receive_this_chunk:
                                    remaining_in_chunk = bytes_to_receive_this_chunk - len(chunk_data)
                                    # socket.recv can return less than requested.
                                    part = self.client_socket.recv(min(BUFFER_SIZE, remaining_in_chunk))
                                    if not part:
                                        raise ConnectionError(
                                            "Server closed connection prematurely during chunk transfer.")
                                    chunk_data += part

                                f.write(chunk_data)
                                total_bytes_received += len(chunk_data)

                                percentage = (total_bytes_received / file_size * 100) if file_size > 0 else 100
                                print(
                                    f"Downloading {filename} part {i + 1}/{num_chunks} .... {percentage:.0f}% complete ({len(chunk_data)} bytes received this part)")

                    if total_bytes_received == file_size:
                        print(f"File '{filename}' downloaded successfully to {save_path}")
                    else:
                        print(f"Error: Download incomplete. Expected {file_size}, got {total_bytes_received}")
                        if os.path.exists(save_path): os.remove(save_path)

                except IndexError:
                    print(f"Error: Malformed FILE_INFO response from server: {response_header_str}")
                except ValueError:
                    print(f"Error: Invalid file size or chunk count in response: {response_header_str}")
                except Exception as e:
                    print(f"Error during file download processing: {e}")
                    if 'save_path' in locals() and os.path.exists(save_path):
                        os.remove(save_path)
            else:
                print(f"Unknown response from server for DOWNLOAD: {response_header_str}")

        except (socket.error, ConnectionError) as e:
            print(f"Communication error downloading file: {e}")
            self.disconnect()

    def run_ui(self):
        if not self.connect():
            return

        try:
            while True:
                print("\nAvailable actions:")
                print("1. List files on server")
                print("2. Download a file")
                print("3. Quit")
                choice = input("Enter your choice: ").strip()

                if choice == '1':
                    self.request_list_files()
                elif choice == '2':
                    filename = input("Enter filename to download: ").strip()
                    if filename:
                        self.request_download_file(filename)
                    else:
                        print("Filename cannot be empty.")
                elif choice == '3':
                    break
                else:
                    print("Invalid choice. Please try again.")
        finally:
            self.disconnect()