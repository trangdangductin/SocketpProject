# streamlit_app.py
import streamlit as st
import os
import threading
import time
import queue
from client_app.client import Client, CLIENT_DOWNLOADS_DIR  # Uses the reverted client.py
from common.protocol import HOST as DEFAULT_HOST, PORT as DEFAULT_PORT  # Uses reverted protocol.py

st.set_page_config(page_title="File Transfer Client", layout="wide")

# --- Session State Initialization ---
if 'ui_client_instance' not in st.session_state:  # For UI operations like LIST
    st.session_state.ui_client_instance = None
if 'ui_client_connected' not in st.session_state:
    st.session_state.ui_client_connected = False
if 'server_files' not in st.session_state:
    st.session_state.server_files = []
if 'server_host' not in st.session_state:
    st.session_state.server_host = DEFAULT_HOST
if 'server_port' not in st.session_state:
    st.session_state.server_port = DEFAULT_PORT
if 'download_status' not in st.session_state:  # Dict to store status of each download thread/file
    st.session_state.download_status = {}
if 'log_messages' not in st.session_state:
    st.session_state.log_messages = []
if 'update_queue' not in st.session_state:
    st.session_state.update_queue = queue.Queue()
if '_processed_queue_this_run' not in st.session_state:
    st.session_state._processed_queue_this_run = False
if 'active_download_threads' not in st.session_state:  # Store actual thread objects
    st.session_state.active_download_threads = {}  # filename: thread_object


# --- Helper Functions ---
def add_log_to_queue(q, message_text):  # Same as before
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    q.put({'type': 'log', 'message': f"[{timestamp}] {message_text}"})


def progress_updater_for_file_thread(q, filename, current_chunk, total_chunks, current_bytes, total_bytes,
                                     status_from_client_lib):
    # This is called by the client lib's progress_callback
    progress_percent = 0
    if total_bytes > 0:
        progress_percent = current_bytes / total_bytes
    elif status_from_client_lib == "empty_file_received":  # Ensure 100% for empty
        progress_percent = 1.0

    update_payload = {
        'type': 'file_progress',
        'filename': filename,
        'progress_percent': progress_percent,
        'message': f"Chunk {current_chunk}/{total_chunks} ({current_bytes}/{total_bytes} bytes) - {status_from_client_lib}",
        'status_from_client_lib': status_from_client_lib
    }
    q.put(update_payload)


def download_file_worker(host, port, filename_to_download, q):
    """Worker to download ONE file. Creates its own Client instance and connection."""
    # Initialize status for this file download
    q.put({'type': 'download_init', 'filename': filename_to_download, 'message': 'Preparing to connect...'})

    worker_client = Client(host, port)  # Each worker has its own client instance
    connected, conn_msg = worker_client.connect()

    if not connected:
        q.put({'type': 'download_result', 'filename': filename_to_download, 'success': False,
               'message': f"Connection failed: {conn_msg}"})
        add_log_to_queue(q, f"DL Worker ({filename_to_download}): Connect failed: {conn_msg}")
        return

    add_log_to_queue(q, f"DL Worker ({filename_to_download}): Connected. Starting download.")

    # Call request_download_file on this worker's client instance
    success, result_msg = worker_client.request_download_file(
        filename_to_download,
        lambda fn, cc, tc, cb, tb, sm: progress_updater_for_file_thread(q, fn, cc, tc, cb, tb, sm)
    )

    # Send the final result for this file
    q.put({'type': 'download_result', 'filename': filename_to_download, 'success': success, 'message': result_msg})

    if success:
        add_log_to_queue(q, f"DL Worker ({filename_to_download}): Success - {result_msg}")
    else:
        add_log_to_queue(q, f"DL Worker ({filename_to_download}): Failed - {result_msg}")

    worker_client.disconnect(send_quit_cmd=False)  # Worker clients just close their socket


