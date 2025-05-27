# streamlit_app.py
import streamlit as st
import os
import threading
import time
import queue
from client_app.client import Client, CLIENT_DOWNLOADS_DIR
from common.protocol import HOST as DEFAULT_HOST, PORT as DEFAULT_PORT

st.set_page_config(page_title="File Transfer Client", layout="wide")

# --- Session State Initialization ---
if 'connected' not in st.session_state:
    st.session_state.connected = False
if 'client_instance' not in st.session_state:
    st.session_state.client_instance = None
if 'server_files' not in st.session_state:
    st.session_state.server_files = []
if 'server_host' not in st.session_state:
    st.session_state.server_host = DEFAULT_HOST
if 'server_port' not in st.session_state:
    st.session_state.server_port = DEFAULT_PORT
if 'download_status' not in st.session_state:
    st.session_state.download_status = {}
if 'log_messages' not in st.session_state:
    st.session_state.log_messages = []
if 'update_queue' not in st.session_state:
    st.session_state.update_queue = queue.Queue()
if '_processed_queue_this_run' not in st.session_state:  # Flag for rerun logic
    st.session_state._processed_queue_this_run = False


# --- Helper Functions ---
def add_log_to_queue(q, message_text):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    q.put({'type': 'log', 'message': f"[{timestamp}] {message_text}"})


def progress_updater_for_thread(q, filename, current_chunk, total_chunks, current_bytes, total_bytes,
                                status_message_from_client):
    progress_percent = 0
    if total_bytes > 0:
        progress_percent = current_bytes / total_bytes
    elif status_message_from_client == "empty_file_received":  # Ensure 100% for empty
        progress_percent = 1.0

    update_payload = {
        'type': 'progress_update',
        'filename': filename,
        'progress_percent': progress_percent,
        'message': f"Chunk {current_chunk}/{total_chunks} ({current_bytes}/{total_bytes} bytes) - {status_message_from_client}",
        'status_from_client': status_message_from_client
    }
    q.put(update_payload)


def download_file_worker(host, port, filename_to_download, q):
    worker_client = Client(host, port)
    q.put({
        'type': 'status_init', 'filename': filename_to_download,
        'message': 'Connecting for download...', 'thread_id': threading.get_ident()
    })
    connected, msg = worker_client.connect()
    if not connected:
        q.put({'type': 'download_result', 'filename': filename_to_download, 'success': False,
               'message': f"Connection failed: {msg}"})
        add_log_to_queue(q, f"Error downloading {filename_to_download}: Connection failed: {msg}")
        return

    add_log_to_queue(q, f"Thread for {filename_to_download} ({threading.get_ident()}): {msg}")
    success, result_msg = worker_client.request_download_file(
        filename_to_download,
        lambda fn, cc, tc, cb, tb, sm: progress_updater_for_thread(q, fn, cc, tc, cb, tb, sm)
    )
    q.put({'type': 'download_result', 'filename': filename_to_download, 'success': success, 'message': result_msg})
    if success:
        add_log_to_queue(q, f"Download thread for {filename_to_download} finished: Success.")
    else:
        add_log_to_queue(q, f"Download thread for {filename_to_download} finished: {result_msg}")
    worker_client.disconnect(send_quit_cmd=False)


def process_update_queue():
    st.session_state._processed_queue_this_run = False  # Reset flag at start of processing
    if not st.session_state.update_queue.empty():
        st.session_state._processed_queue_this_run = True  # Will process, so set flag

    while not st.session_state.update_queue.empty():
        try:
            update = st.session_state.update_queue.get_nowait()
            filename = update.get('filename')  # Get filename if present

            if update['type'] == 'log':
                if len(st.session_state.log_messages) > 20: st.session_state.log_messages.pop()
                st.session_state.log_messages.insert(0, update['message'])

            elif update['type'] == 'status_init' and filename:
                st.session_state.download_status[filename] = {
                    'progress': 0, 'message': update['message'],
                    'thread_id': update['thread_id'], 'thread_active': True,
                    'completed': False, 'error': False
                }
            elif update['type'] == 'progress_update' and filename:
                if filename not in st.session_state.download_status:  # Fallback initialization
                    st.session_state.download_status[filename] = {
                        'progress': 0, 'message': 'Receiving (late init)...', 'thread_active': True,
                        'completed': False, 'error': False
                    }
                status_entry = st.session_state.download_status[filename]
                status_entry['progress'] = update['progress_percent']
                status_entry['message'] = update['message']
                if update['status_from_client'] == "empty_file_received":
                    status_entry['completed'] = True
                    status_entry['message'] = "Empty file received successfully."
                    status_entry['thread_active'] = False  # Empty file is immediately done

            elif update['type'] == 'download_result' and filename:
                if filename not in st.session_state.download_status:  # Fallback
                    st.session_state.download_status[filename] = {'completed': False, 'error': False,
                                                                  'progress': 0}  # Basic init

                status_entry = st.session_state.download_status[filename]
                status_entry['thread_active'] = False  # Download attempt is finished
                if update['success']:
                    status_entry['completed'] = True
                    status_entry['progress'] = 1.0
                    status_entry['message'] = update['message']  # This is the success message from client
                else:
                    status_entry['error'] = True
                    status_entry['message'] = update['message']
        except queue.Empty:
            break
        except Exception as e:
            current_time = time.strftime("%Y-%m-%d %H:%M:%S")
            log_msg = f"[{current_time}] [ERROR] Queue processing error: {e} (Update: {update})"
            print(log_msg)
            if len(st.session_state.log_messages) > 20: st.session_state.log_messages.pop()
            st.session_state.log_messages.insert(0, log_msg)


