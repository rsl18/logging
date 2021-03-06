'''
Summarizes a set of results.
'''

from __future__ import print_function

import argparse
import copy
import glob
import json
import os
import re
import sys

_ALLOWED_BENCHMARKS_V06 = [
    'resnet',
    'ssd',
    'maskrcnn',
    'gnmt',
    'transformer',
    'ncf',
    'minigo',
]

_ALLOWED_BENCHMARKS_V07 = [
    'bert',
    'dlrm',
    'gnmt',
    'maskrcnn',
    'minigo',
    'resnet',
    'ssd',
    'transformer',
]

_RUN_START_REGEX = r':::MLL (.*) run_start: {.*}'
_RUN_STOP_REGEX = r':::MLL (.*) run_stop: {.*}'

def _get_sub_folders(folder):
    sub_folders = [os.path.join(folder, sub_folder)
                   for sub_folder in os.listdir(folder)]
    return [sub_folder
            for sub_folder in sub_folders
            if os.path.isdir(sub_folder)]


def _read_json_file(json_file):
    with open(json_file, 'r') as f:
        return json.load(f)


def _pretty_system_name(system_desc):
    system_name = system_desc['system_name']
    if system_name == 'tpu-v3':
        chips = int(system_desc['accelerators_per_node']) * 2
        return 'TPUv3.{}'.format(chips)
    return system_name


def _linkable_system_name(system_desc):
    system_name = system_desc['system_name']
    if system_name == 'tpu-v3':
        chips = int(system_desc['accelerators_per_node']) * 2
        return 'tpu-v3-{}'.format(chips)
    return system_name


def _pretty_accelerator_model_name(system_desc):
    accelerator_model_name = system_desc['accelerator_model_name']
    if accelerator_model_name == 'tpu-v3':
        return 'TPUv3'
    return accelerator_model_name


def _pretty_framework(system_desc):
    framework = system_desc['framework']
    if 'TensorFlow' in framework:
        commit_hash = re.search(r' commit hash = .*', framework)
        if commit_hash:
            return framework.replace(commit_hash.group(0), '')
    return framework


def _benchmark_alias(benchmark):
    if benchmark == 'mask':
        return 'maskrcnn'
    return benchmark


def _ruleset_url_prefix(ruleset):
    short_ruleset = ruleset.replace('.0', '')
    return 'https://github.com/mlperf/training_results_v{}'.format(short_ruleset)


def _details_url(system_desc, ruleset):
    return '{ruleset_prefix}/blob/master/{submitter}/systems/{system}.json'.format(
        ruleset_prefix=_ruleset_url_prefix(ruleset),
        submitter=system_desc['submitter'],
        system=_linkable_system_name(system_desc))


def _code_url(system_desc, ruleset):
    return '{ruleset_prefix}/blob/master/{submitter}/benchmarks'.format(
        ruleset_prefix=_ruleset_url_prefix(ruleset),
        submitter=system_desc['submitter'])


def _row_key(system_desc):
    system_name = system_desc['system_name']
    if system_name == 'tpu-v3':
        chips = int(system_desc['accelerators_per_node']) * 2
        return 'tpu-v3-{:04d}'.format(chips)
    return system_name


def _read_mlperf_score(result_file):
    with open(result_file, 'r') as f:
        result = f.read()

    run_start = re.search(_RUN_START_REGEX, result)
    run_start = json.loads(run_start.group(1))
    run_stop = re.search(_RUN_STOP_REGEX, result)
    run_stop = json.loads(run_stop.group(1))

    seconds = float(run_stop) - float(run_start)
    minutes = seconds / 60
    return minutes


def _compute_olympic_average(scores):
    copied_scores = copy.deepcopy(scores)
    copied_scores.sort()
    copied_scores = copied_scores[1:-1]
    return sum(copied_scores) / len(copied_scores)