def process_update_queue():  # Same queue processing logic as before the CMD_DOWNLOAD_MULTI
    st.session_state._processed_queue_this_run = False
    if not st.session_state.update_queue.empty():
        st.session_state._processed_queue_this_run = True

    while not st.session_state.update_queue.empty():
        try:
            update = st.session_state.update_queue.get_nowait()
            filename = update.get('filename')

            if update['type'] == 'log':
                if len(st.session_state.log_messages) > 20: st.session_state.log_messages.pop()
                st.session_state.log_messages.insert(0, update['message'])

            elif update['type'] == 'download_init' and filename:
                st.session_state.download_status[filename] = {
                    'progress': 0, 'message': update.get('message', 'Initializing...'),
                    'completed': False, 'error': False, 'thread_active': True
                }
            elif update['type'] == 'file_progress' and filename:
                if filename not in st.session_state.download_status:
                    st.session_state.download_status[filename] = {'completed': False, 'error': False,
                                                                  'thread_active': True, 'progress': 0}

                status_entry = st.session_state.download_status[filename]
                status_entry['progress'] = update['progress_percent']
                status_entry['message'] = update['message']
                if update.get('status_from_client_lib') == "empty_file_received":
                    # Handled by download_result for completion, but progress is 100%
                    pass


            elif update['type'] == 'download_result' and filename:
                if filename not in st.session_state.download_status:
                    st.session_state.download_status[filename] = {}

                status_entry = st.session_state.download_status[filename]
                status_entry['thread_active'] = False  # Mark thread as finished for this file
                if update['success']:
                    status_entry['completed'] = True
                    status_entry['progress'] = 1.0
                    status_entry['message'] = update['message']
                else:
                    status_entry['error'] = True
                    status_entry['message'] = update['message']

                # Remove from active_download_threads if present
                if filename in st.session_state.active_download_threads:
                    del st.session_state.active_download_threads[filename]


        except queue.Empty:
            break
        except Exception as e:
            log_msg = f"[ERROR] Queue processing: {e} (Update: {update if 'update' in locals() else 'N/A'})"
            print(log_msg)  # For server-side console debugging of Streamlit app
            if len(st.session_state.log_messages) > 20: st.session_state.log_messages.pop()
            st.session_state.log_messages.insert(0, log_msg)


# --- UI ---
st.title("📁 File Transfer Client")
process_update_queue()

with st.sidebar:
    st.header("Connection")
    st.session_state.server_host = st.text_input("Server Host", value=st.session_state.server_host)
    st.session_state.server_port = st.number_input("Server Port", value=st.session_state.server_port, min_value=1,
                                                   max_value=65535, step=1)

    if not st.session_state.ui_client_connected or not st.session_state.ui_client_instance:
        if st.button("🔗 Connect to Server"):
            # This client is for UI operations like LIST FILES
            client = Client(st.session_state.server_host, st.session_state.server_port)
            connected, msg = client.connect()
            if connected:
                st.session_state.ui_client_instance = client
                st.session_state.ui_client_connected = True
                st.success(msg)
                add_log_to_queue(st.session_state.update_queue, msg)
                st.rerun()
            else:
                st.session_state.ui_client_instance = None
                st.session_state.ui_client_connected = False
                st.error(msg)
                add_log_to_queue(st.session_state.update_queue, msg)
    else:  # Connected
        st.success(f"✅ Connected to {st.session_state.server_host}:{st.session_state.server_port} (UI Channel)")
        if st.button("🔌 Disconnect UI Client"):
            if st.session_state.ui_client_instance:
                # Send QUIT only for the main UI client, not download workers
                msg = st.session_state.ui_client_instance.disconnect(send_quit_cmd=True)
                add_log_to_queue(st.session_state.update_queue, msg)
            st.session_state.ui_client_instance = None
            st.session_state.ui_client_connected = False
            st.session_state.server_files = []
            # Note: Disconnecting UI client doesn't stop ongoing download threads.
            # A more robust app might signal them to stop or handle this.
            st.session_state.download_status = {}  # Clear status for simplicity on UI disconnect
            st.session_state.active_download_threads = {}
            st.info("UI Client Disconnected.")
            st.rerun()

    st.markdown("---")
    st.subheader("📜 Client Log")
    log_container = st.container(height=200)
    with log_container:
        for msg_text in st.session_state.log_messages:
            st.caption(msg_text)

if not st.session_state.ui_client_connected or not st.session_state.ui_client_instance:
    st.info("Please connect the UI client to the server using the sidebar.")