# --- UI ---
st.title("📁 File Transfer Client")
process_update_queue()  # Process queue at the start of every script run

# Sidebar (Connection & Log)
with st.sidebar:
    st.header("Connection")
    # ... (connection UI remains same, ensure add_log_to_queue(st.session_state.update_queue, ...) is used)
    st.session_state.server_host = st.text_input("Server Host", value=st.session_state.server_host)
    st.session_state.server_port = st.number_input("Server Port", value=st.session_state.server_port, min_value=1,
                                                   max_value=65535, step=1)

    if not st.session_state.connected:
        if st.button("🔗 Connect to Server"):
            client = Client(st.session_state.server_host, st.session_state.server_port)
            connected, msg = client.connect()
            if connected:
                st.session_state.connected = True
                st.session_state.client_instance = client
                st.success(msg)
                add_log_to_queue(st.session_state.update_queue, msg)
                st.rerun()
            else:
                st.error(msg)
                add_log_to_queue(st.session_state.update_queue, msg)
    else:
        st.success(f"✅ Connected to {st.session_state.server_host}:{st.session_state.server_port}")
        if st.button("🔌 Disconnect"):
            if st.session_state.client_instance:
                msg = st.session_state.client_instance.disconnect()
                add_log_to_queue(st.session_state.update_queue, msg)
            st.session_state.connected = False
            st.session_state.client_instance = None
            st.session_state.server_files = []
            st.session_state.download_status = {}
            st.info("Disconnected.")
            add_log_to_queue(st.session_state.update_queue, "User disconnected.")
            st.rerun()

    st.markdown("---")
    st.subheader("📜 Client Log")
    log_container = st.container(height=200)  # Make log scrollable
    with log_container:
        for msg_text in st.session_state.log_messages:
            st.caption(msg_text)

# Main Area
if not st.session_state.connected:
    st.info("Please connect to the server using the sidebar.")
else:
    col1, col2 = st.columns([2, 3])
    with col1:  # Server Files & Download Button
        st.subheader("📄 Server Files")
        # ... (Refresh file list logic remains same, use add_log_to_queue)
        if st.button("🔄 Refresh File List"):
            if st.session_state.client_instance:
                files, msg = st.session_state.client_instance.request_list_files()
                if files is not None:
                    st.session_state.server_files = files
                    add_log_to_queue(st.session_state.update_queue, f"File list updated: {msg}")
                else:
                    st.session_state.server_files = []
                    st.error(msg)
                    add_log_to_queue(st.session_state.update_queue, f"Error listing files: {msg}")
            else:
                st.error("Client not properly initialized.")
                add_log_to_queue(st.session_state.update_queue, "Error: Refresh attempt with no client instance.")

        if not st.session_state.server_files:
            st.info("No files found on server or list not refreshed yet.")
        else:
            selected_files_to_download = st.multiselect(
                "Select files to download:", options=st.session_state.server_files
            )
            if selected_files_to_download:
                if st.button(f"⬇️ Download Selected ({len(selected_files_to_download)})"):
                    active_downloads_count = sum(
                        1 for stat in st.session_state.download_status.values() if stat.get('thread_active'))
                    MAX_CONCURRENT_DOWNLOADS = 5
                    for filename in selected_files_to_download:
                        status = st.session_state.download_status.get(filename, {})
                        if status.get('thread_active') or status.get('completed'):
                            add_log_to_queue(st.session_state.update_queue,
                                             f"Skipping {filename}: already active or completed.")
                            continue
                        if active_downloads_count >= MAX_CONCURRENT_DOWNLOADS:
                            msg = f"Max concurrent downloads ({MAX_CONCURRENT_DOWNLOADS}) reached. {filename} not started."
                            add_log_to_queue(st.session_state.update_queue, msg)
                            st.warning(msg)
                            continue
                        add_log_to_queue(st.session_state.update_queue, f"Initializing download for {filename}...")
                        st.session_state.download_status[filename] = {  # Initial status set by main thread
                            'progress': 0, 'message': 'Queued for download...', 'thread_active': True,
                            'completed': False, 'error': False
                        }
                        thread = threading.Thread(target=download_file_worker, args=(
                            st.session_state.server_host, st.session_state.server_port,
                            filename, st.session_state.update_queue
                        ))
                        thread.daemon = True
                        thread.start()
                        active_downloads_count += 1
                    st.rerun()
    with col2:  # Download Progress
        st.subheader("📥 Download Progress")
        files_being_tracked = list(st.session_state.download_status.keys())
        if not files_being_tracked:
            st.caption("No downloads active or initiated yet.")
        else:
            for filename in files_being_tracked:
                status = st.session_state.download_status.get(filename)
                if status:
                    st.markdown(f"**{filename}**")
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

    # Rerun logic (outside columns, at the end of the main area)
    active_downloads_ui_check = any(s.get('thread_active') for s in st.session_state.download_status.values())
    # If queue was processed this run, or items still in queue, or active downloads, then rerun.
    if st.session_state._processed_queue_this_run or not st.session_state.update_queue.empty() or active_downloads_ui_check:
        time.sleep(0.1)  # Short sleep for smoother updates
        st.rerun()

    st.markdown("---")
    st.subheader("📦 Client Downloads Directory")
    # ... (listing downloaded files remains same) ...
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