def summarize_results(folder, ruleset):
    """Summarizes a set of results.

    Args:
        folder: The folder for a submission package.
        ruleset: The ruleset such as 0.6.0 or 0.7.0.
    """
    systems_folder = os.path.join(folder, 'systems')
    results_folder = os.path.join(folder, 'results')

    rows = {}
    for system_folder in _get_sub_folders(results_folder):
        folder_parts = system_folder.split('/')
        system = folder_parts[-1]

        # Load corresponding system description.
        system_file = os.path.join(
            systems_folder, '{}.json'.format(system))
        if not os.path.exists(system_file):
            print('Missing {}'.format(system_file))
            continue
        desc = _read_json_file(system_file)

        # Construct prefix portion of the row.
        row = ''
        row += '"{}",'.format(desc['submitter'])
        row += '"{}",'.format(_pretty_system_name(desc))
        row += '"{}",'.format(desc['host_processor_model_name'])
        row += '{},'.format(desc['host_processor_core_count'])
        row += '"{}",'.format(_pretty_accelerator_model_name(desc))
        row += '{},'.format(desc['accelerators_per_node'])
        row += '"{}",'.format(_pretty_framework(desc))

        # Collect scores for benchmarks.
        benchmark_scores = {}
        for benchmark_folder in _get_sub_folders(system_folder):
            folder_parts = benchmark_folder.split('/')
            benchmark = _benchmark_alias(folder_parts[-1])

            # Read scores from result files.
            pattern = '{folder}/result_*.txt'.format(folder=benchmark_folder)
            result_files = glob.glob(pattern, recursive=True)
            scores = []
            for result_file in result_files:
                score = _read_mlperf_score(result_file)
                scores.append(score)

            benchmark_scores[benchmark] = _compute_olympic_average(scores)

        # Construct scores portion of the row.
        if ruleset == '0.6.0':
            allowed_benchmarks = _ALLOWED_BENCHMARKS_V06
        elif ruleset == '0.7.0':
            allowed_benchmarks = _ALLOWED_BENCHMARKS_V07
        for benchmark in allowed_benchmarks:
            if benchmark in benchmark_scores:
                row += '{:.2f},'.format(benchmark_scores[benchmark])
            else:
                row += ','

        # Construct postfix portion of the row.
        row += '{},'.format(_details_url(desc, ruleset))
        row += '{},'.format(_code_url(desc, ruleset))

        rows[_row_key(desc)] = row

    # Print rows in order of the sorted keys.
    for key in sorted(rows):
        print(rows[key])


def get_parser():
    parser = argparse.ArgumentParser(
        prog='mlperf_logging.result_summarizer',
        description='Summarize a set of result files.',
    )

    parser.add_argument('folder', type=str,
                    help='the folder for a submission package')
    parser.add_argument('usage', type=str,
                    help='the usage such as training, inference_edge, inference_server')
    parser.add_argument('ruleset', type=str,
                    help='the ruleset such as 0.6.0 or 0.7.0')
    parser.add_argument('--werror', action='store_true',
                    help='Treat warnings as errors')
    parser.add_argument('--quiet', action='store_true',
                    help='Suppress warnings. Does nothing if --werror is set')

    return parser


def main():
    parser = get_parser()
    args = parser.parse_args()

    if args.usage != 'training':
        print('Usage {} is not supported.'.format(args.usage))
        sys.exit(1)
    if args.ruleset not in ['0.6.0', '0.7.0']:
        print('Ruleset {} is not supported.'.format(args.ruleset))
        sys.exit(1)

    multiple_folders_regex = r'(.*)\{(.*)\}'
    multiple_folders = re.search(multiple_folders_regex, args.folder)
    if multiple_folders:
        # Parse results for multiple organizations.
        path_prefix = multiple_folders.group(1)
        orgs = multiple_folders.group(2).split(',')
        for org in orgs:
            org_folder = path_prefix + org
            summarize_results(org_folder, args.ruleset)
    else:
        # Parse results for single organization.
        summarize_results(args.folder, args.ruleset)


if __name__ == '__main__':
    main()
