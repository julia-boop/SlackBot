import os
import requests
from dotenv import load_dotenv
from slack_bolt.adapter.socket_mode import SocketModeHandler 
from slack_bolt import App
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
LOGISTICS_CHANNEL = "C09AVKTL8JF"


app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
)

def normalize(name: str):
    name = name.lower()
    name = name.replace(" ", "-")
    name = name.replace("_", "-")
    name = name.replace("--", "-")
    return name.strip("-")

def get_channel_from_caption(client, caption: str):
    if not caption:
        return None
    
    normalized_caption = normalize(caption)

    response = client.conversations_list(limit=500)

    for ch in response["channels"]:
        if normalize(ch["name"]) in normalized_caption:
            return ch["id"]
        
    print(normalized_caption)
    
    return None

    

    
def process_image_event(event, client: WebClient, logger):

    if event.get("channel") != LOGISTICS_CHANNEL:
        return
    
    files = event.get("files", [])
    text = event.get("text", "")

    if not files:
        return

    if event.get("subtype") == "bot_message":
        return

    destination = get_channel_from_caption(client, text)

    if not destination:
        logger.info(f"No destination channel for caption: {text}")
        return

    source_channel = event.get("channel")
    logger.info(f"Forwarding files from {source_channel} to {destination} with text: {text}")

    for f in files:
        mimetype = f.get("mimetype", "")
        if not mimetype.startswith("image/"):
            continue

        file_url = f["url_private"]
        filename = f.get("name") or f.get("title") or "image.jpg"

        try:
            headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
            resp = requests.get(file_url, headers=headers)
            resp.raise_for_status()
            file_bytes = resp.content

            upload_resp = client.files_upload_v2(
                channel=destination,
                file=file_bytes,
                filename=filename,
                initial_comment=f"Forwarded from <#{source_channel}>:\n{text}"
                if text else f"Forwarded from <#{source_channel}>",
            )

            logger.info(f"Uploaded file to {destination}: {upload_resp['file']['id']}")

        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
        except Exception as e:
            logger.error(f"General error while forwarding file: {e}")


@app.event({"type": "message", "subtype": "file_share"})
def handle_file_share(event, client: WebClient, logger):
    return process_image_event(event, client, logger)


@app.event("message")
def handle_message_events(event, client: WebClient, logger):
    if event.get("subtype") is None:  
        process_image_event(event, client, logger)



if __name__ == "__main__":
    app_token = os.getenv("SLACK_APP_TOKEN")
    handler = SocketModeHandler(app, app_token)
    print("⚡ Bot app is running and handlers are loaded!")
    handler.start()