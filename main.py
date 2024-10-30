import os
import requests
import feedparser
import argparse
import sqlite3
import threading
from googleapiclient.discovery import build
from datetime import datetime, timedelta, UTC
from db import create_connection
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.job import Job

HOURS_FROM_PUBLISH = [2, 5, 24, 7 * 24, 30 * 24]

try:
    API_KEY = os.environ["YT_API_KEY"]
except KeyError:
    raise ValueError("YT_API_KEY not set")

TRENDING_MULTIPLIER = {
    2: 2,
    5: 5,
    24: 10,
    7 * 24: 15,
    30 * 24: 20,
}  # from 2 to 20x based on hours from publish

AVG_WINDOW_SIZE = 5  # 5 videos

db_lock = threading.Lock()

telegram_api_key = None
telegram_chat_id = None
jobs: list[Job] = []


def send_message(message):
    resp = requests.post(
        f"https://api.telegram.org/bot{telegram_api_key}/sendMessage",
        data={"chat_id": telegram_chat_id, "text": message},
    )

    resp.raise_for_status()


def get_video_comments(video_id):
    # Build the YouTube service
    youtube = build("youtube", "v3", developerKey=API_KEY)

    # Initialize a list to store comments
    comments = []

    # Request the comments
    request = youtube.commentThreads().list(
        part="snippet", videoId=video_id, textFormat="plainText"
    )

    while request:
        response = request.execute()

        # Extract comments from the response
        for item in response["items"]:
            comment = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(comment)

        # Check if there is a next page
        request = youtube.commentThreads().list_next(request, response)

    return comments


def get_video_details(video_id):
    # Build the YouTube service
    youtube = build("youtube", "v3", developerKey=API_KEY)

    # Request video details
    request = youtube.videos().list(part="statistics", id=video_id)
    response = request.execute()

    # Extract details from the response
    if response["items"]:
        item = response["items"][0]
        stats = item["statistics"]

        view_count = stats.get("viewCount", 0)
        like_count = stats.get("likeCount", 0)
        comment_count = stats.get("commentCount", 0)

        return {
            "views": view_count,
            "likes": like_count,
            "comments": comment_count,
        }
    else:
        return None


def get_channel_id_from_url(channel_url):
    # Extract the handle from the URL
    handle = channel_url.split("@")[-1]

    # Build the YouTube service
    youtube = build("youtube", "v3", developerKey=API_KEY)

    # Request channel details using the handle
    request = youtube.channels().list(part="id", forHandle=handle)
    response = request.execute()

    # Extract the channel ID from the response
    if response["items"]:
        return response["items"][0]["id"]
    else:
        raise ValueError("Channel not found for the given handle")


def get_latest_videos(channel_id, max_entries=5):
    # Build the YouTube service
    feed = feedparser.parse(
        f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    )
    videos = []
    for item in feed["entries"][:max_entries]:
        video_data = {
            "video_id": item["yt_videoid"],
            "title": item["title"],
            "publish_date": datetime.fromisoformat(item["published"]),
        }
        videos.append(video_data)

    return videos


def add_channel(channel_id, url, thread_conn: sqlite3.Connection):
    cursor = thread_conn.cursor()
    cursor.execute("INSERT INTO channels (yt_id, url) VALUES (?, ?)", (channel_id, url))
    thread_conn.commit()


def remove_channel(channel_url, thread_conn: sqlite3.Connection):
    cursor = thread_conn.cursor()
    cursor.execute("DELETE FROM channels WHERE url = ?", (channel_url,))
    thread_conn.commit()


def add_video(
    video_id, channel_id, title, publish_date, thread_conn: sqlite3.Connection
):
    cursor = thread_conn.cursor()
    cursor.execute(
        "INSERT INTO videos (yt_id, channel_yt_id, title, publish_date) VALUES (?, ?, ?, ?)",
        (video_id, channel_id, title, publish_date),
    )
    thread_conn.commit()


def add_video_meta(
    video_id,
    views,
    likes,
    comments,
    hours_from_publish,
    thread_conn: sqlite3.Connection,
):
    cursor = thread_conn.cursor()
    cursor.execute(
        "INSERT INTO video_meta (video_yt_id, views, likes, comments, hours_from_publish) VALUES (?, ?, ?, ?, ?)",
        (video_id, views, likes, comments, hours_from_publish),
    )
    thread_conn.commit()


def check_video(video_id, channel_id, hours_from_publish):

    thread_conn = create_connection()
    thread_cursor = thread_conn.cursor()
    print(
        f"Checking video {video_id} for channel {channel_id} in {hours_from_publish} hours"
    )
    meta = get_video_details(video_id)

    with db_lock:
        add_video_meta(
            video_id,
            meta["views"],
            meta["likes"],
            meta["comments"],
            hours_from_publish,
            thread_conn,
        )

        if detect_trending(channel_id, hours_from_publish, meta["views"], thread_conn):
            print(f"Trending video {video_id} for channel {channel_id}!!!")
            if telegram_chat_id:
                send_message(
                    f"Trending video {video_id} for channel {channel_id}!!!",
                )
            thread_cursor.execute(
                "INSERT INTO trending_videos (video_yt_id, channel_yt_id) VALUES (?, ?)",
                (video_id, channel_id),
            )
            thread_conn.commit()

        update_channel_stats(channel_id, thread_conn)


