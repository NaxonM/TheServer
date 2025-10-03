"""
This file contains functions which are needed for the Graphical User Interface, as well as the CLI.
If you know what you do, you can change a few things here :)
"""

import os
import re
import logging

from hqporner_api.modules.errors import WeirdError

from src.backend.config import *
from urllib.parse import urlsplit
from mutagen.mp4 import MP4, MP4Cover
from base_api.base import BaseCore, setup_logger
from base_api.modules.config import RuntimeConfig
from phub import Client as ph_Client, errors, Video as ph_Video, consts as phub_consts
from hqporner_api import Client as hq_Client, Video as hq_Video
from xnxx_api import Client as xn_Client, Video as xn_Video
from xvideos_api import Client as xv_Client, Video as xv_Video
from eporner_api import Client as ep_Client, Video as ep_Video, Category as ep_Category # Used in the main file
from youporn_api import Client as yp_Client
from youporn_api.youporn_api import Video as yp_Video

# Patch for eporner_api TypeError issue
import eporner_api.eporner_api as ep_module
original_direct_download_link = ep_module.Video.direct_download_link

def patched_direct_download_link(self, quality, mode):
    try:
        return original_direct_download_link(self, quality, mode)
    except TypeError as e:
        if "exceptions must derive from BaseException" in str(e):
            raise RuntimeError("No URLs available? Please report that") from e
        raise e
    except Exception as e:
        if "No URLs available" in str(e):
            raise RuntimeError("No URLs available? Please report that") from e
        raise e

ep_module.Video.direct_download_link = patched_direct_download_link
from missav_api.missav_api import Video as mv_Video, Client as mv_Client
from xhamster_api import Client as xh_Client, Video as xh_Video
from spankbang_api import Client as sp_Client, Video as sp_Video
from base_api.modules.config import config # This is the global configuration instance of base core config
# which is also affecting all other APIs when the refresh_clients function is called
# Initialize clients globally, so that we can override them later with a new configuration from BaseCore if needed
mv_client = mv_Client()
ep_client = ep_Client()
ph_client = ph_Client()
xv_client = xv_Client()
xh_client = xh_Client()
sp_client = sp_Client()
hq_client = hq_Client()
xn_client = xn_Client()
yp_client = yp_Client()
core = BaseCore() # We need that sometimes in Porn Fetch's main class e.g., thumbnail fetching
core_ph = None
core_internet_checks = BaseCore(config=config, auto_init=True)

def refresh_clients(enable_kill_switch=False):
    global mv_client, ep_client, ph_client, xv_client, xh_client, sp_client, hq_client, xn_client, yp_client, core, core_ph

    # One BaseCore per site, with its own RuntimeConfig (isolated headers/cookies)
    core_common = BaseCore(config=config, auto_init=True)   # if you want a "generic" core
    core_hq    = BaseCore(config=config, auto_init=True)
    core_mv    = BaseCore(config=config, auto_init=True)
    core_ep    = BaseCore(config=config, auto_init=True)
    core_ph    = BaseCore(config=config, auto_init=True)
    core_xv    = BaseCore(config=config, auto_init=True)
    core_xh    = BaseCore(config=config, auto_init=True)
    core_xn    = BaseCore(config=config, auto_init=True)
    core_sp    = BaseCore(config=config, auto_init=True)
    core_yp    = BaseCore(config=config, auto_init=True)

    if enable_kill_switch:
        core_common.enable_kill_switch()
        core_hq.enable_kill_switch()
        core_mv.enable_kill_switch()
        core_ep.enable_kill_switch()
        core_ph.enable_kill_switch()
        core_xv.enable_kill_switch()
        core_xh.enable_kill_switch()
        core_xn.enable_kill_switch()
        core_yp.enable_kill_switch()

    # Instantiate clients with their site-specific cores
    mv_client = mv_Client(core=core_mv)
    ep_client = ep_Client(core=core_ep)
    ph_client = ph_Client(core=core_ph, use_webmaster_api=True)
    xv_client = xv_Client(core=core_xv)
    xh_client = xh_Client(core=core_xh)
    sp_client = sp_Client(core=core_sp)
    hq_client = hq_Client(core=core_hq)
    xn_client = xn_Client(core=core_xn)
    yp_client = yp_Client(core=core_yp)

    core = core_common

def origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}/"

def enable_logging(level=logging.DEBUG, log_file="APIs.log", log_ip=http_log_ip, log_port=http_log_port):
    global mv_client, ep_client, ph_client, xv_client, xh_client, sp_client, hq_client, xn_client
    pass # Need to implement that later lol

logger = setup_logger(name="Porn Fetch - [shared_functions]", log_file="PornFetch.log", level=logging.DEBUG, http_ip=http_log_ip, http_port=http_log_port)


"""
The following are the sections and options for the configuration file. Please don't change anything here, 
as they are indeed needed for the main applications!
"""

# TODO: Implement logging
sections = ["Setup", "Performance", "Video", "UI", "Sponsoring", "Android"]

options_setup = ["license_accepted", "install", "update_checks", "internet_checks", "anonymous_mode", "disclaimer_shown", "activate_logging", "first_run_cli"]
options_performance = ["semaphore", "threading_mode", "workers", "timeout", "retries", "speed_limit", "processing_delay"]
options_video = ["quality", "output_path", "directory_system", "result_limit", "delay", "skip_existing_files", "model_videos", "supress_errors",
                 "video_id_as_filename", "direct_download", "write_metadata"]
options_ui = ["language", "custom_font", "font_size"]
options_sponsoring = ["downloaded_videos", "notice_shown"]
options_android = ["warning_shown"]


pornhub_pattern = re.compile(r'(.*?)pornhub(.*)') # can also be .org
hqporner_pattern = re.compile(r'(.*?)hqporner.com(.*)')
xnxx_pattern = re.compile(r'(.*?)xnxx.com(.*)')
xvideos_pattern = re.compile(r'(.*?)xvideos.com(.*)')
eporner_pattern = re.compile(r'(.*?)eporner.com(.*)')
missav_pattern = re.compile(r'(.*?)missav(.*?)')
xhamster_pattern = re.compile(r'(.*?)xhamster(.*?)')
spankbang_pattern = re.compile(r'(.*?)spankbang(.*?)')
youporn_pattern = re.compile(r'(.*?)youporn(.*?)')


default_configuration = f"""[Setup]
license_accepted = false
install = unknown
update_checks = true
internet_checks = true
anonymous_mode = false
disclaimer_shown = false
activate_logging = not_set
first_run_cli = true

[Performance]
threading_mode = threaded
semaphore = 2
workers = 20
timeout = 10
retries = 4
speed_limit = 0
processing_delay = 0

[Video]
quality = best
output_path = ./
directory_system = false
result_limit = 50
delay = 0
skip_existing_files = true
model_videos = both
supress_errors = false
video_id_as_filename = false
direct_download = false
write_metadata = true

[UI]
language = system
custom_font = true
font_size = 14

[Sponsoring]
downloaded_videos = 0
notice_shown = false

[Android]
warning_shown = false
"""


