import psutil
import time
import threading

# A thread-safe dictionary to hold the latest system stats.
# The 'lock' ensures that we don't have race conditions when updating/reading the stats.
system_stats = {
    "cpu_percent": 0.0,
    "memory_percent": 0.0,
    "lock": threading.Lock()
}

def stats_collector_thread():
    """
    A target function for a background thread that continuously collects
    system stats and updates the global 'system_stats' dictionary.
    """
    # The first call to cpu_percent should not have an interval and is used to initialize.
    psutil.cpu_percent()

    while True:
        # Calculate CPU usage over a 4-second interval. This is non-blocking
        # for other threads while it waits.
        cpu = psutil.cpu_percent(interval=4)
        mem = psutil.virtual_memory().percent

        with system_stats['lock']:
            system_stats['cpu_percent'] = cpu
            system_stats['memory_percent'] = mem

        # A small sleep to prevent this loop from running at 100% CPU
        # if the interval somehow returns immediately.
        time.sleep(1)