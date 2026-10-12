"""Thin wrapper: the importable implementation is secureyourcode.demo_eval (`secureyourcode demo-evaluate`)."""

import sys

from secureyourcode.cli import main

if __name__ == "__main__":
    sys.exit(main(["demo-evaluate", *sys.argv[1:]]))