def check_video(url, is_url=True):
    if is_url:
        if hqporner_pattern.search(str(url)) and not isinstance(url, hq_Video):
            print("Returning HQPorner Video! ")
            return hq_client.get_video(url)

        elif eporner_pattern.search(str(url)) and not isinstance(url, ep_Video):
            return ep_client.get_video(url, enable_html_scraping=True)

        elif xnxx_pattern.search(str(url)) and not isinstance(url, xn_Video):
            return xn_client.get_video(url)

        elif xvideos_pattern.search(str(url)) and not isinstance(url, xv_Video):
            return xv_client.get_video(url)

        elif missav_pattern.search(str(url)) and not isinstance(url, mv_Video):
            return mv_client.get_video(url)

        elif xhamster_pattern.search(str(url)) and not isinstance(url, xh_Video):
            return xh_client.get_video(url)

        elif spankbang_pattern.search(str(url)) and not isinstance(url, sp_Video):
            return sp_client.get_video(url)

        elif youporn_pattern.search(str(url)) and not isinstance(url, yp_Video):
            return yp_client.get_video(url)

        if isinstance(url, ph_Video):
            url.fetch("page@") # If url is a PornHub Video object it does have the `fetch` method
            return url

        elif isinstance(url, hq_Video):
            return url

        elif isinstance(url, ep_Video):
            return url

        elif isinstance(url, xn_Video):
            return url

        elif isinstance(url, xv_Video):
            return url

        elif isinstance(url, xh_Video):
            return url

        elif isinstance(url, mv_Video):
            return url

        elif isinstance(url, sp_Video):
            return url

        elif isinstance(url, yp_Video):
            return url

        elif isinstance(url, str) and not str(url).endswith(".html"):
            video = ph_client.get(url) # PornHub client
            video.fetch("page@")
            return video

        else:
            return False

    else:
        pass

        # TODO


def setup_config_file(force=False):
    if os.path.isfile("config.ini") is False or force:
        logger.warning("Configuration file is broken / not found. Automatically creating a new one with default "
                     "configuration")

        try:
            with open("config.ini", "w") as config_file:
                config_file.write(default_configuration)

        except PermissionError:
            logger.error("Can't write to config.ini due to permission issues.")
            exit(1)

    else:
        config = ConfigParser()
        config.read("config.ini")

        for idx, section in enumerate(sections):
            if idx == 0:
                for option in options_setup:
                    if not config.has_option(section, option):
                        setup_config_file(force=True)
                        print("ISSUE 1")

            if idx == 1:
                for option in options_performance:
                    if not config.has_option(section, option):
                        setup_config_file(force=True)
                        print("ISSUE 2")

            if idx == 2:
                for option in options_video:
                    if not config.has_option(section, option):
                        print(f"Config mismatch: {section} | {option}")
                        setup_config_file(force=True)
                        print("ISSUE 4")

            if idx == 3:
                for option in options_ui:
                    if not config.has_option(section, option):
                        setup_config_file(force=True)
                        print("ISSUE 5")

            if idx == 4:
                for option in options_sponsoring:
                    if not config.has_option(section, option):
                        setup_config_file(force=True)
                        print("ISSUE 6")

            if idx == 5:
                for option in options_android:
                    if not config.has_option(section, option):
                        print(f"ISSUE 7, {section} {option}")
                        setup_config_file(force=True)



