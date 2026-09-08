"""Split a scenario package before starting the runtime process."""

import argparse

from .loader import load_scenario

parser = argparse.ArgumentParser()
parser.add_argument("package")
parser.add_argument("runtime_directory")
parser.add_argument("truth_directory")
args = parser.parse_args()

runtime_path, truth_path = load_scenario(
    args.package, args.runtime_directory, args.truth_directory
)
print(runtime_path)
print(truth_path)
