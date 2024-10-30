import os
import logging
import multiprocessing
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from main import add_channel, remove_channel, server, get_channel_id_from_url
from recommendations import get_recommendations
from db import create_connection, create_tables

TELEGRAM_API_KEY = os.environ.get("TELEGRAM_API_KEY")

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variable to store the server process
server_process = None
conn = None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.mention_markdown()}! Use /add_channel <channel_id> to add a channel, /remove_channel <channel_id> to remove a channel, and /start_server to start polling, /stop_server to stop polling, and /recommendations <video_id> to get recommendations for a video.",
    )


async def add_channel_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /add_channel <channel_id1> <channel_id2> ..."
        )
        return

    for channel_url in context.args:
        try:
            channel_id = get_channel_id_from_url(channel_url)
            add_channel(channel_id, channel_url, conn)
            await update.message.reply_text(
                f"Channel {channel_url} with id {channel_id} added."
            )
        except Exception as e:
            await update.message.reply_text(f"Failed to add channel {channel_url}: {e}")


async def remove_channel_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /remove_channel <channel_id>")
        return

    channel_url = context.args[0]
    remove_channel(channel_url, conn)
    await update.message.reply_text(f"Channel {channel_url} removed.")


async def start_server_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global server_process
    if server_process is not None and server_process.is_alive():
        await update.message.reply_text("Server is already running.")
        return

    poll_interval = int(os.environ.get("POLL_INTERVAL", 60))
    server_process = multiprocessing.Process(
        target=server,
        args=(poll_interval, update.message.chat_id, TELEGRAM_API_KEY),
    )
    server_process.start()
    await update.message.reply_text("Server started.")


async def stop_server_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    global server_process
    if server_process is not None:
        server_process.terminate()
        server_process.join()
        server_process = None
        await update.message.reply_text("Server stopped.")
    else:
        await update.message.reply_text("Server is not running.")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    await update.message.reply_text(update.message.text)


async def recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /recommendations <video_id>")
        return

    video_id = context.args[0]
    recommendations = get_recommendations(video_id)
    await update.message.reply_text(recommendations)


def main() -> None:
    """Start the bot."""
    global conn
    conn = create_connection()
    create_tables(conn)
    # Create the Application and pass it your bot's token.

    application = Application.builder().token(TELEGRAM_API_KEY).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_channel", add_channel_command))
    application.add_handler(CommandHandler("remove_channel", remove_channel_command))
    application.add_handler(CommandHandler("start_server", start_server_command))
    application.add_handler(CommandHandler("stop_server", stop_server_command))
    application.add_handler(CommandHandler("recommendations", recommendations))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()


if __name__ == "__main__":
    main()
