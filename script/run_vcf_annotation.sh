#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="0.1.0"
SCRIPT_PARENT="${BASH_SOURCE[0]%/*}"
[[ "${SCRIPT_PARENT}" != "${BASH_SOURCE[0]}" ]] || SCRIPT_PARENT="."
SCRIPT_DIR="$(cd -- "${SCRIPT_PARENT}" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PANELAPP_SERVER="https://panelapp.genomicsengland.co.uk"
VEP_BATCH_SIZE=200

usage() {
  cat <<'EOF'
VariantScope pure Bash VCF annotation pipeline

Usage:
  run_vcf_annotation_pure.sh INPUT_VCF REGION OUTPUT_PREFIX [CLINVAR_VCF] [OPTIONS]

REGION:
  panel                    Resolve every selected PanelApp gene with Ensembl
  all                      Process the complete input VCF
  chr17:43044292-43170245  Process one explicit interval

Options:
  --assembly auto|GRCh37|GRCh38        Default: auto
  --sample NAME                        Required for a multi-sample VCF
  --reference-fasta PATH               Optional FASTA for left-normalization
  --filter-preset balanced|strict|pass-only
  --min-dp N                           Override FORMAT/DP threshold
  --min-gq N                           Override FORMAT/GQ threshold
  --min-alt-depth N                    Override alternate FORMAT/AD threshold
  --panel-id N                         PanelApp panel ID; default: 635
  --panel-version VERSION              Pinned PanelApp version; default: 3.0
  --panel-confidence green|green-amber|all
  --panel-cache PATH                   Local PanelApp JSON cache
  --refresh-panel                      Download PanelApp again
  --vep-mode rest|skip                 Default: rest
  --vep-cache PATH                     VEP REST JSON cache
  --refresh-vep                        Call VEP again
  --max-rest-variants N                Default: 2000
  --api-timeout SECONDS                Default: 90
  -h, --help

Dependencies:
  bash, bcftools, curl, jq, awk, sed, grep
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

parent_dir() {
  local path=$1
  if [[ "${path}" == */* ]]; then
    printf '%s' "${path%/*}"
  else
    printf '.'
  fi
}

on_error() {
  local code=$?
  printf 'ERROR: stopped at Bash line %s (exit code %s)\n' \
    "${BASH_LINENO[0]:-unknown}" "${code}" >&2
  exit "${code}"
}
trap on_error ERR

[[ $# -gt 0 ]] || { usage; exit 2; }
[[ ${1:-} != "-h" && ${1:-} != "--help" ]] || { usage; exit 0; }
[[ $# -ge 3 ]] || { usage >&2; fail "three positional arguments are required"; }

INPUT_VCF=$1
REGION=$2
OUTPUT_PREFIX=$3
shift 3

CLINVAR_VCF=""
if [[ $# -gt 0 && ${1:-} != --* ]]; then
  CLINVAR_VCF=$1
  shift
fi

ASSEMBLY="auto"
SAMPLE=""
REFERENCE_FASTA=""
FILTER_PRESET="balanced"
MIN_DP=""
MIN_GQ=""
MIN_ALT_DEPTH=""
PANEL_ID="635"
PANEL_VERSION="3.0"
PANEL_CONFIDENCE="green"
PANEL_CACHE=""
REFRESH_PANEL=0
VEP_MODE="rest"
VEP_CACHE=""
REFRESH_VEP=0
MAX_REST_VARIANTS=2000
API_TIMEOUT=90

while [[ $# -gt 0 ]]; do
  case "$1" in
    --assembly) ASSEMBLY=${2:?}; shift 2 ;;
    --sample) SAMPLE=${2:?}; shift 2 ;;
    --reference-fasta) REFERENCE_FASTA=${2:?}; shift 2 ;;
    --filter-preset) FILTER_PRESET=${2:?}; shift 2 ;;
    --min-dp) MIN_DP=${2:?}; shift 2 ;;
    --min-gq) MIN_GQ=${2:?}; shift 2 ;;
    --min-alt-depth) MIN_ALT_DEPTH=${2:?}; shift 2 ;;
    --panel-id) PANEL_ID=${2:?}; shift 2 ;;
    --panel-version) PANEL_VERSION=${2:?}; shift 2 ;;
    --panel-confidence) PANEL_CONFIDENCE=${2:?}; shift 2 ;;
    --panel-cache) PANEL_CACHE=${2:?}; shift 2 ;;
    --refresh-panel) REFRESH_PANEL=1; shift ;;
    --vep-mode) VEP_MODE=${2:?}; shift 2 ;;
    --vep-cache) VEP_CACHE=${2:?}; shift 2 ;;
    --refresh-vep) REFRESH_VEP=1; shift ;;
    --max-rest-variants) MAX_REST_VARIANTS=${2:?}; shift 2 ;;
    --api-timeout) API_TIMEOUT=${2:?}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

for tool in bcftools curl jq awk sed grep; do
  command -v "${tool}" >/dev/null 2>&1 || fail "required tool not found: ${tool}"
done
[[ -f "${INPUT_VCF}" ]] || fail "input VCF not found: ${INPUT_VCF}"
[[ -z "${REFERENCE_FASTA}" || -f "${REFERENCE_FASTA}" ]] \
  || fail "reference FASTA not found: ${REFERENCE_FASTA}"
[[ "${ASSEMBLY}" =~ ^(auto|GRCh37|GRCh38)$ ]] || fail "invalid assembly"
[[ "${FILTER_PRESET}" =~ ^(balanced|strict|pass-only)$ ]] || fail "invalid filter preset"
[[ "${PANEL_CONFIDENCE}" =~ ^(green|green-amber|all)$ ]] || fail "invalid panel confidence"
[[ "${VEP_MODE}" =~ ^(rest|skip)$ ]] || fail "pure Bash supports --vep-mode rest or skip"

OUTPUT_DIR="${OUTPUT_PREFIX%/*}"
[[ "${OUTPUT_DIR}" != "${OUTPUT_PREFIX}" ]] || OUTPUT_DIR="."
mkdir -p -- "${OUTPUT_DIR}"
TMP_DIR="$(mktemp -d "${OUTPUT_DIR}/.variantscope-bash.XXXXXX")"
trap 'rm -rf -- "${TMP_DIR}"' EXIT

SUBSET_VCF="${OUTPUT_PREFIX}.subset.vcf.gz"
FILTERED_VCF="${OUTPUT_PREFIX}.filtered.vcf.gz"
NORMALIZED_VCF="${OUTPUT_PREFIX}.normalized.vcf.gz"
ANNOTATED_VCF="${OUTPUT_PREFIX}.clinvar.vcf.gz"
LEGACY_TSV="${OUTPUT_PREFIX}.clinvar.tsv"
VARIANTS_TSV="${OUTPUT_PREFIX}.variants.tsv"
PANEL_TSV="${OUTPUT_PREFIX}.panel_variants.tsv"
PANEL_JSON="${OUTPUT_PREFIX}.panel.json"
MANIFEST_JSON="${OUTPUT_PREFIX}.manifest.json"
FILTER_TXT="${OUTPUT_PREFIX}.filter.txt"
SUBSET_STATS="${OUTPUT_PREFIX}.subset.stats.txt"
FILTERED_STATS="${OUTPUT_PREFIX}.filtered.stats.txt"
[[ -n "${VEP_CACHE}" ]] || VEP_CACHE="${OUTPUT_PREFIX}.vep.cache.json"

header_for() { bcftools view -h "$1"; }

detect_assembly() {
  local header=$1 length reference
  length="$(printf '%s\n' "${header}" \
    | sed -nE 's/^##contig=<ID=(chr)?1,length=([0-9]+).*/\2/p' | head -n1)"
  reference="$(printf '%s\n' "${header}" \
    | sed -nE 's/^##reference=(.*)/\1/p' | head -n1 | tr '[:upper:]' '[:lower:]')"
  case "${length}" in
    249250621) printf 'GRCh37' ;;
    248956422) printf 'GRCh38' ;;
    *)
      if [[ "${reference}" == *grch38* || "${reference}" == *hg38* ]]; then
        printf 'GRCh38'
      elif [[ "${reference}" == *grch37* || "${reference}" == *hg19* || "${reference}" == *b37* ]]; then
        printf 'GRCh37'
      else
        printf 'unknown'
      fi
      ;;
  esac
}

