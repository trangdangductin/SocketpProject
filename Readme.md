
## How to Run

1.  **Prerequisites**: Python 3.6+
2.  **Clone the repository** (or create the files as described).
3.  **Prepare Server Files (Optional but Recommended for Testing)**:
    *   Place some files you want to share into the `file_transfer_project/server_app/server_files/` directory.
    *   The server script automatically creates `sample1.txt` and a ~2.5MB `sample_large_file.bin` for testing.
4.  **Start the Server**:
    Open a terminal, navigate to the `file_transfer_project` directory, and run:
    ```bash
    python run_server.py
    ```
    The server will start listening on `127.0.0.1:65432`.
5.  **Start the Client**:
    Open another terminal, navigate to the `file_transfer_project` directory, and run:
    ```bash
    python run_client.py
    ```
    The client will connect to the server, and you'll see a menu to list files or download files.

## Design Choices

*   **Object-Oriented**:
    *   `Server` class manages the main listening socket and spawns `ClientHandler` threads.
    *   `ClientHandler` class (threaded) manages communication with a single connected client.
    *   `Client` class manages the connection to the server and user interactions.
*   **Protocol**:
    *   A simple text-based command protocol is used (defined in `common/protocol.py`).
    *   Commands include `LIST`, `DOWNLOAD <filename>`, `QUIT`.
    *   Responses include status codes (`OK`, `ERROR`, `FILE_NOT_FOUND`, `FILE_INFO`) and data.
    *   A special separator `<|>` is used to distinguish parts of a message (e.g., command and arguments, or status and payload).
*   **Chunking**:
    *   Files are transferred in chunks of `CHUNK_SIZE` (default 1MB).
    *   Server sends `FILE_INFO` including filename, total size, and number of chunks.
    *   Client receives chunks sequentially and reassembles them. Progress is shown per chunk.
*   **Error Handling**:
    *   Basic error handling for socket operations, file operations, and invalid commands.
    *   Connection reset errors are caught.

## % Completeness

*   Basic Functionality: 100%
*   Single File Transfer (including chunking): 100%
*   Multiple File Transfer (client can make multiple requests per session): 100%
*   Directory Listing: 100%

## Example Output Screen (Client Interaction)