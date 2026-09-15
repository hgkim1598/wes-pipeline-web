# GRCh38 WES capture BED resources

The WES pipeline accepts a stable `capture_kit.id` from the UI. `main.sh`
resolves that ID through `config/capture_kits.grch38.json`; it does not contain
vendor-specific paths or kit branches.

## Supported profiles

| UI and registry ID | Kit | Status | Target BED | Coverage BED |
|---|---|---|---|---|
| `agilent_sureselect_human_all_exon_v8` | Agilent SureSelect Human All Exon V8, design S33266340 | Manual confirmation required; disabled in UI | SureDesign GRCh38 Regions BED | SureDesign GRCh38 Covered BED |
| `idt_xgen_exome_hyb_panel_v2` | IDT xGen Exome Hyb Panel v2 | Confirmed | Official hg38 targets | Official hg38 probes |
| `twist_exome_2_0` | Twist Exome 2.0 | Confirmed | Official v2.0.2 hg38 covered targets | Same BED |
| `roche_kapa_hyperexome_v2` | Roche KAPA HyperExome V2 | Confirmed | hg38 primary targets | hg38 capture targets |

The target BED limits variant calling. The coverage BED defines the assay
footprint used for WES coverage QC. Their source URLs and SHA-256 values are
stored in the registry.

## Install public resources

From the repository root in WSL:

```bash
bash script/download_capture_beds.sh all
```

Files are written to `resources/capture_beds/grch38/`. That directory is
ignored by Git because the resources can be restored from the recorded source
URLs and checksums.

## Agilent V8

Agilent design files are obtained through SureDesign. Search Published Designs
for design `S33266340`, select GRCh38, and download the Regions and Covered BED
files. Do not convert a GRCh37 BED by adding `chr` prefixes. After downloading,
calculate each checksum:

```bash
sha256sum /path/to/S33266340*.bed
```

Then replace the Agilent TODO values in the registry and change its status to
`confirmed`. Re-enable the matching UI choice only after that verification.

## Final pipeline validation

`main.sh --check-only` validates the selected profile against the actual
GRCh38 FASTA `.fai`, including contig naming, interval bounds, non-empty BED
content, and recorded checksums. A capture profile is not ready merely because
the BED parser accepts it.
