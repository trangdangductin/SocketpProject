# client_app/client.py
import socket
import os
import math
from common.protocol import (
    HOST, PORT, BUFFER_SIZE, CHUNK_SIZE,
    CMD_LIST_FILES, CMD_DOWNLOAD_FILE, CMD_QUIT,
    RESP_OK, RESP_ERROR, RESP_FILE_NOT_FOUND,
    RESP_FILE_INFO, MSG_SEPARATOR
)

CLIENT_DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), 'client_downloads')
if not os.path.exists(CLIENT_DOWNLOADS_DIR):
    os.makedirs(CLIENT_DOWNLOADS_DIR)

SOCKET_TIMEOUT = 30.0


class Client:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.client_socket = None
        self.receive_buffer = b""  # Buffer for line-based protocol and potential data overlap

    def connect(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(SOCKET_TIMEOUT)
            self.client_socket.connect((self.host, self.port))
            self.receive_buffer = b""  # Reset buffer on new connection
            return True, f"Connected to server at {self.host}:{self.port}"
        except socket.timeout:
            self.client_socket = None
            return False, f"Connection to server {self.host}:{self.port} timed out."
        except socket.error as e:
            self.client_socket = None
            return False, f"Error connecting to server: {e}"

    def disconnect(self, send_quit_cmd=True):
        if self.client_socket:
            try:
                if send_quit_cmd:
                    self.client_socket.sendall(CMD_QUIT.encode())
                    try:
                        self.client_socket.recv(BUFFER_SIZE)  # Consume goodbye
                    except socket.error:
                        pass
            except socket.error:
                pass
            finally:
                self.client_socket.close()
                self.client_socket = None
        return "Disconnected."

    def _receive_line(self):
        while b'\n' not in self.receive_buffer:
            try:
                part = self.client_socket.recv(BUFFER_SIZE)
            except socket.timeout:
                raise ConnectionError("Timeout receiving protocol line from server.")
            except socket.error as e:
                raise ConnectionError(f"Socket error during _receive_line: {e}")
            if not part:
                if self.receive_buffer:
                    line_str = self.receive_buffer.decode(errors='ignore').strip()
                    self.receive_buffer = b""
                    raise ConnectionError(f"Connection closed. Partial line: '{line_str}'")
                raise ConnectionError("Connection closed (while expecting protocol line).")
            self.receive_buffer += part

        line_end_index = self.receive_buffer.find(b'\n')
        line = self.receive_buffer[:line_end_index]
        self.receive_buffer = self.receive_buffer[line_end_index + 1:]  # Keep the rest in buffer
        return line.decode().strip()

    def request_list_files(self):
        if not self.client_socket: return None, "Not connected."
        files_list = []
        try:
            self.client_socket.sendall(CMD_LIST_FILES.encode())
            response_header_str = self._receive_line()  # Uses self.receive_buffer
            parts = response_header_str.split(MSG_SEPARATOR, 1)
            status = parts[0]
            msg_payload = parts[1] if len(parts) > 1 else ""

            if status == RESP_OK:
                if "No files available" in msg_payload: return [], msg_payload
                try:
                    num_files = int(msg_payload)
                    for _ in range(num_files):
                        files_list.append(self._receive_line())  # Uses self.receive_buffer
                    return files_list, f"Found {num_files} files."
                except ValueError:
                    return None, f"Invalid file count: {msg_payload}"
            else:
                return None, f"Server error listing: {msg_payload or status}"
        except (socket.error, ConnectionError) as e:
            return None, f"Comm error listing: {e}"

    def request_download_file(self, filename, progress_callback=None):
        if not self.client_socket: return False, "Not connected."
        save_path = os.path.join(CLIENT_DOWNLOADS_DIR, os.path.basename(filename))

        try:
            self.client_socket.sendall(f"{CMD_DOWNLOAD_FILE}{MSG_SEPARATOR}{filename}".encode())
            response_header_str = self._receive_line()  # This reads FILE_INFO\n
            # Any data immediately following \n is now in self.receive_buffer
            parts = response_header_str.split(MSG_SEPARATOR)
            status = parts[0]

            if status == RESP_FILE_NOT_FOUND:
                return False, f"Server: {parts[1] if len(parts) > 1 else 'Not found.'}"
            elif status == RESP_ERROR:
                return False, f"Server error (DL): {parts[1] if len(parts) > 1 else 'Unknown.'}"
            elif status == RESP_FILE_INFO:
                try:
                    _fn, file_size_str, num_chunks_str = parts[1], parts[2], parts[3]
                    file_size = int(file_size_str)
                    num_chunks = int(num_chunks_str)

                    if progress_callback: progress_callback(filename, 0, num_chunks, 0, file_size, "starting")
                    total_bytes_received = 0

                    with open(save_path, 'wb') as f:
                        if file_size == 0 and num_chunks == 1:  # Empty file
                            # Server sends FILE_INFO\n then b'' (empty data) then closes.
                            # The b'' might be in receive_buffer or need a direct recv.
                            # For simplicity, we assume 0 bytes of actual data to write.
                            # If receive_buffer contains anything, it's likely an error or next protocol message
                            # from a misbehaving server, but for 0-byte data, we don't expect anything.
                            # A more robust client might check self.receive_buffer for unexpected data here.
                            if progress_callback: progress_callback(filename, 1, 1, 0, 0, "empty_file_received")
                        else:  # Non-empty file
                            for i in range(num_chunks):
                                bytes_to_receive_this_chunk = min(CHUNK_SIZE, file_size - total_bytes_received)
                                if bytes_to_receive_this_chunk == 0 and total_bytes_received == file_size: break
                                if bytes_to_receive_this_chunk < 0: return False, f"Error ({filename}): Negative bytes."

                                chunk_data_list = []  # Store parts of the chunk
                                current_chunk_bytes_obtained = 0

                                # ** CRITICAL FIX: Consume from self.receive_buffer first **
                                if self.receive_buffer:
                                    can_take_from_buffer = min(len(self.receive_buffer), bytes_to_receive_this_chunk)
                                    chunk_data_list.append(self.receive_buffer[:can_take_from_buffer])
                                    self.receive_buffer = self.receive_buffer[can_take_from_buffer:]
                                    current_chunk_bytes_obtained += can_take_from_buffer

                                # Then, receive remaining from socket if necessary
                                while current_chunk_bytes_obtained < bytes_to_receive_this_chunk:
                                    bytes_needed_from_socket = bytes_to_receive_this_chunk - current_chunk_bytes_obtained
                                    try:
                                        part = self.client_socket.recv(min(BUFFER_SIZE, bytes_needed_from_socket))
                                    except socket.timeout:
                                        raise ConnectionError(
                                            f"Timeout RX chunk {i + 1}/{num_chunks} for {filename} ({current_chunk_bytes_obtained}/{bytes_to_receive_this_chunk}).")
                                    if not part: raise ConnectionError(
                                        f"Socket closed: chunk {i + 1}/{num_chunks} of {filename}.")
                                    chunk_data_list.append(part)
                                    current_chunk_bytes_obtained += len(part)

                                final_chunk_data = b"".join(chunk_data_list)
                                if len(final_chunk_data) != bytes_to_receive_this_chunk:  # Sanity check
                                    return False, f"Logic error: received {len(final_chunk_data)} not {bytes_to_receive_this_chunk} for chunk {i + 1} of {filename}"

                                f.write(final_chunk_data)
                                total_bytes_received += len(final_chunk_data)
                                if progress_callback: progress_callback(filename, i + 1, num_chunks,
                                                                        total_bytes_received, file_size, "progress")

                    if total_bytes_received == file_size:
                        return True, f"File '{filename}' downloaded successfully to {save_path}"
                    else:
                        if os.path.exists(save_path): os.remove(save_path)
                        return False, f"Download of '{filename}' incomplete. Expected {file_size}, got {total_bytes_received}"
                except (IndexError, ValueError) as e_parse:
                    return False, f"Malformed FILE_INFO: {response_header_str} ({e_parse})"
            else:
                return False, f"Unknown response for DOWNLOAD of '{filename}': {response_header_str}"
        except socket.timeout:
            return False, f"Timeout during DL op for '{filename}'."
        except (socket.error, ConnectionError) as e:
            return False, f"Comm error DL '{filename}': {e}"
        except Exception as e_gen:
            if 'save_path' in locals() and os.path.exists(save_path): os.remove(save_path)
            return False, f"Unexpected error during DL of '{filename}': {e_gen}"