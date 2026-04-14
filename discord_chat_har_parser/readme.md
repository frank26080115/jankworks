There is a discord channel I need to extract data out of, I need insights on the conversation that spans years, as in this server, prominent users build robots and use a channel as an interactive blog. I don't have any admin rights on the server so I can't call any APIs.

The strategy is to use Chrome's developer tool network traffic recorder to record har files. There's requests being logged with JSON responses that contain all the messages. These are streamed as I scroll through the channel. So I will start a recording, go to the channel page, and start scrolling until I reach the end, and save the har file.

Write a python script.

Use argparse, allow the user to specify a .har file to open. The output path of the result shall be the input path but with .har replaced with .json

The python script shall have a class object defined to represent each message. It should have a username (string), date, message content (plain string). It should also have a method to output itself as a simplified json chunk with just the username, date, and message.

Open the specified har file, iterate through everything, only pay attention to requests that are GET requests to a URL that contains `/messages?` and there response content type is `application/json`. Open these, take the response, which should be JSON, and will look like:

```
[
    {
        "type": 0,
        "content": "There are 512 data points taken during each rotation.",
        "mentions": [],
        "mention_roles": [],
        "attachments": [],
        "embeds": [],
        "timestamp": "2023-12-01T14:25:34.462000+00:00",
        "edited_timestamp": null,
        "flags": 0,
        "components": [],
        "id": "1180152719315570758",
        "channel_id": "1042557801345593374",
        "author": {
            "id": "447918042844758017",
            "username": "remzakmij",
            "avatar": "0b4f469a7e2f99a5203a9e0999ff17b4",
            "discriminator": "0",
            "public_flags": 0,
            "flags": 0,
            "banner": null,
            "accent_color": null,
            "global_name": "Jim Kazmer",
            "avatar_decoration_data": null,
            "collectibles": null,
            "display_name_styles": null,
            "banner_color": null,
            "clan": null,
            "primary_guild": null
        },
        "pinned": false,
        "mention_everyone": false,
        "tts": false
    },
    {
        "type": 0,
        "content": "That is what my 4'x4' test cage looks like in IR when the Bot is near the center.\nThere are two sets of IR data being shown (blue and orange). The Blue is from the front sensor and the orange is from the back sensor.\n~~I could not believe how identical they were!  The two data points on top of each other were taken one half rotation apart.~~",
        "mentions": [],
        "mention_roles": [],
        "attachments": [],
        "embeds": [],
        "timestamp": "2023-12-01T14:24:45.883000+00:00",
        "edited_timestamp": "2023-12-01T16:27:07.958000+00:00",
        "flags": 0,
        "components": [],
        "id": "1180152515560484925",
        "channel_id": "1042557801345593374",
        "author": {
            "id": "447918042844758017",
            "username": "remzakmij",
            "avatar": "0b4f469a7e2f99a5203a9e0999ff17b4",
            "discriminator": "0",
            "public_flags": 0,
            "flags": 0,
            "banner": null,
            "accent_color": null,
            "global_name": "Jim Kazmer",
            "avatar_decoration_data": null,
            "collectibles": null,
            "display_name_styles": null,
            "banner_color": null,
            "clan": null,
            "primary_guild": null
        },
        "pinned": false,
        "mention_everyone": false,
        "tts": false
    }
]
```

the above example represents two messages

all we are interested in is the `content`, the `timestamp`, and the `username` (under `author`). Make instances of our class object that represent a message using each one of the messages, put them in a gigantic list.

Once the entire har file has been processed and we have a gigantic list, sort them by timestamp, earliest first

Then iterate through the list from earliest to latest, if two messages are from the same author and are within 2 hours of each other, combine them into one message with the first time stamp, and two `\n` separating the text.

Then output all of it to the output JSON file using the json writing method for each message object.
