#!/usr/bin/env python3
"""Read-only Linux pool measurements; never stops nodes or changes wallet/config files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request


def read_stat(path):
    text = path.read_text()
    name = text[text.index('(') + 1:text.rindex(')')]
    fields = text[text.rindex(')') + 2:].split()
    return {'name': name, 'ticks': int(fields[11]) + int(fields[12]), 'start': int(fields[19])}


def snapshot(pid):
    base = Path('/proc') / str(pid)
    process = read_stat(base / 'stat')
    threads = {}
    for path in (base / 'task').glob('*/stat'):
        try:
            threads[path.parent.name] = read_stat(path)
        except FileNotFoundError:
            pass  # A worker exited during the sample.
    return process, threads


def summarize(samples):
    successful = [s['seconds'] for s in samples if s['ok']]
    return {'samples': samples,
            'successes': len(successful),
            'median_seconds': statistics.median(successful) if successful else None,
            'max_seconds': max(successful) if successful else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--datadir', type=Path, default=Path('/home/crypto-data/wallets/.FreakChain'))
    parser.add_argument('--binary', type=Path, default=Path('/usr/bin/FreakChaind'))
    parser.add_argument('--pid', type=int, help='override the PID from FreakChaind.pid')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--timeout', type=int, default=10, help='per RPC/HTTP request timeout in seconds')
    parser.add_argument('--label', default='sample')
    parser.add_argument('--url', default='https://luckydogpool.com/site/coin?id=216')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600 or not 1 <= args.timeout <= 60:
        parser.error('seconds must be 1..3600 and timeout 1..60')
    pid = args.pid or int((args.datadir / 'FreakChaind.pid').read_text().strip())
    before, threads_before = snapshot(pid)
    try:
        executable = os.readlink('/proc/{}/exe'.format(pid))
    except PermissionError:
        executable = 'unavailable (daemon process protection)'
    if not before['name'].startswith('FreakChain'):
        parser.error('PID does not point to a FreakChain process')
    log_path = args.datadir / 'debug.log'
    with log_path.open('rb') as log:
        log.seek(0, 2)
        log_identity = os.fstat(log.fileno()).st_ino
        incomplete = b''
        orphans = evictions = 0
        log_changed = False
        samples = {'getpeerinfo': [], 'getinfo': [], 'yiimp': []}
        started = time.monotonic()
        deadline = started + args.seconds
        stopping = threading.Event()

        def rpc_worker():
            while time.monotonic() < deadline and not stopping.is_set():
                for method in ('getpeerinfo', 'getinfo'):
                    if time.monotonic() >= deadline or stopping.is_set():
                        return
                    tick = time.monotonic()
                    sample = {'ok': False}
                    try:
                        result = subprocess.run([str(args.binary), '-datadir=' + str(args.datadir), method],
                                                capture_output=True, text=True, timeout=args.timeout)
                        sample['exit_code'] = result.returncode
                        if result.returncode == 0:
                            data = json.loads(result.stdout)
                            sample['ok'] = True
                            if method == 'getinfo':
                                sample['state'] = {k: data.get(k) for k in ('version', 'blocks', 'connections', 'errors')}
                            else:
                                sample['peer_count'] = len(data)
                        else:
                            sample['error'] = 'RPC exited unsuccessfully (output omitted)'
                    except subprocess.TimeoutExpired:
                        sample['error'] = 'timeout'
                    except (OSError, ValueError, TypeError) as error:
                        sample['error'] = type(error).__name__
                    sample['seconds'] = round(time.monotonic() - tick, 6)
                    samples[method].append(sample)
                stopping.wait(min(10, max(0, deadline - time.monotonic())))

        def http_worker():
            while time.monotonic() < deadline and not stopping.is_set():
                tick = time.monotonic()
                sample = {'ok': False}
                try:
                    with urllib.request.urlopen(args.url, timeout=args.timeout) as response:
                        sample['status'] = response.status
                        # Read the page, not just its headers, with a finite size limit.
                        response.read(2 * 1024 * 1024)
                        sample['ok'] = response.status == 200
                except urllib.error.HTTPError as error:
                    sample['status'] = error.code
                    error.close()
                except (OSError, ValueError, http.client.HTTPException) as error:
                    sample['error'] = type(error).__name__
                sample['seconds'] = round(time.monotonic() - tick, 6)
                samples['yiimp'].append(sample)
                stopping.wait(min(15, max(0, deadline - time.monotonic())))

        def read_new_log():
            nonlocal incomplete, orphans, evictions, log_changed
            try:
                if log_path.stat().st_ino != log_identity or os.fstat(log.fileno()).st_size < log.tell():
                    log_changed = True
                    return
            except FileNotFoundError:
                log_changed = True
                return
            end = os.fstat(log.fileno()).st_size
            while log.tell() < end:
                chunk = log.read(min(512 * 1024, end - log.tell()))
                if not chunk:
                    break
                lines = (incomplete + chunk).split(b'\n')
                incomplete = lines.pop()
                orphans += sum(b'ProcessBlock: ORPHAN BLOCK' in line for line in lines)
                evictions += sum(b'Orphan block cache: evicted' in line for line in lines)

        with ThreadPoolExecutor(max_workers=2) as workers:
            jobs = [workers.submit(rpc_worker), workers.submit(http_worker)]
            try:
                while time.monotonic() < deadline:
                    read_new_log()
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
            finally:
                stopping.set()
            for job in jobs:
                job.result()
        read_new_log()
        after, threads_after = snapshot(pid)
        elapsed = time.monotonic() - started
        if before['start'] != after['start']:
            raise RuntimeError('Daemon restarted during measurement; discard this sample')
        scale = 100 / os.sysconf('SC_CLK_TCK') / elapsed
        threads = []
        for tid, end in threads_after.items():
            begin = threads_before.get(tid)
            if begin and begin['start'] == end['start']:
                threads.append({'tid': int(tid), 'name': end['name'],
                                'cpu_percent': round((end['ticks'] - begin['ticks']) * scale, 3)})
        report = {'label': args.label, 'pid': pid, 'executable': executable,
                  'elapsed_seconds': round(elapsed, 3),
                  'cpu_percent': round((after['ticks'] - before['ticks']) * scale, 3),
                  'threads': sorted(threads, key=lambda item: item['cpu_percent'], reverse=True),
                  'log_rotated_or_truncated': log_changed,
                  'new_orphan_lines': orphans, 'new_eviction_lines': evictions,
                  'orphans_per_second': None if log_changed else round(orphans / elapsed, 3),
                  'rpc_and_web': {name: summarize(values) for name, values in samples.items()}}
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
