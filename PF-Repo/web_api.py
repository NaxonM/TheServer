from flask import Flask, request, jsonify, Response
import os
import threading
import sys
import logging
import json

# Add the parent directory to the path to allow imports, if needed
# This might not be necessary depending on how the app is run, but it's safer.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the new headless downloader
from downloader import HeadlessDownloader
import src.backend.shared_functions as shared_functions
from src.backend.CLI_model_feature_addon import (
    load_state,
    save_state,
    get_all_saved_models,
    add_model_url,
    remove_model_url
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Global Setup ---
# Create a config file if it doesn't exist. This ensures the downloader can load settings.
if not os.path.exists("config.ini"):
    shared_functions.setup_config_file(force=True)

# Instantiate the headless downloader. It will load settings from config.ini.
downloader = HeadlessDownloader()

# Define paths for data files
DOWNLOAD_PATH = "/downloads"
MODEL_DB_PATH = os.path.join(os.path.dirname(__file__), "model_database.json")

@app.route('/api/download', methods=['POST'])
def download_video():
    """
    Initiates a download based on the provided JSON payload.
    It can handle a single 'url', a 'model' URL, a 'playlist' URL, a 'search' query, or a 'batch' of URLs.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    quality = data.get('quality', 'best')

    # Handle batch download separately for immediate partial success reporting
    if 'urls' in data and isinstance(data['urls'], list):
        urls = data['urls']
        failed_urls = []
        successful_count = 0

        app.logger.info(f"Batch download request for {len(urls)} URLs with quality: {quality}")

        for url in urls:
            try:
                downloader.download_video_by_url(url=url, output_dir=DOWNLOAD_PATH, quality=quality)
                successful_count += 1
            except Exception as e:
                app.logger.error(f"Failed to download {url}: {e}", exc_info=True)
                failed_urls.append(url)
                if not downloader.ignore_errors:
                    app.logger.error("Halting batch download because ignore_errors is False.")
                    break

        response_data = {
            "message": f"Batch download completed. Successful: {successful_count}, Failed: {len(failed_urls)}",
            "failed_urls": failed_urls
        }

        status_code = 207 if failed_urls else 200  # Multi-status for partial success
        return jsonify(response_data), status_code

    # General case for single operations (url, model, etc.)
    download_task = None
    task_info = ""
    try:
        if 'url' in data:
            url = data['url']
            task_info = f"URL: {url}"
            download_task = lambda: downloader.download_video_by_url(url=url, output_dir=DOWNLOAD_PATH, quality=quality)

        elif 'model' in data:
            model_url = data['model']
            task_info = f"Model: {model_url}"
            download_task = lambda: downloader.download_from_model(model_url=model_url, output_dir=DOWNLOAD_PATH, quality=quality)

        elif 'playlist' in data:
            playlist_url = data['playlist']
            task_info = f"Playlist: {playlist_url}"
            download_task = lambda: downloader.download_from_playlist(playlist_url=playlist_url, output_dir=DOWNLOAD_PATH, quality=quality)

        elif 'search' in data:
            query = data['search']
            providers = data.get('providers')  # Can be None
            task_info = f"Search: '{query}' on providers: {providers or 'all'}"
            download_task = lambda: downloader.download_from_search(query=query, providers=providers, output_dir=DOWNLOAD_PATH, quality=quality)

        else:
            return jsonify({"error": "Missing or invalid download key in request body. Use 'url', 'model', 'playlist', or 'search'."}), 400

        app.logger.info(f"Received download request for {task_info} with quality: {quality}")

        # Define the target function for the background thread.
        def background_task_wrapper():
            try:
                app.logger.info(f"Starting download task for {task_info}")
                if download_task:
                    download_task()
                app.logger.info(f"Successfully completed download task for {task_info}")
            except Exception as e:
                app.logger.error(f"Error in background download thread for {task_info}: {e}", exc_info=True)

        # Run the download in a background thread to avoid blocking the request.
        download_thread = threading.Thread(target=background_task_wrapper)
        download_thread.start()

        return jsonify({"message": f"Download initiated for {task_info}"}), 202

    except Exception as e:
        app.logger.error(f"Failed to start download thread for {task_info}: {e}", exc_info=True)
        return jsonify({"error": f"Failed to start download: {str(e)}"}), 500

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    """
    Fetches metadata for a given video URL.
    """
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "Missing 'url' in request body"}), 400

    url = data['url']
    info = downloader.get_video_info(url)

    if "error" in info:
        # Distinguish between client errors (not found) and server errors
        if "not found" in info.get("error", "").lower():
            return jsonify(info), 404
        return jsonify(info), 500

    return jsonify(info)

@app.route('/api/fetch-videos', methods=['POST'])
def fetch_videos():
    """
    Fetches and streams video data from a source (model, playlist, or search).
    """
    data = request.get_json()
    if not data or 'type' not in data or 'query' not in data:
        return jsonify({"error": "Missing 'type' or 'query' in request body"}), 400

    source_type = data['type']
    query = data['query']
    limit = data.get('limit')
    delay = data.get('delay')
    providers = data.get('providers')

    def generate():
        try:
            video_generator = downloader.fetch_videos_from_source(
                source_type,
                query,
                providers=providers,
                limit=limit,
                delay=delay
            )

            yield '['
            first = True
            for video in video_generator:
                if not first:
                    yield ','
                yield json.dumps(video)
                first = False
            yield ']'
        except Exception as e:
            app.logger.error(f"Error during video stream generation for {source_type} '{query}': {e}", exc_info=True)
            # This part of the stream might be broken, but we've logged the error.
            # Depending on when the error occurs, the client might get incomplete JSON.

    return Response(generate(), mimetype='application/json')

@app.route('/api/status', methods=['GET'])
def get_status():
    """
    Returns the status of all active downloads.
    """
    return jsonify(list(downloader.active_downloads.values()))

@app.route('/api/settings', methods=['GET', 'POST'])
def manage_settings():
    """
    Manages the application settings stored in config.ini.
    GET: Returns the current settings.
    POST: Updates the settings.
    """
    if request.method == 'POST':
        try:
            new_settings = request.get_json()
            if not new_settings:
                return jsonify({"error": "Invalid JSON payload"}), 400

            # Update performance settings
            shared_functions.shared_config.set("Performance", "workers", str(new_settings.get('workers', 4)))
            shared_functions.shared_config.set("Performance", "retries", str(new_settings.get('retries', 3)))
            shared_functions.shared_config.set("Performance", "timeout", str(new_settings.get('timeout', 60)))
            shared_functions.shared_config.set("Performance", "threading_mode", new_settings.get('threading_mode', 'threaded'))
            shared_functions.shared_config.set("Performance", "ignore_errors", "true" if new_settings.get('ignore_errors') else "false")

            # Update video settings
            shared_functions.shared_config.set("Video", "directory_system", "1" if new_settings.get('directory_system') else "0")

            # Update network settings
            shared_functions.shared_config.set("Network", "proxy", new_settings.get('proxy', ''))

            # Save the updated configuration
            with open("config.ini", "w") as config_file:
                shared_functions.shared_config.write(config_file)

            # Reload settings in the downloader instance
            downloader.load_user_settings()

            return jsonify({"message": "Settings updated successfully"}), 200
        except Exception as e:
            app.logger.error(f"Failed to update settings: {e}", exc_info=True)
            return jsonify({"error": "An internal error occurred while saving settings."}), 500

    else: # GET request
        try:
            # Ensure the config file is up-to-date
            shared_functions.shared_config.read("config.ini")

            settings = {
                "workers": shared_functions.shared_config.getint("Performance", "workers", fallback=4),
                "retries": shared_functions.shared_config.getint("Performance", "retries", fallback=3),
                "timeout": shared_functions.shared_config.getint("Performance", "timeout", fallback=60),
                "threading_mode": shared_functions.shared_config.get("Performance", "threading_mode", fallback='threaded'),
                "ignore_errors": shared_functions.shared_config.getboolean("Performance", "ignore_errors", fallback=True),
                "directory_system": shared_functions.shared_config.getboolean("Video", "directory_system", fallback=False),
                "proxy": shared_functions.shared_config.get("Network", "proxy", fallback='')
            }
            return jsonify(settings)
        except Exception as e:
            app.logger.error(f"Failed to load settings: {e}", exc_info=True)
            return jsonify({"error": "An internal error occurred while loading settings."}), 500

# --- Model Management API ---

@app.route('/api/models', methods=['GET'])
def get_models():
    """
    Retrieves the list of all tracked models.
    """
    try:
        # get_all_saved_models returns a list of tuples (url, data)
        models_with_data = get_all_saved_models(path=MODEL_DB_PATH)
        # We only need to return the URLs to the frontend
        model_urls = [model[0] for model in models_with_data]
        return jsonify(model_urls)
    except Exception as e:
        app.logger.error(f"Failed to get models: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while fetching models."}), 500

@app.route('/api/models', methods=['POST'])
def add_model():
    """
    Adds a new model URL to be tracked.
    """
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "Missing 'url' in request body"}), 400

    url = data['url']
    try:
        success = add_model_url(model_url=url, path=MODEL_DB_PATH)
        if success:
            return jsonify({"message": f"Model '{url}' added successfully."}), 201
        else:
            return jsonify({"error": f"Model '{url}' is already tracked."}), 409
    except Exception as e:
        app.logger.error(f"Failed to add model {url}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while adding the model."}), 500

@app.route('/api/check-model-updates', methods=['POST'])
def check_model_updates_service():
    """
    Checks for new videos for a model, excluding URLs provided in the payload.
    """
    data = request.get_json()
    if not data or 'model_url' not in data:
        return jsonify({"error": "Missing 'model_url' in request body"}), 400

    model_url = data['model_url']
    downloaded_urls = set(data.get('downloaded_urls', []))

    try:
        # Using the existing fetch_videos_from_source generator
        video_generator = downloader.fetch_videos_from_source(
            source_type='model',
            query=model_url,
            limit=1000  # Use a high limit to get all videos
        )

        new_videos = [
            video for video in video_generator
            if video.get('url') not in downloaded_urls
        ]
        return jsonify(new_videos)

    except Exception as e:
        app.logger.error(f"Failed to check updates for model {model_url}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while checking for updates."}), 500

@app.route('/api/models', methods=['DELETE'])
def remove_model():
    """
    Removes a model URL from the tracking list.
    """
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "Missing 'url' in request body"}), 400

    url = data['url']
    try:
        success = remove_model_url(model_url=url, path=MODEL_DB_PATH)
        if success:
            return jsonify({"message": f"Model '{url}' removed successfully."}), 200
        else:
            return jsonify({"error": f"Model '{url}' not found."}), 404
    except Exception as e:
        app.logger.error(f"Failed to remove model {url}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while removing the model."}), 500


if __name__ == '__main__':
    # Run the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)