def load_video_attributes(video):
    """
    Loads all relevant video attributes, including qualities, after ensuring
    the video object's data has been fetched from the provider.
    This function is designed to be the single source of truth for video metadata.
    """
    title = "N/A"
    author = "N/A"
    length = 0
    tags = []
    publish_date = "N/A"
    thumbnail = None
    qualities = []

    try:
        if isinstance(video, ph_Video):
            video.refresh()
            title = video.title
            author = video.author.name if hasattr(video.author, 'name') else video.pornstars[0]
            length = video.duration.seconds
            tags = [tag.name for tag in video.tags]
            publish_date = video.date
            thumbnail = video.image.url

            # Refactored quality fetching for PornHub with detailed logging
            qualities = []
            logger.debug(f"Starting quality fetch for PornHub video: '{title}'")

            # Attempt 1: Check pre-populated video.qualities (most common)
            if hasattr(video, 'qualities') and isinstance(video.qualities, tuple) and video.qualities:
                logger.debug("Attempt 1: Found 'video.qualities' tuple.")
                qualities = [q.quality for q in video.qualities if hasattr(q, 'quality')]
                logger.debug(f"Extracted qualities: {qualities}")

            # Attempt 2: Try calling video.get_qualities()
            if not qualities and hasattr(video, 'get_qualities'):
                logger.debug("Attempt 2: Calling 'video.get_qualities()'.")
                try:
                    retrieved_qualities = video.get_qualities()
                    if retrieved_qualities:
                        qualities = [q.quality for q in retrieved_qualities if hasattr(q, 'quality')]
                        logger.debug(f"Extracted qualities: {qualities}")
                    else:
                        logger.debug("'video.get_qualities()' returned empty list.")
                except Exception as e:
                    logger.warning(f"'video.get_qualities()' failed for PornHub: {e}", exc_info=True)

            # Attempt 3: Try forcing a refresh with video.fetch_qualities()
            if not qualities and hasattr(video, 'fetch_qualities'):
                logger.debug("Attempt 3: Calling 'video.fetch_qualities()'.")
                try:
                    video.fetch_qualities()
                    if hasattr(video, 'qualities') and isinstance(video.qualities, tuple) and video.qualities:
                        logger.debug("Found 'video.qualities' after fetching.")
                        qualities = [q.quality for q in video.qualities if hasattr(q, 'quality')]
                        logger.debug(f"Extracted qualities: {qualities}")
                    else:
                        logger.debug("'video.fetch_qualities()' did not populate qualities.")
                except Exception as e:
                    logger.warning(f"'video.fetch_qualities()' failed for PornHub: {e}", exc_info=True)

            # Attempt 4: Fallback for other formats of the qualities attribute
            if not qualities and hasattr(video, 'qualities') and video.qualities:
                logger.debug("Attempt 4: Checking 'video.qualities' for other formats (dict/list).")
                if isinstance(video.qualities, dict):
                    qualities = list(video.qualities.keys())
                    logger.debug(f"Extracted qualities from dict: {qualities}")
                elif isinstance(video.qualities, (list, tuple)):
                    qualities = [str(q) for q in video.qualities]
                    logger.debug(f"Extracted qualities from list/tuple: {qualities}")

            if qualities:
                logger.info(f"Successfully fetched qualities for '{title}': {qualities}")
            else:
                logger.warning(f"Could not fetch any qualities for PornHub video: '{title}'")

        elif isinstance(video, (xv_Video, xn_Video)):
            if hasattr(video, 'fetch'): video.fetch()
            title = video.title
            author = video.author.name if hasattr(video.author, 'name') else video.author
            length = video.length
            tags = video.tags
            publish_date = video.publish_date
            thumbnail = video.thumbnail_url[0] if isinstance(video.thumbnail_url, list) else video.thumbnail_url

            # Refactored quality fetching for XVideos/XNXX with detailed logging
            qualities = []
            provider_name = video.__class__.__name__
            logger.debug(f"Starting quality fetch for {provider_name} video: '{title}'")

            # Attempt 1: Call get_available_qualities()
            if hasattr(video, 'get_available_qualities'):
                logger.debug("Attempt 1: Calling 'get_available_qualities()'.")
                try:
                    retrieved_qualities = video.get_available_qualities()
                    if isinstance(retrieved_qualities, (list, tuple)) and retrieved_qualities:
                        qualities = [str(q) for q in retrieved_qualities]
                        logger.debug(f"Extracted qualities: {qualities}")
                except Exception as e:
                    logger.warning(f"'get_available_qualities' failed for {provider_name}: {e}", exc_info=True)

            # Attempt 2: Check 'qualities' attribute
            if not qualities and hasattr(video, 'qualities') and video.qualities:
                logger.debug("Attempt 2: Checking 'qualities' attribute.")
                if isinstance(video.qualities, dict):
                    qualities = list(video.qualities.keys())
                    logger.debug(f"Extracted qualities from dict: {qualities}")
                elif isinstance(video.qualities, (list, tuple)):
                    qualities = [str(q) for q in video.qualities]
                    logger.debug(f"Extracted qualities from list/tuple: {qualities}")

            # Attempt 3: Check 'formats' attribute
            if not qualities and hasattr(video, 'formats') and video.formats:
                logger.debug("Attempt 3: Checking 'formats' attribute.")
                formats = video.formats
                if isinstance(formats, dict):
                    qualities = [str(q) for q in formats.keys()]
                    logger.debug(f"Extracted qualities from formats dict: {qualities}")
                elif isinstance(formats, (list, tuple)):
                    qualities = [str(f.get('quality', f.get('format', f))) for f in formats if isinstance(f, dict)]
                    logger.debug(f"Extracted qualities from formats list: {qualities}")

            # Attempt 4: Specific check for XNXX 'highest_quality' attribute
            if not qualities and isinstance(video, xn_Video) and hasattr(video, 'highest_quality') and video.highest_quality:
                logger.debug("Attempt 4: Found 'highest_quality' attribute for XNXX video.")
                qualities = [video.highest_quality]
                logger.debug(f"Extracted quality: {qualities}")

            if qualities:
                logger.info(f"Successfully fetched qualities for '{title}': {qualities}")
            else:
                logger.warning(f"Could not fetch an explicit quality list for {provider_name} video '{title}'. Downloader will rely on abstract quality settings.")

        elif isinstance(video, ep_Video):
            if hasattr(video, 'fetch'):
                video.fetch()
            title = video.title
            author = video.author
            length = video.length_minutes * 60 if video.length_minutes else 0
            tags = video.tags
            publish_date = video.publish_date
            thumbnail = video.thumbnail

            # Refactored quality fetching for Eporner with detailed logging
            qualities = []
            logger.debug(f"Starting quality fetch for Eporner video: '{title}'")

            # Attempt 1: Check for a 'qualities' or 'available_qualities' attribute
            logger.debug("Attempt 1: Checking for 'video.qualities' or 'video.available_qualities'.")
            if hasattr(video, 'qualities') and video.qualities:
                if isinstance(video.qualities, dict):
                    qualities = list(video.qualities.values()) # Eporner sometimes uses a dict of {id: name}
                    logger.debug(f"Extracted qualities from dict: {qualities}")
                elif isinstance(video.qualities, (list, tuple)):
                    qualities = [str(q) for q in video.qualities]
                    logger.debug(f"Extracted qualities from list/tuple: {qualities}")
            elif hasattr(video, 'available_qualities') and video.available_qualities:
                 if isinstance(video.available_qualities, (list, tuple)):
                    qualities = list(video.available_qualities)
                    logger.debug(f"Extracted qualities from 'available_qualities': {qualities}")

            if qualities:
                logger.info(f"Successfully fetched qualities for '{title}': {qualities}")
            else:
                # Fallback to documented abstract qualities if no explicit list is found
                logger.warning(f"No explicit quality list found for Eporner video '{title}'. Falling back to documented abstract qualities.")
                qualities = ['best', 'half', 'worst']

        elif isinstance(video, hq_Video):
            if hasattr(video, 'fetch'): video.fetch()
            title = video.title
            author = video.pornstars[0] if video.pornstars else "N/A"
            length = video.length
            tags = video.tags
            publish_date = video.publish_date
            thumbnail = video.get_thumbnails()[0] if video.get_thumbnails() else None

            # Refactored quality fetching for HQPorner with detailed logging
            qualities = []
            logger.debug(f"Starting quality fetch for HQPorner video: '{title}'")

            # Attempt 1: Check for 'video.video_qualities' as per documentation
            logger.debug("Attempt 1: Checking for 'video.video_qualities' list.")
            if hasattr(video, 'video_qualities') and video.video_qualities:
                if isinstance(video.video_qualities, (list, tuple)):
                    qualities = [str(q) for q in video.video_qualities]
                    logger.debug(f"Extracted qualities from 'video_qualities': {qualities}")

            # Attempt 2: Fallback to checking 'video.qualities' (often a dict)
            if not qualities and hasattr(video, 'qualities') and video.qualities:
                logger.debug("Attempt 2: Checking for 'video.qualities' (dict/list).")
                if isinstance(video.qualities, dict):
                    # Format is often {'720p': 'url', ...}, so we want the keys
                    qualities = list(video.qualities.keys())
                    logger.debug(f"Extracted qualities from 'qualities' dict: {qualities}")
                elif isinstance(video.qualities, (list, tuple)):
                    qualities = [str(q) for q in video.qualities]
                    logger.debug(f"Extracted qualities from 'qualities' list/tuple: {qualities}")

            # Attempt 3: Fallback to checking 'streams'
            if not qualities and hasattr(video, 'streams') and video.streams:
                logger.debug("Attempt 3: Checking for 'video.streams'.")
                if isinstance(video.streams, dict):
                    qualities = [str(q) for q in video.streams.keys()]
                    logger.debug(f"Extracted qualities from 'streams' dict: {qualities}")
                elif isinstance(video.streams, (list, tuple)):
                    stream_list = video.streams
                    qualities = [str(s.get('quality', s.get('format', s))) for s in stream_list if isinstance(s, dict)]
                    logger.debug(f"Extracted qualities from 'streams' list: {qualities}")

            if qualities:
                logger.info(f"Successfully fetched qualities for '{title}': {qualities}")
            else:
                logger.warning(f"Could not fetch an explicit quality list for HQPorner video '{title}'. Downloader will rely on abstract quality settings (e.g., 'best').")

        elif isinstance(video, (mv_Video, xh_Video, sp_Video, yp_Video)):
            # Generic handling for providers with similar structures
            if hasattr(video, 'fetch'): video.fetch()
            title = video.title
            author = video.author if hasattr(video, 'author') else "N/A"
            length = video.length if hasattr(video, 'length') else 0
            tags = video.tags if hasattr(video, 'tags') else []
            publish_date = video.publish_date if hasattr(video, 'publish_date') else "N/A"
            thumbnail = video.thumbnail

            # Refactored generic quality fetching for other providers with detailed logging
            qualities = []
            provider_name = video.__class__.__name__
            logger.debug(f"Starting quality fetch for {provider_name} video: '{title}'")

            # Attempt 1: Check for a documented 'video_qualities' attribute (e.g., Spankbang)
            if hasattr(video, 'video_qualities') and video.video_qualities:
                 logger.debug("Attempt 1: Checking for 'video_qualities' attribute.")
                 if isinstance(video.video_qualities, (list, tuple)):
                    qualities = [str(q) for q in video.video_qualities]
                    logger.debug(f"Extracted qualities: {qualities}")

            # Attempt 2: Check for a 'get_available_qualities' method
            if not qualities and hasattr(video, 'get_available_qualities'):
                logger.debug("Attempt 2: Calling 'get_available_qualities()'.")
                try:
                    retrieved_qualities = video.get_available_qualities()
                    if isinstance(retrieved_qualities, dict):
                        qualities = list(retrieved_qualities.keys())
                    elif isinstance(retrieved_qualities, (list, tuple)):
                        qualities = [str(q) for q in retrieved_qualities]
                    logger.debug(f"Extracted qualities: {qualities}")
                except Exception as e:
                    logger.warning(f"'get_available_qualities' failed for {provider_name}: {e}", exc_info=True)

            # Attempt 3: Check for a generic 'qualities' attribute
            if not qualities and hasattr(video, 'qualities') and video.qualities:
                logger.debug("Attempt 3: Checking for 'qualities' attribute.")
                if isinstance(video.qualities, dict):
                    qualities = list(video.qualities.keys())
                elif isinstance(video.qualities, (list, tuple)):
                    qualities = [str(q) for q in video.qualities]
                logger.debug(f"Extracted qualities: {qualities}")

            # Attempt 4: Check for a generic 'formats' attribute
            if not qualities and hasattr(video, 'formats') and video.formats:
                logger.debug("Attempt 4: Checking for 'formats' attribute.")
                formats = video.formats
                if isinstance(formats, dict):
                    qualities = [str(q) for q in formats.keys()]
                elif isinstance(formats, (list, tuple)):
                    qualities = [str(f.get('quality', f.get('format', f))) for f in formats if isinstance(f, dict)]
                logger.debug(f"Extracted qualities: {qualities}")

            if qualities:
                logger.info(f"Successfully fetched qualities for '{title}': {qualities}")
            else:
                logger.warning(f"Could not fetch an explicit quality list for {provider_name} video '{title}'. Downloader will rely on abstract quality settings.")

        else:
            logger.error(f"Unsupported video object type: {type(video).__name__}")
            raise TypeError(f"Unsupported video object type: {type(video).__name__}")

        # Ensure tags are a list of strings
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(',')]

        # Fallback quality options if none were found
        if not qualities:
            logger.warning(f"No qualities found for video '{title}', providing default options")
            # Use API-appropriate quality strings based on video type
            if isinstance(video, ep_Video):
                qualities = ['best', 'half', 'worst']  # Eporner API format
            else:
                qualities = ['720p', '480p', '360p']  # Default resolution format
            
        data = {
            "title": title,
            "author": author,
            "length": _parse_duration_to_seconds(length),
            "tags": tags,
            "publish_date": str(publish_date) if publish_date else "N/A",
            "thumbnail": thumbnail,
            "qualities": qualities
        }
        logger.debug(f"Loaded video data for '{title}': {data}")
        return data

    except Exception as e:
        logger.error(f"Failed to load attributes for video '{getattr(video, 'url', 'N/A')}'. Type: {type(video).__name__}. Error: {e}", exc_info=True)
        # Return a default structure on error to prevent downstream crashes
        return {
            "title": "Error: Could not load data", "author": "N/A", "length": 0,
            "tags": [], "publish_date": "N/A", "thumbnail": None, "qualities": ['720p', '480p', '360p']
        }

