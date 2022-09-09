# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.


import sys
import argparse

from arbitrage import ArbitrageInterface


def _run_menu_options() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(description='arbitrage CLI')

    parser.add_argument('-l', dest='loop', nargs=2,
                        help="Run arbitrage in a loop for a given time and quantity. \
                        Example: -l MINUTES QUANTITY")

    return parser


def run_menu() -> None:

    parser = _run_menu_options()
    args = parser.parse_args()
    arbitrage_interface = ArbitrageInterface()

    ########################################
    # Run arbitrage algorithm in a loop
    ########################################
    if args.loop:
        runtime = args.loop[0]
        quantity = args.loop[1]

        print(f'\noperating task... Running loop of {runtime} minute(s) for qty: {quantity}')
        arbitrage_interface.run_arbitrage_loop(runtime, quantity)
        print(f'Done. Results saved at {arbitrage_interface.result_dir}.\n')

    ########################################
    # Print help
    ########################################
    else:
        parser.print_help(sys.stderr)


if __name__ == "__main__":
    run_menu()