chrom_style() {
  if printf '%s\n' "$1" | grep -qE '^##contig=<ID=chr1([,>])'; then
    printf 'chr'
  else
    printf 'plain'
  fi
}

INPUT_HEADER="$(header_for "${INPUT_VCF}")"
DETECTED_ASSEMBLY="$(detect_assembly "${INPUT_HEADER}")"
INPUT_CHROM_STYLE="$(chrom_style "${INPUT_HEADER}")"
if [[ "${ASSEMBLY}" == "auto" ]]; then
  [[ "${DETECTED_ASSEMBLY}" != "unknown" ]] || fail "cannot detect assembly; use --assembly"
  ASSEMBLY="${DETECTED_ASSEMBLY}"
elif [[ "${DETECTED_ASSEMBLY}" != "unknown" && "${DETECTED_ASSEMBLY}" != "${ASSEMBLY}" ]]; then
  fail "--assembly=${ASSEMBLY} conflicts with input=${DETECTED_ASSEMBLY}"
fi

if [[ -z "${CLINVAR_VCF}" ]]; then
  suffix=""
  [[ "${INPUT_CHROM_STYLE}" == "plain" ]] || suffix="_chr"
  CLINVAR_VCF="${PROJECT_ROOT}/data/annotation/clinvar/clinvar_${ASSEMBLY}${suffix}.vcf.gz"
