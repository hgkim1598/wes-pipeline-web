#!/usr/bin/env python3
"""Filter a VCF and combine VEP, ClinVar, gnomAD, and PanelApp annotations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLINVAR_DIR = PROJECT_ROOT / "data" / "annotation" / "clinvar"
DEFAULT_PANELAPP_DIR = PROJECT_ROOT / "data" / "annotation" / "panelapp"
PANELAPP_SERVER = "https://panelapp.genomicsengland.co.uk"
VEP_SERVERS = {
    "GRCh37": "https://grch37.rest.ensembl.org",
    "GRCh38": "https://rest.ensembl.org",
}
ASSEMBLY_BY_CHR1_LENGTH = {
    249250621: "GRCh37",
    248956422: "GRCh38",
}
FILTER_PRESETS = {
    "balanced": {"min_dp": 5, "min_gq": 10, "min_alt_depth": 3},
    "strict": {"min_dp": 10, "min_gq": 20, "min_alt_depth": 3},
    "pass-only": {"min_dp": None, "min_gq": None, "min_alt_depth": None},
}
PANEL_CONFIDENCE_LEVELS = {
    "green": {"green"},
    "green-amber": {"green", "amber"},
    "all": {"green", "amber", "red", "unknown"},
}
VEP_BATCH_SIZE = 200
USER_AGENT = "VariantScope/0.3.1 (research-and-education)"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a region, apply a genotype-quality filter, annotate with "
            "ClinVar and VEP, and select genes from a versioned PanelApp panel."
        )
    )
    parser.add_argument("input_vcf", type=Path, help="Input bgzip-compressed VCF")
    parser.add_argument(
        "region",
        help=(
            "Target region such as 17:41196312-41277500 or chr17:...; "
            "use 'panel' to resolve all selected PanelApp genes through "
            "Ensembl, or 'all' to process the entire input VCF"
        ),
    )
    parser.add_argument(
        "output_prefix",
        type=Path,
        help="Output path prefix without a file extension",
    )
    parser.add_argument(
        "clinvar_vcf",
        nargs="?",
        type=Path,
        help=(
            "ClinVar VCF. If omitted, select the matching GRCh37/GRCh38 file "
            "from data/annotation/clinvar"
        ),
    )
    parser.add_argument(
        "--assembly",
        choices=("auto", "GRCh37", "GRCh38"),
        default="auto",
        help="Reference assembly (default: detect from the input VCF header)",
    )
    parser.add_argument(
        "--sample",
        help="Sample name when the VCF contains more than one sample",
    )
    parser.add_argument(
        "--reference-fasta",
        type=Path,
        help="Matching FASTA for left-normalization and local VEP HGVS",
    )
    parser.add_argument(
        "--filter-preset",
        choices=tuple(FILTER_PRESETS),
        default="balanced",
        help=(
            "balanced=DP>=5,GQ>=10,ALT_AD>=3; "
            "strict=DP>=10,GQ>=20,ALT_AD>=3; "
            "pass-only=VCF FILTER field only"
        ),
    )
    parser.add_argument("--min-dp", type=int, help="Override FORMAT/DP threshold")
    parser.add_argument("--min-gq", type=int, help="Override FORMAT/GQ threshold")
    parser.add_argument(
        "--min-alt-depth",
        type=int,
        help="Override alternate-allele FORMAT/AD threshold",
    )
    parser.add_argument(
        "--panel-id",
        type=int,
        help=(
            "PanelApp panel ID. Use 635 for 'Inherited breast cancer and "
            "ovarian cancer'."
        ),
    )
    parser.add_argument(
        "--panel-version",
        help="Pinned PanelApp version, for example 3.0",
    )
    parser.add_argument(
        "--panel-confidence",
        choices=tuple(PANEL_CONFIDENCE_LEVELS),
        default="green",
        help="Panel evidence levels to retain (default: green)",
    )
    parser.add_argument(
        "--panel-cache",
        type=Path,
        help="PanelApp JSON cache. A default path is generated from ID/version.",
    )
    parser.add_argument(
        "--refresh-panel",
        action="store_true",
        help="Download PanelApp again instead of reusing the JSON cache",
    )
    parser.add_argument(
        "--vep-mode",
        choices=("skip", "rest", "local"),
        default="skip",
        help=(
            "VEP annotation mode. 'rest' uploads variants to Ensembl; "
            "'local' requires a VEP cache; default is skip."
        ),
    )
    parser.add_argument(
        "--vep-cache",
        type=Path,
        help="Cache file for VEP API/local JSON results",
    )
    parser.add_argument(
        "--refresh-vep",
        action="store_true",
        help="Re-run VEP instead of reusing a matching result cache",
    )
    parser.add_argument(
        "--max-rest-variants",
        type=int,
        default=2000,
        help="Safety limit for variants sent to Ensembl REST (default: 2000)",
    )
    parser.add_argument(
        "--vep-executable",
        default="vep",
        help="Local VEP executable name/path (default: vep)",
    )
    parser.add_argument(
        "--vep-dir-cache",
        type=Path,
        help="Directory containing a local Ensembl VEP cache",
    )
    parser.add_argument(
        "--api-timeout",
        type=int,
        default=90,
        help="HTTP timeout in seconds (default: 90)",
    )
    return parser.parse_args(argv)


def run_command(command: Sequence[str]) -> None:
    subprocess.run(command, check=True)


def run_command_capture(command: Sequence[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def run_command_to_file(command: Sequence[str], output_path: Path) -> None:
    with output_path.open("wb") as output_file:
        subprocess.run(command, check=True, stdout=output_file)


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")


def index_path_exists(vcf_path: Path) -> bool:
    return Path(f"{vcf_path}.tbi").is_file() or Path(f"{vcf_path}.csi").is_file()


def ensure_index(vcf_path: Path, step_number: int, label: str) -> None:
    if index_path_exists(vcf_path):
        return
    print(f"[{step_number}] Indexing {label} VCF...")
    run_command(["bcftools", "index", str(vcf_path)])


def inspect_vcf_assembly(vcf_path: Path) -> tuple[str | None, bool]:
    header = run_command_capture(["bcftools", "view", "-h", str(vcf_path)])
    contig_match = re.search(
        r"^##contig=<ID=((?:chr)?1)(?:,([^>]*))?>",
        header,
        flags=re.MULTILINE,
    )
    if contig_match is None:
        raise ValueError(f"chromosome 1 contig is missing from: {vcf_path}")
    uses_chr_prefix = contig_match.group(1).startswith("chr")
    attributes = contig_match.group(2) or ""
    length_match = re.search(r"(?:^|,)length=(\d+)(?:,|$)", attributes)
    assembly = (
        ASSEMBLY_BY_CHR1_LENGTH.get(int(length_match.group(1)))
        if length_match
        else None
    )
    if assembly is None:
        reference_match = re.search(
            r"^##reference=([^\r\n]+)",
            header,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        reference = reference_match.group(1).lower() if reference_match else ""
        if "grch38" in reference or "hg38" in reference:
            assembly = "GRCh38"
        elif "grch37" in reference or "hg19" in reference or "b37" in reference:
            assembly = "GRCh37"
    return assembly, uses_chr_prefix


def read_vcf_header_value(vcf_path: Path, key: str) -> str | None:
    header = run_command_capture(["bcftools", "view", "-h", str(vcf_path)])
    match = re.search(rf"^##{re.escape(key)}=(.+)$", header, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def select_clinvar_vcf(assembly: str, uses_chr_prefix: bool) -> Path:
    suffix = "_chr" if uses_chr_prefix else ""
    return DEFAULT_CLINVAR_DIR / f"clinvar_{assembly}{suffix}.vcf.gz"


def build_filter_expression(
    preset_name: str,
    min_dp_override: int | None,
    min_gq_override: int | None,
    min_alt_depth_override: int | None,
) -> tuple[str, dict[str, int | None]]:
    thresholds = FILTER_PRESETS[preset_name].copy()
    overrides = {
        "min_dp": min_dp_override,
        "min_gq": min_gq_override,
        "min_alt_depth": min_alt_depth_override,
    }
    for name, value in overrides.items():
        if value is not None:
            if value < 0:
                raise ValueError(f"{name} must be zero or greater")
            thresholds[name] = value

    conditions = ['(FILTER="PASS" || FILTER=".")']
    if thresholds["min_dp"] is not None:
        conditions.append(f'FMT/DP>={thresholds["min_dp"]}')
    if thresholds["min_gq"] is not None:
        conditions.append(f'FMT/GQ>={thresholds["min_gq"]}')
    if thresholds["min_alt_depth"] is not None:
        conditions.append(f'FMT/AD[0:1]>={thresholds["min_alt_depth"]}')
    return " && ".join(conditions), thresholds


def select_sample(vcf_path: Path, requested_sample: str | None) -> str | None:
    samples = [
        line.strip()
        for line in run_command_capture(["bcftools", "query", "-l", str(vcf_path)]).splitlines()
        if line.strip()
    ]
    if requested_sample:
        if requested_sample not in samples:
            raise ValueError(
                f"sample '{requested_sample}' is not present in the VCF: {samples}"
            )
        return requested_sample
    if len(samples) > 1:
        raise ValueError(
            "the VCF contains multiple samples; select one with --sample: "
            + ", ".join(samples)
        )
    return samples[0] if samples else None


def json_request(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 90,
    retries: int = 3,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method="POST" if body is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                detail = error.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"HTTP {error.code} from {url}: {detail[:300]}"
                ) from error
        except urllib.error.URLError as error:
            if attempt == retries - 1:
                raise RuntimeError(f"could not reach {url}: {error.reason}") from error
        time.sleep(2**attempt)
    raise RuntimeError(f"request failed: {url}")


def confidence_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"green", "high", "3", "4"} or "green" in text:
        return "green"
    if text in {"amber", "moderate", "2"} or "amber" in text:
        return "amber"
    if text in {"red", "low", "0", "1"} or "red" in text:
        return "red"
    return "unknown"


def first_value(data: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def normalize_panel_payload(
    stored: dict[str, Any],
    panel_id: int,
    requested_version: str | None,
) -> dict[str, Any]:
    if "normalized" in stored:
        normalized = stored["normalized"]
        if isinstance(normalized, dict):
            return normalized

    raw = stored.get("payload", stored)
    if not isinstance(raw, dict):
        raise ValueError("PanelApp response is not a JSON object")

    panel_data = raw.get("panel") if isinstance(raw.get("panel"), dict) else raw
    entity_payload = stored.get("entities_payload")
    candidates: list[Any] = []
    for container in (raw, entity_payload):
        if not isinstance(container, dict):
            continue
        for key in ("genes", "entities", "results"):
            value = container.get(key)
            if isinstance(value, list):
                candidates.extend(value)
    if isinstance(raw.get("panel"), dict):
        for key in ("genes", "entities"):
            value = raw["panel"].get(key)
            if isinstance(value, list):
                candidates.extend(value)

    genes_by_symbol: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        gene_data = item.get("gene_data")
        if not isinstance(gene_data, dict):
            gene_data = {}
        entity_data = item.get("entity_data")
        if not isinstance(entity_data, dict):
            entity_data = {}

        entity_type = str(
            first_value(item, ("entity_type", "type")) or "gene"
        ).lower()
        if entity_type not in {"gene", "genes", ""}:
            continue

        symbol = first_value(
            item,
            ("gene_symbol", "entity_name", "symbol", "name"),
        )
        symbol = symbol or first_value(
            gene_data,
            ("gene_symbol", "symbol", "name"),
        )
        symbol = symbol or first_value(
            entity_data,
            ("gene_symbol", "symbol", "name"),
        )
        if not symbol:
            continue
        symbol = str(symbol).strip().upper()
        confidence = confidence_name(
            first_value(item, ("confidence_level", "status", "colour", "color"))
        )
        phenotypes = first_value(item, ("phenotypes", "phenotype")) or []
        if isinstance(phenotypes, str):
            phenotypes = [phenotypes]

        genes_by_symbol[symbol] = {
            "symbol": symbol,
            "hgnc_id": str(
                first_value(gene_data, ("hgnc_id", "hgnc_symbol"))
                or first_value(item, ("hgnc_id",))
                or ""
            ),
            "confidence": confidence,
            "mode_of_inheritance": str(
                first_value(item, ("mode_of_inheritance", "moi")) or ""
            ),
            "phenotypes": [str(value) for value in phenotypes],
        }

    name = str(
        first_value(panel_data, ("name", "panel_name", "title"))
        or f"PanelApp panel {panel_id}"
    )
    version = str(
        first_value(panel_data, ("version", "current_version"))
        or requested_version
        or ""
    )
    return {
        "panel_id": panel_id,
        "name": name,
        "version": version,
        "genes": sorted(genes_by_symbol.values(), key=lambda item: item["symbol"]),
    }


def default_panel_cache(panel_id: int, panel_version: str | None) -> Path:
    version = re.sub(r"[^A-Za-z0-9_.-]", "_", panel_version or "latest")
    return DEFAULT_PANELAPP_DIR / f"panel_{panel_id}_v{version}.json"


def load_panel(
    panel_id: int,
    panel_version: str | None,
    confidence: str,
    cache_path: Path,
    refresh: bool,
    timeout: int,
) -> dict[str, Any]:
    source_url = f"{PANELAPP_SERVER}/api/v1/panels/{panel_id}/"
    params = {"format": "json"}
    if panel_version:
        params["version"] = panel_version
    request_url = source_url + "?" + urllib.parse.urlencode(params)

    if cache_path.is_file() and not refresh:
        stored = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        print(f"    Downloading PanelApp panel {panel_id}...")
        payload = json_request(request_url, timeout=timeout)
        genes_params = {"format": "json"}
        if panel_version:
            genes_params["version"] = panel_version
        genes_url = (
            f"{PANELAPP_SERVER}/api/v1/panels/{panel_id}/genes/?"
            + urllib.parse.urlencode(genes_params)
        )
        stored = {
            "source_url": request_url,
            "genes_url": genes_url,
            "retrieved_at": utc_now(),
            "payload": payload,
            "entities_payload": json_request(genes_url, timeout=timeout),
        }
        normalized = normalize_panel_payload(stored, panel_id, panel_version)
        if not normalized["genes"]:
            entities_url = (
                f"{PANELAPP_SERVER}/api/v1/entities/?"
                + urllib.parse.urlencode(
                    {"panel_id": panel_id, "format": "json"}
                )
            )
            stored["entities_payload"] = json_request(
                entities_url,
                timeout=timeout,
            )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(stored, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    normalized = normalize_panel_payload(stored, panel_id, panel_version)
    if panel_version and normalized["version"] and normalized["version"] != panel_version:
        raise ValueError(
            f"PanelApp version mismatch: requested={panel_version}, "
            f"received={normalized['version']}"
        )
    accepted = PANEL_CONFIDENCE_LEVELS[confidence]
    normalized["genes"] = [
        gene for gene in normalized["genes"] if gene["confidence"] in accepted
    ]
    normalized["confidence_filter"] = confidence
    normalized["source_url"] = stored.get("source_url", request_url)
    normalized["cache_path"] = str(cache_path)
    if not normalized["genes"]:
        raise ValueError(
            f"PanelApp panel {panel_id} has no genes after '{confidence}' filtering"
        )
    return normalized


def resolve_panel_regions(
    panel: dict[str, Any],
    assembly: str,
    uses_chr_prefix: bool,
    timeout: int,
) -> list[dict[str, Any]]:
    server = VEP_SERVERS[assembly]
    regions: list[dict[str, Any]] = []
    for gene in panel.get("genes", []):
        symbol = str(gene.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        url = (
            f"{server}/lookup/symbol/homo_sapiens/"
            f"{urllib.parse.quote(symbol, safe='')}?expand=0"
        )
        payload = json_request(url, timeout=timeout)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Ensembl returned a non-object gene lookup for {symbol}"
            )
        chromosome = str(payload.get("seq_region_name") or "")
        start = payload.get("start")
        end = payload.get("end")
        returned_assembly = str(payload.get("assembly_name") or "")
        if returned_assembly and returned_assembly != assembly:
            raise ValueError(
                f"Ensembl assembly mismatch for {symbol}: "
                f"requested={assembly}, returned={returned_assembly}"
            )
        if not chromosome or not isinstance(start, int) or not isinstance(end, int):
            raise ValueError(f"Ensembl gene coordinates are incomplete for {symbol}")
        if uses_chr_prefix and not chromosome.startswith("chr"):
            chromosome = f"chr{chromosome}"
        elif not uses_chr_prefix and chromosome.startswith("chr"):
            chromosome = chromosome[3:]
        regions.append(
            {
                "gene": symbol,
                "chrom": chromosome,
                "start": start,
                "end": end,
                "region": f"{chromosome}:{start}-{end}",
                "ensembl_gene_id": str(payload.get("id") or ""),
                "source_url": url,
            }
        )
    if not regions:
        raise ValueError("the selected PanelApp panel contains no resolvable genes")
    return regions


def variant_key(chrom: str, pos: int | str, ref: str, alt: str) -> str:
    return f"{chrom.removeprefix('chr')}:{int(pos)}:{ref}:{alt}"


def vep_input_for_row(row: dict[str, str]) -> str:
    chrom = row["chrom"].removeprefix("chr")
    return f"{chrom} {row['pos']} . {row['ref']} {row['alt']} . . ."


def input_digest(rows: Sequence[dict[str, str]], assembly: str) -> str:
    content = assembly + "\n" + "\n".join(vep_input_for_row(row) for row in rows)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_matching_vep_cache(
    cache_path: Path,
    digest: str,
    assembly: str,
    refresh: bool,
) -> list[dict[str, Any]] | None:
    if not cache_path.is_file() or refresh:
        return None
    stored = json.loads(cache_path.read_text(encoding="utf-8"))
    if (
        stored.get("input_sha256") != digest
        or stored.get("assembly") != assembly
    ):
        return None
    results = stored.get("results")
    return results if isinstance(results, list) else None


def save_vep_cache(
    cache_path: Path,
    assembly: str,
    digest: str,
    source: str,
    results: list[dict[str, Any]],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "assembly": assembly,
                "input_sha256": digest,
                "source": source,
                "created_at": utc_now(),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def fetch_vep_rest(
    rows: Sequence[dict[str, str]],
    assembly: str,
    cache_path: Path,
    refresh: bool,
    timeout: int,
    max_variants: int,
) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if row["alt"] != "*" and not row["alt"].startswith("<")
    ]
    if len(eligible) > max_variants:
        raise ValueError(
            f"{len(eligible)} variants exceed --max-rest-variants={max_variants}. "
            "Use local VEP for a full WES VCF."
        )

    digest = input_digest(eligible, assembly)
    cached = load_matching_vep_cache(cache_path, digest, assembly, refresh)
    if cached is not None:
        print(f"    Reusing VEP cache: {cache_path}")
        return cached

    server = VEP_SERVERS[assembly]
    options = urllib.parse.urlencode(
        {
            "canonical": 1,
            "hgvs": 1,
            "protein": 1,
            "variant_class": 1,
            "symbol": 1,
            "numbers": 1,
            "af_gnomade": 1,
            "af_gnomadg": 1,
        }
    )
    url = f"{server}/vep/homo_sapiens/region?{options}"
    results: list[dict[str, Any]] = []
    for start in range(0, len(eligible), VEP_BATCH_SIZE):
        batch = eligible[start : start + VEP_BATCH_SIZE]
        print(
            f"    Ensembl VEP REST: {start + 1}-"
            f"{start + len(batch)} / {len(eligible)}"
        )
        response = json_request(
            url,
            payload={"variants": [vep_input_for_row(row) for row in batch]},
            timeout=timeout,
        )
        if not isinstance(response, list):
            raise RuntimeError("Ensembl VEP REST returned a non-list response")
        results.extend(item for item in response if isinstance(item, dict))
        if start + VEP_BATCH_SIZE < len(eligible):
            time.sleep(0.25)

    save_vep_cache(cache_path, assembly, digest, url, results)
    return results


def run_vep_local(
    rows: Sequence[dict[str, str]],
    annotated_vcf: Path,
    output_prefix: Path,
    assembly: str,
    cache_path: Path,
    refresh: bool,
    executable: str,
    dir_cache: Path | None,
    reference_fasta: Path | None,
) -> list[dict[str, Any]]:
    digest = input_digest(rows, assembly)
    cached = load_matching_vep_cache(cache_path, digest, assembly, refresh)
    if cached is not None:
        print(f"    Reusing VEP cache: {cache_path}")
        return cached
    if shutil.which(executable) is None and not Path(executable).is_file():
        raise RuntimeError(
            f"local VEP executable was not found: {executable}. "
            "Install VEP or use --vep-mode rest for a small public test VCF."
        )

    raw_json = Path(f"{output_prefix}.vep.raw.jsonl")
    command = [
        executable,
        "--input_file",
        str(annotated_vcf),
        "--format",
        "vcf",
        "--output_file",
        str(raw_json),
        "--json",
        "--cache",
        "--offline",
        "--assembly",
        assembly,
        "--symbol",
        "--hgvs",
        "--protein",
        "--canonical",
        "--numbers",
        "--variant_class",
        "--af_gnomade",
        "--af_gnomadg",
        "--no_stats",
        "--force_overwrite",
    ]
    if dir_cache:
        command.extend(["--dir_cache", str(dir_cache)])
    if reference_fasta:
        command.extend(["--fasta", str(reference_fasta)])
    run_command(command)

    results: list[dict[str, Any]] = []
    with raw_json.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    results.append(item)
    save_vep_cache(cache_path, assembly, digest, "local VEP", results)
    return results


def parse_vep_result_key(result: dict[str, Any]) -> str | None:
    input_line = str(result.get("input") or "").strip()
    fields = input_line.split()
    if len(fields) >= 5:
        try:
            return variant_key(fields[0], fields[1], fields[3], fields[4])
        except (TypeError, ValueError):
            pass

    chrom = result.get("seq_region_name")
    pos = result.get("start")
    allele_string = str(result.get("allele_string") or "")
    alleles = allele_string.split("/")
    if chrom is not None and pos is not None and len(alleles) >= 2:
        return variant_key(str(chrom), int(pos), alleles[0], alleles[1])
    return None


def index_vep_results(
    results: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for result in results:
        key = parse_vep_result_key(result)
        if key:
            indexed[key] = result
    return indexed


def normalize_scalar(value: Any) -> str:
    if value in (None, "", "."):
        return ""
    if isinstance(value, list):
        return "&".join(str(item) for item in value)
    return str(value)


def select_transcript(
    result: dict[str, Any],
    panel_symbols: set[str],
) -> tuple[dict[str, Any], list[str], list[str]]:
    transcripts = [
        item
        for item in (result.get("transcript_consequences") or [])
        if isinstance(item, dict)
    ]
    all_genes = sorted(
        {
            str(item.get("gene_symbol")).upper()
            for item in transcripts
            if item.get("gene_symbol")
        }
    )
    panel_genes = sorted(set(all_genes) & panel_symbols)
    impact_rank = {"HIGH": 0, "MODERATE": 1, "LOW": 2, "MODIFIER": 3}

    def rank(item: dict[str, Any]) -> tuple[int, int, int, int, str]:
        symbol = str(item.get("gene_symbol") or "").upper()
        return (
            0 if symbol in panel_symbols else 1,
            0 if item.get("canonical") in {1, "1"} else 1,
            0 if item.get("biotype") == "protein_coding" else 1,
            impact_rank.get(str(item.get("impact") or ""), 9),
            str(item.get("transcript_id") or ""),
        )

    selected = min(transcripts, key=rank) if transcripts else {}
    return selected, all_genes, panel_genes


def extract_gnomad_frequency(
    result: dict[str, Any],
    alt: str,
    dataset: str,
) -> str:
    aliases = {
        "exome": ("gnomade", "gnomad_exomes", "gnomad_exome", "gnomad"),
        "genome": ("gnomadg", "gnomad_genomes", "gnomad_genome"),
    }[dataset]
    values: list[float] = []
    for colocated in result.get("colocated_variants") or []:
        if not isinstance(colocated, dict):
            continue
        frequencies = colocated.get("frequencies")
        if not isinstance(frequencies, dict):
            continue
        allele_data = frequencies.get(alt)
        if not isinstance(allele_data, dict):
            continue
        for key, value in allele_data.items():
            if str(key).lower() not in aliases:
                continue
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
    return f"{max(values):.8g}" if values else ""


def query_variant_rows(vcf_path: Path, sample: str | None) -> list[dict[str, str]]:
    fields = [
        "chrom",
        "pos",
        "ref",
        "alt",
        "filter",
        "clinvar_id",
        "qual",
        "geneinfo",
        "clinvar_significance",
        "clinvar_disease",
        "clinvar_review_status",
        "clinvar_hgvs",
        "gt",
        "ad",
        "dp",
        "gq",
    ]
    query_format = (
        r"%CHROM\t%POS\t%REF\t%ALT\t%FILTER\t%ID\t%QUAL"
        r"\t%INFO/GENEINFO\t%INFO/CLNSIG\t%INFO/CLNDN"
        r"\t%INFO/CLNREVSTAT\t%INFO/CLNHGVS"
        r"[\t%GT\t%AD\t%DP\t%GQ]\n"
    )
    command = ["bcftools", "query", "--allow-undef-tags"]
    if sample:
        command.extend(["-s", sample])
    command.extend(["-f", query_format, str(vcf_path)])
    output = run_command_capture(command)

    rows: list[dict[str, str]] = []
    for line in output.splitlines():
        values = line.split("\t")
        values.extend([""] * (len(fields) - len(values)))
        row = dict(zip(fields, values[: len(fields)]))
        for key, value in list(row.items()):
            row[key] = "" if value == "." else value
        rows.append(row)
    return rows


def build_result_rows(
    variant_rows: Sequence[dict[str, str]],
    vep_results: Sequence[dict[str, Any]],
    panel: dict[str, Any] | None,
) -> list[dict[str, str]]:
    indexed_vep = index_vep_results(vep_results)
    panel_gene_data = {
        gene["symbol"]: gene for gene in (panel or {}).get("genes", [])
    }
    panel_symbols = set(panel_gene_data)
    output: list[dict[str, str]] = []

    for row in variant_rows:
        key = variant_key(row["chrom"], row["pos"], row["ref"], row["alt"])
        result = indexed_vep.get(key, {})
        transcript, all_genes, matching_panel_genes = select_transcript(
            result,
            panel_symbols,
        )
        selected_gene = str(transcript.get("gene_symbol") or "").upper()
        if matching_panel_genes and selected_gene not in matching_panel_genes:
            selected_gene = matching_panel_genes[0]
        panel_metadata = panel_gene_data.get(selected_gene, {})

        consequence = normalize_scalar(transcript.get("consequence_terms"))
        if not consequence:
            consequence = normalize_scalar(result.get("most_severe_consequence"))
        output.append(
            {
                **row,
                "gene": selected_gene,
                "all_vep_genes": ";".join(all_genes),
                "transcript": normalize_scalar(transcript.get("transcript_id")),
                "consequence": consequence,
                "impact": normalize_scalar(transcript.get("impact")),
                "hgvsc": normalize_scalar(transcript.get("hgvsc")),
                "hgvsp": normalize_scalar(transcript.get("hgvsp")),
                "canonical": (
                    "yes"
                    if transcript.get("canonical") in {1, "1"}
                    else "no" if transcript else ""
                ),
                "sift_prediction": normalize_scalar(
                    transcript.get("sift_prediction")
                ),
                "sift_score": normalize_scalar(transcript.get("sift_score")),
                "polyphen_prediction": normalize_scalar(
                    transcript.get("polyphen_prediction")
                ),
                "polyphen_score": normalize_scalar(
                    transcript.get("polyphen_score")
                ),
                "gnomad_exome_af": extract_gnomad_frequency(
                    result,
                    row["alt"],
                    "exome",
                ),
                "gnomad_genome_af": extract_gnomad_frequency(
                    result,
                    row["alt"],
                    "genome",
                ),
                "in_selected_panel": "yes" if matching_panel_genes else "no",
                "panel_genes": ";".join(matching_panel_genes),
                "panel_confidence": normalize_scalar(
                    panel_metadata.get("confidence")
                ),
                "panel_mode_of_inheritance": normalize_scalar(
                    panel_metadata.get("mode_of_inheritance")
                ),
                "panel_id": normalize_scalar((panel or {}).get("panel_id")),
                "panel_version": normalize_scalar((panel or {}).get("version")),
                "panel_name": normalize_scalar((panel or {}).get("name")),
            }
        )
    return output


RESULT_FIELDS = [
    "chrom",
    "pos",
    "ref",
    "alt",
    "filter",
    "qual",
    "gt",
    "ad",
    "dp",
    "gq",
    "gene",
    "all_vep_genes",
    "transcript",
    "consequence",
    "impact",
    "hgvsc",
    "hgvsp",
    "canonical",
    "sift_prediction",
    "sift_score",
    "polyphen_prediction",
    "polyphen_score",
    "clinvar_id",
    "clinvar_significance",
    "clinvar_disease",
    "clinvar_review_status",
    "clinvar_hgvs",
    "gnomad_exome_af",
    "gnomad_genome_af",
    "in_selected_panel",
    "panel_genes",
    "panel_confidence",
    "panel_mode_of_inheritance",
    "panel_id",
    "panel_version",
    "panel_name",
    "geneinfo",
]


def write_tsv(
    path: Path,
    rows: Sequence[dict[str, str]],
    *,
    panel_only: bool = False,
) -> int:
    selected = [
        row
        for row in rows
        if not panel_only or row.get("in_selected_panel") == "yes"
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=RESULT_FIELDS,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(selected)
    return len(selected)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    filter_expression, thresholds = build_filter_expression(
        args.filter_preset,
        args.min_dp,
        args.min_gq,
        args.min_alt_depth,
    )
    if shutil.which("bcftools") is None:
        raise RuntimeError(
            "bcftools was not found. Run this program in the WSL/conda "
            "environment where bcftools is installed."
        )
    if args.panel_id and args.vep_mode == "skip":
        raise ValueError(
            "--panel-id requires --vep-mode rest or --vep-mode local because "
            "VEP maps variants to panel genes"
        )
    if args.reference_fasta:
        require_file(args.reference_fasta, "Reference FASTA")
    require_file(args.input_vcf, "Input VCF")

    detected_assembly, input_uses_chr = inspect_vcf_assembly(args.input_vcf)
    if args.assembly == "auto":
        if detected_assembly is None:
            raise ValueError(
                "could not detect GRCh37/GRCh38; specify --assembly"
            )
        assembly = detected_assembly
    else:
        assembly = args.assembly
        if detected_assembly and detected_assembly != assembly:
            raise ValueError(
                f"--assembly={assembly} conflicts with VCF={detected_assembly}"
            )

    sample = select_sample(args.input_vcf, args.sample)
    clinvar_vcf = args.clinvar_vcf or select_clinvar_vcf(
        assembly,
        input_uses_chr,
    )
    require_file(clinvar_vcf, f"{assembly} ClinVar VCF")
    clinvar_assembly, clinvar_uses_chr = inspect_vcf_assembly(clinvar_vcf)
    if clinvar_assembly and clinvar_assembly != assembly:
        raise ValueError(
            f"ClinVar assembly mismatch: input={assembly}, "
            f"ClinVar={clinvar_assembly}"
        )
    if clinvar_uses_chr != input_uses_chr:
        raise ValueError(
            "chromosome naming mismatch between input and ClinVar "
            "('chr1' versus '1')"
        )

    output_prefix: Path = args.output_prefix
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    subset_vcf = Path(f"{output_prefix}.subset.vcf.gz")
    filtered_vcf = Path(f"{output_prefix}.filtered.vcf.gz")
    normalized_vcf = Path(f"{output_prefix}.normalized.vcf.gz")
    annotated_vcf = Path(f"{output_prefix}.clinvar.vcf.gz")
    legacy_tsv = Path(f"{output_prefix}.clinvar.tsv")
    variants_tsv = Path(f"{output_prefix}.variants.tsv")
    panel_variants_tsv = Path(f"{output_prefix}.panel_variants.tsv")
    panel_output_json = Path(f"{output_prefix}.panel.json")
    manifest_json = Path(f"{output_prefix}.manifest.json")
    subset_stats = Path(f"{output_prefix}.subset.stats.txt")
    filtered_stats = Path(f"{output_prefix}.filtered.stats.txt")
    filter_config = Path(f"{output_prefix}.filter.txt")
    vep_cache = args.vep_cache or Path(f"{output_prefix}.vep.cache.json")

    panel: dict[str, Any] | None = None
    panel_cache: Path | None = None
    if args.panel_id:
        panel_cache = args.panel_cache or default_panel_cache(
            args.panel_id,
            args.panel_version,
        )
        panel = load_panel(
            args.panel_id,
            args.panel_version,
            args.panel_confidence,
            panel_cache,
            args.refresh_panel,
            args.api_timeout,
        )

    panel_regions: list[dict[str, Any]] = []
    extraction_region = args.region
    if args.region.lower() == "panel":
        if panel is None:
            raise ValueError("region='panel' requires --panel-id")
        print("    Resolving all panel gene coordinates through Ensembl...")
        panel_regions = resolve_panel_regions(
            panel,
            assembly,
            input_uses_chr,
            args.api_timeout,
        )
        extraction_region = ",".join(
            item["region"] for item in panel_regions
        )
        panel["regions"] = panel_regions
    if panel:
        panel_output_json.write_text(
            json.dumps(panel, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"[1] Input VCF: {args.input_vcf}")
    print(f"[2] Region: {args.region}")
    if panel_regions:
        print(
            "[2a] Resolved panel regions: "
            + ", ".join(
                f"{item['gene']}={item['region']}" for item in panel_regions
            )
        )
    print(f"[3] Output prefix: {output_prefix}")
    print(f"[4] Assembly: {assembly}")
    print(f"[5] Chromosome style: {'chr1' if input_uses_chr else '1'}")
    print(f"[6] Sample: {sample or 'none'}")
    print(f"[7] ClinVar VCF: {clinvar_vcf}")
    print(f"[8] Filter expression: {filter_expression}")
    print(f"[9] VEP mode: {args.vep_mode}")
    if panel:
        print(
            f"[10] Disease panel: {panel['name']} "
            f"(ID={panel['panel_id']}, version={panel['version']}, "
            f"genes={len(panel['genes'])})"
        )

    ensure_index(args.input_vcf, 11, "input")
    ensure_index(clinvar_vcf, 12, "ClinVar")

    print("[13] Extracting target variants...")
    subset_command = ["bcftools", "view"]
    if extraction_region.lower() != "all":
        subset_command.extend(["-r", extraction_region])
    subset_command.extend(
        [str(args.input_vcf), "-Oz", "-o", str(subset_vcf)]
    )
    run_command(subset_command)
    run_command(["bcftools", "index", "-f", str(subset_vcf)])

    print("[14] Applying the selected quality filter...")
    run_command(
        [
            "bcftools",
            "view",
            "-i",
            filter_expression,
            str(subset_vcf),
            "-Oz",
            "-o",
            str(filtered_vcf),
        ]
    )
    run_command(["bcftools", "index", "-f", str(filtered_vcf)])

    print("[15] Splitting and normalizing alleles...")
    normalize_command = ["bcftools", "norm", "-m", "-any"]
    if args.reference_fasta:
        normalize_command.extend(["-f", str(args.reference_fasta)])
    normalize_command.extend(
        [str(filtered_vcf), "-Oz", "-o", str(normalized_vcf)]
    )
    run_command(normalize_command)
    run_command(["bcftools", "index", "-f", str(normalized_vcf)])

    print("[16] Annotating exact alleles with local ClinVar...")
    run_command(
        [
            "bcftools",
            "annotate",
            "-a",
            str(clinvar_vcf),
            "-c",
            (
                "ID,INFO/CLNSIG,INFO/CLNDN,INFO/CLNREVSTAT,"
                "INFO/CLNHGVS,INFO/GENEINFO"
            ),
            str(normalized_vcf),
            "-Oz",
            "-o",
            str(annotated_vcf),
        ]
    )
    run_command(["bcftools", "index", "-f", str(annotated_vcf)])

    print("[17] Creating backward-compatible ClinVar TSV...")
    legacy_query = (
        r"%CHROM\t%POS\t%REF\t%ALT\t%FILTER\t%ID\t%INFO/GENEINFO"
        r"\t%INFO/CLNSIG\t%INFO/CLNDN\t%INFO/CLNREVSTAT\n"
    )
    run_command_to_file(
        ["bcftools", "query", "-f", legacy_query, str(annotated_vcf)],
        legacy_tsv,
    )
    variant_rows = query_variant_rows(annotated_vcf, sample)

    vep_results: list[dict[str, Any]] = []
    if args.vep_mode == "rest":
        print("[18] Annotating with Ensembl VEP REST...")
        vep_results = fetch_vep_rest(
            variant_rows,
            assembly,
            vep_cache,
            args.refresh_vep,
            args.api_timeout,
            args.max_rest_variants,
        )
    elif args.vep_mode == "local":
        print("[18] Annotating with local Ensembl VEP...")
        vep_results = run_vep_local(
            variant_rows,
            annotated_vcf,
            output_prefix,
            assembly,
            vep_cache,
            args.refresh_vep,
            args.vep_executable,
            args.vep_dir_cache,
            args.reference_fasta,
        )
    else:
        print("[18] Skipping VEP annotation...")

    print("[19] Combining annotation and disease-panel results...")
    result_rows = build_result_rows(variant_rows, vep_results, panel)
    total_count = write_tsv(variants_tsv, result_rows)
    panel_count = (
        write_tsv(panel_variants_tsv, result_rows, panel_only=True)
        if panel
        else 0
    )

    print("[20] Creating statistics and resource manifest...")
    run_command_to_file(["bcftools", "stats", str(subset_vcf)], subset_stats)
    run_command_to_file(["bcftools", "stats", str(filtered_vcf)], filtered_stats)
    filter_config.write_text(
        "\n".join(
            [
                f"preset={args.filter_preset}",
                f"min_dp={thresholds['min_dp']}",
                f"min_gq={thresholds['min_gq']}",
                f"min_alt_depth={thresholds['min_alt_depth']}",
                f"assembly={assembly}",
                f"chromosome_style={'chr' if input_uses_chr else 'no_chr'}",
                f"sample={sample or ''}",
                f"clinvar_vcf={clinvar_vcf}",
                f"expression={filter_expression}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    manifest = {
        "pipeline": "VariantScope annotation pipeline",
        "pipeline_version": "0.3.1",
        "created_at": utc_now(),
        "input_vcf": str(args.input_vcf),
        "region": args.region,
        "resolved_panel_regions": panel_regions,
        "sample": sample,
        "assembly": assembly,
        "filter": {
            "preset": args.filter_preset,
            "expression": filter_expression,
            **thresholds,
        },
        "clinvar": {
            "path": str(clinvar_vcf),
            "file_date": read_vcf_header_value(clinvar_vcf, "fileDate"),
            "match": "normalized CHROM+POS+REF+ALT exact allele",
        },
        "vep": {
            "mode": args.vep_mode,
            "server": VEP_SERVERS[assembly] if args.vep_mode == "rest" else None,
            "cache": str(vep_cache) if args.vep_mode != "skip" else None,
        },
        "panelapp": panel,
        "counts": {
            "filtered_alleles": total_count,
            "selected_panel_alleles": panel_count,
        },
        "outputs": {
            "clinvar_vcf": str(annotated_vcf),
            "all_variants_tsv": str(variants_tsv),
            "panel_variants_tsv": str(panel_variants_tsv) if panel else None,
            "panel_json": str(panel_output_json) if panel else None,
        },
        "limitations": [
            "Research and education only; not a clinical diagnosis.",
            "ClinVar absence does not mean benign.",
            "gnomAD absence does not mean pathogenic.",
            "REST mode sends variant coordinates and alleles to Ensembl.",
            "Small-variant WES analysis does not replace validated CNV analysis.",
        ],
    }
    manifest_json.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Done.")
    print(f"Filtered alleles: {total_count}")
    if panel:
        print(f"Panel alleles:    {panel_count}")
    print(f"ClinVar VCF:      {annotated_vcf}")
    print(f"All variants TSV: {variants_tsv}")
    if panel:
        print(f"Panel TSV:        {panel_variants_tsv}")
        print(f"Panel metadata:   {panel_output_json}")
    print(f"Manifest:         {manifest_json}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except (ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except subprocess.CalledProcessError as error:
        print(
            f"ERROR: command failed with exit code {error.returncode}",
            file=sys.stderr,
        )
        raise SystemExit(error.returncode) from error
