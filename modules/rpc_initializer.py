from web3.middleware import async_geth_poa_middleware
from eth_typing.evm import Address
from web3 import Web3, AsyncWeb3
from web3.auto import w3
from random import choice

from settings import RPCS


class RPCInitializer:
    connector_list: dict = {}

    def __init__(self, proxies: list | None):
        if not self.connector_list:
            self.initialize_rpcs(proxies)


    def initialize_rpcs(self, proxies: list | None):
        if self.connector_list: return

        if proxies:
            self.connector_list["default"] = {
                chain: [
                    AsyncWeb3(Web3.AsyncHTTPProvider(
                        rpc,
                        request_kwargs={"proxy": proxy},
                    ))
                    for proxy in proxies
                    for rpc in RPCS[chain]
                ]
                for chain in RPCS
            }

        else:
            for connector_type, rpc_list in [
                ["default", RPCS],
            ]:
                self.connector_list[connector_type] = {
                    chain: [
                        AsyncWeb3(Web3.AsyncHTTPProvider(rpc))
                        for rpc in rpc_list[chain]
                    ]
                    for chain in rpc_list
                }

        for connector_type in self.connector_list:
            for chain in self.connector_list[connector_type]:
                for web3 in self.connector_list[connector_type][chain]:
                    web3.middleware_onion.inject(async_geth_poa_middleware, layer=0)


    @classmethod
    def get_rpc(cls, chain_name: str):
        return choice(cls.connector_list["default"][chain_name])


    @classmethod
    def initialize_contract(
            cls,
            chain_name: str,
            address: str | Address,
            abi: str
    ):
        return cls.get_rpc(chain_name=chain_name).eth.contract(
            address=w3.to_checksum_address(address),
            abi=abi,
        )
