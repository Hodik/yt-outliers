import os
import feedparser
import argparse
from googleapiclient.discovery import build
from datetime import datetime, timedelta, UTC
from db import cursor, conn
import time

from apscheduler.schedulers.background import BackgroundScheduler

HOURS_FROM_PUBLISH = [2, 5, 24, 7 * 24, 30 * 24]

try:
    API_KEY = os.environ["YT_API_KEY"]
except KeyError:
    raise ValueError("YT_API_KEY not set")

TRENDING_MULTIPLIER = 20  # 20x
AVG_WINDOW_SIZE = 5  # 5 videos


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


def add_channel(channel_id):
    cursor.execute("INSERT INTO channels (yt_id) VALUES (?)", (channel_id,))
    conn.commit()


def remove_channel(channel_id):
    cursor.execute("DELETE FROM channels WHERE yt_id = ?", (channel_id,))
    conn.commit()


def add_video(video_id, channel_id, title, publish_date):
    cursor.execute(
        "INSERT INTO videos (yt_id, channel_yt_id, title, publish_date) VALUES (?, ?, ?, ?)",
        (video_id, channel_id, title, publish_date),
    )
    conn.commit()


def add_video_meta(video_id, views, likes, comments, hours_from_publish):
    cursor.execute(
        "INSERT INTO video_meta (video_yt_id, views, likes, comments, hours_from_publish) VALUES (?, ?, ?, ?, ?)",
        (video_id, views, likes, comments, hours_from_publish),
    )
    conn.commit()


def check_video(video_id, channel_id, hours_from_publish):
    meta = get_video_details(video_id)
    add_video_meta(
        video_id, meta["views"], meta["likes"], meta["comments"], hours_from_publish
    )

    if detect_trending(channel_id, hours_from_publish, meta["views"]):
        print(f"Trending video {video_id} for channel {channel_id}!!!")
        cursor.execute(
            "INSERT INTO trending_videos (video_yt_id, channel_yt_id) VALUES (?, ?)",
            (video_id, channel_id),
        )
        conn.commit()

    update_channel_stats(channel_id)


def detect_trending(channel_id, hours_from_publish, views):
    cursor.execute(
        f"""SELECT avg_views_{hours_from_publish}h FROM channels WHERE yt_id = ?""",
        (channel_id,),
    )
    avg_views = cursor.fetchone()[0]
    return views >= avg_views * TRENDING_MULTIPLIER


def update_channel_stats(channel_id):

    cursor.execute(
        f"""SELECT SUM(views) / COUNT(*) as avg_views, hours_from_publish FROM video_meta WHERE video_yt_id IN (SELECT yt_id FROM videos WHERE channel_yt_id = ? ORDER BY publish_date DESC LIMIT ?) GROUP BY hours_from_publish""",
        (channel_id, AVG_WINDOW_SIZE),
    )

    for stat in cursor.fetchall():
        cursor.execute(
            f"UPDATE channels SET avg_views_{stat[1]}h = ? WHERE yt_id = ?",
            (stat[0], channel_id),
        )


def video_exists(video_id):
    cursor.execute("SELECT * FROM videos WHERE yt_id = ?", (video_id,))
    return cursor.fetchone() is not None


def schedule_checks(
    video_id, channel_id, publish_date: str, scheduler: BackgroundScheduler
):
    for interval in HOURS_FROM_PUBLISH:
        next_check = publish_date + timedelta(hours=interval)
        scheduler.add_job(
            check_video,
            "date",
            run_date=next_check,
            args=[video_id, channel_id, interval],
        )


def poll_channels(scheduler: BackgroundScheduler, interval: int):
    try:
        while True:
            channels = cursor.execute("SELECT * FROM channels").fetchall()
            for channel in channels:
                print(f"Polling channel {channel[0]}")
                videos = get_latest_videos(channel[0], 5)
                for video in videos:

                    if datetime.now(UTC) - timedelta(hours=2) < video[
                        "publish_date"
                    ] and not video_exists(video["video_id"]):
                        print(
                            f"Scheduling checks for video {video['video_id']} for channel {channel[0]}"
                        )
                        add_video(
                            video["video_id"],
                            channel[0],
                            video["title"],
                            video["publish_date"],
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
        conn.close()
        raise


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
    args = parser.parse_args()

    scheduler = BackgroundScheduler()
    scheduler.start()

    if args.command == "add-channel" and args.channel_id:
        add_channel(args.channel_id)
    elif args.command == "remove-channel" and args.channel_id:
        remove_channel(args.channel_id)
    elif args.command == "run" and args.poll_interval:
        poll_channels(scheduler, args.poll_interval)
    else:
        parser.print_help()

    scheduler.shutdown()
    conn.close()
