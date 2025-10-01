import os
import logging
import traceback
import requests
import uuid
import time
import itertools
from werkzeug.utils import secure_filename

# Assuming these imports are still needed and correct
import src.backend.shared_functions as shared_functions
from base_api.base import BaseCore
from base_api.modules.config import RuntimeConfig

try:
    import av
    remux = True
except (ModuleNotFoundError, ImportError):
    remux = False

conf = shared_functions.shared_config
logger = logging.getLogger(__name__)


class HeadlessDownloader:
    def __init__(self):
        self.active_downloads = {} # To store progress of active downloads
        self.skip_existing_files = None
        self.threading_mode = None
        self.speed_limit = None
        self.directory_system = None
        self.output_path = None
        self.quality = None
        self.result_limit = None
        self.retries = None
        self.timeout = None
        self.delay = None
        self.main_api_url = "http://proxy_app:8000/api/internal/register-download"

        shared_functions.refresh_clients()
        self.load_user_settings()

    def load_user_settings(self):
        # This function reads from the global 'conf' object
        conf.read("config.ini")
        self.delay = int(conf.get("Video", "delay"))
        self.timeout = int(conf.get("Performance", "timeout"))
        self.retries = int(conf.get("Performance", "retries"))
        self.speed_limit = float(conf.get("Performance", "speed_limit"))
        self.quality = conf.get("Video", "quality")
        self.output_path = conf.get("Video", "output_path")
        self.directory_system = True if conf.get("Video", "directory_system") == "1" else False
        self.skip_existing_files = True if conf.get("Video", "skip_existing_files") == "true" else False
        self.result_limit = int(conf.get("Video", "result_limit", fallback=50))
        self.threading_mode = conf.get("Performance", "threading_mode")

        # Apply settings to backend clients
        shared_functions.config.request_delay = self.delay
        shared_functions.config.timeout = self.timeout
        shared_functions.config.max_retries = self.retries
        shared_functions.config.max_bandwidth_mb = self.speed_limit
        shared_functions.refresh_clients()
        logger.info("Refreshed Clients with user settings being applied!")

    def register_with_main_app(self, filename, remote_url, file_path, source_url=None, thumbnail=None):
        """
        Notifies the main application of a new download.
        """
        if not os.path.exists(file_path):
            logger.error(f"Cannot register '{filename}'; file not found at {file_path}")
            return

        try:
            size_bytes = os.path.getsize(file_path)
            if size_bytes == 0:
                logger.error(f"Download of '{filename}' resulted in a 0-byte file. Deleting and skipping registration.")
                os.remove(file_path)  # Clean up the empty file
                return

            payload = {
                "filename": filename,
                "remote_url": remote_url,
                "size_bytes": size_bytes,
                "source_url": source_url,
                "thumbnail": thumbnail,
            }
            # Filter out None values so they are not sent in the payload
            payload = {k: v for k, v in payload.items() if v is not None}

            response = requests.post(self.main_api_url, json=payload, timeout=15)
            response.raise_for_status()
            logger.info(f"Successfully registered '{filename}' with the main application.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to register '{filename}' with main app: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during registration of '{filename}': {e}")

    def download_video_by_url(self, url, output_dir=None, quality='best', source_url=None, thumbnail=None):
        """
        Main entry point for downloading a single video.
        """
        download_id = str(uuid.uuid4())
        try:
            video = shared_functions.check_video(url=url)
            if not video:
                raise ValueError(f"Could not find video for URL: {url}")

            # Determine if progress is measured in bytes or segments.
            # Most modern video downloads (like HQPorner, Eporner) are byte-based (MP4).
            # Others (like PornHub) use segmented streams (HLS/DASH).
            # Determine if progress is measured in bytes or segments
            is_segment_download = isinstance(video, shared_functions.ph_Video)
            progress_unit = 'segments' if is_segment_download else 'bytes'

            attrs = shared_functions.load_video_attributes(video)
            unsafe_title = attrs.get('title', 'video')
            safe_title = secure_filename(unsafe_title)

            # Use the provided thumbnail or try to get it from the video attributes
            final_thumbnail = thumbnail or attrs.get('thumbnail')

            final_output_dir = output_dir or self.output_path or os.getcwd()

            if self.directory_system:
                author = attrs.get('author', 'unknown_author')
                author_dir = os.path.join(final_output_dir, secure_filename(author))
                os.makedirs(author_dir, exist_ok=True)
                out_file = os.path.join(author_dir, f"{safe_title}.mp4")
            else:
                os.makedirs(final_output_dir, exist_ok=True)
                out_file = os.path.join(final_output_dir, f"{safe_title}.mp4")

            if self.skip_existing_files and os.path.exists(out_file):
                logger.info(f"File exists, skipping: {out_file}")
                return out_file, "Skipped"

            self.active_downloads[download_id] = {
                "id": download_id,
                "filename": os.path.basename(out_file),
                "status": "DOWNLOADING",
                "progress": 0,
                "total": 0,
                "unit": progress_unit,
                "speed_bps": 0,
                "last_update": time.time()
            }

            self.perform_download(video, out_file, remote_url=url, quality=quality, download_id=download_id, source_url=source_url, thumbnail=final_thumbnail)

            return out_file, "Downloaded"

        except Exception as e:
            logger.error(f"Failed to download {url}: {traceback.format_exc()}")
            if download_id in self.active_downloads:
                self.active_downloads[download_id]['status'] = 'FAILED'
            raise e
        finally:
            # Clean up the download from active list after a delay
            time.sleep(10)
            if download_id in self.active_downloads:
                del self.active_downloads[download_id]


    def perform_download(self, video, output_path, remote_url, quality, download_id, source_url=None, thumbnail=None):
        """
        The actual download logic, with progress callback.
        """
        def progress_callback(pos, total):
            current_time = time.time()
            if download_id in self.active_downloads:
                # For segmented downloads, total might be segments. We prefer bytes.
                # Let's try to get the total size in bytes if available.
                total_bytes = total
                if self.active_downloads[download_id]['unit'] != 'bytes':
                    # This part is tricky as not all libraries provide total size for segmented streams.
                    # We will assume `pos` is segment count and `total` is total segments.
                    # A better implementation would require library support for byte progress.
                    # For now, we will report segment-based progress and calculate speed based on segment completion.
                    pass # Placeholder for future byte-based conversion logic

                last_update = self.active_downloads[download_id].get('last_update', current_time)
                last_progress = self.active_downloads[download_id].get('progress', 0)

                time_diff = current_time - last_update
                progress_diff = pos - last_progress

                # Speed calculation is only meaningful for byte-based downloads
                speed_bps = 0
                if self.active_downloads[download_id]['unit'] == 'bytes' and time_diff > 0:
                    speed_bps = (progress_diff / time_diff) * 8

                self.active_downloads[download_id].update({
                    "progress": pos,
                    "total": total_bytes,
                    "speed_bps": speed_bps,
                    "last_update": current_time
                })

        try:
            # Call the appropriate download method based on the video object type.
            if isinstance(video, shared_functions.ph_Video):
                # PornHub downloads are segment-based and use the 'display' parameter for progress.
                video.download(path=output_path, quality=quality, downloader=self.threading_mode, display=progress_callback, remux=remux, no_title=True)
            elif isinstance(video, (shared_functions.hq_Video, shared_functions.ep_Video)):
                # HQPorner and Eporner have a simpler download method signature for byte-based downloads.
                video.download(path=output_path, quality=quality, callback=progress_callback, no_title=True)
            else:
                # This is the default for other byte-based downloaders (e.g., XVideos, XNXX).
                # They use the 'callback' parameter for progress and may support threading/remuxing.
                video.download(path=output_path, quality=quality, downloader=self.threading_mode, callback=progress_callback, remux=remux, no_title=True)

            if download_id in self.active_downloads:
                self.active_downloads[download_id]['status'] = 'COMPLETED'

        finally:
            logger.info(f"Finished download: {video.title}")
            if conf.get("Video", "write_metadata") == "true" and os.path.exists(output_path):
                if remux:
                    shared_functions.write_tags(
                        path=output_path,
                        data=shared_functions.load_video_attributes(video))

            self.register_with_main_app(
                filename=os.path.basename(output_path),
                remote_url=remote_url,
                file_path=output_path,
                source_url=source_url,
                thumbnail=thumbnail
            )

    def _get_video_generator(self, source_type, query, providers=None):
        """
        Creates and returns a video generator based on the source type.
        """
        logger.info(f"Creating video generator for {source_type}: {query}")
        video_generator = None

        if source_type == 'model':
            if shared_functions.eporner_pattern.search(query):
                video_generator = shared_functions.ep_client.get_pornstar(query, enable_html_scraping=True).videos(pages=10)
            elif shared_functions.xnxx_pattern.match(query):
                video_generator = shared_functions.xn_client.get_user(query).videos
            elif shared_functions.pornhub_pattern.match(query):
                video_generator = itertools.chain(shared_functions.ph_client.get_user(query).videos, shared_functions.ph_client.get_user(query).uploads)
            elif shared_functions.hqporner_pattern.match(query):
                video_generator = shared_functions.hq_client.get_videos_by_actress(query)
            elif shared_functions.xvideos_pattern.match(query):
                if "/model" in query or "/pornstar" in query:
                    video_generator = shared_functions.xv_client.get_pornstar(query).videos
                else:
                    video_generator = shared_functions.xv_client.get_channel(query).videos
            else:
                raise ValueError(f"Unsupported model URL: {query}")

        elif source_type == 'playlist':
            if "pornhub.com/playlist/" not in query:
                raise ValueError("Only PornHub playlists are supported.")
            playlist = shared_functions.ph_client.get_playlist(query)
            video_generator = playlist.sample()

        elif source_type == 'search':
            if providers is None:
                providers = ['pornhub', 'xvideos', 'xnxx', 'eporner']

            logger.info(f"Creating search generator for query: '{query}' across providers: {', '.join(providers)}")

            active_generators = []
            if 'pornhub' in providers:
                active_generators.append(shared_functions.ph_client.search(query))
            if 'xvideos' in providers:
                active_generators.append(shared_functions.xv_client.search(query))
            if 'xnxx' in providers:
                active_generators.append(shared_functions.xn_client.search(query).videos)
            if 'eporner' in providers:
                active_generators.append(shared_functions.ep_client.search_videos(
                    query,
                    per_page=50,
                    sorting_order="",
                    sorting_gay="",
                    sorting_low_quality="",
                    enable_html_scraping=True,
                    page=20
                ))

            if not active_generators:
                logger.warning(f"No valid search providers selected for query: '{query}'")
                return iter([]) # Return an empty iterator

            video_generator = itertools.chain(*active_generators)

        else:
            raise ValueError(f"Unsupported source type: {source_type}")

        return video_generator

    def download_from_model(self, model_url, output_dir=None, quality='best'):
        """
        Downloads all videos from a model's page.
        """
        logger.info(f"Starting download for model: {model_url}")
        video_generator = self._get_video_generator('model', model_url)
        for video in video_generator:
            try:
                thumbnail = getattr(video, 'thumbnail', None)
                self.download_video_by_url(
                    url=video.url,
                    output_dir=output_dir,
                    quality=quality,
                    source_url=model_url,
                    thumbnail=thumbnail
                )
            except Exception as e:
                logger.error(f"Failed to download a video from model {model_url}. Video URL: {getattr(video, 'url', 'N/A')}. Error: {e}")
                continue
        logger.info(f"Finished processing model: {model_url}")

    def download_from_playlist(self, playlist_url, output_dir=None, quality='best'):
        """
        Downloads all videos from a PornHub playlist.
        """
        logger.info(f"Starting download for playlist: {playlist_url}")
        video_generator = self._get_video_generator('playlist', playlist_url)
        for video in video_generator:
            try:
                thumbnail = getattr(video, 'thumbnail', None)
                self.download_video_by_url(
                    url=video.url,
                    output_dir=output_dir,
                    quality=quality,
                    source_url=playlist_url,
                    thumbnail=thumbnail
                )
            except Exception as e:
                logger.error(f"Failed to download a video from playlist {playlist_url}. Video URL: {getattr(video, 'url', 'N/A')}. Error: {e}")
                continue
        logger.info(f"Finished processing playlist: {playlist_url}")

    def download_from_search(self, query, providers=None, output_dir=None, quality='best'):
        """
        Searches for videos across supported sites and downloads them.
        """
        logger.info(f"Starting search and download for query: '{query}'")
        video_generator = self._get_video_generator('search', query, providers=providers)

        video_count = 0
        for video in video_generator:
            if video_count >= self.result_limit:
                logger.info(f"Search result limit of {self.result_limit} reached. Stopping download.")
                break
            try:
                thumbnail = getattr(video, 'thumbnail', None)
                self.download_video_by_url(
                    url=video.url,
                    output_dir=output_dir,
                    quality=quality,
                    source_url=f"search: {query}", # Use the search query as the source identifier
                    thumbnail=thumbnail
                )
                video_count += 1
            except Exception as e:
                logger.error(f"Failed to download a video from search query '{query}'. Video URL: {getattr(video, 'url', 'N/A')}. Error: {e}")
                continue
        logger.info(f"Finished processing search query: '{query}'")

    def fetch_videos_from_source(self, source_type, query, providers=None, limit=None, delay=None):
        """
        Fetches and yields video data from a model, playlist, or search, with optional rate limiting.
        """
        # Temporarily override config settings if provided
        original_delay = shared_functions.config.request_delay
        if delay is not None:
            try:
                shared_functions.config.request_delay = float(delay)
                logger.info(f"Temporarily setting request delay to {delay}s")
            except (ValueError, TypeError):
                logger.warning(f"Invalid delay value '{delay}' provided. Using default.")

        # Use provided limit, or fall back to the instance's result_limit
        effective_limit = self.result_limit
        if limit is not None:
            try:
                effective_limit = int(limit)
            except (ValueError, TypeError):
                logger.warning(f"Invalid limit value '{limit}' provided. Using default.")

        video_generator = self._get_video_generator(source_type, query, providers=providers)

        video_count = 0
        try:
            for video in video_generator:
                if video_count >= effective_limit:
                    logger.info(f"Result limit of {effective_limit} reached. Stopping fetch.")
                    break
                try:
                    title = getattr(video, 'title', 'Untitled Video')
                    if not title or title == 'video':
                        title = 'Untitled Video'
                    thumbnail = getattr(video, 'thumbnail', None)
                    yield {
                        "title": title,
                        "url": video.url,
                        "thumbnail": thumbnail
                    }
                    video_count += 1
                except Exception as e:
                    logger.error(f"Could not process a video from {query}. Error: {e}\n{traceback.format_exc()}")
                    continue
        finally:
            # Restore original delay to not affect other operations
            shared_functions.config.request_delay = original_delay
            logger.info(f"Restored request delay to {original_delay}s")

    def get_video_info(self, url):
        """
        Fetches metadata and available qualities for a single video URL without downloading.
        """
        try:
            logger.info(f"Fetching video info for URL: {url}")
            video = shared_functions.check_video(url=url)
            if not video:
                logger.warning(f"Video not found or unsupported for URL: {url}")
                return {"error": "Video not found or unsupported URL."}

            attrs = shared_functions.load_video_attributes(video)

            qualities = []
            # Attempt to get qualities for different video types. This requires knowledge
            # of the underlying libraries.
            if hasattr(video, 'qualities') and video.qualities:
                # Common pattern for pornhub-api and similar libraries
                qualities = list(video.qualities.keys())
            elif hasattr(video, 'get_available_qualities'):
                # Pattern for hqporner-api
                qualities = video.get_available_qualities()
            elif hasattr(video, 'files') and isinstance(video.files, dict):
                # Pattern for eporner-api where qualities are keys in a 'files' dict
                qualities = list(video.files.keys())

            # If no specific qualities are found, provide a default list.
            if not qualities:
                qualities = ['best', 'worst', '1080p', '720p', '480p']

            info = {
                "title": attrs.get('title', 'Untitled Video'),
                "thumbnail": attrs.get('thumbnail'),
                "author": attrs.get('author'),
                "tags": attrs.get('tags', []),
                "qualities": sorted(list(set(qualities)), reverse=True) # Ensure unique and sorted
            }
            logger.info(f"Successfully fetched video info for {url}: {info['title']}")
            return info

        except Exception as e:
            logger.error(f"Failed to get video info for {url}: {e}", exc_info=True)
            return {"error": f"An internal error occurred while fetching video info: {str(e)}"}