from dataclasses import dataclass
import json
from functools import cached_property
from io import BytesIO, BufferedIOBase
import typing as t

import requests
from requests import RequestException

from PIL import Image

from iris.bot._internal.iris import IrisAPI


DEFAULT_REQUEST_TIMEOUT = 5

@dataclass
class Message:
    id: int
    type: int
    msg: str
    attachment: t.Union[str, dict[str, t.Any]]
    v: dict[str, t.Any]

    def __post_init__(self):
        msg_text = self.msg or ""
        self.msg = msg_text

        self.command, *param = msg_text.split(" ", 1)
        self.has_param = len(param) > 0
        self.param = param[0] if self.has_param else None

        attachment_data: t.Optional[dict] = None
        if isinstance(self.attachment, str):
            try:
                attachment_data = json.loads(self.attachment)
            except (json.JSONDecodeError, TypeError, ValueError):
                attachment_data = None
        elif isinstance(self.attachment, dict):
            attachment_data = self.attachment

        self.attachment = attachment_data or {}

        if self.type in {71, 27, 2, 71 + 16384, 27 + 16384, 2 + 16384}:
            self.image = ChatImage(self)
        else:
            self.image = None

        if len(self.msg) >= 3900 and "path" in self.attachment:
            try:
                attachment_full_msg = requests.get(
                    "https://dn-m.talk.kakao.com/" + self.attachment["path"],
                    timeout=DEFAULT_REQUEST_TIMEOUT,
                )
                attachment_full_msg.raise_for_status()
                attachment_full_msg.encoding = "utf-8"
                self.msg = attachment_full_msg.text
            except RequestException as exc:
                print(f"메시지 본문을 불러오지 못했습니다: {exc}")
    
    def __repr__(self) -> str:
        return f"Message(id={self.id}, type={self.type}, msg={self.msg})"

class Room:
    def __init__(self, id: int, name: str, api: IrisAPI):
        self.id = id
        self.name = name
        self._api = api

    @cached_property
    def type(self) -> t.Optional[str]:
        try:
            results = self._api.query(
                'select type from chat_rooms where id = ?',
                [self.id]
            )
            if results and results[0]:
                fetched_type = results[0].get("type")
                return fetched_type
            else:
                return None

        except Exception as e:
            return None

    def __repr__(self) -> str:
        return f"Room(id={self.id}, name={self.name})"


class User:
    def __init__(self, id: int, chat_id: int, api: IrisAPI, name: str = None, bot_id: int = None):
        self.id = id
        self._chat_id = chat_id
        self._api = api
        self._name = name
        self._bot_id = bot_id
        self.avatar = Avatar(id, chat_id, api)
    
    @cached_property
    def name(self) -> t.Optional[str]:
        try:
            if not self._name:
                if self.id == self._bot_id:
                    query = "SELECT T2.nickname FROM chat_rooms AS T1 JOIN db2.open_profile AS T2 ON T1.link_id = T2.link_id WHERE T1.id = ?"
                    results = self._api.query(query, [self._chat_id])
                    name = results[0].get("nickname")
                elif self.id < 10000000000:
                    query = "SELECT name, enc FROM db2.friends WHERE id = ?"
                    results = self._api.query(query, [self.id])
                    name = results[0].get("name")
                else:
                    query = "SELECT nickname,enc FROM db2.open_chat_member WHERE user_id = ?"
                    results = self._api.query(query, [self.id])
                    name = results[0].get("nickname")
                return name
            
            else:
                return self._name
            
        except Exception as e:
            return None
    
    @cached_property
    def type(self) -> t.Optional[str]:
        try:
            if self.id == self._bot_id:
                query = "SELECT T2.link_member_type FROM chat_rooms AS T1 INNER JOIN open_profile AS T2 ON T1.link_id = T2.link_id WHERE T1.id = ?"
                results = self._api.query(query, [self._chat_id])
                
            else:
                query = "SELECT link_member_type FROM db2.open_chat_member WHERE user_id = ?"
                results = self._api.query(query, [self.id])
            
            member_type = int(results[0].get("link_member_type"))
            match member_type:
                case 1:
                    return "HOST"
                case 2:
                    return "NORMAL"
                case 4:
                    return "MANAGER"
                case 8:
                    return "BOT"
                case _:
                    return "UNKNOWN"
            
        except Exception as e:
            return "REAL_PROFILE"
    
    def __repr__(self) -> str:
        return f"User(name={self.name})"

