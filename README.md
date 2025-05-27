
# Network File Transfer with Streamlit UI

## Overview

This project implements a client-server application for transferring files over a network. The server can handle multiple client connections simultaneously. The client provides a modern, interactive web-based UI built with Streamlit, allowing users to:
*   Connect to the server.
*   List available files on the server.
*   Download individual files.
*   Download multiple files concurrently, each with its own progress indication.

## Features

**Server (`server_app/server.py`):**
*   **Multi-Client Handling**: Manages multiple concurrent client connections using threading.
*   **File Listing**: Provides a list of available files from its designated `server_files` directory.
*   **Chunked File Transfer**: Sends files in manageable chunks for efficient transfer and progress tracking.
*   **Robust Connection Management**: Handles client connections and disconnections.
*   **Automatic Sample File Creation**: Creates `sample1.txt` and a ~2MB `sample_large_file.bin` on startup if they don't exist, for easy testing.

**Client (`streamlit_app.py` & `client_app/client.py`):**
*   **Streamlit Web UI**: Modern, interactive user interface running in the browser.
*   **Server Connection**: Connects to the specified server host and port.
*   **File Listing**: Displays files available on the server.
*   **Single File Download**: Allows users to select and download individual files.
*   **Simultaneous Multiple File Downloads**: Enables selection and concurrent download of multiple files.
    *   Each download runs in a separate thread, establishing its own connection to the server.
    *   Individual progress bars and status messages for each concurrent download.
*   **Progress Indication**: Shows download progress per chunk and overall status.
*   **Local Download Management**: Saves downloaded files to a `client_app/client_downloads/` directory.
*   **Client-Side Logging**: Displays a log of client actions and server messages in the UI.

**Common (`common/protocol.py`):**
*   **Text-Based Protocol**: Uses a simple command-based protocol (e.g., `LIST`, `DOWNLOAD <filename>`, `QUIT`).
*   **Message Separation**: Employs a `<|>` separator for distinguishing parts of a message.
*   **Status Responses**: Clear status codes (`OK`, `ERROR`, `FILE_NOT_FOUND`, `FILE_INFO`) for command outcomes.
*   **Defined Chunk Size**: Uses a configurable `CHUNK_SIZE` for file transfers.

## Prerequisites

*   Python 3.7+
*   Streamlit: Install using pip:
    ```bash
    pip install streamlit
    ```

## How to Run

1.  **Clone the repository** (or create the files as described in the structure above).

2.  **Prepare Server Files (Optional)**:
    *   The server script automatically creates `sample1.txt` and `sample_large_file.bin` in `server_app/server_files/` on its first run if they don't exist.
    *   You can place additional files you want to share into the `file_transfer_project/server_app/server_files/` directory.

3.  **Start the Server**:
    Open a terminal, navigate to the `file_transfer_project` directory (or the directory containing `server_app`), and run:
    ```bash
    python server_app/server.py
    ```
    By default, the server will start listening on `127.0.0.1:65432`. You can modify host/port in `common/protocol.py`.

4.  **Start the Client UI**:
    Open another terminal, navigate to the `file_transfer_project` directory (or the directory containing `streamlit_app.py`), and run:
    ```bash
    streamlit run streamlit_app.py
    ```
    This will typically open the Streamlit application in your default web browser. You can then connect to the server using the UI.

## Design Choices & Architecture

*   **Server**:
    *   **Object-Oriented**: `Server` class manages the main listening socket.
    *   **Threaded Client Handling**: Spawns a `ClientHandler` thread for each connected client to manage communication independently.
*   **Client (Streamlit UI - `streamlit_app.py`)**:
    *   **State Management**: Utilizes `st.session_state` to maintain connection status, file lists, download progress, and logs across UI interactions.
    *   **Concurrent Downloads**:
        *   Leverages Python's `threading` module to download multiple files simultaneously.
        *   Each download operation spawns a new thread, which creates its own `Client` instance and socket connection to the server. This allows for true parallel data streams (up to server/network limits).
    *   **Thread-Safe UI Updates**: Uses a `queue.Queue` to pass status and progress updates from background download threads to the main Streamlit thread. The main thread then processes these queued updates to safely modify `st.session_state` and refresh the UI.
    *   **Modular Client Logic**: The core network communication logic for the client is encapsulated in the `client_app/client.py` class, which is instantiated and used by the Streamlit application.
*   **Protocol (`common/protocol.py`)**:
    *   A simple, custom text-based protocol defines interactions.
    *   Commands (`LIST`, `DOWNLOAD`, `QUIT`) and responses (`OK`, `ERROR`, `FILE_INFO`, etc.) are clearly defined.
    *   Uses `<|>` as a message part separator.
*   **Chunking**:
    *   Files are broken down into `CHUNK_SIZE` segments (default 1MB in `protocol.py`) for transfer.
    *   The server first sends metadata (`FILE_INFO`) about the file (name, total size, number of chunks).
    *   The client receives chunks sequentially, writes them to a local file, and updates progress.
*   **Error Handling**:
    *   Basic error handling is implemented for socket operations, file I/O, and protocol validation on both client and server sides.
    *   The Streamlit UI displays errors reported by the client or server.
## % Completeness

*   Basic Functionality: 100%
*   Single File Transfer (including chunking): 100%
*   Multiple File Transfer (client can make multiple requests per session): 100%
*   Directory Listing: 100%
