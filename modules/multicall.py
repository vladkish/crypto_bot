from eth_typing.evm import Address
from web3.auto import w3

from modules.rpc_initializer import RPCInitializer


class MultiCall:
    multicall_address: Address = "0xcA11bde05977b3631167028862bE2a173976CA11"
    multicall_abi: str = '[{"inputs":[{"components":[{"internalType":"address","name":"target","type":"address"},{"internalType":"bool","name":"allowFailure","type":"bool"},{"internalType":"bytes","name":"callData","type":"bytes"}],"internalType":"structMulticall3.Call3[]","name":"calls","type":"tuple[]"}],"name":"aggregate3","outputs":[{"components":[{"internalType":"bool","name":"success","type":"bool"},{"internalType":"bytes","name":"returnData","type":"bytes"}],"internalType":"structMulticall3.Result[]","name":"returnData","type":"tuple[]"}],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"address","name":"addr","type":"address"}],"name":"getEthBalance","outputs":[{"internalType":"uint256","name":"balance","type":"uint256"}],"stateMutability":"view","type":"function"}]'

    @classmethod
    async def call(cls, chain_name: str, call_data: dict, **kwargs):
        contract = RPCInitializer.initialize_contract(
            chain_name=chain_name,
            address=cls.multicall_address,
            abi=cls.multicall_abi
        )

        call_response = await contract.functions.aggregate3([
            [
                call_data[k]["contract"].address,
                True,
                call_data[k]["contract"].functions[call_data[k]["func"]](*call_data[k]["args"])._encode_transaction_data()
            ]
            for k in call_data
        ]).call()

        call_result = {}
        for token_name, resp in zip(call_data, call_response):
            if resp[0]:
                readable_response, abi_types = cls.decode_resp(call_data[token_name], resp[1])
                if kwargs.get("decimals") and "int" in str(abi_types[0]):
                    readable_response /= 10 ** kwargs["decimals"]
            else:
                readable_response = 0
            call_result[token_name] = readable_response

        return call_result


    @classmethod
    def decode_resp(cls, token_data: dict, resp: bytes):
        for _func in token_data["contract"].abi:
            if _func["name"] == token_data["func"]:
                abi_types = []
                for func in _func["outputs"]:
                    if func["type"] == "tuple" and func.get("components"):
                        abi_types += [comp["type"] for comp in func["components"]]
                    else:
                        abi_types.append(func["type"])
                break

        if len(abi_types) == 1:
            readable_response = w3.codec.decode(abi_types, resp)[0]
        else:
            readable_response = w3.codec.decode(abi_types, resp)

        return readable_response, abi_types
