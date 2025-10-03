from eth_account.messages import encode_defunct, encode_typed_data, _hash_eip191_message
from typing import Union, Optional, Dict, Any
from loguru import logger
from web3.auto import w3
from time import time
import asyncio

from modules.rpc_initializer import RPCInitializer
from modules.retry import TransactionError
from modules.multicall import MultiCall
from modules.database import DataBase
import modules.config as config
import settings

from requests.exceptions import HTTPError
from web3.exceptions import ContractLogicError, BadFunctionCallOutput


class Wallet:

    def __init__(self, privatekey: str, encoded_pk: str, db: DataBase, proxy: str | None = None):
        if not privatekey or not isinstance(privatekey, str) or len(privatekey) != 66:
            raise ValueError("Invalid private key format")
        self.privatekey = privatekey
        self.encoded_pk = encoded_pk
        self.db = db

        self.account = w3.eth.account.from_key(privatekey)
        self.address = self.account.address

        self.proxy = self._parse_proxy(proxy) if proxy else None
        self._web3_cache = {}

        logger_opt = logger.opt(colors=True)
        if self.proxy:
            logger_opt.debug(f'[•] <white>{self.address}</white> | <white>{self.proxy}</white> | Started')
        else:
            logger_opt.debug(f'[•] <white>{self.address}</white> | <red>No proxy</red> | Started')

    def _parse_proxy(self, proxy: str) -> str | None:
        invalid_proxies = ['https://log:pass@ip:port', 'http://log:pass@ip:port', 'log:pass@ip:port', '', None]
        if proxy in invalid_proxies:
            return None
        return "http://" + proxy.removeprefix("https://").removeprefix("http://")

    def get_web3(self, chain_name: str) -> Any:
        if chain_name not in self._web3_cache:
            self._web3_cache[chain_name] = RPCInitializer.get_rpc(chain_name)
        return self._web3_cache[chain_name]

    async def wait_for_gwei(self, max_retries: int = 10) -> None:
        chain_data = {'chain_name': 'ethereum', 'max_gwei': settings.ETH_MAX_GWEI}
        first_check = True
        retry_count = 0

        while retry_count < max_retries:
            try:
                new_gwei = round((await self.get_web3(chain_data['chain_name']).eth.gas_price) / 10 ** 9, 2)
                if new_gwei < chain_data["max_gwei"]:
                    if not first_check:
                        logger.debug(f'[•] {self.address} | New {chain_data["chain_name"].title()} GWEI is {new_gwei}')
                    break
                await asyncio.sleep(5 ** min(retry_count, 3))  # Exponential backoff
                if first_check:
                    first_check = False
                    logger.debug(f'[•] {self.address} | Waiting for GWEI in {chain_data["chain_name"].title()} '
                               f'at least {chain_data["max_gwei"]}. Current is {new_gwei}')
                retry_count += 1
            except Exception as err:
                logger.warning(f'[•] {self.address} | {chain_data["chain_name"].title()} gwei waiting error: {err}')
                await asyncio.sleep(10)
        else:
            raise TimeoutError(f"Max retries ({max_retries}) reached waiting for GWEI on {chain_data['chain_name']}")

    async def get_gas(self, chain_name: str, increasing_gwei: float = 0) -> Dict[str, int]:
        web3 = self.get_web3(chain_name)
        tasks = [
            web3.eth.max_priority_fee,
            web3.eth.get_block('latest'),
            web3.eth.gas_price,
        ]
        max_priority, last_block, gas_price = await asyncio.gather(*tasks)

        base_fee = int(max(last_block['baseFeePerGas'], gas_price) * (settings.GWEI_MULTIPLIER + increasing_gwei))
        block_filled = last_block['gasUsed'] / last_block['gasLimit'] * 100
        if block_filled > 50:
            base_fee = int(base_fee * 1.127)

        max_fee = int(base_fee + int(max_priority))
        return {'maxPriorityFeePerGas': int(max_priority), 'maxFeePerGas': max_fee}

    async def send_tx(self, chain_name: str, tx: Any, tx_label: str, tx_raw: bool = False, value: int = 0,
                      increasing_gwei: float = 0) -> str:
        try:
            web3 = self.get_web3(chain_name)
            if not tx_raw:
                chain_id, nonce, gas_params = await asyncio.gather(
                    web3.eth.chain_id,
                    web3.eth.get_transaction_count(self.address),
                    self.get_gas(chain_name, increasing_gwei),
                )
                tx_completed = await tx.build_transaction({
                    'from': self.address,
                    'chainId': chain_id,
                    'nonce': nonce,
                    'value': value,
                    **gas_params,
                })
            else:
                tx_completed = {**tx, **await self.get_gas(chain_name, increasing_gwei)}
                if "gas" not in tx_completed:
                    tx_completed["gas"] = await web3.eth.estimate_gas(tx_completed)

            signed_tx = web3.eth.account.sign_transaction(tx_completed, self.privatekey)
            raw_tx_hash = await web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_hash = web3.to_hex(raw_tx_hash)
            return await self.wait_for_tx(chain_name, tx_hash, tx_label)

        except Exception as err:
            encoded_tx = getattr(tx_completed, '_encode_transaction_data', lambda: '')()
            raise TransactionError(f'tx failed error', error_code=str(err), encoded_tx=encoded_tx)

    async def wait_for_tx(self, chain_name: str, tx_hash: str, tx_label: str) -> str:
        web3 = self.get_web3(chain_name)
        tx_link = f'{config.CHAINS_DATA[chain_name]["explorer"]}{tx_hash}'
        logger.debug(f'[•] {self.address} | {tx_label} tx sent: {tx_link}')

        try:
            receipt = await web3.eth.wait_for_transaction_receipt(tx_hash, timeout=int(settings.TO_WAIT_TX * 60))
            if receipt.status == 1:
                logger.success(f'[+] {self.address} | {tx_label} tx confirmed')
                await self.db.append_report(encoded_pk=self.encoded_pk, text=tx_label, success=True)
                return tx_hash
            else:
                await self.db.append_report(
                    encoded_pk=self.encoded_pk,
                    text=f'{tx_label} | tx is failed | <a href="{tx_link}">link 👈</a>',
                    success=False
                )
                raise ValueError(f'tx failed: {tx_link}')
        except HTTPError as err:
            logger.error(f'[-] {self.address} | Couldn\'t get TX, probably need to change RPC ({web3.provider.endpoint_uri}): {err}')
            await asyncio.sleep(5)
            raise

    async def approve(self, chain_name: str, token_name: str, spender: str, amount: float = None, value: int = None,
                      force_approve: bool = False) -> Optional[str]:
        """Approve token spending for a spender.

        Args:
            chain_name (str): Name of the blockchain.
            token_name (str): Name of the token.
            spender (str): Spender address.
            amount (float, optional): Amount in human-readable format.
            value (int, optional): Amount in wei.
            force_approve (bool): Force approval even if already approved.

        Returns:
            Optional[str]: Transaction hash or False if no approval needed.
        """
        web3 = self.get_web3(chain_name)
        token_contract = web3.eth.contract(
            address=config.TOKEN_ADDRESSES[chain_name][token_name],
            abi=[
                {"inputs": [{"internalType": "address", "name": "owner", "type": "address"}, {"internalType": "address", "name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
                {"inputs": [{"internalType": "address", "name": "spender", "type": "address"}, {"internalType": "uint256", "name": "value", "type": "uint256"}], "name": "approve", "outputs": [{"internalType": "bool", "name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
                {"inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"}
            ]
        )
        decimals = await token_contract.functions.decimals().call()

        value = self._calculate_value(amount, value, decimals)
        min_allowance = 0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff if value == 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff else value
        amount_str = "infinity" if value == 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff else str(amount)

        current_allowance = await token_contract.functions.allowance(self.address, spender).call()
        if force_approve or current_allowance < min_allowance:
            module_str = f"approve {amount_str} {token_name}"
            tx = token_contract.functions.approve(spender, value)
            return await self.send_tx(chain_name=chain_name, tx=tx, tx_label=module_str)

        return False

    def _calculate_value(self, amount: Optional[float], value: Optional[int], decimals: int) -> int:
        """Calculate value in wei based on amount or value."""
        if amount is not None:
            return int(amount * 10 ** decimals)
        if value is not None:
            return value
        raise ValueError("Either amount or value must be provided")