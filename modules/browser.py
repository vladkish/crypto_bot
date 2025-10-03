from curl_cffi.requests import AsyncSession
from random import choice
from loguru import logger
from uuid import uuid4

from modules.utils import get_current_date
from modules.retry import have_json
from modules.database import DataBase


class Browser:

    SYSTEM_PROMPT_TEMPLATE: str = ("User has connected from country code {} via Injected with their wallet address: "
                          "{} and it supports the following chains: Arbitrum, Base, Optimism, Polygon, BSC, "
                          "Berachain, Hyperliquid, Ink, Soneium, Zksync, Monad Testnet")

    def __init__(
            self,
            encoded_privatekey: str,
            address: str,
            db: DataBase,
            proxy: str,
    ):
        self.encoded_privatekey = encoded_privatekey
        self.address = address
        self.db = db

        self.system_prompt = None

        if proxy in [None, "", " ", "\n"]:
            self.proxy = None
        else:
            self.proxy = "http://" + proxy.removeprefix("https://").removeprefix("http://")

        self.session = self.get_new_session()
        self.chats_memory = {}
        self.signature_body = {}


    def get_new_session(self):
        session = AsyncSession(
            impersonate="chrome131",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.3",
                "Origin": "https://app.heyelsa.ai",
                "Referer": "https://app.heyelsa.ai/",
            }
        )
        if self.proxy not in ['http://log:pass@ip:port', '', None]:
            session.proxies.update({'http': self.proxy, 'https': self.proxy})

        return session


    @have_json
    async def send_request(self, **kwargs):
        if kwargs.get("session"):
            session = kwargs["session"]
            del kwargs["session"]
        else:
            session = self.session

        if kwargs.get("method"): kwargs["method"] = kwargs["method"].upper()
        return await session.request(**kwargs)


    async def get_country_code(self):
        r = await self.session.get("https://ipinfo.io/country")
        country_code = r.text.strip()
        if country_code in ["RU", "UA", "BY"]:
            country_code = choice(["CH", "IN", "GB", "DE", "IT", "JP"])

        self.system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(
            country_code,
            self.address
        )


    async def auth(self, sign_text: str, signature: str, ref_code: str):
        headers = {}
        if ref_code:
            headers = {"Referer": f"https://app.heyelsa.ai/login?referral={ref_code}"}

        r = await self.send_request(
            method="POST",
            url="https://app.heyelsa.ai/api/siwe_verification",
            json={
                "message": sign_text,
                "signature": signature,
                "walletAddress": self.address
            },
            headers=headers,
        )
        if r.json().get('success') is not True or r.json().get("message") != "Signature validation successful":
            raise Exception(f'Unexpected auth response: {r.text}')


    async def get_points(self):
        r = await self.send_request(
            method="POST",
            url="https://app.heyelsa.ai/api/points",
            json={
                "evm_address": self.address,
                **self.signature_body
            },
        )
        return r.json()


    async def get_quests(self):
        r = await self.send_request(
            method="POST",
            url="https://app.heyelsa.ai/api/quests",
            json={"evm_address": self.address},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://app.heyelsa.ai/points",
            }
        )
        quests = r.json()
        if type(quests) != list:
            raise Exception(f'Failed to get quests: {quests}')

        completed_quests = [quest for quest in quests if quest["progress_completed"] >= quest["progress_total"]]
        uncompleted_quests = [quest for quest in quests if quest not in completed_quests]
        return {
            "completed": completed_quests,
            "uncompleted": uncompleted_quests,
            "str_result": f"{len(completed_quests)}/{len(quests)}"
        }


    async def ask_ai(self, question: str, chat_id: str = None, previous_message: dict = None):
        if chat_id is None:
            chat_id = str(uuid4())
            messages = [{
                "id": str(uuid4()),
                "role": "system",
                "content": self.system_prompt,
                "parts": [{"type": "text", "text": self.system_prompt}]
            }]
        else:
            messages = self.chats_memory[chat_id]

        if previous_message:
            # todo: mb not save prev messages locally, but get chat history from request
            messages.append(previous_message)

        messages.append({
            "id": str(uuid4()),
            "createdAt": get_current_date(),
            "role": "user",
            "content": question,
            "parts": [{"type": "text", "text": question}]
        })

        self.chats_memory[chat_id] = messages

        payload = {
            "id": chat_id,
            "messages": messages,
            "modelId": "gpt-4.1-mini-2025-04-14",
            "multiChainAddress": {"evmAddress": self.address},
            **self.signature_body,
        }
        if len(messages) == 2:
            payload["locale"] = "en"

        r = await self.session.post(
            url="https://app.heyelsa.ai/api/chat",
            json=payload,
            headers={
                "Referer": f"https://app.heyelsa.ai/chat/{chat_id}",
            }
        )
        return r.text, chat_id


    async def pipeline(
            self,
            action_type: str,
            bundled_execution: bool,
            **kwargs
    ):
        r = await self.send_request(
            method="POST",
            url="https://app.heyelsa.ai/api/pipeline",
            json={
                "pipeline": [{
                    "action_type": action_type,
                    **kwargs,
                }],
                "dry_run": True,
                "bundledExecution": bundled_execution,
                "isBrowserWallet": True
            },
        )
        return r.json()


    async def send_pipeline_data(self, chat_id: str, pipeline_data: dict | str, action: str):
        if action == "create_swap":
            next_action = "a831b0e504b3ba6cff855dc044e7b68692282af7"
            json = [pipeline_data, True]

        elif action == "get_swap_data":
            next_action = "fa538a090030a8a9e2a5fca2171f22dd1891f8be"
            json = [pipeline_data, True]

        elif action == "send_tx":
            next_action = "4595dcc7970106ab7b07f377d4ac56c9e37d4067"
            json = [pipeline_data, True]

        elif action == "signed_message":
            next_action = "9c7a4279b05b2de05c8b7d0a7f3a7fe717f202dc"
            json = [pipeline_data]

        r = await self.session.post(
            url=f"https://app.heyelsa.ai/chat/{chat_id}",
            json=json,
            headers={
                "Referer": f"https://app.heyelsa.ai/chat/{chat_id}",
                "Next-Action": next_action,
                "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22(main)%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2F%22%2C%22refresh%22%5D%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D",
                "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="134"',
                "Sec-Ch-Ua-Arch": '"x86"',
                "Sec-Ch-Ua-Bitness": '"64"',
                "Sec-Ch-Ua-Full-Version": '"136.0.6400.0"',
                "Sec-Ch-Ua-Full-Version-List": '"Not/A)Brand";v="8.0.0.0", "Chromium";v="134.0.6400.0"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Model": '""',
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Ch-Ua-Platform-Version": '"19.0.0"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            cookies={
                # "cf_clearance": "7IIbC8IKm5hiRZNxD9mnLuJvfFnakmkON1A_XSHazXI-1754410566-1.2.1.1-bSb8fZr6Lv9BcVpnTbdAcW1u6dbWhvBVRTWr4VAgku4AcQzS8ejBDY_jODstO.Kva5dq1v6_jUGvUxfufY_EhpTLYhRTdd6mwzL8_u9.24myOaNCaoP80G4nUOjJ8rvtMyu.bW1gboNeX98aSYc09N8KLf5irTKukdYLUJRnjgRbygsQZ6Aidb51ISQ_HkEpeUrCw6NeyVLHszJhltULLTp1pi9QO7zXpc.XcWs9tqU",
                "locale": "en",
            },
        )
        return r


    async def register_account(self, ref_code: str):
        r = await self.session.post(
            url="https://app.heyelsa.ai/",
            json=[self.address],
            headers={
                "Next-Action": "d2b7eee79fc50da3dc8db7ccb2d33e9dc428eb42",
                "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22(main)%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2F%22%2C%22refresh%22%5D%7D%2Cnull%2Cnull%2Ctrue%5D%7D%2Cnull%2Cnull%2Ctrue%5D",
                "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="134"',
                "Sec-Ch-Ua-Arch": '"x86"',
                "Sec-Ch-Ua-Bitness": '"64"',
                "Sec-Ch-Ua-Full-Version": '"136.0.6400.0"',
                "Sec-Ch-Ua-Full-Version-List": '"Not/A)Brand";v="8.0.0.0", "Chromium";v="134.0.6400.0"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Model": '""',
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Ch-Ua-Platform-Version": '"19.0.0"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            cookies={
                "locale": "en",
            },
        )

        r = await self.session.post(
            url="https://app.heyelsa.ai/",
            json=[
                {"evmAddress": self.address},
                "Injected",
                "$undefined",
                ref_code
            ],
            headers={
                "Next-Action": "387b8e2c267dcadab8db293e8b84de57649ec4cd",
                "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22(main)%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2C%22%2F%22%2C%22refresh%22%5D%7D%2Cnull%2Cnull%2Ctrue%5D%7D%2Cnull%2Cnull%2Ctrue%5D",
                "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="134"',
                "Sec-Ch-Ua-Arch": '"x86"',
                "Sec-Ch-Ua-Bitness": '"64"',
                "Sec-Ch-Ua-Full-Version": '"136.0.6400.0"',
                "Sec-Ch-Ua-Full-Version-List": '"Not/A)Brand";v="8.0.0.0", "Chromium";v="134.0.6400.0"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Model": '""',
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Ch-Ua-Platform-Version": '"19.0.0"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            cookies={
                "locale": "en",
            },
        )
