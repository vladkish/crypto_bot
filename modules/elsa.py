from random import uniform, randint, choice, random
from loguru import logger
from web3.auto import w3
from os import urandom
from json import loads
from uuid import uuid4
import asyncio
import string
import re

from modules.utils import get_current_date, round_cut, make_border
from modules.rpc_initializer import RPCInitializer
from modules.retry import CustomError, retry
from modules.config import TOKEN_ADDRESSES
from modules.browser import Browser
from modules.wallet import Wallet
from settings import SWAP_SETTINGS, BRIDGE_SETTINGS, MINT_NFT


class Elsa:
    def __init__(self, wallet: Wallet, browser: Browser):
        self.wallet = wallet
        self.browser = browser


    async def run(self, module_info: dict):
        await self.browser.get_country_code()

        await self.login()

        if (
                MINT_NFT and
                random() <= 1 / max(1, await self.wallet.db.get_wallet_modules_left(encoded_pk=self.wallet.encoded_pk))
        ):
            try:
                await self.mint_elsian_nft()
            except Exception as err:
                self.log_message(f"Failed to mint Elsa NFT: {err}", "-", "ERROR")
                await self.wallet.db.append_report(
                    encoded_pk=self.wallet.encoded_pk,
                    text=f"failed to mint Elsa NFT",
                    success=True
                )

        await self.process_actions(module_info=module_info)

        if await self.wallet.db.get_wallet_modules_left(encoded_pk=self.wallet.encoded_pk) == 1:
            points = await self.browser.get_points()
            quests = await self.browser.get_quests()
            self.log_message("Wallet stats:\n" + make_border(
                    table_elements={
                        "Points": points['points_v2'],
                        "Rank": points['rank_v2'],
                        "Completed quests": quests['str_result']
                    },
                    values_color="white"
                )
            )
            await self.wallet.db.append_report(
                encoded_pk=self.wallet.encoded_pk,
                text=f"\n⭐️ <b>points</b> {points['points_v2']}\n"
                     f"🏆 <b>rank</b> {points['rank_v2']}\n"
                     f"📝 <b>completed quests</b> {quests['str_result']}",
            )

        return True


    async def process_actions(self, module_info: dict):
        actions = {
            "swap": self.process_swap,
            "bridge": self.process_bridge,
        }
        if module_info["module_name"] not in actions:
            raise Exception(f'Unexpected module "{module_info["module_name"]}"')
        else:
            return await actions[module_info["module_name"]](module_info)


    async def process_swap(self, module_info: dict):
        if not module_info["advance_info"]:
            random_token = choice(SWAP_SETTINGS["tokens"])
            eth_usd_amount = round(uniform(*SWAP_SETTINGS["swap_eth_usd"]), randint(0, 2))

            await self.swap(
                chain_name="Base",
                from_token="ETH",
                to_token=random_token,
                usd_amount=eth_usd_amount
            )
            await self.wallet.db.add_wallet_module(
                encoded_pk=self.wallet.encoded_pk,
                new_module={"module_name": "swap", "status": "to_run", "advance_info": {"token_name": random_token}}
            )

        else:
            random_token = module_info["advance_info"]["token_name"]
            token_balance = await self.wallet.get_balance(chain_name="base", token_name=random_token, human=True)
            back_swap_percent = uniform(*SWAP_SETTINGS["back_swap"]) / 100

            await self.swap(
                chain_name="Base",
                from_token=random_token,
                to_token="ETH",
                token_amount=float(round_cut(token_balance * back_swap_percent, randint(5, 7)))
            )


    async def process_bridge(self, module_info: dict):
        if not module_info["advance_info"]:
            random_chain = choice(BRIDGE_SETTINGS["to_chains"])
            eth_usd_amount = round(uniform(*BRIDGE_SETTINGS["bridge_eth_usd"]), randint(0, 2))

            eth_bridged = await self.bridge(
                from_chain="base",
                to_chain=random_chain,
                usd_amount=eth_usd_amount
            )
            await self.wallet.db.add_wallet_module(
                encoded_pk=self.wallet.encoded_pk,
                new_module={
                    "module_name": "bridge",
                    "status": "to_run",
                    "advance_info": {
                        "from_chain": random_chain,
                        "token_amount": eth_bridged,
                    }
                }
            )

        else:
            from_chain = module_info["advance_info"]["from_chain"]
            token_amount = module_info["advance_info"]["token_amount"]

            chain_balance = await self.wallet.get_balance(chain_name=from_chain, human=True)
            if chain_balance - token_amount <= 0.000005: # if was no balance before bridge in chain
                token_amount -= 0.000005

            await self.bridge(
                from_chain=from_chain,
                to_chain="base",
                token_amount=float(round_cut(token_amount, randint(5, 7))),
            )


    @retry("Elsa")
    async def swap(
            self,
            chain_name: str,
            from_token: str,
            to_token: str,
            token_amount: float = 0,
            usd_amount: float = 0,
    ):
        with open('input_data/swap_prompts.txt') as f:
            swap_prompts_raw = f.read().splitlines()
        if token_amount:
            prompt_template = ['token_amount', 'from_token', 'to_token', 'chain_name']
        elif usd_amount:
            prompt_template = ['usd_amount', 'from_token', 'to_token', 'chain_name']
        else:
            raise Exception(f'For swap any of `token_amount`, `usd_amount` must be provided!')

        swap_prompts = [
            prompt
            for prompt in swap_prompts_raw
            if re.findall(r"\{([^}]+)\}", prompt) == prompt_template
        ]
        if not swap_prompts:
            raise Exception(f'Not found any prompt in `input_data/swap_prompts.txt` with variables: ' + ", ".join(prompt_template))
        else:
            swap_prompt = choice(swap_prompts)

        ai_question = swap_prompt.format(
            from_token=from_token,
            to_token=to_token,
            chain_name=chain_name,
            token_amount=token_amount,
            usd_amount=usd_amount,
        )

        chat_id, ai_response = await self.ask_elsa(
            ai_question,
            "show_swap_or_bridge_ui",
            "Not found Swap routes"
        )
        ai_response = await self.process_elsa_swap_or_bridge(chat_id=chat_id, ai_response=ai_response)

        from_chain = ai_response["tx"]["json_data"]["estimate"]["from_chain"]
        web3 = self.wallet.get_web3(from_chain)
        action_name = ai_response["tx"]["json_data"]["short_description"]
        tx_label = action_name[0].lower() + action_name[1:]
        self.log_message(action_name)

        if ai_response["tx"].get("signature"):
            old_balance = await self.wallet.get_balance(chain_name=from_chain, human=True)
            r = await self.browser.send_pipeline_data(
                chat_id=ai_response["chat"]["id"],
                pipeline_data={
                    "task_id": ai_response["chat"]["pipeline_id"],
                    "status": "signed",
                    "signature": ai_response["tx"]["signature"]
                },
                action="signed_message"
            )
            await self.wallet.wait_balance(chain_name=from_chain, needed_balance=old_balance, only_more=True)
            # todo: mb add последний запрос для красоты (после свапа через подпись)

            self.log_message(action_name, "+", "SUCCESS")
            await self.wallet.db.append_report(
                encoded_pk=self.wallet.encoded_pk,
                text=tx_label,
                success=True
            )

        else:

            tx = {
                "from": self.wallet.address,
                "to": w3.to_checksum_address(ai_response["tx"]["json_data"]["evm_tx_data"]["to"]),
                "data": ai_response["tx"]["data"],
                "gas": int(ai_response["tx"]["json_data"]["evm_tx_data"]["gas"], 16),
                "value": int(ai_response["tx"]["json_data"]["evm_tx_data"]["value"], 16),
                'chainId': int(ai_response["tx"]["json_data"]["evm_tx_data"]["chain_id"], 16),
                'nonce': await web3.eth.get_transaction_count(self.wallet.address),
            }
            tx_hash = await self.wallet.sent_tx(
                chain_name=from_chain,
                tx=tx,
                tx_label=tx_label,
                tx_raw=True,
            )

            await self.browser.send_pipeline_data(
                chat_id=ai_response["chat"]["id"],
                pipeline_data={
                    "task_id": ai_response["chat"]["pipeline_id"],
                    "status": "submitted",
                    "tx_hash": str(tx_hash)
                },
                action="send_tx"
            )

        return True


    @retry("Elsa")
    async def bridge(
            self,
            from_chain: str,
            to_chain: str,
            token_amount: float = 0,
            usd_amount: float = 0,
    ):
        with open('input_data/bridge_prompts.txt') as f:
            bridge_prompts_raw = f.read().splitlines()
        if token_amount:
            prompt_template = ['token_amount', 'from_chain', 'to_chain']
        elif usd_amount:
            prompt_template = ['usd_amount', 'from_chain', 'to_chain']
        else:
            raise Exception(f'For bridge any of `token_amount`, `usd_amount` must be provided!')

        bridge_prompts = [
            prompt
            for prompt in bridge_prompts_raw
            if re.findall(r"\{([^}]+)\}", prompt) == prompt_template
        ]
        if not bridge_prompts:
            raise Exception(f'Not found any prompt in `input_data/bridge_prompts.txt` with variables: ' + ", ".join(prompt_template))
        else:
            bridge_prompt = choice(bridge_prompts)

        ai_question = bridge_prompt.format(
            from_chain=from_chain,
            to_chain=to_chain,
            token_amount=token_amount,
            usd_amount=usd_amount,
        )

        chat_id, ai_response = await self.ask_elsa(
            ai_question,
            "show_swap_or_bridge_ui",
            "Not found Bridge routes"
        )
        ai_response = await self.process_elsa_swap_or_bridge(chat_id=chat_id, ai_response=ai_response)

        from_chain = ai_response["tx"]["json_data"]["estimate"]["from_chain"]
        web3 = self.wallet.get_web3(from_chain)
        action_name = ai_response["tx"]["json_data"]["short_description"]
        tx_label = action_name[0].lower() + action_name[1:]
        self.log_message(action_name)

        old_balance = await self.wallet.get_balance(chain_name=to_chain, human=True)
        tx = {
            "from": self.wallet.address,
            "to": w3.to_checksum_address(ai_response["tx"]["json_data"]["evm_tx_data"]["to"]),
            "data": ai_response["tx"]["json_data"]["evm_tx_data"]["data"],
            "gas": int(ai_response["tx"]["json_data"]["evm_tx_data"]["gas"], 16),
            "value": int(ai_response["tx"]["json_data"]["evm_tx_data"]["value"], 16),
            'chainId': int(ai_response["tx"]["json_data"]["evm_tx_data"]["chain_id"], 16),
            'nonce': await web3.eth.get_transaction_count(self.wallet.address),
        }
        tx_hash = await self.wallet.sent_tx(
            chain_name=from_chain,
            tx=tx,
            tx_label=tx_label,
            tx_raw=True,
        )

        r = await self.browser.send_pipeline_data(
            chat_id=ai_response["chat"]["id"],
            pipeline_data={
                "task_id": ai_response["chat"]["pipeline_id"],
                "status": "submitted",
                "tx_hash": str(tx_hash)
            },
            action="send_tx"
        )
        new_balance = await self.wallet.wait_balance(
            chain_name=to_chain,
            needed_balance=old_balance,
            only_more=True
        )

        return new_balance - old_balance


    @retry(source="Elsa")
    async def login(self):
        ref_code = await self.wallet.db.get_ref_code(self.wallet.address)
        expired_at = get_current_date({"days": 1})
        issued_at = get_current_date()

        sign_text = f"""app.heyelsa.ai wants you to sign in with your Ethereum account:
{self.wallet.address}


URI: https://app.heyelsa.ai
Version: 1
Chain ID: 8453
Nonce: {self._generate_nonce()}
Issued At: {issued_at}
Expiration Time: {expired_at}"""
        signature = self.wallet.sign_message(text=sign_text)
        await self.browser.auth(sign_text=sign_text, signature=signature, ref_code=ref_code)

        self.browser.signature_body.update({
            "sign_in_message": sign_text,
            "signature": signature,
        })

        points = await self.browser.get_points()
        if points.get("referral_code") is None:
            await self.browser.register_account(ref_code=ref_code)
            if ref_code:
                self.log_message(f"Register account with referral code <white>{ref_code}</white>")
                tg_log = f"register with ref code {ref_code}"
            else:
                self.log_message(f"Register account <red>without</red> referral code")
                tg_log = f"register <b>without</b> ref code"

            await self.wallet.db.append_report(
                encoded_pk=self.wallet.encoded_pk,
                text=tg_log,
                success=True,
            )
            points = await self.browser.get_points()

        await self.wallet.db.add_new_ref_code(self.wallet.address, points["referral_code"])


    async def ask_elsa(
            self,
            question: str,
            ai_response_tool_name: str,
            error_text: str,
    ):
        self.log_message(f'Ask Elsa "<white>{question}</white>"')
        ai_resp, chat_id = await self.browser.ask_ai(question)
        ai_response = self.format_response(ai_resp, ai_response_tool_name)
        if ai_response["formatted_resp"] is None:
            if ai_response["buttons"]:
                agree_button = next(
                    (
                        button for button in ai_response["buttons"]
                        if (
                            "yes" in button.lower() or
                            button.startswith("Proceed")  # for some shitcoins
                        )
                    ), None
                )
                if agree_button:
                    ai_resp, chat_id = await self.browser.ask_ai(
                        question=agree_button,
                        previous_message=ai_response["previous_message"],
                        chat_id=chat_id
                    )
                    ai_response = self.format_response(ai_resp, ai_response_tool_name)
                    if ai_response["formatted_resp"] is None:
                        raise Exception(f'{error_text} in AI answer (after Yes)')
                else:
                    raise Exception(f'{error_text} in AI answer (no agree button)')
            else:
                raise Exception(f'{error_text} in AI answer (no buttons)')

        return chat_id, ai_response


    async def process_elsa_swap_or_bridge(self, chat_id: str, ai_response: dict):
        swap_data_raw = ai_response["formatted_resp"]["response"]["result"]
        swap_data = {
            "amount": swap_data_raw["amount"],
            "from_asset": swap_data_raw["fromToken"],
            "from_chain": swap_data_raw["fromChain"],
            "to_asset": swap_data_raw["toToken"],
            "to_chain": swap_data_raw["toChain"],
            "eoa_address": swap_data_raw["fromAddress"],
            "to_address": swap_data_raw["toAddress"],
            "slippage": swap_data_raw["slippage"],
            "provider": swap_data_raw["provider"],
        }
        pipeline_resp_ = await self.browser.pipeline(
            action_type="swap",  # was `swap_data_raw["type"]` - swap, but for `bridge` we need `swap` too
            bundled_execution=swap_data_raw["bundledExecution"],
            swap_data=swap_data,
        )

        for pipeline_resp in pipeline_resp_:
            if pipeline_resp.get("action_type") == "approve":
                pass

            elif pipeline_resp.get("action_type") == "swap":
                swap_estimate_id = pipeline_resp["estimate"]["id"]

            else:
                self.log_message(f"Unexpected action type: {pipeline_resp}", "!", "ERROR")

        pipeline_data = {
            "pipeline": [{"action_type": "swap", "swap_estimate_id": swap_estimate_id}],
            "bundled_execution": swap_data_raw["bundledExecution"],
            "message_id": ai_response["formatted_resp"]["response"]["toolCallId"]
        }
        pipeline_resp_raw  = await self.browser.send_pipeline_data(
            chat_id=chat_id,
            pipeline_data=pipeline_data,
            action="create_swap"
        )
        pipeline_resp = self.format_response_by_num(pipeline_resp_raw.text, "1")
        if (
                pipeline_resp.get("status") != 200 or
                pipeline_resp.get("data") is None or
                pipeline_resp["data"].get("pipeline_id") is None
        ):
            raise Exception(f'Unexpected pipeline id response: {pipeline_resp}')
        pipeline_id = pipeline_resp["data"]["pipeline_id"]

        while True:
            r = await self.browser.send_pipeline_data(
                chat_id=chat_id,
                pipeline_data=pipeline_id,
                action="get_swap_data"
            )

            sign_message_raw_resp = self.format_response_by_num(r.text, "1")
            tx_raw_resp = self.format_response_by_num(r.text, "2", json_format=False)
            if tx_raw_resp:
                tx_raw_resp = tx_raw_resp[tx_raw_resp.find(',') + 1:]
                json_resp = loads(tx_raw_resp.split('1:')[1])
                tx_data = tx_raw_resp.split('1:')[0]
                tx_json_data = next((action for action in json_resp["data"] if action.get("action_type") == "swap"), None)
                if tx_json_data is None:
                    raise Exception(f'Failed to get transaction data: {json_resp}')
                tx = {
                    "json_data": tx_json_data,
                    "data": tx_data
                }
                break

            elif sign_message_raw_resp:
                approve_response = next(
                    (
                        raw_resp for raw_resp in sign_message_raw_resp["data"]
                        if raw_resp["action_type"] == "approve"
                    ), None
                )
                swap_response = next(
                    (
                        raw_resp for raw_resp in sign_message_raw_resp["data"]
                        if raw_resp["action_type"] == "swap"
                    ), None
                )

                if swap_response and swap_response.get("evm_typed_data"):
                    sign_typed_data = {
                        "domain": swap_response["evm_typed_data"]["domain"],
                        "message": swap_response["evm_typed_data"]["message"],
                        "primaryType": swap_response["evm_typed_data"]["primaryType"],
                        "types": {
                            "EIP712Domain": [{"name": "name", "type": "string"}, {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
                            **swap_response["evm_typed_data"]["types"],
                        },
                    }
                    signature = self.wallet.sign_message(typed_data=sign_typed_data)
                    tx = {
                        "json_data": swap_response,
                        "signature": signature,
                    }
                    pipeline_id = swap_response["task_id"]
                    break

                elif swap_response and swap_response.get("evm_tx_data"):  # for bridges
                    tx = {"json_data": swap_response}
                    pipeline_id = swap_response["task_id"]
                    break

                elif approve_response and approve_response.get("evm_tx_data"):
                    token_contract = w3.eth.contract(
                        abi='[{"inputs":[{"internalType":"address","name":"spender","type":"address"},{"internalType":"uint256","name":"value","type":"uint256"}],"name":"approve","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"}]',
                    )
                    spender = token_contract.decode_function_input(approve_response["evm_tx_data"]["data"])[1]["spender"]
                    value_approve = token_contract.decode_function_input(approve_response["evm_tx_data"]["data"])[1]["value"]

                    if swap_data["from_asset"].startswith("0x"):
                        approve_token_name = next(
                            (
                                token_name for token_name, token_address
                                in TOKEN_ADDRESSES[swap_data["from_chain"]].items()
                                if token_address.lower() == swap_data["from_asset"].lower()
                            ), None
                        )
                    else:
                        approve_token_name = swap_data["from_asset"]

                    tx_hash = await self.wallet.approve(
                        chain_name=swap_data["from_chain"],
                        token_name=approve_token_name,
                        spender=spender,
                        value=value_approve,  # `float(swap_data["amount"])` for correct amount
                        force_approve=True
                    )
                    if approve_response["status"] == "sign_pending":
                        r = await self.browser.send_pipeline_data(
                            chat_id=chat_id,
                            pipeline_data={
                                "task_id": pipeline_id,
                                "status": "submitted",
                                "tx_hash": str(tx_hash)
                            },
                            action="send_tx"
                        )

            await asyncio.sleep(3)

        return {
            "tx": tx,
            "chat": {
                "id": chat_id,
                "pipeline_id": pipeline_id
            },
        }


    async def mint_elsian_nft(self):
        quests = await self.browser.get_quests()
        mint_nft_quest = next((
            quest for quest in quests["uncompleted"]
            if (
                quest["quest_type"] == "onboarding" and
                quest["title"] == "Mint the Elsian NFT"
            )
        ), None)
        if not mint_nft_quest:
            return True

        chat_id, ai_response = await self.ask_elsa(
            "Mint Elsa PFP NFT",
            "show_nft_minting_widget_ui",
            "Not found Mint NFT data"
        )

        pipeline_data = {
            "pipeline": [{
                "action_type": "mint_nft",
                "mint_nft_data": {"nft": "elsa-pfp", "count": 1, "eoa_address": self.wallet.address}
            }],
            "bundled_execution": False
        }
        pipeline_resp_raw = await self.browser.send_pipeline_data(
            chat_id=chat_id,
            pipeline_data=pipeline_data,
            action="create_swap"
        )

        pipeline_resp = self.format_response_by_num(pipeline_resp_raw.text, "1")
        if (
                pipeline_resp.get("status") != 200 or
                pipeline_resp.get("data") is None or
                pipeline_resp["data"].get("pipeline_id") is None
        ):
            raise Exception(f'Unexpected pipeline id response: {pipeline_resp}')
        pipeline_id = pipeline_resp["data"]["pipeline_id"]

        while True:
            r = await self.browser.send_pipeline_data(
                chat_id=chat_id,
                pipeline_data=pipeline_id,
                action="get_swap_data"
            )

            mint_nft_data = self.format_response_by_num(r.text, "1")
            if mint_nft_data and mint_nft_data.get("data") and mint_nft_data["data"][0].get("evm_tx_data"):
                mint_tx_data = mint_nft_data["data"][0]
                break

            await asyncio.sleep(3)

        from_chain = "base"
        web3 = self.wallet.get_web3(from_chain)
        tx_label = mint_tx_data["short_description"][:1].lower() + mint_tx_data["short_description"][1:]

        tx = {
            "from": self.wallet.address,
            "to": w3.to_checksum_address(mint_tx_data["evm_tx_data"]["to"]),
            "data": mint_tx_data["evm_tx_data"]["data"],
            "gas": int(mint_tx_data["evm_tx_data"]["gas"], 16),
            "value": int(mint_tx_data["evm_tx_data"]["value"], 16),
            'chainId': int(mint_tx_data["evm_tx_data"]["chain_id"], 16),
            'nonce': await web3.eth.get_transaction_count(self.wallet.address),
        }
        tx_hash = await self.wallet.sent_tx(
            chain_name=from_chain,
            tx=tx,
            tx_label=tx_label,
            tx_raw=True,
        )

        r = await self.browser.send_pipeline_data(
            chat_id=chat_id,
            pipeline_data={
                "task_id": mint_tx_data["task_id"],
                "status": "submitted",
                "tx_hash": str(tx_hash)
            },
            action="send_tx"
        )
        return True


    @classmethod
    def _generate_nonce(
            cls,
            charset: str = string.digits + string.ascii_uppercase + string.ascii_lowercase,
            length: int = 17
    ):
        result = ""
        charset_length = len(charset)
        usable_range = 256 - (256 % charset_length)

        while length > 0:
            bytes_needed = (256 * length + usable_range - 1) // usable_range
            random_bytes = urandom(bytes_needed)

            for b in random_bytes:
                if length == 0:
                    break
                if b < usable_range:
                    result += charset[b % charset_length]
                    length -= 1

        return result


    @classmethod
    def format_response(cls, response_text: str, label: str):
        formatted_responses = []
        splitted_text = response_text.splitlines()
        for index, part_text in enumerate(splitted_text):
            # start of new part
            if part_text.startswith("f:"):
                message_id = loads(part_text[2:])["messageId"]
                formatted_responses.append({"message_id": message_id})
            # human text
            elif part_text.startswith("0:"):
                # if len(formatted_responses[-1]) == 1:
                if formatted_responses[-1].get("response") is None:
                    formatted_responses[-1]["response"] = ""
                formatted_responses[-1]["response"] += part_text[3:-1]
            # json
            else:
                part_text = part_text[2:]
                if part_text.startswith("{") and part_text.endswith("}"):
                    if formatted_responses[-1].get("response") is None:
                        formatted_responses[-1]["response"] = {}
                    json_part = loads(part_text)
                    if json_part.get("toolCallId"):
                        formatted_responses[-1]["response"].update(json_part)

        # GET TEXT AI ANSWER
        text_raw_resp = next((
            resp for resp in formatted_responses
            if (
                type(resp["response"]) == str
        )
        ), None)

        # FORMAT ANSWER FOR NEXT QUESTION (previous_message)
        message_parts = []
        tool_invocations = []
        for part_index, part_response in enumerate(formatted_responses):
            if type(part_response["response"]) == dict:
                tool_invocation = {
                    "state": "result",
                    "toolCallId": part_response["response"]["toolCallId"],
                    "toolName": part_response["response"]["toolName"],
                    "args": part_response["response"]["args"],
                    "result": part_response["response"]["result"]
                }
                message_parts.append({
                    "type": "tool-invocation",
                    "toolInvocation": {
                        **tool_invocation,
                        "step": part_index,
                    }
                })
                tool_invocations.append({
                    **tool_invocation,
                    "step": len(tool_invocations)
                })
            else:
                message_parts.append({
                    "type": "text",
                    "text": part_response["response"]
                })

        previous_message = {
            "createdAt": get_current_date(),
            "role": "assistant",
            "parts": message_parts,
            "toolInvocations": tool_invocations,
            "revisionId": str(uuid4())
        }
        if text_raw_resp:
            previous_message.update({
                "id": text_raw_resp["message_id"],
                "content": text_raw_resp["response"],
            })

        buttons = None
        for el in formatted_responses:
            if type(el["response"]) == str:
                buttons = re.findall(r':suggestion\[(.*?)\]', el["response"])

        """
        formatted_responses: list[dict]
        [
            {
                "message_id": (str),
                "response": (
                    str: ai_response_text |
                    dict: {
                        "toolCallId": str,
                        "toolName": str,
                        "args": dict,
                        "result": dict,
                    }
                )
            },
        ]
        """

        formatted_resp = next((
            resp for resp in formatted_responses
            if (
                type(resp["response"]) == dict and
                resp["response"].get("toolName") == label
            )
        ), None)

        return {
            "formatted_resp": formatted_resp,
            "previous_message": previous_message,
            "raw_results": formatted_responses,
            # "text_answer": text_raw_resp["response"].replace('\\n', '\n') if text_raw_resp else None,
            "buttons": buttons,
        }

    @classmethod
    def format_response_by_num(cls, response_text: str, index: str | int, json_format: bool = True):
        for text_part in response_text.splitlines():
            if text_part.startswith(f"{index}:"):
                text_part = text_part.removeprefix(f"{index}:")
                if json_format:
                    if text_part.startswith("{") and text_part.endswith("}"):
                        return loads(text_part)
                else:
                    return text_part
        return None


    def log_message(
            self,
            text: str,
            smile: str = "•",
            level: str = "DEBUG",
            colors: bool = True
    ):
        label = f"<white>{self.wallet.address}</white>" if colors else self.wallet.address
        logger.opt(colors=colors).log(level.upper(), f'[{smile}] {label} | {text}')
