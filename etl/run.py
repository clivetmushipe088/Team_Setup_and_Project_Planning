# Runs the ETL: parse -> clean -> categorize -> load -> export JSON
import argparse


def main():
    parser = argparse.ArgumentParser(description="MoMo SMS ETL")
    parser.add_argument("--xml", default="data/raw/momo.xml", help="path to the XML file")
    parser.add_argument("--export-only", action="store_true", help="only rebuild dashboard.json")
    args = parser.parse_args()

    # TODO: call the steps in order
    print("ETL not done yet. XML file:", args.xml)


if __name__ == "__main__":
    main()
