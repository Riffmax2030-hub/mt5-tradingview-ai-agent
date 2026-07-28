import argparse

import alphaedge


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit one freshly confirmed AlphaEdge trade.")
    parser.add_argument("symbol", choices=alphaedge.SYMBOLS)
    arguments = parser.parse_args()
    alphaedge.run_alphaedge(execute_orders=True, approved_symbols={arguments.symbol})


if __name__ == "__main__":
    main()