def detect_trending(
    channel_id, hours_from_publish, views, thread_conn: sqlite3.Connection
):
    cursor = thread_conn.cursor()
    cursor.execute(
        f"""SELECT avg_views_{hours_from_publish}h FROM channels WHERE yt_id = ?""",
        (channel_id,),
    )
    avg_views = cursor.fetchone()[0]

    if not avg_views:
        return False

    return views >= avg_views * TRENDING_MULTIPLIER[hours_from_publish]


def update_channel_stats(channel_id, thread_conn: sqlite3.Connection):
    cursor = thread_conn.cursor()
    cursor.execute(
        f"""SELECT SUM(views) / COUNT(*) as avg_views, hours_from_publish FROM video_meta WHERE video_yt_id IN (SELECT yt_id FROM videos WHERE channel_yt_id = ? ORDER BY publish_date DESC LIMIT ?) GROUP BY hours_from_publish""",
        (channel_id, AVG_WINDOW_SIZE),
    )

    for stat in cursor.fetchall():
        cursor.execute(
            f"UPDATE channels SET avg_views_{stat[1]}h = ? WHERE yt_id = ?",
            (stat[0], channel_id),
        )
    thread_conn.commit()


def video_exists(video_id, thread_conn: sqlite3.Connection):
    cursor = thread_conn.cursor()
    cursor.execute("SELECT * FROM videos WHERE yt_id = ?", (video_id,))
    return cursor.fetchone() is not None


def print_jobs(scheduler: BackgroundScheduler):
    """Prints active scheduler jobs in a formatted table."""
    jobs = scheduler.get_jobs()

    if not jobs:
        print("No active jobs.")
        return

    # Define table headers
    headers = ["Job ID", "Next Run Time", "Function", "Arguments"]
    # Define column widths
    col_widths = [20, 25, 30, 30]

    # Create header row
    header_row = "".join(
        f"{header:<{width}}" for header, width in zip(headers, col_widths)
    )
    separator = "-" * sum(col_widths)

    print(separator)
    print(header_row)
    print(separator)

    # Create each job row
    for job in jobs:
        job_id = job.id[:18] + "..." if len(job.id) > 20 else job.id
        next_run = (
            job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
            if job.next_run_time
            else "N/A"
        )
        func_name = (
            job.func.__name__ if hasattr(job.func, "__name__") else str(job.func)
        )
        func_name = func_name[:28] + "..." if len(func_name) > 30 else func_name
        args = (
            ", ".join(map(str, job.args))[:28] + "..."
            if len(", ".join(map(str, job.args))) > 30
            else ", ".join(map(str, job.args))
        )

        row = f"{job_id:<{col_widths[0]}}{next_run:<{col_widths[1]}}{func_name:<{col_widths[2]}}{args:<{col_widths[3]}}"
        print(row)

    print(separator)


def schedule_checks(
    video_id,
    channel_id,
    publish_date: str,
    scheduler: BackgroundScheduler,
):
    for interval in HOURS_FROM_PUBLISH:
        next_check = publish_date + timedelta(hours=interval)
        job = scheduler.add_job(
            check_video,
            "date",
            run_date=next_check,
            timezone="UTC",
            args=[video_id, channel_id, interval],
        )
        jobs.append(job)

    print_jobs(scheduler)


def poll_channels(
    scheduler: BackgroundScheduler, interval: int, thread_conn: sqlite3.Connection
):
    cursor = thread_conn.cursor()
    try:
        while True:
            channels = cursor.execute("SELECT * FROM channels").fetchall()
            for channel in channels:
                videos = get_latest_videos(channel[0], 5)
                for video in videos:

                    if datetime.now(UTC) - timedelta(hours=2) < video[
                        "publish_date"
                    ] and not video_exists(video["video_id"], thread_conn):
                        print(
                            f"Scheduling checks for video {video['video_id']} for channel {channel[0]}"
                        )
                        send_message(
                            f"New video was uploaded to {channel[1]}: {video['title']} https://www.youtube.com/watch?v={video['video_id']}"
                        )
                        add_video(
                            video["video_id"],
                            channel[0],
                            video["title"],
                            video["publish_date"],
                            thread_conn,
                        )
                        schedule_checks(
                            video["video_id"],
                            channel[0],
                            video["publish_date"],
                            scheduler,
                        )
            time.sleep(interval)

    except (KeyboardInterrupt, SystemExit):
        print("Polling stopped")
        scheduler.shutdown()
        thread_conn.close()
        quit(0)


def server(poll_interval: int, chat_id: str, api_key: str):
    global telegram_api_key, telegram_chat_id
    telegram_api_key = api_key
    telegram_chat_id = chat_id

    thread_conn = create_connection()
    scheduler = BackgroundScheduler()
    scheduler.start()

    poll_channels(scheduler, poll_interval, thread_conn)

    scheduler.shutdown()
    thread_conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["add-channel", "remove-channel", "run"],
        help="Command to run",
    )
    parser.add_argument("--channel_id", type=str, help="Add a channel to the database")
    parser.add_argument(
        "--poll_interval", type=int, help="Poll interval in seconds", default=60
    )
    parser.add_argument(
        "--telegram_chat_id", type=str, help="Telegram chat ID to send messages to"
    )
    args = parser.parse_args()

    if args.command == "add-channel" and args.channel_id:
        add_channel(args.channel_id)
    elif args.command == "remove-channel" and args.channel_id:
        remove_channel(args.channel_id)
    elif args.command == "run" and args.poll_interval:
        server(args.poll_interval, args.telegram_chat_id, args.telegram_api_key)
    else:
        parser.print_help()
