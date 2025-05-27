# client_app/client.py
import socket
import os
import math
import time  # For progress reporting
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
        self.receive_buffer = b""

    def connect(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.host, self.port))
            self.receive_buffer = b""
            return True, f"Connected to server at {self.host}:{self.port}"
        except socket.error as e:
            self.client_socket = None
            return False, f"Error connecting to server: {e}"

    def disconnect(self, send_quit_cmd=True):
        if self.client_socket:
            try:
                if send_quit_cmd:
                    self.client_socket.sendall(CMD_QUIT.encode())
                    # It's okay if this recv fails, server might close immediately
                    try:
                        response = self.client_socket.recv(BUFFER_SIZE).decode()
                        # print(f"Server (on disconnect): {response.split(MSG_SEPARATOR, 1)[-1]}")
                    except socket.error:
                        pass  # Expected if server closes quickly
            except socket.error as e:
                # print(f"Error sending QUIT command: {e}")
                pass  # Might already be closed
            finally:
                self.client_socket.close()
                self.client_socket = None
                return "Disconnected from server."
        return "Not connected or already disconnected."

    def _receive_line(self):
        while b'\n' not in self.receive_buffer:
            try:
                part = self.client_socket.recv(BUFFER_SIZE)
            except socket.error as e:
                raise ConnectionError(f"Socket error during receive: {e}")

            if not part:
                if self.receive_buffer:
                    line = self.receive_buffer
                    self.receive_buffer = b""
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
            return None, "Not connected to server."

        files_list = []
        try:
            self.client_socket.sendall(CMD_LIST_FILES.encode())
            response_header_str = self._receive_line()
            parts = response_header_str.split(MSG_SEPARATOR, 1)
            status = parts[0]

            if status == RESP_OK:
                message_part = parts[1] if len(parts) > 1 else ""
                if message_part.startswith("No files available"):
                    return [], message_part  # Return empty list and message

                try:
                    num_files = int(message_part)
                    for _ in range(num_files):
                        file_name = self._receive_line()
                        files_list.append(file_name)
                    return files_list, f"Found {num_files} files."
                except ValueError:
                    return None, f"Error: Server sent invalid file count: {message_part}"
                except Exception as e:
                    return None, f"Error receiving file list details: {e}"

            elif status == RESP_ERROR:
                return None, f"Server error listing files: {parts[1] if len(parts) > 1 else 'Unknown error'}"
            else:
                return None, f"Unknown response from server for LIST: {response_header_str}"

        except (socket.error, ConnectionError) as e:
            # self.disconnect(send_quit_cmd=False) # Disconnect on comm error
            return None, f"Communication error listing files: {e}"

    def request_download_file(self, filename, progress_callback=None):
        if not self.client_socket:
            return False, "Not connected to server."

        save_path = os.path.join(CLIENT_DOWNLOADS_DIR, os.path.basename(filename))

        try:
            self.client_socket.sendall(f"{CMD_DOWNLOAD_FILE}{MSG_SEPARATOR}{filename}".encode())
            response_header_str = self._receive_line()
            parts = response_header_str.split(MSG_SEPARATOR)
            status = parts[0]

            if status == RESP_FILE_NOT_FOUND:
                return False, f"Server: {parts[1] if len(parts) > 1 else 'File not found.'}"
            elif status == RESP_ERROR:
                return False, f"Server error: {parts[1] if len(parts) > 1 else 'Unknown download error.'}"
            elif status == RESP_FILE_INFO:
                try:
                    _filename_on_server = parts[1]
                    file_size = int(parts[2])
                    num_chunks = int(parts[3])

                    if progress_callback:
                        # Initial "starting" callback
                        progress_callback(filename, 0, num_chunks, 0, file_size, "starting")

                    total_bytes_received = 0
                    with open(save_path, 'wb') as f:
                        if file_size == 0 and num_chunks == 1:  # Empty file
                            if progress_callback:
                                progress_callback(filename, 1, 1, 0, 0, "empty_file_received")
                        else:
                            for i in range(num_chunks):
                                bytes_to_receive_this_chunk = min(CHUNK_SIZE, file_size - total_bytes_received)
                                if bytes_to_receive_this_chunk == 0 and total_bytes_received == file_size:
                                    break

                                chunk_data = b''
                                while len(chunk_data) < bytes_to_receive_this_chunk:
                                    remaining_in_chunk = bytes_to_receive_this_chunk - len(chunk_data)
                                    part = self.client_socket.recv(min(BUFFER_SIZE, remaining_in_chunk))
                                    if not part:
                                        raise ConnectionError(
                                            "Server closed connection prematurely during chunk transfer.")
                                    chunk_data += part

                                f.write(chunk_data)
                                total_bytes_received += len(chunk_data)

                                if progress_callback:
                                    # "progress" callback during download
                                    progress_callback(filename, i + 1, num_chunks, total_bytes_received, file_size,
                                                      "progress")

                    # The final "completed" status will be handled by the worker thread based on this method's return value.
                    # No specific "completed" callback here.
                    if total_bytes_received == file_size:
                        return True, f"File '{filename}' downloaded successfully to {save_path}"
                    else:
                        if os.path.exists(save_path): os.remove(save_path)
                        return False, f"Error: Download incomplete. Expected {file_size}, got {total_bytes_received}"

                except IndexError:
                    return False, f"Error: Malformed FILE_INFO response from server: {response_header_str}"
                except ValueError:
                    return False, f"Error: Invalid file size or chunk count in response: {response_header_str}"
                except Exception as e:
                    if os.path.exists(save_path) and 'save_path' in locals(): os.remove(
                        save_path)  # Check if save_path is defined
                    return False, f"Error during file download processing: {e}"
            else:
                return False, f"Unknown response from server for DOWNLOAD: {response_header_str}"

        except (socket.error, ConnectionError) as e:
            return False, f"Communication error downloading file: {e}"

    # run_ui method is removed as Streamlit will handle the UI