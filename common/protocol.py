# common/protocol.py

HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
PORT = 65432        # Port to listen on (non-privileged ports are > 1023)
BUFFER_SIZE = 4096
CHUNK_SIZE = 1024 * 1024  # 1MB

# Commands
CMD_LIST_FILES = "LIST"
CMD_DOWNLOAD_FILE = "DOWNLOAD"
CMD_QUIT = "QUIT"

# Server Responses
RESP_OK = "OK"
RESP_ERROR = "ERROR"
RESP_FILE_NOT_FOUND = "FILE_NOT_FOUND"
RESP_END_OF_LIST = "END_OF_LIST"
RESP_FILE_INFO = "FILE_INFO" # Followed by filename, filesize, num_chunks
RESP_CHUNK = "CHUNK" # Followed by chunk_size, then chunk data
RESP_DOWNLOAD_COMPLETE = "DOWNLOAD_COMPLETE"

# Separator for messages
MSG_SEPARATOR = "<|>" # Using a less common separator