# -*- encoding: utf-8 -*-
# Arbitrage API

import os
import time
import logging
from constants import ALCHEMY_API_KEY, ALCHEMY_URL, MIN_HEALTHY_POOL, SLEEP_TIME, ARBITRAGE_THRESHOLD, RESULT_DIR

from web3 import Web3
from pathlib import Path
from dotenv import load_dotenv

from tools import hex_to_int, wei_to_eth, send_request, \
                        craft_url, format_price, \
                        save_results, format_path, create_dir, \
                        format_filename, get_time_now, format_perc


class ArbitrageInterface(object):

    def __init__(self):

        # Smart constracts for supoorted tokens
        self.tokens_address = {
            'WETH': '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',
            'DAI': '0x6b175474e89094c44da98b954eedeac495271d0f'
        }
        # Address for supported exchanges
        self.exchanges_address = {
            'UNISWAP': '0xa478c2975ab1ea89e8196811f51a7b7ade33eb11',
            'SUSHISWAP': '0xc3d03e4f041fd4cd388c549ee2a29a9e5075882f',
            'SHEBASWAP': '0x8faf958e36c6970497386118030e6297fff8d275',
            'SAKESWAP': '0x2ad95483ac838e2884563ad278e933fba96bc242',
            'CROSWAP': '0x60a26d69263ef43e9a68964ba141263f19d71d51'
        }

        # In-memory data for this API
        self.current_balances = {}
        self.current_balances_web3 = {}
        self.current_price_data = {}
        self.arbitrage_result = []

        self.load_config()

    @classmethod
    def load_config(cls) -> None:
        """Load and set enviroment variables."""

        load_dotenv(Path('.') / '.env')

        if not (bool(ARBITRAGE_THRESHOLD) and bool(RESULT_DIR)
                and bool(MIN_HEALTHY_POOL) and bool(SLEEP_TIME)):
            raise Exception('Please add info to constants file')

        cls.result_dir = RESULT_DIR
        cls.min_healthy_pool = MIN_HEALTHY_POOL
        cls.arbitrage_threshold = float(ARBITRAGE_THRESHOLD)
        cls.sleep_time = float(SLEEP_TIME)

        if (bool(ALCHEMY_URL) and bool(ALCHEMY_API_KEY)):
            cls.provider_url = craft_url(ALCHEMY_URL, ALCHEMY_API_KEY)

    def fetch_token_balance(self, token, exchange) -> str:
        """
            Send a crafted request to retrieve a given token balance in a
            a given exchanges.
        """

        token_address = self.tokens_address[token]
        exchange_address = self.exchanges_address[exchange][2:]

        data = '{"jsonrpc": "2.0", "method": "eth_call", "params":' + \
            '[{"data": "' + \
            '0x70a08231000000000000000000000000' + \
            exchange_address + \
            '", "to": "' + \
            token_address + \
            '"}, "latest"], "id": 1}'

        response = send_request(self.provider_url, data)
        try:
            return wei_to_eth(hex_to_int(response['result']))
        except TypeError:
            logging.error(f'\n !!! Retrieved data is ill-formatted: {response}')

    def fetch_all_balances(self) -> None:
        """Loop over supported exchanges and tokens to retrieve balance."""

        for exchange in self.exchanges_address.keys():
            self.current_balances[exchange] = {}

            for token in self.tokens_address.keys():
                self.current_balances[exchange][token] = \
                    self.fetch_token_balance(token, exchange)

    def calculate_price_data(self, t1_balance, t2_balance, quantity) -> float:
        """
            Calculate price and price effect for a given token and its pair
            using the AMM constant product equation.
        """

        CONSTANT_PRODUCT = t1_balance * t2_balance
        CURRENT_PRICE = t2_balance / t1_balance

        ###########################
        #  Calculate BUY data
        ###########################

        # 1) How much WETH needs to remain in balance to keep the constant
        token1_balance_buy = CONSTANT_PRODUCT / (t2_balance + quantity)

        # 2) How much WETH goes out to keep the constant
        t1_amount_out_buy = t1_balance - token1_balance_buy

        # 3) Buy price to reflect the balances change
        buy_price = quantity / t1_amount_out_buy

        # 4) Difference of buy price to current price
        buy_impact = 1 - (CURRENT_PRICE / buy_price)

        ###########################
        #  Calculate SELL data
        ###########################

        # 1) How much DAI to keep the balances constant
        token2_balance_buy = CONSTANT_PRODUCT / (t1_balance + quantity)

        # 2) How much DAI goes out that constant
        t2_amount_out_buy = t2_balance + token2_balance_buy

        # 3) How the DAI balance reflects with the income WETH
        token1_balance_sell = CONSTANT_PRODUCT / (t2_balance - quantity)

        # 4) The proportion of WETH in the new balance:
        t1_amount_in_sell = t1_balance + token1_balance_sell

        # 5) Sell price to reflect the balances change
        sell_price = t2_amount_out_buy / t1_amount_in_sell

        # 6) Difference of sell price to current price
        sell_impact = 1 - (CURRENT_PRICE / sell_price)

        return [format_price(CURRENT_PRICE), format_price(buy_price),
                format_price(sell_price), format_perc(buy_impact),
                format_perc(sell_impact), CONSTANT_PRODUCT]

    def evaluate_pair_prices(self, token1, token2, quantity) -> None:
        """Loop over a token pair to get prices on supported exchanges."""

        self.fetch_all_balances()

        for exchange in self.exchanges_address.keys():

            token1_balance = self.current_balances[exchange][token1]
            token2_balance = self.current_balances[exchange][token2]

            price_data = self.calculate_price_data(token1_balance,
                                                   token2_balance,
                                                   float(quantity))

            self.current_price_data[exchange] = {
                    'current_price': price_data[0],
                    'balance_constant': price_data[5],
                    'token1': token1,
                    'token2': token2,
                    'balance_t1': self.current_balances[exchange][token1],
                    'balance_t2': self.current_balances[exchange][token2]
            }

            if float(price_data[5]) <= float(self.min_healthy_pool):
                self.current_price_data[exchange].update({
                    'info': "Pool is unbalanced for at least one token.",
                })

            else:
                self.current_price_data[exchange].update({
                    'buy_price': price_data[1],
                    'sell_price': price_data[2],
                    'buy_impact': price_data[3],
                    'sell_impact': price_data[4],
                    'info': get_time_now(),
                })

    def calculate_arbitrage_brute_force(self) -> None:
        """
            Brute force algorithm to calculate arbitrage with the
            current prices for a pair of tokens in the supported exchanges.
        """

        price_info = []
        data = [(exchange, data) for (exchange, data) \
                            in self.current_price_data.items()]

        for exchange, data in self.current_price_data.items():

            if 'buy_price' not in data.keys():
                continue

            price_info.append([exchange, float(data['buy_price']), \
                                            float(data['sell_price'])])

        for i, buy_data in enumerate(price_info):
            for sell_data in price_info[:i] + price_info[i+1:]:

                arbitrage = sell_data[2] - buy_data[1]

                if arbitrage > 0.0:
                    self.arbitrage_result.append({
                        'buy_exchange': buy_data[0],
                        'sell_exchange': sell_data[0],
                        'arbitrage': format_price(arbitrage),
                        'buy_price': buy_data[1],
                        'sell_price': sell_data[2]
                    })

    def find_arbitrages(self, quantity, token1=None, token2=None) -> None:
        """Get AMM arbitrage data for a given pair of tokens."""

        token1 = token1 or 'WETH'
        token2 = token2 or 'DAI'

        self.evaluate_pair_prices(token1, token2, quantity)
        self.calculate_arbitrage_brute_force()

    def run_arbitrage_loop(self, runtime, quantity) -> None:
        """Run arbitrage algorithm for a given runtime and quantity."""

        end = time.time() + float(runtime) * 60

        while time.time() < end:
            self.find_arbitrages(quantity)
            time.sleep(self.sleep_time)

        create_dir(self.result_dir)
        destination = format_path(self.result_dir, format_filename())
        save_results(destination, self.arbitrage_result)
