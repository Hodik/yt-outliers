import sqlite3

conn = sqlite3.connect("youtube.db")
cursor = conn.cursor()

cursor.execute(
    """CREATE TABLE IF NOT EXISTS channels (
        yt_id TEXT NOT NULL UNIQUE PRIMARY KEY,
        avg_views_2h INTEGER,
        avg_views_5h INTEGER,
        avg_views_24h INTEGER,
        avg_views_168h INTEGER,
        avg_views_720h INTEGER
    )"""
)

cursor.execute(
    """CREATE TABLE IF NOT EXISTS videos (
        yt_id TEXT PRIMARY KEY,
        title TEXT,
        channel_yt_id TEXT NOT NULL,
        publish_date DATETIME, 
        FOREIGN KEY (channel_yt_id) REFERENCES channels(yt_id)
    )"""
)


cursor.execute(
    """CREATE TABLE IF NOT EXISTS video_meta (
        video_yt_id TEXT NOT NULL,
        views INTEGER,
        likes INTEGER,
        comments INTEGER,
        hours_from_publish INTEGER,
        FOREIGN KEY (video_yt_id) REFERENCES videos(yt_id),
        PRIMARY KEY (video_yt_id, hours_from_publish)
    )"""
)

cursor.execute(
    """CREATE TABLE IF NOT EXISTS trending_videos (
        video_yt_id TEXT PRIMARY KEY,
        channel_yt_id TEXT NOT NULL,
        FOREIGN KEY (channel_yt_id) REFERENCES channels(yt_id),
        FOREIGN KEY (video_yt_id) REFERENCES videos(yt_id)
    )"""
)

conn.commit()
