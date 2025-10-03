import os
import logging
import traceback
import requests
import uuid
import time
import itertools
import re
from slugify import slugify
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
        self.ignore_errors = True
        self.main_api_url = "http://proxy_app:8000/api/internal/register-download"

        shared_functions.refresh_clients()
        self.load_user_settings()

    def load_user_settings(self):
        # This function reads from the global 'conf' object
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        conf.read(config_path)
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
        self.ignore_errors = conf.getboolean("Performance", "ignore_errors", fallback=True)

        # Apply settings to backend clients
        shared_functions.config.request_delay = self.delay
        shared_functions.config.timeout = self.timeout
        shared_functions.config.max_retries = self.retries
        shared_functions.config.max_bandwidth_mb = self.speed_limit
        shared_functions.refresh_clients()
        logger.info("Refreshed Clients with user settings being applied!")

    def register_with_main_app(self, filename, remote_url, file_path, source_url=None, thumbnail=None, duration=None, author=None, tags=None, publish_date=None):
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
                "duration": duration,
                "author": author,
                "tags": tags,
                "publish_date": publish_date,
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

    def _sanitize_filename(self, title):
        """
        A more robust filename sanitization function.
        - Uses slugify to handle non-ASCII characters gracefully.
        - Falls back to a default if the title is empty or invalid.
        """
        if not title:
            return "video"
        # Call slugify in a more compatible way to avoid argument errors with different library versions.
        # This will convert the title to a URL-friendly slug.
        safe_title = slugify(title)
        safe_title = safe_title.replace('-', '_')
        # If slugify results in an empty string (e.g., title was all special characters), fallback.
        return safe_title if safe_title else "video"

    def _select_best_available_quality(self, requested_quality, available_qualities):
        """
        Selects the best possible quality from the available list based on the requested quality.
        - 'best': Highest available quality.
        - 'half': Middle available quality.
        - 'worst': Lowest available quality.
        - Specific (e.g., '720p'): The requested quality or the next best available.
        """
        if not available_qualities:
            logger.warning("No available qualities found for this video.")
            return None

        # Normalize available qualities to strings and remove duplicates
        normalized_qualities = []
        for q in available_qualities:
            q_str = str(q).strip()
            if q_str and q_str not in normalized_qualities:
                normalized_qualities.append(q_str)
        
        if not normalized_qualities:
            logger.warning("No valid qualities found after normalization.")
            return None

        # Check if this is an Eporner video (uses 'best', 'half', 'worst' format)
        is_eporner_format = any(q in ['best', 'half', 'worst'] for q in normalized_qualities)
        
        if is_eporner_format:
            # Handle Eporner API format (best, half, worst)
            if requested_quality in ['best', 'half', 'worst']:
                if requested_quality in normalized_qualities:
                    return requested_quality
                else:
                    # Fallback to best if requested quality not available
                    return 'best' if 'best' in normalized_qualities else normalized_qualities[0]
            else:
                # Convert resolution-based request to Eporner format
                if requested_quality in ['720p', '1080p', '1440p', '2160p']:
                    return 'best' if 'best' in normalized_qualities else normalized_qualities[0]
                elif requested_quality in ['480p', '540p']:
                    return 'half' if 'half' in normalized_qualities else 'best' if 'best' in normalized_qualities else normalized_qualities[0]
                else:
                    return 'worst' if 'worst' in normalized_qualities else normalized_qualities[0]

        # Handle resolution-based format (720p, 480p, etc.)
        def quality_sort_key(q):
            s = str(q).lower()
            if 'high' in s: return 10000
            if 'low' in s: return 0
            numeric_part = re.search(r'(\d+)', s)
            if numeric_part:
                return int(numeric_part.group(1))
            return -1

        # Sort the qualities from best to worst
        sorted_qualities = sorted(normalized_qualities, key=quality_sort_key, reverse=True)
        logger.debug(f"Available qualities sorted: {sorted_qualities}")

        # Handle abstract quality settings
        if requested_quality == 'best':
            return sorted_qualities[0]
        if requested_quality == 'half':
            middle_index = len(sorted_qualities) // 2
            return sorted_qualities[middle_index]
        if requested_quality == 'worst':
            return sorted_qualities[-1]

        # Handle specific quality requests (e.g., '1080p')
        # First try exact match
        if requested_quality in sorted_qualities:
            return requested_quality
        
        # Try case-insensitive match
        for q in sorted_qualities:
            if str(q).lower() == str(requested_quality).lower():
                return q

        # If the specific quality is not found, find the next best (lower) resolution.
        try:
            # Extract numeric part of the requested quality (e.g., 720 from '720p')
            requested_res = int(re.sub(r'[^0-9]', '', str(requested_quality)))

            # Iterate through sorted qualities to find the first one that is <= requested
            for q in sorted_qualities:
                q_res_str = re.sub(r'[^0-9]', '', str(q))
                if q_res_str:
                    q_res = int(q_res_str)
                    if q_res <= requested_res:
                        logger.info(f"Quality '{requested_quality}' not available. Falling back to next best: '{q}'.")
                        return q

            # If requested quality is lower than all available options, return the lowest available.
            lowest_quality = sorted_qualities[-1]
            logger.warning(f"Requested quality '{requested_quality}' is lower than all available options. Falling back to lowest: '{lowest_quality}'.")
            return lowest_quality

        except (ValueError, TypeError):
            # If resolution parsing fails (e.g., for non-numeric qualities), default to the best available.
            best_quality = sorted_qualities[0]
            logger.warning(f"Could not parse resolution from '{requested_quality}'. Defaulting to best available: '{best_quality}'.")
            return best_quality

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
            is_segment_download = isinstance(video, shared_functions.ph_Video) and not hasattr(video, '_custom_downloader')
            progress_unit = 'segments' if is_segment_download else 'bytes'

            attrs = shared_functions.load_video_attributes(video)
            unsafe_title = attrs.get('title', 'video')
            safe_title = self._sanitize_filename(unsafe_title)

            # Use the provided thumbnail or try to get it from the video attributes
            final_thumbnail = thumbnail or attrs.get('thumbnail')
            # If no explicit source_url is given, use the video's own URL.
            if not source_url:
                source_url = url

            final_output_dir = output_dir or self.output_path or os.getcwd()

            # Ensure the output directory exists and is writable
            try:
                os.makedirs(final_output_dir, exist_ok=True)
                logging.info(f"Ensuring output directory exists: {final_output_dir}")
                
                # Test write permissions by creating a temporary test file
                test_file = os.path.join(final_output_dir, '.test_write_permissions')
                try:
                    with open(test_file, 'w') as f:
                        f.write('test')
                    os.remove(test_file)
                    logging.info(f"Write permissions verified for directory: {final_output_dir}")
                except Exception as perm_e:
                    logging.warning(f"Potential write permission issue in {final_output_dir}: {perm_e}")
            except Exception as dir_e:
                logging.error(f"Failed to create output directory {final_output_dir}: {dir_e}")
                raise dir_e

            if self.directory_system:
                author = attrs.get('author', 'unknown_author')
                author_dir = os.path.join(final_output_dir, secure_filename(author))
                os.makedirs(author_dir, exist_ok=True)
                out_file = os.path.join(author_dir, f"{safe_title}.mp4")
            else:
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

            self.perform_download(
                video=video,
                output_path=out_file,
                remote_url=url,
                quality=quality,
                download_id=download_id,
                source_url=source_url,
                thumbnail=final_thumbnail,
                video_attrs=attrs
            )

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


    def _custom_pornhub_downloader(self, video, output_path, quality, progress_callback):
        """
        Custom downloader for PornHub to get byte-based progress.
        This bypasses the library's segment-based progress reporting.
        """
        try:
            # Try to get download URL using different methods
            download_url = None
            
            # Method 1: Try get_download_url if it exists
            if hasattr(video, 'get_download_url'):
                try:
                    download_url = video.get_download_url(quality)
                except Exception as e:
                    logger.warning(f"get_download_url failed: {e}")
            
            # Method 2: Try to get from qualities attribute
            if not download_url and hasattr(video, 'qualities'):
                qualities = video.qualities
                if isinstance(qualities, dict) and quality in qualities:
                    download_url = qualities[quality]
                elif isinstance(qualities, (list, tuple)):
                    # Try to find a quality that matches
                    for q in qualities:
                        if hasattr(q, 'quality') and str(q.quality) == str(quality):
                            download_url = q.url if hasattr(q, 'url') else str(q)
                            break
            
            # Method 3: Try to get from video attributes
            if not download_url and hasattr(video, 'url'):
                # For PornHub, we might need to construct the download URL
                video_url = video.url
                if 'pornhub.com' in video_url:
                    # Try to get the video ID and construct download URL
                    import re
                    video_id_match = re.search(r'viewkey=([a-zA-Z0-9]+)', video_url)
                    if video_id_match:
                        video_id = video_id_match.group(1)
                        # This is a simplified approach - in reality, you'd need to parse the page
                        download_url = f"https://www.pornhub.com/view_video.php?viewkey={video_id}"
            
            if not download_url:
                raise Exception("Could not get a valid download URL for PornHub video.")

            # If we got a page URL instead of direct download URL, we need to parse it
            if 'pornhub.com/view_video' in download_url:
                # For now, fall back to the library's built-in download method
                raise Exception("Need to use library's built-in download method for PornHub")

            # Let's assume the library gives us an M3U8 playlist URL
            with requests.get(download_url, stream=True, timeout=self.timeout) as r:
                r.raise_for_status()
                playlist_content = r.text
                base_url = os.path.dirname(download_url)
                ts_urls = [line.strip() for line in playlist_content.split('\n') if line.strip() and not line.startswith('#')]

                total_size = 0
                # Some M3U8 files might not have full URLs
                full_ts_urls = [url if url.startswith('http') else f"{base_url}/{url}" for url in ts_urls]

                # First, get the total size of all segments
                for ts_url in full_ts_urls:
                    try:
                        with requests.head(ts_url, timeout=self.timeout) as ts_head:
                            ts_head.raise_for_status()
                            total_size += int(ts_head.headers.get('content-length', 0))
                    except requests.RequestException as e:
                        logger.warning(f"Could not get size for segment {ts_url}: {e}")

                if total_size == 0:
                    raise Exception("Could not determine total download size from M3U8 segments.")

                downloaded_size = 0
                progress_callback(0, total_size) # Initial progress update

                with open(output_path, 'wb') as f:
                    for i, ts_url in enumerate(full_ts_urls):
                        try:
                            with requests.get(ts_url, stream=True, timeout=self.timeout) as ts_r:
                                ts_r.raise_for_status()
                                for chunk in ts_r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                                    downloaded_size += len(chunk)
                                    progress_callback(downloaded_size, total_size)
                        except requests.RequestException as e:
                            logger.error(f"Failed to download segment {i+1}/{len(full_ts_urls)}: {e}")
                            # Decide if you want to retry or fail the whole download
                            raise e # Re-raise to fail the download
        except Exception as e:
            logger.warning(f"Custom PornHub downloader failed: {e}")
            raise e

    def perform_download(self, video, output_path, remote_url, quality, download_id, source_url=None, thumbnail=None, video_attrs=None):
        """
        The actual download logic, with progress callback.
        """
        def progress_callback(pos, total):
            current_time = time.time()
            if download_id in self.active_downloads:
                last_update = self.active_downloads[download_id].get('last_update', current_time)
                last_progress = self.active_downloads[download_id].get('progress', 0)
                time_diff = current_time - last_update
                progress_diff = pos - last_progress
                speed_bps = 0
                if self.active_downloads[download_id]['unit'] == 'bytes' and time_diff > 0.5:
                    speed_bps = (progress_diff / time_diff) * 8
                elif self.active_downloads[download_id].get('speed_bps'):
                    speed_bps = self.active_downloads[download_id]['speed_bps']
                self.active_downloads[download_id].update({
                    "progress": pos, "total": total, "speed_bps": speed_bps, "last_update": current_time
                })

        try:
            # --- Resolve Quality ---
            if not video_attrs: # Failsafe if attrs weren't passed
                video_attrs = shared_functions.load_video_attributes(video)

            available_qualities = video_attrs.get('qualities', [])
            final_quality = self._select_best_available_quality(quality, available_qualities)

            if final_quality is None:
                logger.error(f"Could not determine a valid download quality for {remote_url} with requested quality '{quality}'. Available: {available_qualities}")
                raise ValueError(f"No suitable download quality found for {remote_url}")
            elif final_quality != quality:
                logger.warning(f"Quality '{quality}' not found for {remote_url}. Available: {available_qualities}. Falling back to '{final_quality}'.")

            # --- Download Execution ---
            download_dir = os.path.dirname(output_path)
            os.makedirs(download_dir, exist_ok=True)
            
            temp_dir = os.path.join(download_dir, f"temp_{download_id}")
            os.makedirs(temp_dir, exist_ok=True)
            
            try:
                # Provider-specific download logic
                if isinstance(video, shared_functions.ph_Video):
                    # PornHub's download method does not support the 'callback' argument.
                    video.download(path=temp_dir, quality=final_quality)
                elif isinstance(video, shared_functions.xn_Video):
                    # XNXX requires a 'downloader' argument.
                    video.download(path=temp_dir, quality=final_quality, downloader=shared_functions.xn_client)
                elif isinstance(video, shared_functions.xv_Video):
                    # XVIDEOS also requires a 'downloader' argument.
                    video.download(path=temp_dir, quality=final_quality, downloader=shared_functions.xv_client)
                elif isinstance(video, shared_functions.hq_Video):
                    try:
                        # HQPorner has an issue where it might not find the specified quality.
                        video.download(path=temp_dir, quality=final_quality, callback=progress_callback)
                    except KeyError:
                        logger.warning(f"HQPorner download failed for quality '{final_quality}'. Falling back to 'best' quality.")
                        video.download(path=temp_dir, quality='best', callback=progress_callback)
                else:
                    # Generic download call for other providers.
                    video.download(path=temp_dir, quality=final_quality, callback=progress_callback)

                # Find the downloaded file and move it to the final destination
                downloaded_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                if not downloaded_files:
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        logger.info(f"File '{output_path}' created directly. Assuming download was successful.")
                    else:
                        # Improved error message to pinpoint the source of the failure.
                        provider_name = video.__class__.__name__
                        error_message = (
                            f"The external download library ({provider_name}) failed to create a file "
                            f"in the temporary directory: {temp_dir}. This is likely an issue with the "
                            f"provider's API or the library itself."
                        )
                        logger.error(error_message)
                        raise FileNotFoundError(error_message)
                else:
                    created_filename = max(downloaded_files, key=lambda f: os.path.getsize(os.path.join(temp_dir, f)))
                    created_filepath = os.path.join(temp_dir, created_filename)
                    os.rename(created_filepath, output_path)
                    logger.info(f"Successfully downloaded and moved file to '{output_path}'")

            finally:
                # Clean up the temporary directory
                if os.path.exists(temp_dir):
                    for file in os.listdir(temp_dir):
                        try:
                            os.remove(os.path.join(temp_dir, file))
                        except OSError: pass
                    try:
                        os.rmdir(temp_dir)
                    except OSError:
                        logger.warning(f"Could not remove temporary directory: {temp_dir}")

            if download_id in self.active_downloads:
                self.active_downloads[download_id]['status'] = 'COMPLETED'

        finally:
            logger.info(f"Finished download: {getattr(video, 'title', 'N/A')}")
            if os.path.exists(output_path):
                if conf.get("Video", "write_metadata") == "true":
                    if remux:
                        shared_functions.write_tags(path=output_path, data=video_attrs)

                self.register_with_main_app(
                    filename=os.path.basename(output_path),
                    remote_url=remote_url,
                    file_path=output_path,
                    source_url=source_url,
                    thumbnail=thumbnail,
                    duration=video_attrs.get('length'),
                    author=video_attrs.get('author'),
                    tags=video_attrs.get('tags'),
                    publish_date=video_attrs.get('publish_date')
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
            elif shared_functions.missav_pattern.match(query):
                video_generator = shared_functions.mv_client.get_actress(query)
            elif shared_functions.xhamster_pattern.match(query):
                video_generator = shared_functions.xh_client.get_actress(query)
            elif shared_functions.spankbang_pattern.match(query):
                video_generator = shared_functions.sp_client.get_performer(query)
            elif shared_functions.youporn_pattern.match(query):
                video_generator = shared_functions.yp_client.get_performer(query)
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
            if 'hqporner' in providers:
                active_generators.append(shared_functions.hq_client.search_videos(query))
            if 'missav' in providers:
                active_generators.append(shared_functions.mv_client.search(query))
            if 'xhamster' in providers:
                active_generators.append(shared_functions.xh_client.search(query))
            if 'spankbang' in providers:
                active_generators.append(shared_functions.sp_client.search(query))
            if 'youporn' in providers:
                active_generators.append(shared_functions.yp_client.search(query))

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
                if not self.ignore_errors:
                    logger.error("Halting model download because ignore_errors is set to False.")
                    raise
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
                if not self.ignore_errors:
                    logger.error("Halting playlist download because ignore_errors is set to False.")
                    raise
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
                if not self.ignore_errors:
                    logger.error("Halting search download because ignore_errors is set to False.")
                    raise
                continue
        logger.info(f"Finished processing search query: '{query}'")

    def fetch_videos_from_source(self, source_type, query, providers=None, limit=None, delay=None):
        """
        Fetches and yields video data from a model, playlist, or search, with optional rate limiting.
        """
        original_delay = shared_functions.config.request_delay
        if delay is not None:
            try:
                shared_functions.config.request_delay = float(delay)
                logger.info(f"Temporarily setting request delay to {delay}s")
            except (ValueError, TypeError):
                logger.warning(f"Invalid delay value '{delay}' provided. Using default.")

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
                    attrs = shared_functions.load_video_attributes(video)
                    url = getattr(video, 'url', None)
                    if not url:
                         logger.warning(f"Could not determine URL for a video in the list for query: {query}. Skipping.")
                         continue

                    # Add the URL to the attributes dict to ensure it's always available
                    attrs['url'] = url
                    yield attrs
                    video_count += 1
                except Exception as e:
                    logger.error(f"Could not process a video from {query}. Error: {e}\n{traceback.format_exc()}")
                    continue
        finally:
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
            logger.info(f"Successfully fetched video info for {url}: {attrs.get('title')}")
            logger.info(f"Available qualities for '{attrs.get('title')}': {attrs.get('qualities', [])}")
            
            # Additional debugging for quality issues
            if not attrs.get('qualities'):
                logger.warning(f"No qualities found for video '{attrs.get('title')}' at URL: {url}")
            else:
                logger.info(f"Fetched {len(attrs.get('qualities', []))} quality options for '{attrs.get('title')}'")
                
            return attrs

        except Exception as e:
            logger.error(f"Failed to get video info for {url}: {e}", exc_info=True)
            return {"error": f"An internal error occurred while fetching video info: {str(e)}"}