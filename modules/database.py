from random import choice, randint, shuffle, random
from cryptography.fernet import Fernet
from base64 import urlsafe_b64encode
from time import sleep, time
from os import path, mkdir
from loguru import logger
from hashlib import md5
import asyncio
import json

from .retry import DataBaseError
from modules.utils import get_address, WindowName, sleeping
from settings import SHUFFLE_WALLETS, SWAP_SETTINGS, BRIDGE_SETTINGS, USE_REF_CHANCE

from cryptography.fernet import InvalidToken


class DataBase:
    def __init__(self):

        self.modules_db_name = 'databases/modules.json'
        self.report_db_name = 'databases/report.json'
        self.refs_db_name = 'databases/refcodes.json'
        self.personal_key = None
        self.window_name = None

        self.changes_lock = asyncio.Lock()

        # create db's if not exists
        if not path.isdir(self.modules_db_name.split('/')[0]):
            mkdir(self.modules_db_name.split('/')[0])

        for db_params in [
            {"name": self.modules_db_name, "value": "[]"},
            {"name": self.report_db_name, "value": "{}"},
            {"name": self.refs_db_name, "value": "[]"},
        ]:
            if not path.isfile(db_params["name"]):
                with open(db_params["name"], 'w') as f: f.write(db_params["value"])

        with open('input_data/proxies.txt') as f:
            self.proxies = [
                "http://" + proxy.removeprefix("https://").removeprefix("http://")
                for proxy in f.read().splitlines()
                if proxy not in ['https://log:pass@ip:port', 'http://log:pass@ip:port', 'log:pass@ip:port', '', None]
            ]

        amounts = self.get_amounts()
        logger.info(f'Loaded {amounts["modules_amount"]} modules for {amounts["accs_amount"]} accounts\n')


    def set_password(self):
        if self.personal_key is not None: return

        logger.debug(f'Enter password to encrypt privatekeys (empty for default):')
        raw_password = input("")

        if not raw_password:
            raw_password = "@karamelniy dumb shit encrypting"
            logger.success(f'[+] Soft | You set empty password for Database\n')
        else:
            print(f'')
        sleep(0.2)

        password = md5(raw_password.encode()).hexdigest().encode()
        self.personal_key = Fernet(urlsafe_b64encode(password))


    def get_password(self):
        if self.personal_key is not None: return

        with open(self.modules_db_name, encoding="utf-8") as f: modules_db = json.load(f)
        if not modules_db: return

        first_pk = list(modules_db.keys())[0]
        if not first_pk: return
        try:
            temp_key = Fernet(urlsafe_b64encode(md5("@karamelniy dumb shit encrypting".encode()).hexdigest().encode()))
            self.decode_pk(pk=first_pk, key=temp_key)
            self.personal_key = temp_key
            return
        except InvalidToken: pass

        while True:
            try:
                logger.debug(f'Enter password to decrypt your privatekeys (empty for default):')
                raw_password = input("")
                password = md5(raw_password.encode()).hexdigest().encode()

                temp_key = Fernet(urlsafe_b64encode(password))
                self.decode_pk(pk=first_pk, key=temp_key)
                self.personal_key = temp_key
                logger.success(f'[+] Soft | Access granted!\n')
                return

            except InvalidToken:
                logger.error(f'[-] Soft | Invalid password\n')


    def encode_pk(self, pk: str, key: None | Fernet = None):
        if key is None:
            return self.personal_key.encrypt(pk.encode()).decode()
        return key.encrypt(pk.encode()).decode()


    def decode_pk(self, pk: str, key: None | Fernet = None):
        if key is None:
            return self.personal_key.decrypt(pk).decode()
        return key.decrypt(pk).decode()


    def create_modules(self, mode: int):
        def create_raw_modules():
            swap_modules = [
                {"module_name": "swap", "status": "to_run", "advance_info": {}}
                for _ in range(randint(*SWAP_SETTINGS["swap_times"]))
            ]
            bridge_modules = [
                {"module_name": "bridge", "status": "to_run", "advance_info": {}}
                for _ in range(randint(*BRIDGE_SETTINGS["bridge_times"]))
            ]
            return swap_modules + bridge_modules

        self.set_password()

        with open('input_data/privatekeys.txt') as f:
            privatekeys = f.read().splitlines()

        with open('input_data/proxies.txt') as f:
            proxies = f.read().splitlines()
        if len(proxies) == 0 or proxies == [""] or proxies == ["http://login:password@ip:port"]:
            logger.error('You will not use proxy')
            proxies = [None for _ in range(len(privatekeys))]
        else:
            proxies = list(proxies * (len(privatekeys) // len(proxies) + 1))[:len(privatekeys)]

        with open(self.report_db_name, 'w') as f: f.write('{}')  # clear report db

        new_modules = {
            self.encode_pk(pk): {
                "address": get_address(pk),
                "modules": create_raw_modules(),
                "proxy": proxy,
            }
            for pk, proxy in zip(privatekeys, proxies)
        }

        with open(self.modules_db_name, 'w', encoding="utf-8") as f: json.dump(new_modules, f)
        amounts = self.get_amounts()
        logger.info(f'Created Database for {amounts["accs_amount"]} accounts with {amounts["modules_amount"]} modules!\n')


    def get_amounts(self):
        with open(self.modules_db_name, encoding="utf-8") as f: modules_db = json.load(f)
        modules_len = sum([len(modules_db[acc]["modules"]) for acc in modules_db])

        for acc in modules_db:
            for index, module in enumerate(modules_db[acc]["modules"]):
                if module["status"] in ["failed", "cloudflare"]: modules_db[acc]["modules"][index]["status"] = "to_run"

        with open(self.modules_db_name, 'w', encoding="utf-8") as f:
            json.dump(modules_db, f)

        if self.window_name == None: self.window_name = WindowName(accs_amount=len(modules_db))
        else: self.window_name.accs_amount = len(modules_db)
        self.window_name.set_modules(modules_amount=modules_len)

        return {
            'accs_amount': len(modules_db),
            'modules_amount': modules_len,
        }


    def get_all_modules(self):
        self.get_password()
        with open(self.modules_db_name, encoding="utf-8") as f: modules_db = json.load(f)

        if not modules_db:
            return 'No more accounts left'

        all_wallets_modules = [
            {
                'privatekey': self.decode_pk(pk=encoded_privatekey),
                'encoded_privatekey': encoded_privatekey,
                'proxy': wallet_data.get("proxy"),
                'address': wallet_data["address"],
                'module_info': wallet_data["modules"][0],
                'last': True
            }
            for encoded_privatekey, wallet_data in modules_db.items()
        ]
        if SHUFFLE_WALLETS:
            shuffle(all_wallets_modules)
        return all_wallets_modules


    def get_random_module(self, active_wallets: list):
        self.get_password()
        with open(self.modules_db_name, encoding="utf-8") as f: modules_db = json.load(f)

        all_wallets_modules = []
        for encoded_privatekey, wallet_data in modules_db.items():
            if wallet_data["address"] in active_wallets:
                continue

            sell_modules = [
                module for module in wallet_data["modules"]
                if (
                           module["advance_info"] and
                           module["module_name"] == "swap" and
                           module["status"] == "to_run"
                )
            ]
            back_bridge_modules = [
                module for module in wallet_data["modules"]
                if (
                           module["advance_info"] and
                           module["module_name"] == "bridge" and
                           module["status"] == "to_run"
                )
            ]
            wallet_modules = []
            if len(back_bridge_modules) >= BRIDGE_SETTINGS["max_chains_hold"]:
                wallet_modules += back_bridge_modules
            if len(sell_modules) >= SWAP_SETTINGS["max_token_hold"]:
                wallet_modules += sell_modules
            if not wallet_modules:
                wallet_modules = wallet_data["modules"]

            all_wallets_modules += [
                {
                    'privatekey': self.decode_pk(pk=encoded_privatekey),
                    'encoded_privatekey': encoded_privatekey,
                    'proxy': wallet_data.get("proxy"),
                    'address': wallet_data["address"],
                    'module_info': module_info,
                }
                for module_info in wallet_modules
                if module_info["status"] == "to_run"
            ]

        if not all_wallets_modules:
            return 'No more accounts left'
        elif SHUFFLE_WALLETS:
            shuffle(all_wallets_modules)

        return all_wallets_modules[0]


    async def remove_module(self, module_data: dict):
        async with self.changes_lock:
            with open(self.modules_db_name, encoding="utf-8") as f: modules_db = json.load(f)
            self.window_name.add_module()
            for module_index, module in enumerate(modules_db[module_data["encoded_privatekey"]]["modules"]):
                if module == {**module_data["module_info"], "status": "to_run"}:
                    if module_data["module_info"]["status"] in [True, "completed"]:
                        if len(modules_db[module_data["encoded_privatekey"]]["modules"]) == 1:
                            self.window_name.add_acc()
                            del modules_db[module_data["encoded_privatekey"]]
                        else:
                            modules_db[module_data["encoded_privatekey"]]["modules"].pop(module_index)

                    else:
                        modules_db[module_data["encoded_privatekey"]]["modules"][module_index]["status"] = "failed"

                    break

            with open(self.modules_db_name, 'w', encoding="utf-8") as f:
                json.dump(modules_db, f)


    async def remove_account(self, module_data: dict):
        async with self.changes_lock:
            with open(self.modules_db_name, encoding="utf-8") as f: modules_db = json.load(f)
            self.window_name.add_acc()
            if module_data["module_info"]["status"] in [True, "completed"]:
                del modules_db[module_data["encoded_privatekey"]]
            else:
                modules_db[module_data["encoded_privatekey"]]["modules"] = [
                    {**module, "status": "failed"}
                    for module in modules_db[module_data["encoded_privatekey"]]["modules"]
                ]

            with open(self.modules_db_name, 'w', encoding="utf-8") as f:
                json.dump(modules_db, f)


    async def add_wallet_module(self, encoded_pk: str, new_module: dict):
        async with self.changes_lock:
            with open(self.modules_db_name, encoding="utf-8") as f: modules_db = json.load(f)
            modules_db[encoded_pk]["modules"].append(new_module)

            with open(self.modules_db_name, 'w', encoding="utf-8") as f:
                json.dump(modules_db, f)


    async def get_wallet_modules_left(self, encoded_pk: str):
        async with self.changes_lock:
            with open(self.modules_db_name, encoding="utf-8") as f: modules_db = json.load(f)
            if modules_db.get(encoded_pk) is None: return 0
            return len([module for module in modules_db[encoded_pk]["modules"] if module["status"] == "to_run"])


    async def add_new_ref_code(self, address: str, code: str):
        async with self.changes_lock:
            with open(self.refs_db_name, encoding="utf-8") as f:
                refs_db = json.load(f)
            old_record = next((
                ref_data for ref_data in refs_db
                if ref_data["owner"] == address
            ), None)
            if old_record is None:
                refs_db.append({
                    "owner": address,
                    "code": code,
                    "used": False,
                })
                with open(self.refs_db_name, 'w', encoding="utf-8") as f:
                    json.dump(refs_db, f)


    async def get_ref_code(self, address: str):
        async with self.changes_lock:
            with open(self.refs_db_name, encoding="utf-8") as f:
                refs_db = json.load(f)
            old_record = next((
                ref_data for ref_data in refs_db
                if ref_data["owner"] == address
            ), None)
            if old_record or not refs_db:
                return ""

            if random() <= USE_REF_CHANCE / 100:
                for ref_data in refs_db:
                    if ref_data["used"]: continue
                    ref_data["used"] = True
                    with open(self.refs_db_name, 'w', encoding="utf-8") as f:
                        json.dump(refs_db, f)

                    return ref_data["code"]

                return choice(refs_db)["code"] # if no free ref codes left

            return ""


    async def append_report(self, encoded_pk: str, text: str, success: bool = None):
        status_smiles = {True: '✅ ', False: "❌ ", None: ""}
        async with self.changes_lock:

            with open(self.report_db_name, encoding="utf-8") as f: report_db = json.load(f)

            if not report_db.get(encoded_pk): report_db[encoded_pk] = {'texts': [], 'success_rate': [0, 0]}

            report_db[encoded_pk]["texts"].append(status_smiles[success] + text)
            if success != None:
                report_db[encoded_pk]["success_rate"][1] += 1
                if success == True: report_db[encoded_pk]["success_rate"][0] += 1

            with open(self.report_db_name, 'w') as f: json.dump(report_db, f)


    async def get_account_reports(self, encoded_pk: str, get_rate: bool = False):
        async with self.changes_lock:
            with open(self.report_db_name, encoding="utf-8") as f: report_db = json.load(f)

            decoded_privatekey = self.decode_pk(pk=encoded_pk)
            account_index = f"[{self.window_name.accs_done}/{self.window_name.accs_amount}]"

            if report_db.get(encoded_pk):
                account_reports = report_db[encoded_pk]
                if get_rate: return f'{account_reports["success_rate"][0]}/{account_reports["success_rate"][1]}'
                del report_db[encoded_pk]

                with open(self.report_db_name, 'w', encoding="utf-8") as f: json.dump(report_db, f)

                logs_text = '\n'.join(account_reports['texts'])
                tg_text = f'{account_index} <b>{get_address(pk=decoded_privatekey)}</b>\n\n{logs_text}'
                if account_reports["success_rate"][1]:
                    tg_text += f'\n\nSuccess rate {account_reports["success_rate"][0]}/{account_reports["success_rate"][1]}'

                return tg_text

            else:
                return f'{account_index} <b>{get_address(pk=decoded_privatekey)}</b>\n\nNo actions'
