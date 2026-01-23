import os
import re
import requests
from dotenv import load_dotenv
from slack_bolt.adapter.socket_mode import SocketModeHandler 
from slack_bolt import App
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging
logging.basicConfig(level=logging.DEBUG)


load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
LOGISTICS_CHANNEL = "C09AVKTL8JF"


app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
)
app.logger.setLevel(logging.DEBUG)

def extract_channel_id_from_text(text: str):
    if not text:
        return None
    m = re.search(r"<#([A-Z0-9]+)(?:\|[^>]+)?>", text)
    return m.group(1) if m else None

def extract_channel_id_from_blocks(blocks):
    if not blocks:
        return None
    for b in blocks:
        for el in b.get("elements", []):
            for inner in el.get("elements", []):
                if inner.get("type") == "channel" and inner.get("channel_id"):
                    return inner["channel_id"]
    return None

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

    logger.info(
        f"process_image_event: channel={event.get('channel')} subtype={event.get('subtype')} ts={event.get('ts')}"
    )

    if event.get("channel") != LOGISTICS_CHANNEL:
        logger.info(f"Skip: not logistics channel (got {event.get('channel')} expected {LOGISTICS_CHANNEL})")
        return

    if event.get("subtype") == "bot_message":
        logger.info("Skip: bot_message")
        return

    files = event.get("files", [])
    logger.info(f"files_count={len(files)}")

    if not files:
        logger.info("Skip: no files")
        return

    text = event.get("text", "") or ""
    blocks = event.get("blocks")
    destination = extract_channel_id_from_text(text) or extract_channel_id_from_blocks(blocks)

    logger.info(f"raw_text='{text}'")
    logger.info(f"resolved_destination={destination}")

    if not destination:
        logger.info("Skip: no destination channel found in text/blocks")
        return
    
    for f in files:
        mimetype = f.get("mimetype")
        logger.info(f"File candidate: id={f.get('id')} name={f.get('name')} mimetype={mimetype}")

        if not mimetype:
            logger.info("Skip file: mimetype is missing")
            continue

        if not mimetype.startswith("image/"):
            logger.info("Skip file: not an image")
            continue

        file_url = f.get("url_private_download") or f.get("url_private")
        logger.info(f"Downloading from: {file_url}")

        filename = f.get("name") or f.get("title") or "image.jpg"

        try:
            headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
            resp = requests.get(file_url, headers=headers, timeout=30)
            logger.info(f"Download status={resp.status_code} bytes={len(resp.content)}")
            resp.raise_for_status()

            logger.info(f"Uploading to channel={destination} filename={filename}")

            upload_resp = client.files_upload_v2(
                channel=destination,
                file=resp.content,
                filename=filename,
                initial_comment=f"Forwarded from <#{event.get('channel')}>:\n{event.get('text')}",
            )

            logger.info(f"Upload OK: {upload_resp}")

        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            logger.error(f"Slack API response: {e.response.data}")
        except Exception as e:
            logger.error(f"General error while forwarding file: {e}", exc_info=True)


    try:
        ch_info = client.conversations_info(channel=destination)
        logger.info(f"destination_name={ch_info['channel']['name']} is_private={ch_info['channel'].get('is_private')}")
    except SlackApiError as e:
        logger.error(f"conversations_info failed: {e.response['error']}")
        return



@app.event({"type": "message", "subtype": "file_share"})
def handle_file_share(event, client: WebClient, logger, ack):
    return process_image_event(event, client, logger)


@app.event("message")
def handle_message_events(event, client: WebClient, logger, ack):
    logger.info(f"INCOMING EVENT subtype={event.get('subtype')} channel={event.get('channel')} text={event.get('text')} at {event.get('ts')}")
    process_image_event(event, client, logger)
    if event.get("subtype") is None:  
        process_image_event(event, client, logger)


if __name__ == "__main__":
    app_token = os.getenv("SLACK_APP_TOKEN")
    handler = SocketModeHandler(app, app_token)
    print("⚡ Bot app is running and handlers are loaded!")
    handler.start()