else:
    col1, col2 = st.columns([2, 3])
    with col1:
        st.subheader("📄 Server Files")
        if st.button("🔄 Refresh File List"):
            files, msg = st.session_state.ui_client_instance.request_list_files()
            if files is not None:
                st.session_state.server_files = files
                add_log_to_queue(st.session_state.update_queue, f"File list: {msg}")
            else:
                st.error(msg)
                add_log_to_queue(st.session_state.update_queue, f"List error: {msg}")

        if not st.session_state.server_files:
            st.info("No files on server or list not refreshed.")
        else:
            selected_files_to_download = st.multiselect(
                "Select files to download:", options=st.session_state.server_files
            )

            if selected_files_to_download:
                # Check how many threads are currently active
                active_thread_count = sum(1 for t in st.session_state.active_download_threads.values() if t.is_alive())
                MAX_CONCURRENT_DOWNLOADS = 5  # Limit simultaneous connections

                if st.button(f"⬇️ Download Selected ({len(selected_files_to_download)})"):
                    for filename in selected_files_to_download:
                        # Check if already downloading this file (thread exists and is alive)
                        if filename in st.session_state.active_download_threads and \
                                st.session_state.active_download_threads[filename].is_alive():
                            add_log_to_queue(st.session_state.update_queue,
                                             f"Skipping {filename}: download already in progress.")
                            continue

                        # Check if file has already been completed successfully
                        if st.session_state.download_status.get(filename, {}).get('completed'):
                            add_log_to_queue(st.session_state.update_queue,
                                             f"Skipping {filename}: already downloaded successfully.")
                            continue

                        if active_thread_count >= MAX_CONCURRENT_DOWNLOADS:
                            msg = f"Max concurrent downloads ({MAX_CONCURRENT_DOWNLOADS}) reached. {filename} not started."
                            add_log_to_queue(st.session_state.update_queue, msg)
                            st.warning(msg)
                            continue  # Skip starting new threads if limit reached

                        add_log_to_queue(st.session_state.update_queue, f"Starting download thread for {filename}...")
                        # Initialize status for this specific file download attempt
                        st.session_state.download_status[filename] = {
                            'progress': 0, 'message': 'Initializing thread...',
                            'completed': False, 'error': False, 'thread_active': True
                        }

                        thread = threading.Thread(
                            target=download_file_worker,
                            args=(st.session_state.server_host, st.session_state.server_port,
                                  filename, st.session_state.update_queue)
                        )
                        thread.daemon = True
                        st.session_state.active_download_threads[filename] = thread
                        thread.start()
                        active_thread_count += 1
                    st.rerun()

    with col2:  # Download Progress display
        st.subheader("📥 Download Progress")
        files_being_tracked = list(st.session_state.download_status.keys())  # Show all initiated
        if not files_being_tracked:
            st.caption("No downloads active or initiated yet.")
        else:
            for filename_key in files_being_tracked:
                status = st.session_state.download_status.get(filename_key)
                if status:  # If there's any status info for this file
                    st.markdown(f"**{filename_key}**")
                    col_prog_bar, col_prog_status = st.columns([1, 2])
                    with col_prog_bar:
                        st.progress(status.get('progress', 0))
                    with col_prog_status:
                        message = status.get('message', 'Status unknown')
                        if status.get('error'):
                            st.error(message, icon="🔥")
                        elif status.get('completed'):
                            st.success(message, icon="✅")
                        else:
                            st.caption(message)

    # Rerun logic for UI updates if there are active threads or queue items
    any_thread_alive = any(t.is_alive() for t in st.session_state.active_download_threads.values())
    if st.session_state._processed_queue_this_run or not st.session_state.update_queue.empty() or any_thread_alive:
        time.sleep(0.1)  # Short sleep for smoother UI updates
        st.rerun()

    st.markdown("---")  # Local downloads directory listing
    st.subheader("📦 Client Downloads Directory")
    st.info(f"Files are downloaded to: `{os.path.abspath(CLIENT_DOWNLOADS_DIR)}`")
    if os.path.exists(CLIENT_DOWNLOADS_DIR):
        try:
            downloaded_files_list = [f for f in os.listdir(CLIENT_DOWNLOADS_DIR) if
                                     os.path.isfile(os.path.join(CLIENT_DOWNLOADS_DIR, f))]
            if downloaded_files_list:
                st.write("Files in downloads directory:")
                for f_name in downloaded_files_list:
                    st.caption(f"- {f_name}")
            else:
                st.caption("No files in the download directory yet.")
        except Exception as e:
            st.error(f"Could not list client downloads: {e}")