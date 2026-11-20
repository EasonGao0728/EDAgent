"""Reconcile final DRC markers separately from pre-filter runtime candidates.

The producer profile is pinned to inspected machine code, not to a product name.
Unknown producers keep the old conservative counter-discrepancy gate.
"""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re

VERSION = 'drc-count-semantics-v2'
AUDITED_BINARY = 'd9ae28962bf622f1139e2b438c6f69deb646d93a48ece783da80a082d607694a'


def marker_stream(path):
    """Stream canonical markers, including validation of commas and file ending."""
    dec = json.JSONDecoder()
    buf = ''
    with Path(path).open(encoding='utf-8') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                raise ValueError('VIOLATIONS_ARRAY_MISSING')
            buf += chunk
            m = re.search(r'"violations"\s*:\s*\[', buf)
            if m:
                header = json.loads(buf[:m.start()].rstrip().rstrip(',') + '}')
                buf = buf[m.end():]
                break
            if len(buf) > 1024 * 1024:
                raise ValueError('DRC_HEADER_TOO_LARGE')
        yield 'header', header
        first = True
        while True:
            buf = buf.lstrip()
            while not buf:
                buf = f.read(65536).lstrip()
                if not buf:
                    raise ValueError('TRUNCATED_DRC_ARRAY')
            if buf.startswith(']'):
                # Native canonical v1 puts the array last. Fail closed on extensions.
                tail = buf[1:]
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    tail += chunk
                    if len(tail) > 65536:
                        raise ValueError('UNSUPPORTED_DRC_TRAILER')
                if tail.strip() != '}':
                    raise ValueError('TRUNCATED_OR_UNSUPPORTED_DRC_TRAILER')
                return
            if not first:
                if not buf.startswith(','):
                    raise ValueError('DRC_ARRAY_COMMA_MISSING')
                buf = buf[1:].lstrip()
            while True:
                buf = buf.lstrip()
                try:
                    obj, end = dec.raw_decode(buf)
                    break
                except ValueError:
                    chunk = f.read(65536)
                    if not chunk:
                        raise ValueError('TRUNCATED_OR_INVALID_DRC_ARRAY') from None
                    buf += chunk
                    if len(buf) > 2 * 1024 * 1024:
                        raise ValueError('DRC_RECORD_TOO_LARGE')
            if not isinstance(obj, dict):
                raise ValueError('INVALID_DRC_MARKER')
            yield 'marker', obj
            first = False
            buf = buf[end:]


