import os
import openai
from googleapiclient.discovery import build

try:
    API_KEY = os.environ["YT_API_KEY"]
except KeyError:
    raise ValueError("YT_API_KEY not set")


try:
    OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
except KeyError:
    raise ValueError("OPENAI_API_KEY not set")


client = openai.OpenAI(api_key=OPENAI_API_KEY)


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


def openai_completion(prompt: str):
    completion = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": prompt}]
    )
    return completion.choices[0].message.content


def get_recommendations(video_id: str):
    comments = get_video_comments(video_id)

    prompt = f"""Here are the comments for the YT video:
    
    {str(comments)}

    I want to create a similar video. Please create a list of recommendations for my video based on the comments. If there are any questions or requests from viewers that i can answer in the video, add them to the list. But if there are no questions or requests, don't recommend anything.
    """

    return openai_completion(prompt)
