import asyncio
import logging
import os
import ssl
from collections.abc import AsyncIterator
from typing import IO, BinaryIO, Literal

import aiofiles
import aiohttp
from aiohttp.client_exceptions import ClientConnectorCertificateError

from . import buttons, exceptions, fsm, utils
from .cache import MessageCache
from .router import Router
from .types import (
    Attachment,
    AudioAttachment,
    BotCommand,
    BotStartPayload,
    Callback,
    Chat,
    ChatCreatePayload,
    ChatMembershipPayload,
    ChatTitleEditPayload,
    CommandContext,
    FileAttachment,
    ImageRequestPayload,
    Message,
    MessageDeletePayload,
    PhotoAttachment,
    User,
    UserMembershipPayload,
    VideoAttachment,
)

bot_logger = logging.getLogger("aiomax.bot")


class Bot(Router):
    def __init__(
        self,
        access_token: str,
        command_prefixes: "str | list[str]" = "/",
        mention_prefix: bool = True,
        case_sensitive: bool = True,
        default_format: "Literal['markdown', 'html'] | None" = None,
        max_messages_cached: int = 10000,
        use_certificate: bool = False,
        api_url: str = "https://platform-api2.max.ru/",
        shutdown_timeout: "float | None" = 5.0,
        attachment_retries: int = 10,
    ):
        """
        Bot init

        :param access_token: Bot access token from https://max.ru/masterbot
        :param command_prefixes: List of command prefixes or a command prefix
        :param mention_prefix: Whether to respond to commands starting with
        the ping of the bot
        :param case_sensitive: If False the bot will respond to commands
        regardless of case
        :param default_format: Default message formatting mode
        :param max_messages_cached: Maximum number of messages to cache.
        Set to 0 to disable caching
        :param use_certificate: Whether to automatically use
        a Russian Mintsifra SSL certificate
        :param shutdown_timeout: How long (in seconds) to wait for running
        handlers to finish on shutdown before cancelling them. ``None`` waits
        indefinitely.
        :param attachment_retries: How many times to retry sending/editing a
        message while its attachment is still being processed by the server
        before giving up and raising ``AttachmentNotReady``.
        """
        super().__init__(case_sensitive)

        self.use_certificate: bool = use_certificate
        self.api_url: str = api_url
        self.shutdown_timeout: "float | None" = shutdown_timeout
        self.attachment_retries: int = attachment_retries

        self.access_token: str = access_token
        self.session: aiohttp.ClientSession | None = None
        self.polling = False
        self._handler_tasks: set[asyncio.Task] = set()
        # Per-user locks serialise handler execution for a single user so
        # concurrent updates from the same user cannot race on FSM state.
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._user_lock_counts: dict[int, int] = {}

        self.command_prefixes: str | list[str] = command_prefixes
        self.mention_prefix: bool = mention_prefix
        self.default_format: str | None = default_format
        self.cache: MessageCache | None = (
            MessageCache(max_messages_cached)
            if max_messages_cached > 0
            else None
        )

        self.id: int | None = None
        self.username: str | None = None
        self.name: str | None = None
        self.description: str | None = None
        self.bot_commands: list[BotCommand] | None = None

        self.marker: int | None = None

        self.storage = fsm.FSMStorage()

    async def get(self, url: str, *args, **kwargs):
        """
        Sends a GET request to the API.
        """
        if self.session is None:
            raise Exception("Session is not initialized")

        params = kwargs.get("params", {})
        if "params" in kwargs:
            del kwargs["params"]

        response = await self.session.get(url, *args, params=params, **kwargs)

        exception = await utils.get_exception(response)

        if not exception:
            return response
        raise exception

    async def post(self, url: str, *args, **kwargs):
        """
        Sends a POST request to the API.
        """
        if self.session is None:
            raise Exception("Session is not initialized")

        params = kwargs.get("params", {})
        if "params" in kwargs:
            del kwargs["params"]

        response = await self.session.post(url, *args, params=params, **kwargs)

        exception = await utils.get_exception(response)

        if not exception:
            return response
        raise exception

    async def patch(self, url: str, *args, **kwargs):
        """
        Sends a PATCH request to the API.
        """
        if self.session is None:
            raise Exception("Session is not initialized")

        params = kwargs.get("params", {})
        if "params" in kwargs:
            del kwargs["params"]

        response = await self.session.patch(
            url, *args, params=params, **kwargs
        )

        exception = await utils.get_exception(response)

        if not exception:
            return response
        raise exception

    async def put(self, url: str, *args, **kwargs):
        """
        Sends a PUT request to the API.
        """
        if self.session is None:
            raise Exception("Session is not initialized")

        params = kwargs.get("params", {})
        if "params" in kwargs:
            del kwargs["params"]

        response = await self.session.put(url, *args, params=params, **kwargs)

        exception = await utils.get_exception(response)

        if not exception:
            return response
        raise exception

    async def delete(self, url: str, *args, **kwargs):
        """
        Sends a DELETE request to the API.
        """
        if self.session is None:
            raise Exception("Session is not initialized")

        params = kwargs.get("params", {})
        if "params" in kwargs:
            del kwargs["params"]

        response = await self.session.delete(
            url, *args, params=params, **kwargs
        )

        exception = await utils.get_exception(response)

        if not exception:
            return response
        raise exception

    # send requests

    async def get_me(self) -> User:
        """
        Returns info about the bot.
        """
        response = await self.get("me")
        user = await response.json()
        user = User.from_json(user)

        # caching info
        self.id = user.user_id
        self.username = user.username
        self.name = user.name
        self.bot_commands = user.commands
        self.description = user.description
        return user

    async def patch_me(
        self,
        name: "str | None" = None,
        description: "str | None" = None,
        commands: "list[BotCommand] | None" = None,
        photo: "ImageRequestPayload | None" = None,
    ) -> User:
        """
        Allows you to change info about the bot. Fill in only the fields that
        need to be updated.

        :param name: Bot display name
        :param description: Bot description
        :param commands: Commands supported by the bot. To remove all commands,
        pass an empty list.
        :param photo: Bot profile pictur
        """
        if commands:
            commands = [i.as_dict() for i in commands]
        if photo:
            photo = photo.as_dict()

        payload = {
            "name": name,
            "description": description,
            "commands": commands,
            "photo": photo,
        }
        payload = {k: v for k, v in payload.items() if v}

        response = await self.patch("me", json=payload)
        data = await response.json()

        # caching info
        if name:
            self.name = name
        if commands:
            self.bot_commands = commands
        if description:
            self.description = description

        return User.from_json(data)

    async def get_chats(
        self, count_per_iter: int = 100
    ) -> AsyncIterator[Chat]:
        """
        Returns an asynchronous interator of chats the bot is in.

        :param count_per_iter: The number of chats to fetch per request.
        """
        marker = None

        while True:
            params = {
                "count": count_per_iter,
                "marker": marker,
            }
            params = {k: v for k, v in params.items() if v}
            response = await self.get("chats", params=params)
            data = await response.json()

            for chat in data["chats"]:
                yield Chat.from_json(chat)

            marker = data.get("marker", None)
            if marker is None:
                break

    async def chat_by_link(self, link: str) -> Chat:
        """
        Returns chat by a link or username.

        :param link: Public chat link or username.
        """
        response = await self.get(f"chats/{link}")
        json = await response.json()

        return Chat.from_json(json)

    async def get_chat(self, chat_id: int) -> Chat:
        """
        Returns information about a chat.

        :param chat_id: The ID of the chat.
        """
        response = await self.get(f"chats/{chat_id}")
        json = await response.json()

        return Chat.from_json(json)

    async def get_pin(self, chat_id: int) -> "Message | None":
        """
        Returns pinned message in the chat as ``. None if there is no pinned
        message

        :param chat_id: The ID of the chat.
        """
        response = await self.get(f"chats/{chat_id}/pin")
        json = await response.json()

        if json["message"] is None:
            return None

        return Message.from_json(json["message"])

    async def pin(
        self, chat_id: int, message_id: str, notify: "bool | None" = None
    ):
        """
        Pin a message in a chat

        :param chat_id: The ID of the chat.
        :param message_id: The ID of the message to pin.
        :param notify: Whether to notify users about the pin. True by default.
        """
        payload = {"message_id": message_id, "notify": notify}
        payload = {k: v for k, v in payload.items() if v is not None}

        response = await self.put(f"chats/{chat_id}/pin", json=payload)
        return await response.json()

    async def delete_pin(self, chat_id: int):
        """
        Delete pinned message in the chat

        :param chat_id: The ID of the chat.
        """
        response = await self.delete(f"chats/{chat_id}/pin")

        return await response.json()

    async def my_membership(self, chat_id: int) -> User:
        """
        Returns information about the bot's membership in the chat.

        :param chat_id: The ID of the chat.
        """
        response = await self.get(f"chats/{chat_id}/members/me")
        json = await response.json()

        return User.from_json(json)

    async def leave_chat(self, chat_id: int):
        """
        Remove the bot from the chat.

        :param chat_id: The ID of the chat.
        """
        response = await self.delete(f"chats/{chat_id}/members/me")

        return await response.json()

    async def get_admins(self, chat_id: int) -> list[User]:
        """
        Returns a list of administrators in the chat.

        :param chat_id: The ID of the chat.
        """
        response = await self.get(f"chats/{chat_id}/members/admins")

        users = [User.from_json(i) for i in (await response.json())["members"]]

        return users

    async def get_memberships(
        self, chat_id: int, user_ids: "list[int] | int"
    ) -> "list[User] | User | None":
        """
        Returns a list of memberships in the chat for the users with the
        specified ID.
        """
        params = {
            "user_ids": user_ids if isinstance(user_ids, list) else [user_ids]
        }
        response = await self.get(
            f"chats/{chat_id}/members",
            params=params,
        )

        users = [User.from_json(i) for i in (await response.json())["members"]]

        if isinstance(user_ids, list):
            return users
        else:
            return users[0] if len(users) > 0 else None

    async def get_members(
        self, chat_id: int, count_per_iter: int = 100
    ) -> AsyncIterator[User]:
        """
        Returns an asynchronous interator of members in the chat.

        :param chat_id: The ID of the chat.
        :param count_per_iter: The number of users to fetch per request.
        """
        marker = None

        while True:
            params = {
                "count": count_per_iter,
                "marker": marker,
            }
            params = {k: v for k, v in params.items() if v}
            response = await self.get(
                f"chats/{chat_id}/members",
                params=params,
            )
            data = await response.json()

            for user in data["members"]:
                yield User.from_json(user)

            marker = data.get("marker", None)
            if marker is None:
                break

    async def add_members(self, chat_id: int, users: list[int]):
        """
        Adds users to the chat.

        :param chat_id: The ID of the chat.
        :param users: List of user IDs to add.
        """

        response = await self.post(
            f"chats/{chat_id}/members",
            json={"user_ids": users},
        )

        return await response.json()

    async def kick_member(
        self, chat_id: int, user_id: int, block: "bool | None" = None
    ):
        """
        Removes a user from the chat.

        :param chat_id: The ID of the chat.
        :param user_id: The ID of the user to remove.
        :param block: Whether to block the user. Ignored by default.
        """

        params = {"chat_id": chat_id, "user_id": user_id, "block": block}
        params = {k: v for k, v in params.items() if v}

        if block is not None:
            params["block"] = str(block)

        response = await self.delete(
            f"chats/{chat_id}/members/",
            params=params,
        )

        return await response.json()

    async def patch_chat(
        self,
        chat_id: int,
        icon: "ImageRequestPayload | None" = None,
        title: "str | None" = None,
        pin: "str | None" = None,
        notify: "bool | None" = None,
    ) -> Chat:
        """
        Allows you to edit chat information, like the name,
        icon and pinned message.

        :param chat_id: ID of the chat to change
        :param icon: Chat picture
        :param title: Chat name. From 1 to 200 characters
        :param pin: ID of the message to pin
        :param notify: Whether to notify users about the edit. True by default.
        """

        payload = {
            "icon": icon.as_dict() if icon else None,
            "title": title,
            "pin": pin,
            "notify": notify,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        response = await self.patch(f"chats/{chat_id}", json=payload)
        json = await response.json()

        return Chat.from_json(json)

    async def post_action(self, chat_id: int, action: str):
        """
        Allows you to show a badge about performing an action in a chat, like
        "typing". Also allows for marking messages as read.

        :param chat_id: ID of the chat to do the action in
        :param action: The action to perform
        """

        response = await self.post(
            f"chats/{chat_id}/actions",
            json={"action": action},
        )

        return await response.json()

    async def _upload(
        self, data: "IO | str", type: str, filename: "str | None" = None
    ) -> dict:
        """
        Uploads a file to the server. Returns raw JSON with the token.

        :param data: File-like object or path to the file
        :param type: File type
        :param filename: Optional file name sent alongside the file
        """
        if isinstance(data, str):
            async with aiofiles.open(data, "rb") as f:
                data = await f.read()

        # The form field name must be a fixed, safe literal. Passing an
        # attacker-influenced filename as the field name (previously the case
        # for upload_file) with quote_fields disabled allowed header injection
        # into the multipart request. aiohttp encodes ``filename`` safely.
        form = aiohttp.FormData()
        form.add_field("data", data, filename=filename)

        url_resp = await self.post("uploads", params={"type": type})
        url_json = await url_resp.json()
        token_resp = await self.session.post(url_json["url"], data=form)
        token_resp.raise_for_status()

        if type in {"audio", "video"}:
            return url_json

        token_json = await token_resp.json()
        return token_json

    async def upload_image(self, data: "BinaryIO | str") -> PhotoAttachment:
        """
        Uploads an image to the server and returns a PhotoAttachment.

        :param data: File-like object or path to the file
        """
        raw_photo = await self._upload(data, "image")
        token = list(raw_photo["photos"].values())[0]["token"]
        return PhotoAttachment(token=token)

    async def upload_video(self, data: "BinaryIO | str") -> VideoAttachment:
        """
        Uploads a video to the server and returns a VideoAttachment.

        :param data: File-like object or path to the file
        """
        raw_video = await self._upload(data, "video")
        token = raw_video["token"]
        return VideoAttachment(token=token)

    async def upload_audio(self, data: "BinaryIO | str") -> AudioAttachment:
        """
        Uploads an audio file to the server and returns an AudioAttachment.

        :param data: File-like object or path to the file
        """
        raw_audio = await self._upload(data, "audio")
        token = raw_audio["token"]
        return AudioAttachment(token=token)

    async def upload_file(
        self, data: "IO | str", filename: "str | None" = None
    ) -> FileAttachment:
        """
        Uploads a file to the server and returns a FileAttachment.

        :param data: File-like object or path to the file
        :param filename: Filename that will be uploaded
        """
        if filename is None:
            if isinstance(data, str):
                filename = os.path.basename(data)
            elif hasattr(data, "name"):
                filename = data.name
            else:
                raise exceptions.FilenameNotProvided(
                    "filename is required for use with "
                    f"object of type {type(data).__name__}"
                )

        raw_file = await self._upload(data, "file", filename)
        token = raw_file["token"]
        return FileAttachment(token=token)

    async def send_message(
        self,
        text: "str | None" = None,
        chat_id: "int | None" = None,
        user_id: "int | None" = None,
        format: "Literal['markdown', 'html', 'default'] | None" = "default",
        reply_to: "int | None" = None,
        notify: bool = True,
        disable_link_preview: bool = False,
        keyboard: """list[list[buttons.Button]] \
        | buttons.KeyboardBuilder \
        | None""" = None,
        attachments: "list[Attachment] | Attachment | None" = None,
    ) -> Message:
        """
        Allows you to send a message to a user or in a chat.

        :param text: Message text. Up to 4000 characters
        :param chat_id: Chat ID to send the message in.
        :param user_id: User ID to send the message to.
        :param format: Message format. Bot.default_format by default
        :param reply_to: ID of the message to reply to. Optional
        :param notify: Whether to notify users about the message.
            True by default.
        :param disable_link_preview: Whether to disable link embedding
            in messages. True by default
        :param keyboard: An inline keyboard to attach to the message
        :param attachments: List of attachments
        """
        # error checking
        if chat_id is None and user_id is None:
            raise exceptions.AiomaxException(
                "Either chat_id or user_id must be provided"
            )
        if not (chat_id is None or user_id is None):
            raise exceptions.AiomaxException(
                "Both chat_id and user_id cannot be provided"
            )

        # sending
        params = {
            "chat_id": chat_id,
            "user_id": user_id,
            "disable_link_preview": str(disable_link_preview).lower(),
        }
        params = {k: v for k, v in params.items() if v}

        if format == "default":
            format = self.default_format

        body = utils.get_message_body(
            text, format, reply_to, notify, keyboard, attachments
        )

        # Retry a bounded number of times while the attachment is still being
        # processed, instead of recursing forever (which grew the stack until
        # RecursionError and blocked the handler indefinitely).
        for attempt in range(self.attachment_retries + 1):
            try:
                response = await self.post(
                    "messages",
                    params=params,
                    json=body,
                )
                json = await response.json()
                if not json.get("success", True):
                    # get_exception() returns None for 2xx responses, so a
                    # bare `raise await get_exception(...)` would `raise None`
                    # (TypeError). Fall back to a real exception.
                    exception = await utils.get_exception(response)
                    raise exception or exceptions.UnknownErrorException(
                        json.get("code"), json.get("message")
                    )
                message = Message.from_json(json["message"])
                message.bot = self
                return message

            except exceptions.AttachmentNotReady:
                if attempt >= self.attachment_retries:
                    raise
                await asyncio.sleep(1)

    async def edit_message(
        self,
        message_id: str,
        text: "str | None" = None,
        format: "Literal['markdown', 'html', 'default'] | None" = "default",
        reply_to: "int | None" = None,
        notify: bool = True,
        keyboard: """list[list[buttons.Button]] \
        | buttons.KeyboardBuilder \
        | None""" = None,
        attachments: "list[Attachment] | Attachment | None" = None,
    ) -> Message:
        """
        Allows you to edit a message.

        :param message_id: ID of the message to edit
        :param text: Message text. Up to 4000 characters
        :param format: Message format. Bot.default_format by default
        :param reply_to: ID of the message to reply to. Optional
        :param notify: Whether to notify users about the message.
            True by default.
        :param keyboard: An inline keyboard to attach to the message
        :param attachments: List of attachments
        """
        # editing
        params = {"message_id": message_id}
        if format == "default":
            format = self.default_format

        body = utils.get_message_body(
            text, format, reply_to, notify, keyboard, attachments
        )

        for attempt in range(self.attachment_retries + 1):
            try:
                response = await self.put(
                    "messages",
                    params=params,
                    json=body,
                )
                json = await response.json()
                if not json.get("success", True):
                    # Never fall through to Message.from_json() on failure (it
                    # would return a broken Message with body=None); and never
                    # `raise None` when get_exception() returns None for 2xx.
                    exception = await utils.get_exception(response)
                    raise exception or exceptions.UnknownErrorException(
                        json.get("code"), json.get("message")
                    )
                # The edit endpoint may return either the bare message or a
                # ``{"message": {...}}`` envelope; handle both instead of
                # building a broken Message from the wrong shape.
                message = Message.from_json(json.get("message") or json)
                message.bot = self
                return message

            except exceptions.AttachmentNotReady:
                if attempt >= self.attachment_retries:
                    raise
                await asyncio.sleep(1)

    async def delete_message(self, message_id: str):
        """
        Allows you to delete a message in chat.

        :param message_id: ID of the message to delete
        """
        # editing
        params = {"message_id": message_id}

        response = await self.delete("messages", params=params)

        json = await response.json()
        if not json["success"]:
            raise Exception(json["message"])

    async def get_message(self, message_id: str) -> Message:
        """
        Allows you to fetch message's info.

        :param message_id: ID of the message to get info of
        """
        try:
            response = await self.get(f"messages/{message_id}")

            data = await response.json()

            return Message.from_json(data)
        except exceptions.NotFoundException:
            raise exceptions.MessageNotFoundException from None

    async def get_updates(self, limit: int = 100) -> tuple[int, dict]:
        """
        Get bot updates / events.

        :param limit: Maximum amount of updates to return.
        """
        payload = {"limit": limit, "marker": self.marker}
        payload = {k: v for k, v in payload.items() if v}

        response = await self.get("updates", params=payload)
        json = await response.json()
        if "marker" in json:
            self.marker = json["marker"]

        return json

    def _run_handler(self, coro, user_id: "int | None" = None) -> asyncio.Task:
        """
        Runs a handler as a task, keeping a reference to it until it
        finishes so that it is not garbage collected mid-flight and can
        be awaited on shutdown.

        If ``user_id`` is given, handlers for the same user are serialised:
        the next update from that user waits for the previous handler to
        finish, so they cannot race on shared FSM state.
        """
        if user_id is not None:
            coro = self._run_serialized(coro, user_id)
        task = asyncio.create_task(coro)
        self._handler_tasks.add(task)
        task.add_done_callback(self._handler_tasks.discard)
        return task

    async def _run_serialized(self, coro, user_id: int):
        """
        Runs ``coro`` while holding the per-user lock, cleaning the lock up
        once no more handlers are queued for that user (bounded memory).
        """
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock

        self._user_lock_counts[user_id] = (
            self._user_lock_counts.get(user_id, 0) + 1
        )
        try:
            async with lock:
                await coro
        finally:
            self._user_lock_counts[user_id] -= 1
            if self._user_lock_counts[user_id] <= 0:
                self._user_lock_counts.pop(user_id, None)
                self._user_locks.pop(user_id, None)

    async def handle_update(self, update: dict):
        """
        Handles an update.
        """
        update_type = update["update_type"]

        if update_type == "message_created":
            message = Message.from_json(update["message"])
            message.bot = self
            message.user_locale = update.get("user_locale")
            cursor = fsm.FSMCursor(self.storage, message.sender.user_id)

            # caching
            if self.cache:
                self.cache.add_message(message)

            # handling commands
            prefixes = (
                self.command_prefixes
                if not isinstance(self.command_prefixes, str)
                else [self.command_prefixes]
            )
            prefixes = list(prefixes)
            handled = False
            block = False

            if self.mention_prefix:
                prefixes.extend([f"@{self.username} {i}" for i in prefixes])

            # Media-only messages (stickers, photos/files without a caption)
            # arrive with body.text=None and cannot be commands. Fall back to
            # an empty string so the checks below skip them instead of
            # raising `TypeError: object of type 'NoneType' has no len()`.
            text = message.body.text or ""

            for prefix in prefixes:
                if len(text) <= len(prefix):
                    continue

                if self.case_sensitive:
                    if not text.startswith(prefix):
                        continue
                else:
                    if not text.lower().startswith(prefix.lower()):
                        continue

                command = text[len(prefix) :]
                parts = command.split()
                if not parts:
                    # Prefix followed by whitespace only (e.g. "/ ") — not a
                    # command; avoid IndexError on parts[0].
                    continue
                name = parts[0]
                check_name = name if self.case_sensitive else name.lower()
                args = " ".join(parts[1:])

                if check_name not in self.commands:
                    bot_logger.debug(f'Command "{name}" not handled')
                    continue

                if len(self.commands[check_name]) == 0:
                    bot_logger.debug(f'Command "{name}" not handled')
                    continue

                for i in self.commands[check_name]:
                    kwargs = utils.context_kwargs(i.call, cursor=cursor)
                    self._run_handler(
                        i.call(
                            CommandContext(self, message, name, args), **kwargs
                        ),
                        user_id=cursor.user_id,
                    )

                    if not i.as_message:
                        block = True

                bot_logger.debug(f'Command "{name}" handled')

            # handling
            handled = False

            for handler in self.handlers["message_created"]:
                if not handler.detect_commands and block:
                    continue

                filters = [filter(message) for filter in handler.filters]

                if all(filters):
                    kwargs = utils.context_kwargs(handler.call, cursor=cursor)
                    self._run_handler(
                        handler.call(message, **kwargs),
                        user_id=cursor.user_id,
                    )
                    handled = True

            # handle logs
            if handled:
                bot_logger.debug(f'Message "{message.body.text}" handled')
            else:
                bot_logger.debug(f'Message "{message.body.text}" not handled')

        if update_type == "message_edited":
            message = Message.from_json(update["message"])
            message.bot = self
            message.user_locale = update.get("user_locale")
            cursor = fsm.FSMCursor(self.storage, message.sender.user_id)

            # caching
            old_message = None
            if self.cache:
                old_message = self.cache.get_message(message.id)
                self.cache.add_message(message)

            # handling
            for handler in self.handlers[update_type]:
                filters = [filter(message) for filter in handler.filters]

                if all(filters):
                    kwargs = utils.context_kwargs(
                        handler.call,
                        cursor=cursor,
                    )
                    self._run_handler(
                        handler.call(old_message, message, **kwargs),
                        user_id=cursor.user_id,
                    )

            # handle logs
            bot_logger.debug(f'Message "{message.body.text}" edited')

        if update_type == "message_removed":
            payload = MessageDeletePayload.from_json(update, self)

            if payload.user_id:
                cursor = fsm.FSMCursor(self.storage, payload.user_id)
            else:
                cursor = None

            # handling
            for handler in self.handlers[update_type]:
                filters = [filter(payload) for filter in handler.filters]

                if all(filters):
                    kwargs = utils.context_kwargs(handler.call, cursor=cursor)
                    self._run_handler(
                        handler.call(payload, **kwargs),
                        user_id=cursor.user_id if cursor else None,
                    )

            # handle logs
            bot_logger.debug(f'Message "{payload.content}" deleted')

        if update_type == "bot_started":
            payload = BotStartPayload.from_json(update, self)
            cursor = fsm.FSMCursor(self.storage, payload.user.user_id)

            bot_logger.debug(f'User "{payload.user!r}" started bot')

            for i in self.handlers[update_type]:
                kwargs = utils.context_kwargs(i, cursor=cursor)
                self._run_handler(i(payload, **kwargs), user_id=cursor.user_id)

        if update_type == "chat_title_changed":
            payload = ChatTitleEditPayload.from_json(update)
            cursor = fsm.FSMCursor(self.storage, payload.user.user_id)

            bot_logger.debug(
                f'User "{payload.user!r} '
                f"changed title of chat {payload.chat_id}"
            )

            for i in self.handlers[update_type]:
                kwargs = utils.context_kwargs(i, cursor=cursor)
                self._run_handler(i(payload, **kwargs), user_id=cursor.user_id)

        if update_type == "bot_added" or update_type == "bot_removed":
            payload = ChatMembershipPayload.from_json(update)
            cursor = fsm.FSMCursor(self.storage, payload.user.user_id)

            for i in self.handlers[update_type]:
                kwargs = utils.context_kwargs(i, cursor=cursor)
                self._run_handler(i(payload, **kwargs), user_id=cursor.user_id)

        if update_type == "user_added" or update_type == "user_removed":
            payload = UserMembershipPayload.from_json(update)
            cursor = fsm.FSMCursor(self.storage, payload.user.user_id)

            for i in self.handlers[update_type]:
                kwargs = utils.context_kwargs(i, cursor=cursor)
                self._run_handler(i(payload, **kwargs), user_id=cursor.user_id)

        if update_type == "message_callback":
            handled = False

            callback = Callback.from_json(
                update["callback"],
                update.get("message"),
                update.get("user_locale"),
                self,
            )

            cursor = fsm.FSMCursor(self.storage, callback.user.user_id)

            for handler in self.handlers[update_type]:
                filters = [filter(callback) for filter in handler.filters]

                if all(filters):
                    kwargs = utils.context_kwargs(handler.call, cursor=cursor)
                    self._run_handler(
                        handler.call(callback, **kwargs),
                        user_id=cursor.user_id,
                    )
                    handled = True

            if handled:
                bot_logger.debug(f'Callback "{callback.payload}" handled')
            else:
                bot_logger.debug(f'Callback "{callback.payload}" not handled')

        if update_type == "message_chat_created":
            payload = ChatCreatePayload.from_json(update)
            bot_logger.debug(f'Created chat "{payload.start_payload}"')

            for i in self.handlers[update_type]:
                self._run_handler(i(payload))

    async def start_polling(
        self, session: "aiohttp.ClientSession | None" = None
    ):
        """
        Starts polling.

        :param session: Custom aiohttp client session
        """
        self.polling = True

        conn = None

        if self.use_certificate:
            path = os.path.dirname(__file__) + "/russian_trusted_root_ca.cer"
            ssl_context = ssl.create_default_context()
            ssl_context.load_verify_locations(cafile=path)
            conn = aiohttp.TCPConnector(ssl=ssl_context)

        if not session:
            session = aiohttp.ClientSession(
                headers={"Authorization": self.access_token},
                connector=conn,
                base_url=self.api_url,
            )

        async with session:
            self.session = session

            # self info (this will cache the info automatically)
            # also used to check the SSL certificate
            try:
                await self.get_me()

            except ClientConnectorCertificateError as e:
                raise exceptions.InvalidSSLException(
                    "Invalid SSL certificate. A Mintsifra certificate is now "
                    "required to connect to the Max servers. You can set "
                    "`use_certificate=True` when creating your `Bot` "
                    "instance to use the embedded certificate if you do not "
                    "wish to install the certificate system-wide."
                ) from e

            bot_logger.info(
                f"Started polling with bot "
                f"@{self.username} ({self.id}) - {self.name}"
            )

            # ready event
            for i in self.handlers["on_ready"]:
                self._run_handler(i())

            while self.polling:
                try:
                    updates = await self.get_updates()

                    for update in updates["updates"]:
                        try:
                            await self.handle_update(update)
                        except Exception as e:
                            # One malformed/unhandled update must not drop the
                            # rest of the batch: the polling marker is already
                            # committed in get_updates(), so a raise here would
                            # lose every remaining update permanently.
                            bot_logger.exception(e)

                except Exception as e:
                    bot_logger.exception(e)
                    await asyncio.sleep(3)

                except asyncio.exceptions.CancelledError:
                    break  # Python 3.9 throws an error when exit() is used

            # Let running handlers finish before closing the session, but do
            # not block shutdown forever on a hung handler.
            if self._handler_tasks:
                _, pending = await asyncio.wait(
                    set(self._handler_tasks),
                    timeout=self.shutdown_timeout,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    bot_logger.warning(
                        "%d handler task(s) did not finish within %ss on "
                        "shutdown and were cancelled",
                        len(pending),
                        self.shutdown_timeout,
                    )

        self.session = None
        self.polling = False

    def run(self, *args, **kwargs):
        """
        Shortcut for `asyncio.run(Bot.start_polling())`
        """
        asyncio.run(self.start_polling(*args, **kwargs))