class Avatar:
    def __init__(self, id: int, chat_id: int, api: IrisAPI):
        self._id = id
        self._api = api
        self._chat_id = chat_id

    @cached_property
    def url(self) -> t.Optional[str]:
        try:
            if self._id < 10000000000:
                query = "SELECT T2.o_profile_image_url FROM chat_rooms AS T1 JOIN db2.open_profile AS T2 ON T1.link_id = T2.link_id WHERE T1.id = ?"
                results = self._api.query(query, [self._chat_id])
                fetched_url = results[0].get("o_profile_image_url")
            else:
                query = "SELECT original_profile_image_url,enc FROM db2.open_chat_member WHERE user_id = ?"
                results = self._api.query(query, [self._id])
                fetched_url = results[0].get("original_profile_image_url")
            return fetched_url
            
        except Exception as e:
            return None

    @cached_property
    def img(self) -> t.Optional[bytes]:
        avatar_url = self.url

        if not avatar_url:
            return None

        try:
            image_data = self.__get_image_from_url(avatar_url)
            return image_data
        except Exception as e:
            print(f"아바타 이미지 로딩 실패: {e}")
            return None
    
    def __get_image_from_url(self, url: str) -> Image:
        try:
            response = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            return img.convert("RGBA")
        except RequestException as exc:
            print(f"아바타 이미지 로딩 실패: {exc}")
        except Exception as e:
            print(f"아바타 이미지 로딩 실패: {e}")

        return None

    def __repr__(self) -> str:
        return f"Avatar(url={self.url})"

class ChatImage:
    def __init__(self, message: Message):
        self.url = self.__get_photo_url(message)

    @cached_property
    def img(self):
        if not self.url:
            return None

        images = []
        for url in self.url:
            img = self.__get_image_from_url(url)
            if img:
                images.append(img)

        return images or None

    def __get_photo_url(self, message) -> t.Optional[list[str]]:
        attachment = getattr(message, "attachment", {}) or {}
        urls: list[str] = []

        try:
            if message.type == 71:
                for item in attachment.get("C", {}).get("THL", []):
                    url = item.get("TH", {}).get("THU")
                    if url:
                        urls.append(url)
            elif message.type == 27:
                for item in attachment.get("imageUrls", []):
                    if item:
                        urls.append(item)
            else:
                url = attachment.get("url")
                if url:
                    urls.append(url)
        except AttributeError:
            return None

        return urls or None
    
    def __get_image_from_url(self, url: str) -> Image:
        try:
            response = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            return img.convert("RGBA")
        except RequestException as exc:
            print(f"이미지 로딩 실패: {exc}")
        except Exception as e:
            print(f"이미지 로딩 실패: {e}")

        return None

    def __repr__(self) -> str:
        return f"ChatImage(url={self.url})"