def file_ref(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def reconcile(summary, report_dir, producer_sha256):
    """Read only; never alter native evidence or grant an execution receipt."""
    root = Path(report_dir)
    errors = []
    refs = []
    count = None
    header = {}
    by_rule = Counter()
    by_layer = Counter()
    log_total = None
    runtime = summary.get('runtime', {})
    rows = runtime.get('per_rule', {})
    raw = {k: v.get('violation_count') for k, v in rows.items() if isinstance(v, dict)}
    if len(raw) != len(rows) or any(type(n) is not int or n < 0 for n in raw.values()):
        errors.append('invalid_runtime_counts')
    known = producer_sha256 == AUDITED_BINARY
    try:
        for name in ('drc_summary.json', 'violations.json', 'drc.rpt'):
            refs.append(file_ref(root / name))
        if json.loads((root / 'drc_summary.json').read_text(encoding='utf-8')) != summary:
            errors.append('summary_file_mismatch')
        count = 0
        for kind, obj in marker_stream(root / 'violations.json'):
            if kind == 'header':
                header = obj
            else:
                count += 1
                by_rule[str(obj.get('type', 'unknown'))] += 1
                by_layer[str(obj.get('layer', 'unknown'))] += 1
        if header.get('schema_version') != 'ieda.drc.violations.v1' or header.get('source') != 'idrc_in_design' or header.get('stage') != 'DRC':
            errors.append('canonical_schema_or_source_mismatch')
        counts = [summary.get('violation_count'), header.get('count'), header.get('summary', {}).get('total'), count]
        if any(type(n) is not int or n < 0 for n in counts) or len(set(counts)) != 1:
            errors.append('final_marker_count_mismatch')
        if header.get('summary', {}).get('by_type') != dict(by_rule) or header.get('summary', {}).get('by_layer') != dict(by_layer):
            errors.append('final_marker_histogram_mismatch')
        if header.get('status') != summary.get('status'):
            errors.append('canonical_status_mismatch')
        for key in ('checked', 'skipped', 'unsupported'):
            if header.get('coverage', {}).get(key) != summary.get(key):
                errors.append('canonical_coverage_mismatch:' + key)
        totals = []
        # Some native interfaces write a structured drc.rpt; the engine table
        # remains in logs/drc.log. Validate both when both contain that table.
        for log_path in (root / 'drc.rpt', root.parent.parent / 'logs/drc.log'):
            if log_path.is_file():
                refs.append(file_ref(log_path))
                text = log_path.read_text(encoding='utf-8', errors='replace')
                found = re.findall(r'\|\s*Total\s*\|\s*(\d+)\s*\|', text)
                if len(found) > 1:
                    errors.append('ambiguous_native_log_totals')
                totals.extend(int(n) for n in found)
        if not totals or any(n != count for n in totals):
            errors.append('native_log_final_count_mismatch_or_missing')
        else:
            log_total = totals[0]
        # The pinned exporter writes these copies. A stale copied summary is not evidence.
        for name in ('drc_summary.json', 'violations.json'):
            a = file_ref(root / name)
            duplicate = root / 'drc.rpt.artifacts' / name
            if not duplicate.exists() and name == 'violations.json':
                # Existing AES storage policy deletes exact duplicates and leaves
                # a checksum receipt. Do not restore hundreds of MB or waive proof.
                dedup = root.parent.parent / 'drc-storage-dedup.json'
                refs.append(file_ref(dedup))
                record = json.loads(dedup.read_text(encoding='utf-8'))
                matches = [v for v in record.get('removed', []) if v.get('removed') == 'result/report/drc.rpt.artifacts/violations.json'
                           and v.get('canonical') == 'result/report/violations.json'
                           and v.get('sha256') == a['sha256'] and v.get('bytes') == a['bytes']]
                if record.get('details_preserved') is not True or len(matches) != 1:
                    errors.append('unverified_native_duplicate_removal')
                continue
            b = file_ref(duplicate)
            refs.append(b)
            if a['sha256'] != b['sha256']:
                errors.append('native_artifact_copy_mismatch:' + name)
        if known:
            if runtime.get('attached') is not True or runtime.get('stale_cluster_cache_count') != 0 or not raw:
                errors.append('runtime_evidence_missing_or_stale')
            if any(rule not in raw or type(raw[rule]) is not int or raw[rule] < n for rule, n in by_rule.items()):
                errors.append('final_count_exceeds_prefilter_candidates')
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        errors.append('canonical_evidence_unavailable:' + str(exc))
    total = sum(raw.values()) if all(type(n) is int and n >= 0 for n in raw.values()) else None
    mismatch = total is not None and total != summary.get('violation_count')
    if mismatch and not known:
        errors.append('unknown_producer_counter_semantics')
    return {'schema_version': VERSION, 'passed': not errors, 'errors': errors,
            'producer_sha256': producer_sha256,
            'runtime_scope': 'pre_filter_per_cluster_candidates' if known else 'unknown',
            'final_scope': 'post_filter_deduplicated_exported_markers',
            'final_violation_count': count, 'native_log_total': log_total,
            'runtime_candidate_count': total, 'runtime_per_rule': raw,
            'different_scopes_explain_counts': known and mismatch and not errors,
            'physical_filter_correctness_verified': False, 'signoff_clean': False,
            'sources': refs}


def runtime_identity(rt):
    """Identity comes from the execution adapter, never from model input."""
    status = rt.status()
    return status.get('binary_sha256') if status.get('available') and status.get('execution_location') == 'server' else None