def _parse_duration_to_seconds(duration):
    """
    Parses various duration formats (e.g., '17m 16s', '15 min', raw seconds)
    into a total number of seconds.
    """
    if isinstance(duration, int):
        return duration
    if isinstance(duration, float):
        return int(duration)
    if isinstance(duration, str):
        duration = duration.lower()
        total_seconds = 0
        if 'h' in duration:
            match = re.search(r'(\d+)\s*h', duration)
            if match: total_seconds += int(match.group(1)) * 3600
        if 'm' in duration:
            match = re.search(r'(\d+)\s*m', duration)
            if match: total_seconds += int(match.group(1)) * 60
        if 's' in duration:
            match = re.search(r'(\d+)\s*s', duration)
            if match: total_seconds += int(match.group(1))

        # If no units found, assume it's just seconds or minutes:seconds
        if total_seconds == 0:
            if ':' in duration:
                parts = duration.split(':')
                if len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif duration.isdigit():
                # Ambiguous case: could be minutes or seconds. Assume seconds.
                return int(duration)
        return total_seconds
    return 0


def write_tags(path, data: dict): # Using core from Porn Fetch to keep proxy support
    comment = "Downloaded with Porn Fetch (GPLv3)"
    genre = "Porn"

    title = data.get("title")
    artist = data.get("author")
    date = data.get("publish_date")
    thumbnail = data.get("thumbnail")
    logging.debug("Tags [1/3]")

    audio = MP4(path)
    audio.tags["\xa9nam"] = str(title)
    audio.tags["\xa9ART"] = str(artist)
    audio.tags["\xa9cmt"] = str(comment)
    audio.tags["\xa9gen"] = str(genre)
    audio.tags["\xa9day"] = str(date)

    logging.debug("Tags: [2/3] - Writing Thumbnail")

    try:
        content = BaseCore().fetch(url=thumbnail, get_bytes=True)
        cover = MP4Cover(content, imageformat=MP4Cover.FORMAT_JPEG)
        audio.tags["covr"] = [cover] # Yes, it needs to be in a list

    except Exception as e:
        logger.error("Could not download / write thumbnail into the metadata tags of the video. Please report the"
                     f"following error on GitHub: {e} - Image URL: {thumbnail}")

    audio.save()
    logging.debug("Tags: [3/3] ✔")


