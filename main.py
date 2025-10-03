from random import randint
from loguru import logger
from time import sleep
import asyncio
import os

from eth_account.messages import encode_typed_data
from modules import *
from modules.retry import DataBaseError
from settings import THREADS, SLEEP_AFTER_ACCOUNT


async def run_modules(
        mode: int,
        module_data: dict,
):
    try:
        browser = Browser(
            encoded_privatekey=module_data["encoded_privatekey"],
            address=module_data["address"],
            db=db,
            proxy=module_data["proxy"],
        )
        wallet = Wallet(
            privatekey=module_data["privatekey"],
            encoded_pk=module_data["encoded_privatekey"],
            db=db,
            proxy=module_data["proxy"],
        )
        module_data["module_info"]["status"] = await Elsa(
            wallet=wallet,
            browser=browser
        ).run(
            module_info=module_data["module_info"]
        )

    except DataBaseError:
        module_data = None
        raise

    except Exception as err:
        logger.error(f'[-] {wallet.address} | Global error: {err}')
        await db.append_report(encoded_pk=module_data["encoded_privatekey"], text=str(err), success=False)

    finally:
        if type(module_data) == dict:
            await db.remove_module(module_data)

            if await db.get_wallet_modules_left(encoded_pk=module_data["encoded_privatekey"]) == 0:
                reports = await db.get_account_reports(encoded_pk=module_data["encoded_privatekey"])
                await TgReport().send_log(logs=reports)

            await asyncio.sleep(randint(*SLEEP_AFTER_ACCOUNT))


async def thread_runner(mode: int, active_wallets: list, lock: asyncio.Lock):
    while True:
        async with lock:
            module_data = db.get_random_module(active_wallets=active_wallets)

            if module_data == 'No more accounts left':
                return
            else:
                active_wallets.append(module_data["address"])

        await run_modules(
            mode=mode,
            module_data=module_data,
        )
        async with lock:
            active_wallets.remove(module_data["address"])


async def runner(mode: int):
    RPCInitializer(proxies=db.proxies)
    lock = asyncio.Lock()
    active_wallets = []

    await asyncio.gather(*[
        thread_runner(mode=mode, active_wallets=active_wallets, lock=lock)
        for _ in range(THREADS)
    ])

    logger.success(f'All accounts done.')
    return 'Ended'


if __name__ == '__main__':
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        db = DataBase()

        while True:
            mode = choose_mode()

            match mode.type:
                case "database":
                    db.create_modules(mode=mode.soft_id)

                case "module":
                    if asyncio.run(runner(mode=mode.soft_id)) == "Ended": break
                    print('')


        sleep(0.1)
        input('\n > Exit\n')

    except DataBaseError as e:
        logger.error(f'[-] Database | {e}')

    except KeyboardInterrupt:
        pass

    finally:
        logger.info('[•] Soft | Closed')