@dataclass
class ChatContext:
    room: Room
    sender: User
    message: Message
    raw: dict
    api: IrisAPI
    _bot_id: int = None

    def __post_init__(self):
        pass

    def reply(self, message: str, room_id: int = None):
        if room_id is None:
            room_id = self.room.id

        try:
            self.api.reply(room_id, message)
        except Exception as e:
            print(f"reply 오류: {e}")

    def reply_media(
        self,
        files: t.List[BufferedIOBase | bytes | Image.Image | str],
        room_id: int = None,
    ):
        if room_id is None:
            room_id = self.room.id
        
        self.api.reply_media(room_id, files)
    
    def get_source(self):
        source_record = self.__get_reply_chat(self.message)
        if source_record:
            source_chat = self.__make_chat(self, source_record)
            return source_chat
        else:
            return None

    def get_next_chat(self, n: int = 1):
        next_record = self.__get_next_record(self.message.id, n)
        if next_record:
            next_chat = self.__make_chat(self, next_record)
            return next_chat
        else:
            return None

    def get_previous_chat(self, n: int = 1):
        previous_record = self.__get_previous_record(self.message.id, n)
        if previous_record:
            previous_chat = self.__make_chat(self, previous_record)
            return previous_chat
        else:
            return None
        
    def __get_reply_chat(self, message: Message):
        try:
            src_log_id = message.attachment['src_logId']
            query = "select * from chat_logs where id = ?"    
            src_record = self.api.query(query,[src_log_id])
            return src_record[0]
        except Exception as e:
            print(e)
            return None
    
    def __get_previous_record(self, log_id, n: int = 1):
        if n < 0:
            raise ValueError("n must be greater than 0")
        
        query = """
            WITH RECURSIVE ChatHistory AS (
                SELECT *
                FROM chat_logs
                WHERE id = ?
                UNION ALL
                SELECT c.*
                FROM chat_logs c
                JOIN ChatHistory h ON c.id = h.prev_id
            )
            SELECT *
            FROM ChatHistory
            LIMIT 1 OFFSET ?;
            """
        record = self.api.query(query, [log_id, n])
        return record[0] if record else None

    def __get_next_record(self, log_id, n: int = 1):
        n = n - 1
        if n < -1:
            raise ValueError("n must be greater than 0")
        query = """
            WITH RECURSIVE ChatHistory AS (
                SELECT
                    *,
                    0 AS depth
                FROM
                    chat_logs
                WHERE
                    id = ?

                UNION ALL

                SELECT
                    c.*,
                    h.depth + 1
                FROM
                    chat_logs c
                JOIN ChatHistory h ON c.prev_id = h.id
                WHERE
                    h.depth < 100
                    AND c.prev_id IS NOT NULL
                    AND h.id IS NOT NULL
                    AND c.id IS NOT NULL
            )
            SELECT *
            FROM ChatHistory
            WHERE depth = ? + 1
            LIMIT 1; 
            """
        record = self.api.query(query, [log_id, n])
        return record[0] if record else None
    
    def __make_chat(self, chat, record):
        v = {}
        try:
            v = json.loads(record["v"])
        except Exception:
            pass

        room = Room(
            id=int(record["chat_id"]),
            name=chat.room.name,
            api=self.api,
        )
        sender = User(
            id=int(record["user_id"]),
            chat_id=chat.room.id,
            api=self.api,
            name=self.__get_name_of_user_id(int(record["user_id"])),
            bot_id=self._bot_id,
        )
        message = Message(
            id=int(record["id"]),
            type=int(record["type"]),
            msg=record["message"],
            attachment=record["attachment"],
            v=v,
        )
        new_chat = ChatContext(
            room=room, sender=sender, message=message, raw=record, api=self.api, _bot_id=self._bot_id
        )
        
        return new_chat
    
    def __get_name_of_user_id(self, user_id: int):
        query = "WITH info AS (SELECT ? AS user_id) SELECT COALESCE(open_chat_member.nickname, friends.name) AS name, COALESCE(open_chat_member.enc, friends.enc) AS enc FROM info LEFT JOIN db2.open_chat_member ON open_chat_member.user_id = info.user_id LEFT JOIN db2.friends ON friends.id = info.user_id;"
        result = self.api.query(query,[user_id])
        if len(result) == 0:
            return None
        return result[0]['name']

@dataclass
class ErrorContext:
    event: str
    func: t.Callable
    exception: Exception
    args: list[t.Any]

