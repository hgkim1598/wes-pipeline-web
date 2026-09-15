#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
DEST_DIR=${CAPTURE_BED_DIR:-"$REPO_ROOT/resources/capture_beds/grch38"}
SELECTED_KIT=${1:-all}

IDT_TARGET_URL='https://sfvideo.blob.core.windows.net/sitefinity/docs/default-source/supplementary-product-info/xgen-exome-hyb-panel-v2-targets-hg38.bed?download=true&sfvrsn=5dc1e207_4'
IDT_PROBE_URL='https://sfvideo.blob.core.windows.net/sitefinity/docs/default-source/supplementary-product-info/xgen-exome-hyb-panel-v2-probes-hg38.bed?download=true&sfvrsn=45c1e207_4'
TWIST_URL='https://www.twistbioscience.com/content/dam/twistbioscience/resources/2022-12/hg38_exome_v2.0.2_targets_sorted_validated.re_annotated.bed'
ROCHE_ARCHIVE_URL='https://n-genetics.com/files/co/Documents/technicaldata/kapa_20130.zip'

IDT_TARGET_SHA='9b18f157033c49380e146ab370258976aa0eaf2a48e4f466c05a5e9f4e41df3a'
IDT_PROBE_SHA='3934ebff86cba64901f1441435feec75fe8fab21cf7b83d96a683552a3bcc66f'
TWIST_SHA='8fa8f1a9fd5d2dcbefa2b48713e8b242065eb60bef0f9b8482322246ed4d5a77'
ROCHE_ARCHIVE_SHA='41b5c6cdbc6860a27da972e1126224a7007fd7a549d7246f691306bf7a700f26'
ROCHE_PRIMARY_SHA='1dedc7d6fd130c54b8c5e5feadea751b2329ddfb71e882676b282c5a5a474b30'
ROCHE_CAPTURE_SHA='0808567356fdccefcdec5ad3b4c5d954795c63c2088ba710370564ee2ea79175'

usage() {
    cat <<'EOF'
Usage: script/download_capture_beds.sh [all|idt|twist|roche|agilent]

Downloads verified GRCh38 BED resources for supported WES capture kits.
Agilent SureSelect V8 design S33266340 requires a manual SureDesign download.
EOF
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

sha256_of() {
    sha256sum "$1" | awk '{print $1}'
}

verify_sha256() {
    local path=$1 expected=$2 actual
    actual=$(sha256_of "$path")
    [[ "$actual" == "$expected" ]] \
        || die "checksum mismatch for $path (expected $expected, got $actual)"
}

download() {
    local url=$1 output=$2 expected_sha=$3
    if [[ -s "$output" ]] && [[ "$(sha256_of "$output")" == "$expected_sha" ]]; then
        printf 'Already verified: %s\n' "$output"
        return 0
    fi

    printf 'Downloading: %s\n' "$output"
    curl --fail --location --retry 3 --connect-timeout 30 \
        --output "${output}.part" "$url"
    verify_sha256 "${output}.part" "$expected_sha"
    mv -- "${output}.part" "$output"
}

validate_bed_shape() {
    local bed=$1
    awk 'BEGIN { n=0 }
         /^track([[:space:]]|$)/ || /^browser([[:space:]]|$)/ || /^#/ || NF==0 { next }
         NF < 3 || $2 !~ /^[0-9]+$/ || $3 !~ /^[0-9]+$/ || $2 >= $3 { bad++; next }
         $1 !~ /^chr([1-9]|1[0-9]|2[0-2]|X|Y|M|MT)$/ { bad_contig++ }
         { n++ }
         END {
             if (n == 0 || bad > 0 || bad_contig > 0) {
                 printf("invalid BED: intervals=%d invalid_rows=%d unsupported_contigs=%d\n", n, bad, bad_contig) > "/dev/stderr"
                 exit 1
             }
             printf("BED verified: %s intervals=%d\n", FILENAME, n)
         }' "$bed"
}

install_idt() {
    require_command curl
    require_command sha256sum
    require_command awk
    local targets="$DEST_DIR/idt_xgen_exome_hyb_panel_v2.targets.hg38.bed"
    local probes="$DEST_DIR/idt_xgen_exome_hyb_panel_v2.probes.hg38.bed"
    download "$IDT_TARGET_URL" "$targets" "$IDT_TARGET_SHA"
    download "$IDT_PROBE_URL" "$probes" "$IDT_PROBE_SHA"
    validate_bed_shape "$targets"
    validate_bed_shape "$probes"
}

install_twist() {
    require_command curl
    require_command sha256sum
    require_command awk
    local targets="$DEST_DIR/twist_exome_2.0.2.covered_targets.hg38.bed"
    download "$TWIST_URL" "$targets" "$TWIST_SHA"
    validate_bed_shape "$targets"
}

install_roche() (
    require_command curl
    require_command sha256sum
    require_command awk
    require_command unzip
    local archive="$DEST_DIR/roche_kapa_hyperexome_v2.hg38.zip"
    local unpack_dir primary_source capture_source primary_dest capture_dest
    download "$ROCHE_ARCHIVE_URL" "$archive" "$ROCHE_ARCHIVE_SHA"

    unpack_dir=$(mktemp -d "${TMPDIR:-/tmp}/hyperexome-v2.XXXXXX")
    trap 'rm -rf -- "${unpack_dir:-}"' EXIT
    unzip -q "$archive" -d "$unpack_dir"

    primary_source="$unpack_dir/HyperExomeV2_hg38/HyperExomeV2_primary_targets.bed"
    capture_source="$unpack_dir/HyperExomeV2_hg38/HyperExomeV2_capture_targets.bed"
    [[ -s "$primary_source" && -s "$capture_source" ]] \
        || die "Roche archive does not contain the expected hg38 BED files"
    verify_sha256 "$primary_source" "$ROCHE_PRIMARY_SHA"
    verify_sha256 "$capture_source" "$ROCHE_CAPTURE_SHA"

    primary_dest="$DEST_DIR/roche_kapa_hyperexome_v2.primary_targets.hg38.bed"
    capture_dest="$DEST_DIR/roche_kapa_hyperexome_v2.capture_targets.hg38.bed"
    cp -- "$primary_source" "$primary_dest"
    cp -- "$capture_source" "$capture_dest"
    validate_bed_shape "$primary_dest"
    validate_bed_shape "$capture_dest"
)

show_agilent_instructions() {
    cat <<EOF
Agilent SureSelect Human All Exon V8 requires manual confirmation:
  1. Open https://suredesign.agilent.com/
  2. Find Published Design S33266340.
  3. Select the GRCh38 genome build.
  4. Download the design's Regions and Covered BED files.
  5. Place them under: $DEST_DIR
  6. Record their exact file names and sha256sum values in:
     $REPO_ROOT/config/capture_kits.grch38.json

The Agilent profile intentionally remains unconfirmed until those files are verified.
EOF
}

mkdir -p -- "$DEST_DIR"

case "$SELECTED_KIT" in
    all)
        install_idt
        install_twist
        install_roche
        show_agilent_instructions
        ;;
    idt) install_idt ;;
    twist) install_twist ;;
    roche) install_roche ;;
    agilent) show_agilent_instructions ;;
    -h|--help) usage ;;
    *) usage >&2; die "unsupported kit selector: $SELECTED_KIT" ;;
esac

printf 'Capture BED resource directory: %s\n' "$DEST_DIR"