fi
[[ -f "${CLINVAR_VCF}" ]] || fail "ClinVar VCF not found: ${CLINVAR_VCF}"
CLINVAR_HEADER="$(header_for "${CLINVAR_VCF}")"
CLINVAR_ASSEMBLY="$(detect_assembly "${CLINVAR_HEADER}")"
CLINVAR_CHROM_STYLE="$(chrom_style "${CLINVAR_HEADER}")"
[[ "${CLINVAR_ASSEMBLY}" == "unknown" || "${CLINVAR_ASSEMBLY}" == "${ASSEMBLY}" ]] \
  || fail "ClinVar assembly mismatch"
[[ "${CLINVAR_CHROM_STYLE}" == "${INPUT_CHROM_STYLE}" ]] \
  || fail "input and ClinVar chromosome naming mismatch"

mapfile -t VCF_SAMPLES < <(bcftools query -l "${INPUT_VCF}")
if [[ -n "${SAMPLE}" ]]; then
  printf '%s\n' "${VCF_SAMPLES[@]:-}" | grep -Fxq "${SAMPLE}" \
    || fail "sample not found in VCF: ${SAMPLE}"
elif [[ ${#VCF_SAMPLES[@]} -eq 1 ]]; then
  SAMPLE="${VCF_SAMPLES[0]}"
elif [[ ${#VCF_SAMPLES[@]} -gt 1 ]]; then
  fail "multi-sample VCF requires --sample"
fi

case "${FILTER_PRESET}" in
  balanced)
    [[ -n "${MIN_DP}" ]] || MIN_DP=5
    [[ -n "${MIN_GQ}" ]] || MIN_GQ=10
    [[ -n "${MIN_ALT_DEPTH}" ]] || MIN_ALT_DEPTH=3
    ;;
  strict)
    [[ -n "${MIN_DP}" ]] || MIN_DP=10
    [[ -n "${MIN_GQ}" ]] || MIN_GQ=20
    [[ -n "${MIN_ALT_DEPTH}" ]] || MIN_ALT_DEPTH=3
    ;;
  pass-only)
    MIN_DP=""; MIN_GQ=""; MIN_ALT_DEPTH=""
    ;;
esac
FILTER_EXPRESSION='(FILTER="PASS" || FILTER=".")'
[[ -z "${MIN_DP}" ]] || FILTER_EXPRESSION+=" && FMT/DP>=${MIN_DP}"
[[ -z "${MIN_GQ}" ]] || FILTER_EXPRESSION+=" && FMT/GQ>=${MIN_GQ}"
[[ -z "${MIN_ALT_DEPTH}" ]] || FILTER_EXPRESSION+=" && FMT/AD[0:1]>=${MIN_ALT_DEPTH}"

[[ -n "${PANEL_CACHE}" ]] \
  || PANEL_CACHE="${PROJECT_ROOT}/data/annotation/panelapp/panel_${PANEL_ID}_v${PANEL_VERSION}.json"
PANEL_NORMALIZED="${TMP_DIR}/panel.normalized.json"

normalize_panel() {
  jq --arg panel_id "${PANEL_ID}" --arg version "${PANEL_VERSION}" \
    --arg confidence "${PANEL_CONFIDENCE}" '
    def confidence:
      tostring | ascii_downcase as $v |
      if ($v == "3" or $v == "4" or ($v|contains("green")) or ($v|contains("high"))) then "green"
      elif ($v == "2" or ($v|contains("amber")) or ($v|contains("moderate"))) then "amber"
      elif ($v == "0" or $v == "1" or ($v|contains("red")) or ($v|contains("low"))) then "red"
      else "unknown" end;
    def source_genes:
      if ((.genes? // null) | type) == "array" then .genes
      elif ((.results? // null) | type) == "array" then .results
      elif ((.entities? // null) | type) == "array" then .entities
      elif ((.entities_payload.results? // null) | type) == "array" then .entities_payload.results
      elif ((.entities_payload.genes? // null) | type) == "array" then .entities_payload.genes
      else [] end;
    {
      panel_id: ($panel_id|tonumber),
      name: (.panel.name // .name // .payload.name // ("PanelApp panel " + $panel_id)),
      version: ((.panel.version // .version // .payload.version // $version)|tostring),
      confidence_filter: $confidence,
      genes: [
        source_genes[] |
        {
          symbol: (.symbol // .gene_symbol // .entity_name // .gene_data.gene_symbol // .entity_data.gene_symbol // "" | ascii_upcase),
          confidence: ((.confidence // .confidence_level // .status // .colour // .color // "unknown") | confidence),
          mode_of_inheritance: (.mode_of_inheritance // ""),
          phenotypes: (.phenotypes // [])
        } |
        select(.symbol != "") |
        select(
          $confidence == "all" or
          ($confidence == "green" and .confidence == "green") or
          ($confidence == "green-amber" and (.confidence == "green" or .confidence == "amber"))
        )
      ]
    } |
    .genes |= unique_by(.symbol)
  ' "$1"
}

if [[ -f "${PANEL_CACHE}" && ${REFRESH_PANEL} -eq 0 ]]; then
  normalize_panel "${PANEL_CACHE}" > "${PANEL_NORMALIZED}"
else
  mkdir -p -- "$(parent_dir "${PANEL_CACHE}")"
  panel_url="${PANELAPP_SERVER}/api/v1/panels/${PANEL_ID}/?version=${PANEL_VERSION}&format=json"
  genes_url="${PANELAPP_SERVER}/api/v1/panels/${PANEL_ID}/genes/?version=${PANEL_VERSION}&format=json"
  curl -fsSL --max-time "${API_TIMEOUT}" -H 'Accept: application/json' \
    "${panel_url}" -o "${TMP_DIR}/panel.metadata.json"
  curl -fsSL --max-time "${API_TIMEOUT}" -H 'Accept: application/json' \
    "${genes_url}" -o "${TMP_DIR}/panel.genes.json"
  jq -n --slurpfile payload "${TMP_DIR}/panel.metadata.json" \
    --slurpfile entities "${TMP_DIR}/panel.genes.json" \
    '{payload:$payload[0], entities_payload:$entities[0]}' \
    > "${TMP_DIR}/panel.raw.json"
  normalize_panel "${TMP_DIR}/panel.raw.json" > "${PANEL_NORMALIZED}"
  cp -- "${PANEL_NORMALIZED}" "${PANEL_CACHE}"
fi
PANEL_GENE_COUNT="$(jq '.genes|length' "${PANEL_NORMALIZED}")"
[[ "${PANEL_GENE_COUNT}" -gt 0 ]] || fail "selected panel contains no genes"

if [[ "${ASSEMBLY}" == "GRCh37" ]]; then
  ENSEMBL_SERVER="https://grch37.rest.ensembl.org"
else
  ENSEMBL_SERVER="https://rest.ensembl.org"
fi

EXTRACTION_REGION="${REGION}"
REGIONS_JSON="${TMP_DIR}/panel.regions.json"
if [[ "${REGION,,}" == "panel" ]]; then
  : > "${TMP_DIR}/regions.ndjson"
  : > "${TMP_DIR}/regions.txt"
  while IFS= read -r gene; do
    lookup="${TMP_DIR}/gene.${gene}.json"
    url="${ENSEMBL_SERVER}/lookup/symbol/homo_sapiens/${gene}?expand=0"
    curl -fsSL --max-time "${API_TIMEOUT}" -H 'Accept: application/json' \
      "${url}" -o "${lookup}"
    returned_assembly="$(jq -r '.assembly_name // ""' "${lookup}")"
    [[ -z "${returned_assembly}" || "${returned_assembly}" == "${ASSEMBLY}" ]] \
      || fail "Ensembl assembly mismatch for ${gene}"
    chrom="$(jq -r '.seq_region_name // empty' "${lookup}")"
    start="$(jq -r '.start // empty' "${lookup}")"
    end="$(jq -r '.end // empty' "${lookup}")"
    ensembl_id="$(jq -r '.id // ""' "${lookup}")"
    [[ -n "${chrom}" && -n "${start}" && -n "${end}" ]] \
      || fail "missing Ensembl coordinates for ${gene}"
    [[ "${INPUT_CHROM_STYLE}" == "plain" || "${chrom}" == chr* ]] || chrom="chr${chrom}"
    [[ "${INPUT_CHROM_STYLE}" == "chr" || "${chrom}" != chr* ]] || chrom="${chrom#chr}"
    resolved="${chrom}:${start}-${end}"
    printf '%s\n' "${resolved}" >> "${TMP_DIR}/regions.txt"
    jq -n --arg gene "${gene}" --arg chrom "${chrom}" --arg id "${ensembl_id}" \
      --arg region "${resolved}" --arg url "${url}" \
      --argjson start "${start}" --argjson end "${end}" \
      '{gene:$gene,chrom:$chrom,start:$start,end:$end,region:$region,ensembl_gene_id:$id,source_url:$url}' \
      >> "${TMP_DIR}/regions.ndjson"
  done < <(jq -r '.genes[].symbol' "${PANEL_NORMALIZED}")
  jq -s '.' "${TMP_DIR}/regions.ndjson" > "${REGIONS_JSON}"
  EXTRACTION_REGION="$(paste -sd, "${TMP_DIR}/regions.txt")"
else
  printf '[]\n' > "${REGIONS_JSON}"
fi
jq --slurpfile regions "${REGIONS_JSON}" '. + {regions:$regions[0]}' \
  "${PANEL_NORMALIZED}" > "${PANEL_JSON}"

printf '%s\n' \
  "[1] Input VCF: ${INPUT_VCF}" \
  "[2] Region: ${REGION}" \
  "[3] Output prefix: ${OUTPUT_PREFIX}" \
  "[4] Assembly: ${ASSEMBLY}" \
  "[5] Chromosome style: ${INPUT_CHROM_STYLE}" \
  "[6] Sample: ${SAMPLE:-none}" \
  "[7] ClinVar VCF: ${CLINVAR_VCF}" \
  "[8] Filter: ${FILTER_EXPRESSION}" \
  "[9] Panel: $(jq -r '.name' "${PANEL_NORMALIZED}") (${PANEL_GENE_COUNT} genes)"

[[ -f "${INPUT_VCF}.tbi" || -f "${INPUT_VCF}.csi" ]] || bcftools index "${INPUT_VCF}"
[[ -f "${CLINVAR_VCF}.tbi" || -f "${CLINVAR_VCF}.csi" ]] || bcftools index "${CLINVAR_VCF}"

echo "[10] Extracting target variants..."
subset_cmd=(bcftools view)
[[ -z "${SAMPLE}" ]] || subset_cmd+=(-s "${SAMPLE}")
[[ "${EXTRACTION_REGION,,}" == "all" ]] || subset_cmd+=(-r "${EXTRACTION_REGION}")
subset_cmd+=("${INPUT_VCF}" -Oz -o "${SUBSET_VCF}")
"${subset_cmd[@]}"
bcftools index -f "${SUBSET_VCF}"

echo "[11] Applying quality filter..."
bcftools view -i "${FILTER_EXPRESSION}" "${SUBSET_VCF}" -Oz -o "${FILTERED_VCF}"
bcftools index -f "${FILTERED_VCF}"

echo "[12] Splitting and normalizing alleles..."
norm_cmd=(bcftools norm -m -any)
[[ -z "${REFERENCE_FASTA}" ]] || norm_cmd+=(-f "${REFERENCE_FASTA}")
norm_cmd+=("${FILTERED_VCF}" -Oz -o "${NORMALIZED_VCF}")
"${norm_cmd[@]}"
bcftools index -f "${NORMALIZED_VCF}"

echo "[13] Annotating exact alleles with ClinVar..."
bcftools annotate -a "${CLINVAR_VCF}" \
  -c 'ID,INFO/CLNSIG,INFO/CLNDN,INFO/CLNREVSTAT,INFO/CLNHGVS,INFO/GENEINFO' \
  "${NORMALIZED_VCF}" -Oz -o "${ANNOTATED_VCF}"
bcftools index -f "${ANNOTATED_VCF}"

echo "[14] Creating ClinVar and base TSV files..."
bcftools query --allow-undef-tags \
  -f '%CHROM\t%POS\t%REF\t%ALT\t%FILTER\t%ID\t%INFO/GENEINFO\t%INFO/CLNSIG\t%INFO/CLNDN\t%INFO/CLNREVSTAT\n' \
  "${ANNOTATED_VCF}" > "${LEGACY_TSV}"

BASE_TSV="${TMP_DIR}/base.tsv"
printf 'chrom\tpos\tref\talt\tfilter\tclinvar_id\tqual\tgeneinfo\tclinvar_significance\tclinvar_disease\tclinvar_review_status\tclinvar_hgvs\tgt\tad\tdp\tgq\n' \
  > "${BASE_TSV}"
query_cmd=(bcftools query --allow-undef-tags)
[[ -z "${SAMPLE}" ]] || query_cmd+=(-s "${SAMPLE}")
query_cmd+=(-f '%CHROM\t%POS\t%REF\t%ALT\t%FILTER\t%ID\t%QUAL\t%INFO/GENEINFO\t%INFO/CLNSIG\t%INFO/CLNDN\t%INFO/CLNREVSTAT\t%INFO/CLNHGVS[\t%GT\t%AD\t%DP\t%GQ]\n' "${ANNOTATED_VCF}")
"${query_cmd[@]}" >> "${BASE_TSV}"

VEP_JSON="${VEP_CACHE}"
if [[ "${VEP_MODE}" == "rest" ]]; then
  mkdir -p -- "$(parent_dir "${VEP_CACHE}")"
  ELIGIBLE="${TMP_DIR}/vep.inputs.txt"
  tail -n +2 "${BASE_TSV}" \
    | awk -F '\t' '$4 != "*" && $4 !~ /^</ {c=$1; sub(/^chr/,"",c); print c" "$2" . "$3" "$4" . . ."}' \
    > "${ELIGIBLE}"
  variant_count="$(wc -l < "${ELIGIBLE}" | tr -d ' ')"
  [[ "${variant_count}" -le "${MAX_REST_VARIANTS}" ]] \
    || fail "${variant_count} variants exceed --max-rest-variants=${MAX_REST_VARIANTS}"
  if [[ ! -f "${VEP_CACHE}" || ${REFRESH_VEP} -eq 1 ]]; then
    echo "[15] Calling Ensembl VEP REST for ${variant_count} variants..."
    : > "${TMP_DIR}/responses.list"
    if [[ "${variant_count}" -gt 0 ]]; then
      split -l "${VEP_BATCH_SIZE}" -d -a 4 "${ELIGIBLE}" "${TMP_DIR}/batch."
      batch_number=0
      for batch in "${TMP_DIR}"/batch.*; do
        batch_number=$((batch_number + 1))
        payload="${batch}.payload.json"
        response="${batch}.response.json"
        jq -Rn '{variants:[inputs]}' < "${batch}" > "${payload}"
        curl -fsSL --max-time "${API_TIMEOUT}" -X POST \
          -H 'Accept: application/json' -H 'Content-Type: application/json' \
          --data-binary "@${payload}" \
          "${ENSEMBL_SERVER}/vep/homo_sapiens/region?canonical=1&hgvs=1&protein=1&variant_class=1&symbol=1&numbers=1&af_gnomade=1&af_gnomadg=1" \
          -o "${response}"
        jq -e 'type == "array"' "${response}" >/dev/null \
          || fail "VEP returned an invalid response for batch ${batch_number}"
        printf '%s\n' "${response}" >> "${TMP_DIR}/responses.list"
        echo "    VEP batch ${batch_number} complete"
      done
      mapfile -t responses < "${TMP_DIR}/responses.list"
      jq -s 'add' "${responses[@]}" > "${VEP_CACHE}"
    else
      printf '[]\n' > "${VEP_CACHE}"
    fi
  else
    echo "[15] Reusing VEP cache: ${VEP_CACHE}"
  fi
else
  echo "[15] Skipping VEP..."
  printf '[]\n' > "${TMP_DIR}/vep.skip.json"
  VEP_JSON="${TMP_DIR}/vep.skip.json"
fi

echo "[16] Merging VEP, gnomAD, ClinVar, and PanelApp..."
jq -r --rawfile base "${BASE_TSV}" --slurpfile vep "${VEP_JSON}" \
  --slurpfile panel "${PANEL_JSON}" '
  def clean: if . == null or . == "." then "" elif type == "array" then join("&") else tostring end;
  def key($c;$p;$r;$a): (($c|sub("^chr";"")) + ":" + ($p|tostring) + ":" + $r + ":" + $a);
  def vkey($v):
    (($v.input // "") | split(" ")) as $f |
    if ($f|length) >= 5 then key($f[0];$f[1];$f[3];$f[4])
    else key(($v.seq_region_name//"");($v.start//0);(($v.allele_string//"/")|split("/")[0]);(($v.allele_string//"/")|split("/")[1])) end;
  def parse_tsv($text):
    ($text|split("\n")|map(select(length>0))) as $lines |
    ($lines[0]|split("\t")) as $headers |
    [$lines[1:][] | split("\t") as $values |
      reduce range(0; $headers|length) as $i
        ({}; .[$headers[$i]] = (($values[$i] // "") | clean))];
  def impact_rank($x):
    if $x == "HIGH" then 0 elif $x == "MODERATE" then 1
    elif $x == "LOW" then 2 elif $x == "MODIFIER" then 3 else 9 end;
  def frequency($v;$alt;$name):
    [($v.colocated_variants // [])[]? |
      (.frequencies[$alt] // {}) |
      to_entries[]? | select(.key == $name) | .value] |
    if length > 0 then max else "" end;
  ($panel[0]) as $p |
  ($vep[0].results // $vep[0]) as $vep_results |
  (reduce $p.genes[] as $g ({}; .[$g.symbol]=$g)) as $panel_index |
  (reduce $vep_results[] as $v ({}; .[vkey($v)]=$v)) as $vep_index |
  parse_tsv($base) |
  map(
    . as $row |
    ($vep_index[key(.chrom;.pos;.ref;.alt)] // {}) as $v |
    (($v.transcript_consequences // []) |
      map(select(type=="object")) |
      sort_by([
        (if $panel_index[((.gene_symbol//"")|ascii_upcase)] != null then 0 else 1 end),
        (if (.canonical//0) == 1 then 0 else 1 end),
        (if (.biotype//"") == "protein_coding" then 0 else 1 end),
        impact_rank(.impact//""),
        (.transcript_id//"")
      ])) as $transcripts |
    ($transcripts[0] // {}) as $t |
    ([$transcripts[]?.gene_symbol // empty] | map(ascii_upcase) | unique) as $vep_genes |
    ((($row.geneinfo//"")|split("|")[0]|split(":")[0]) | ascii_upcase) as $clinvar_gene |
    (($vep_genes + (if $clinvar_gene != "" then [$clinvar_gene] else [] end)) | unique) as $all_genes |
    ([$all_genes[] | select($panel_index[.] != null)]) as $panel_genes |
    (($t.gene_symbol // $clinvar_gene // "") | ascii_upcase) as $gene |
    (($panel_genes[0] // "") | ascii_upcase) as $panel_gene |
    ($panel_index[$panel_gene] // {}) as $panel_data |
    $row + {
      gene: $gene,
      all_vep_genes: ($all_genes|join(";")),
      transcript: ($t.transcript_id|clean),
      consequence: (($t.consequence_terms//[])|clean),
      impact: ($t.impact|clean),
      hgvsc: ($t.hgvsc|clean),
      hgvsp: ($t.hgvsp|clean),
      canonical: (if ($t.canonical//0)==1 then "yes" else "" end),
      sift_prediction: ($t.sift_prediction|clean),
      sift_score: ($t.sift_score|clean),
      polyphen_prediction: ($t.polyphen_prediction|clean),
      polyphen_score: ($t.polyphen_score|clean),
      gnomad_exome_af: (frequency($v;$row.alt;"gnomade")|clean),
      gnomad_genome_af: (frequency($v;$row.alt;"gnomadg")|clean),
      in_selected_panel: (if ($panel_genes|length)>0 then "yes" else "no" end),
      panel_genes: ($panel_genes|join(";")),
      panel_confidence: ($panel_data.confidence|clean),
      panel_mode_of_inheritance: ($panel_data.mode_of_inheritance|clean),
      panel_id: ($p.panel_id|tostring),
      panel_version: ($p.version|tostring),
      panel_name: $p.name
    }
  ) as $rows |
  [
    "chrom","pos","ref","alt","filter","qual","gt","ad","dp","gq",
    "gene","all_vep_genes","transcript","consequence","impact","hgvsc","hgvsp",
    "canonical","sift_prediction","sift_score","polyphen_prediction","polyphen_score",
    "clinvar_id","clinvar_significance","clinvar_disease","clinvar_review_status",
    "clinvar_hgvs","gnomad_exome_af","gnomad_genome_af","in_selected_panel",
    "panel_genes","panel_confidence","panel_mode_of_inheritance","panel_id",
    "panel_version","panel_name","geneinfo"
  ] as $fields |
  ($fields|@tsv),
  ($rows[] | [.[$fields[]] // ""] | @tsv)
  ' > "${VARIANTS_TSV}"

awk -F '\t' 'NR==1 || $30=="yes"' "${VARIANTS_TSV}" > "${PANEL_TSV}"
bcftools stats "${SUBSET_VCF}" > "${SUBSET_STATS}"
bcftools stats "${FILTERED_VCF}" > "${FILTERED_STATS}"

cat > "${FILTER_TXT}" <<EOF
preset=${FILTER_PRESET}
min_dp=${MIN_DP}
min_gq=${MIN_GQ}
min_alt_depth=${MIN_ALT_DEPTH}
assembly=${ASSEMBLY}
chromosome_style=${INPUT_CHROM_STYLE}
sample=${SAMPLE}
clinvar_vcf=${CLINVAR_VCF}
expression=${FILTER_EXPRESSION}
EOF

filtered_count="$(( $(wc -l < "${VARIANTS_TSV}") - 1 ))"
panel_count="$(( $(wc -l < "${PANEL_TSV}") - 1 ))"
jq -n --arg version "${VERSION}" --arg input "${INPUT_VCF}" \
  --arg region "${REGION}" --arg sample "${SAMPLE}" --arg assembly "${ASSEMBLY}" \
  --arg preset "${FILTER_PRESET}" --arg expression "${FILTER_EXPRESSION}" \
  --arg clinvar "${CLINVAR_VCF}" --arg vep_mode "${VEP_MODE}" \
  --arg variants "${VARIANTS_TSV}" --arg panel_tsv "${PANEL_TSV}" \
  --arg panel_json "${PANEL_JSON}" --argjson filtered "${filtered_count}" \
  --argjson selected "${panel_count}" --slurpfile panel "${PANEL_JSON}" \
  '{
    pipeline:"VariantScope pure Bash annotation pipeline",
    pipeline_version:$version,
    input_vcf:$input, region:$region, sample:$sample, assembly:$assembly,
    filter:{preset:$preset,expression:$expression},
    clinvar:{path:$clinvar,match:"normalized CHROM+POS+REF+ALT exact allele"},
    vep:{mode:$vep_mode},
    panelapp:$panel[0],
    counts:{filtered_alleles:$filtered,selected_panel_alleles:$selected},
    outputs:{all_variants_tsv:$variants,panel_variants_tsv:$panel_tsv,panel_json:$panel_json},
    limitations:[
      "Research and education only; not a clinical diagnosis.",
      "ClinVar absence does not mean benign.",
      "gnomAD absence does not mean pathogenic."
    ]
  }' > "${MANIFEST_JSON}"

printf '%s\n' \
  "Done." \
  "All variants TSV: ${VARIANTS_TSV}" \
  "Panel TSV:        ${PANEL_TSV}" \
  "Manifest:         ${MANIFEST_JSON}" \
  "Panel alleles:    ${panel_count}/${filtered_count}"
