
SHUFFLE_WALLETS     = True                              # True | False - перемешивать ли кошельки
RETRY               = 3

ETH_MAX_GWEI        = 2
GWEI_MULTIPLIER     = 1.05                              # умножать текущий гвей при отправке транз на 5%
TO_WAIT_TX          = 1                                 # сколько минут ожидать транзакцию. если транза будет находится в пендинге после указанного времени то будет считатся зафейленной

RPCS                = {
    'ethereum'  : [
        "https://rpc.flashbots.net/fast",
        "https://eth.rpc.blxrbdn.com",
        "https://1rpc.io/eth",
        "https://eth.drpc.org",
        "https://ethereum-rpc.publicnode.com",
    ],
    "base"      : [
        "https://1rpc.io/base",
        "https://mainnet.base.org",
        "https://0xrpc.io/base",
        "https://base-mainnet.public.blastapi.io",
    ],
    "arbitrum"  : [
        "https://arb1.arbitrum.io/rpc",
        "https://arb-pokt.nodies.app",
        "https://arbitrum.drpc.org",
    ],
    "optimism"  : [
        "https://1rpc.io/op",
        "https://mainnet.optimism.io",
        "https://0xrpc.io/op"
    ],
    "linea"     : [
        "https://1rpc.io/linea",
        "https://linea.therpc.io",
        "https://rpc.linea.build"
    ],
}

# --- MAIN SETTINGS ---
MINT_NFT            = False                             # минтить Elsian NFT (8$), если еще не сминчено (дает +2500XP)
                                                        # минитит в рандомный момент между модулями, не сразу

USE_REF_CHANCE      = 80                                # использовать рефку при регистрации нового аккаунта с шансом 80%
                                                        # то есть каждый 5ый аккаунт (20%) будет регистрироваться без
                                                        # рефки, что предотвращает регистрацию всех аккаунтов паравозиком

# --- SWAP SETTINGS ---
SWAP_SETTINGS       = {
    "tokens"        : [
        "USDC",
        "wstETH",
        "WBTC",
        "USDe",
        "DAI",
        "ENA",
        "TRUMP",
        "CRV",
        "AERO",
        "PENDLE",
        "AAVE",
    ],
    "swap_times"    : [1, 2],                           # сколько раз выполнять свапы (1 свап = ETH → token → ETH)
    "swap_eth_usd"  : [4, 8],                           # сколько $ в эфире свапать в рандомный токен (например свап 10$ из ETH в WBTC)
    "back_swap"     : [100, 100],                       # сколько процентов от баланса токена свапать обратно в ETH
    "max_token_hold": 1,                                # сколько токенов может быть куплено на кошельке без продажи
                                                        # например если указать 1, то действия кошелька всегда будут:
                                                        # купил-продал-купил-продал (ETH → Token → ETH → Token)
                                                        # если указать 2, то кошелек может после покупки первого токена,
                                                        # сразу покупать второй токен, без продажи первого. но как...
                                                        # только на кошельке будет 2 токена - любой из токенов будет...
                                                        # продан обратно в ETH
}

# --- BRIDGE SETTINGS ---
BRIDGE_SETTINGS     = {
    "bridge_times"  : [0, 0],                           # сколько раз выполнять бриджи (1 бридж = Base → RandomChain → Base)
    "bridge_eth_usd": [2, 4],                           # сколько $ в ETH бриджить из Base в рандомную сеть и обратно
    "to_chains"     : [                                 # в какие сети можно бриджить из Base и обратно
        "arbitrum",
        "optimism",
        "linea",
    ],
    "max_chains_hold": 1,                               # сколько бриджей может быть сделано без обратного бриджа
                                                        # логика такая же, как в свапах в `max_token_hold`
}

SLEEP_AFTER_ACCOUNT = [50, 100]                         # задержка после каждого аккаунта

# --- GENERAL SETTINGS ---
THREADS             = 1                                 # количество потоков (одновременно работающих кошельков)


# --- PERSONAL SETTINGS ---

TG_BOT_TOKEN        = ''                                # токен от тг бота (`12345:Abcde`) для уведомлений. если не нужно - оставляй пустым
TG_USER_ID          = []                                # тг айди куда должны приходить уведомления.
                                                        # [21957123] - для отправления уведомления только себе
                                                        # [21957123, 103514123] - отправлять нескольким людями
